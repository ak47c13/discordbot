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
from services.raid_service import create_raid_queue, join_raid, start_raid, raids_remaining, RaidError
from config.game_config import RAID_DIFFICULTIES, RAID_DAILY_LIMIT


def _difficulty_overview_embed(user: User) -> discord.Embed:
    remaining = raids_remaining(user)
    embed = discord.Embed(
        title="Raid",
        description=(
            f"Challenge a raid boss solo or with up to 5 players.\n"
            f"**{remaining}/{RAID_DAILY_LIMIT}** raids remaining today.\n\n"
            "Bosses stay at full strength regardless of group size — solo is doable but brutal."
        ),
        color=COLOR_INFO,
    )
    for key, cfg in RAID_DIFFICULTIES.items():
        embed.add_field(
            name=cfg["display"],
            value=(
                f"Gold: {cfg['gold_min']:,}–{cfg['gold_max']:,}\n"
                f"Tokens: {cfg['token_min']}–{cfg['token_max']}\n"
                f"Champion: {int(cfg['champ_chance']*100)}%  Item: {int(cfg['item_chance']*100)}%"
            ),
            inline=True,
        )
    embed.set_footer(text="Solo clears give 60% gold/tokens. Daily limit resets at midnight UTC.")
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

    @app_commands.command(name="raid-create", description="Create a raid queue. Others can join before you start.")
    @app_commands.describe(difficulty="Raid difficulty F (easy) through S (extreme)")
    @app_commands.choices(difficulty=[
        app_commands.Choice(name=cfg["display"], value=k)
        for k, cfg in RAID_DIFFICULTIES.items()
    ])
    async def raid_create(self, interaction: discord.Interaction, difficulty: str):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        await User.get_or_create(uid, interaction.user.display_name)

        async with get_user_lock(uid):
            client = get_motor_client()
            async with await client.start_session() as session:
                try:
                    raid = await create_raid_queue(uid, difficulty, session)
                except RaidError as e:
                    await interaction.followup.send(embed=error_embed(str(e)), ephemeral=True)
                    return

        cfg = RAID_DIFFICULTIES[difficulty]
        embed = discord.Embed(
            title=f"Raid Created — {cfg['display']}",
            description=(
                f"**Raid ID:** `{raid.id}`\n\n"
                f"Others join with:\n`/raid-join {raid.id} <champion_number>`\n\n"
                f"Start when ready:\n`/raid-start {raid.id}`\n\n"
                f"You can also start immediately to solo.\n"
                f"Max 5 players."
            ),
            color=COLOR_INFO,
        )
        embed.add_field(name="Gold Payout",  value=f"{cfg['gold_min']:,} – {cfg['gold_max']:,}", inline=True)
        embed.add_field(name="Token Payout", value=f"{cfg['token_min']} – {cfg['token_max']}", inline=True)
        embed.add_field(name="Solo Penalty", value="60% gold & tokens", inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)

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
        await interaction.response.defer(ephemeral=True)
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
            ephemeral=True,
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
        cfg = RAID_DIFFICULTIES.get(difficulty, {})
        diff_display = cfg.get("display", difficulty)

        won = result.winner == 0
        title = f"{'Victory' if won else 'Defeat'} — {diff_display}"
        if is_solo:
            title += " (Solo)"

        embed = discord.Embed(
            title=title,
            description=f"Battle lasted {result.rounds} rounds.",
            color=COLOR_SUCCESS if won else COLOR_DANGER,
        )

        log_lines = [l for l in outcome["battle_log"] if l.strip()][-8:]
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
