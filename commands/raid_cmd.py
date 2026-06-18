"""Raid commands — F-S difficulties, 5 raids/day, solo or group."""
import discord
from discord import app_commands
from discord.ext import commands

from models.user import User
from models.raid import RaidQueue
from models.champion import ChampionInstance
from utils.embeds import reward_embed, error_embed, success_embed, get_champion_by_number, COLOR_INFO, COLOR_SUCCESS, COLOR_DANGER
from utils.locks import get_user_lock
from utils.db_session import get_motor_client
from utils.idempotency import is_already_processed, mark_processed
from services.raid_service import create_raid_queue, join_raid, start_raid, raids_remaining, RaidError, CHAMP_DROP_CHANCE
from config.game_config import RAID_DIFFICULTIES, RAID_DAILY_LIMIT, RAID_RESET_HOURS, RAID_DIFFICULTY_WEIGHTS


def _difficulty_overview_embed(user: User) -> discord.Embed:
    remaining = raids_remaining(user)
    from datetime import datetime, timezone, timedelta
    last = user.daily_raids_reset
    if last:
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        next_reset = last + timedelta(hours=RAID_RESET_HOURS)
        mins_left = max(0, int((next_reset - datetime.now(timezone.utc)).total_seconds() / 60))
        reset_str = f"Resets in {mins_left}m" if mins_left > 0 else "Resets now"
    else:
        reset_str = f"Resets every {RAID_RESET_HOURS}h"
    embed = discord.Embed(
        title="Raid",
        description=(
            f"**{remaining}/{RAID_DAILY_LIMIT}** raids remaining — {reset_str}.\n\n"
            "Each raid rolls a random difficulty (F→S). Higher tiers are rarer but pay much more.\n"
            "Boss level is also randomized within the tier's range.\n"
            "Bosses stay at full strength for solo runs — 60% gold/token payout if you win alone."
        ),
        color=COLOR_INFO,
    )
    for key, cfg in RAID_DIFFICULTIES.items():
        lvl = cfg["boss_level"]
        weight = RAID_DIFFICULTY_WEIGHTS[key]
        total_weight = sum(RAID_DIFFICULTY_WEIGHTS.values())
        chance = int(weight / total_weight * 100)
        embed.add_field(
            name=f"{cfg['display']}  ({chance}%)",
            value=(
                f"Boss Lv.{lvl[0]}–{lvl[1]}\n"
                f"Gold: {cfg['gold_min']:,}–{cfg['gold_max']:,}\n"
                f"Tokens: {cfg['token_min']}–{cfg['token_max']}"
            ),
            inline=True,
        )
    embed.set_footer(text="Raid limit resets every 3 hours.")
    return embed


class RaidCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ------------------------------------------------------------------
    # /raid-info
    # ------------------------------------------------------------------

    @app_commands.command(name="raid-info", description="View raid difficulties and today's remaining raids.")
    async def raid_info(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user = await User.get_or_create(str(interaction.user.id), interaction.user.display_name)
        await interaction.followup.send(embed=_difficulty_overview_embed(user), ephemeral=True)

    # ------------------------------------------------------------------
    # /raid-create
    # ------------------------------------------------------------------

    @app_commands.command(name="raid-create", description="Roll a random raid difficulty and create a queue.")
    async def raid_create(self, interaction: discord.Interaction):
        await interaction.response.defer()
        uid = str(interaction.user.id)
        await User.get_or_create(uid, interaction.user.display_name)

        async with get_user_lock(uid):
            client = get_motor_client()
            async with await client.start_session() as session:
                try:
                    raid, difficulty = await create_raid_queue(uid, session)
                except RaidError as e:
                    await interaction.followup.send(embed=error_embed(str(e)), ephemeral=True)
                    return

        cfg = RAID_DIFFICULTIES[difficulty]
        lvl = cfg["boss_level"]
        drop_pct = int(CHAMP_DROP_CHANCE.get(cfg["boss_rank"], 0.05) * 100 * (0.5 if True else 1))  # solo shown
        embed = discord.Embed(
            title=f"⚔️ Raid Rolled — {cfg['display']}",
            description=(
                f"**Boss Champion:** {raid.boss_champion_name} [{cfg['boss_rank']}]\n\n"
                f"**Raid ID:** `{raid.id}`\n\n"
                f"Others join with:\n`/raid-join {raid.id} <champion_number>`\n\n"
                f"Start when ready:\n`/raid-start {raid.id}`\n\n"
                f"You can start immediately to solo (60% gold/token payout).\n"
                f"Max 5 players."
            ),
            color=COLOR_INFO,
        )
        embed.add_field(name="Boss Level Range", value=f"Lv.{lvl[0]}–{lvl[1]}", inline=True)
        embed.add_field(name="Gold Payout",      value=f"{cfg['gold_min']:,}–{cfg['gold_max']:,}", inline=True)
        embed.add_field(name="Token Payout",     value=f"{cfg['token_min']}–{cfg['token_max']}", inline=True)
        embed.add_field(
            name="Champion Drop Chance",
            value=f"{CHAMP_DROP_CHANCE.get(cfg['boss_rank'], 0.05) * 100:.1f}% (×0.5 solo)\nTop contributor has highest odds",
            inline=False,
        )
        await interaction.followup.send(embed=embed)

    # ------------------------------------------------------------------
    # /raid-list
    # ------------------------------------------------------------------

    @app_commands.command(name="raid-list", description="List open raids you can join.")
    async def raid_list(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        raids = await RaidQueue.find(RaidQueue.status == "waiting").to_list()
        if not raids:
            await interaction.followup.send(
                embed=error_embed("No open raids right now. Create one with /raid-create."),
                ephemeral=True,
            )
            return

        embed = discord.Embed(title="Open Raids", color=COLOR_INFO)
        for raid in raids[:20]:
            diff = raid.zone
            cfg = RAID_DIFFICULTIES.get(diff, {})
            diff_display = cfg.get("display", diff)
            try:
                member = interaction.guild.get_member(int(raid.leader_id)) if interaction.guild else None
                leader = member.display_name if member else f"<@{raid.leader_id}>"
            except Exception:
                leader = f"<@{raid.leader_id}>"
            embed.add_field(
                name=f"{diff_display}  |  {len(raid.player_ids)}/5  |  {leader}",
                value=f"```{raid.id}```",
                inline=False,
            )
        embed.set_footer(text="/raid-join <id> <champion_number>")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ------------------------------------------------------------------
    # /raid-join
    # ------------------------------------------------------------------

    @app_commands.command(name="raid-join", description="Join an open raid queue.")
    @app_commands.describe(raid_id="Raid ID from /raid-list", champion_number="Your champion number (see /champions)")
    async def raid_join(self, interaction: discord.Interaction, raid_id: str, champion_number: int):
        await interaction.response.defer()
        uid = str(interaction.user.id)
        await User.get_or_create(uid, interaction.user.display_name)

        champ = await get_champion_by_number(uid, champion_number)
        if champ is None or champ.owner_id != uid:
            await interaction.followup.send(
                embed=error_embed("Champion not found. Use `/champions` to find the right number."),
                ephemeral=True,
            )
            return

        async with get_user_lock(uid):
            client = get_motor_client()
            async with await client.start_session() as session:
                try:
                    raid = await join_raid(uid, raid_id, str(champ.id), session)
                except RaidError as e:
                    await interaction.followup.send(embed=error_embed(str(e)), ephemeral=True)
                    return

        diff = RAID_DIFFICULTIES.get(raid.zone, {}).get("display", raid.zone)
        await interaction.followup.send(
            embed=success_embed(
                f"Joined **{diff}** raid with **{champ.name} [{champ.rank}]**!\n"
                f"Players: {len(raid.player_ids)}/5"
            ),
        )

    # ------------------------------------------------------------------
    # /raid-start
    # ------------------------------------------------------------------

    @app_commands.command(name="raid-start", description="Start your raid (leader only). Can solo immediately.")
    @app_commands.describe(raid_id="Raid ID")
    async def raid_start(self, interaction: discord.Interaction, raid_id: str):
        await interaction.response.defer()
        uid = str(interaction.user.id)

        iid = str(interaction.id)
        if await is_already_processed(iid):
            await interaction.followup.send(embed=error_embed("Raid already started."))
            return

        try:
            async with get_user_lock(uid):
                client = get_motor_client()
                async with await client.start_session() as session:
                    try:
                        outcome = await start_raid(uid, raid_id, session)
                    except RaidError as e:
                        await interaction.followup.send(embed=error_embed(str(e)))
                        return
        except Exception as e:
            try:
                await interaction.followup.send(
                    embed=error_embed("Something went wrong starting the raid.", str(e)[:200])
                )
            except Exception:
                pass
            return

        await mark_processed(iid, f"raid_start:{raid_id}")

        result = outcome["battle_result"]
        difficulty = outcome["difficulty"]
        is_solo = outcome["is_solo"]
        boss_name = outcome.get("boss_name", "Raid Boss")
        boss_rank = outcome.get("boss_rank", "?")
        contributions = outcome.get("contributions", {})
        cfg = RAID_DIFFICULTIES.get(difficulty, {})
        diff_display = cfg.get("display", difficulty)

        won = result.winner == 0
        title = f"{'⚔️ Victory' if won else '💀 Defeat'} — {boss_name} [{boss_rank}]"
        if is_solo:
            title += " (Solo)"

        embed = discord.Embed(
            title=title,
            description=f"Difficulty: **{diff_display}** · {result.rounds} rounds",
            color=COLOR_SUCCESS if won else COLOR_DANGER,
        )

        # Show contribution breakdown
        if contributions:
            contrib_lines = []
            for pid, pct in sorted(contributions.items(), key=lambda x: -x[1]):
                try:
                    member = interaction.guild.get_member(int(pid)) if interaction.guild else None
                    name = member.display_name if member else f"<@{pid}>"
                except Exception:
                    name = f"<@{pid}>"
                contrib_lines.append(f"{name}: {pct * 100:.1f}%")
            embed.add_field(name="Contribution", value="\n".join(contrib_lines), inline=True)

        log_lines = [l for l in outcome["battle_log"] if l.strip()][-6:]
        if log_lines:
            embed.add_field(name="Battle Log", value="\n".join(log_lines)[:1000], inline=False)

        if not won:
            embed.add_field(
                name="Defeated",
                value="The raid boss was too powerful. No rewards this time.\nYour daily raid count was still used.",
                inline=False,
            )

        await interaction.followup.send(embed=embed)

        if won:
            for player_id, rewards in outcome["player_rewards"].items():
                if rewards.get("already_rewarded") or rewards.get("lost"):
                    continue
                try:
                    member = interaction.guild.get_member(int(player_id)) if interaction.guild else None
                    mention = member.mention if member else f"<@{player_id}>"
                except Exception:
                    mention = f"<@{player_id}>"

                solo_note = " (Solo — 60% payout)" if is_solo else ""
                await interaction.followup.send(
                    content=mention,
                    embed=reward_embed(rewards, f"Raid Rewards — {diff_display}{solo_note}"),
                )


async def setup(bot: commands.Bot):
    await bot.add_cog(RaidCog(bot))
