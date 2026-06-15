import discord
from discord import app_commands
from discord.ext import commands

from models.user import User
from models.raid import RaidQueue
from models.champion import ChampionInstance
from utils.embeds import (
    reward_embed, error_embed, success_embed, get_champion_by_number,
    COLOR_INFO, COLOR_SUCCESS, COLOR_DANGER,
)
from utils.locks import get_user_lock
from utils.db_session import get_motor_client
from utils.idempotency import is_already_processed, mark_processed
from services.raid_service import create_raid_queue, join_raid, start_raid, RaidError
from config.game_config import HUNT_ZONES


class RaidCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="raid-create", description="Create a raid queue.")
    @app_commands.describe(zone="Zone to raid")
    @app_commands.choices(zone=[
        app_commands.Choice(name=v["name"], value=k)
        for k, v in HUNT_ZONES.items()
    ])
    async def raid_create(self, interaction: discord.Interaction, zone: str):
        await interaction.response.defer()
        uid = str(interaction.user.id)
        await User.get_or_create(uid, interaction.user.display_name)

        async with get_user_lock(uid):
            client = get_motor_client()
            async with await client.start_session() as session:
                async with session.start_transaction():
                    try:
                        raid = await create_raid_queue(uid, zone, session)
                    except RaidError as e:
                        await interaction.followup.send(embed=error_embed(str(e)))
                        return

        embed = discord.Embed(
            title="✅ Raid created!",
            description=(
                f"**Zone:** {HUNT_ZONES[zone]['name']}\n"
                f"**ID:** `{raid.id}`  ← copy this\n\n"
                f"Share this ID so others can join with:\n"
                f"`/raid-join <raid_id> <your_champion_number>`\n\n"
                f"Leader starts with `/raid-start {raid.id}`\n"
                f"Max 5 players."
            ),
            color=COLOR_INFO,
        )
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="raid-list", description="List open raids you can join.")
    async def raid_list(self, interaction: discord.Interaction):
        await interaction.response.defer()
        raids = await RaidQueue.find(RaidQueue.status == "waiting").to_list()
        if not raids:
            await interaction.followup.send(embed=error_embed("No open raids right now. Create one with /raid-create."))
            return

        embed = discord.Embed(title="⚔️ Open Raids", color=COLOR_INFO)
        for raid in raids[:20]:
            zone_name = HUNT_ZONES.get(raid.zone, {}).get("name", raid.zone)
            try:
                member = interaction.guild.get_member(int(raid.leader_id)) if interaction.guild else None
                leader = member.mention if member else f"<@{raid.leader_id}>"
            except Exception:
                leader = f"<@{raid.leader_id}>"
            embed.add_field(
                name=f"{zone_name} | {len(raid.player_ids)}/5 players | Leader: {leader}",
                value=f"```{raid.id}```",
                inline=False,
            )
        embed.set_footer(text="Use /raid-join <id> <champion_number> to join")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="raid-join", description="Join an existing raid queue.")
    @app_commands.describe(raid_id="Raid ID", champion_number="Your champion list number (see /champions)")
    async def raid_join(self, interaction: discord.Interaction, raid_id: str, champion_number: int):
        await interaction.response.defer()
        uid = str(interaction.user.id)
        await User.get_or_create(uid, interaction.user.display_name)

        champ = await get_champion_by_number(uid, champion_number)
        if champ is None or champ.owner_id != uid:
            await interaction.followup.send(
                embed=error_embed("Champion not found.", "Use `/champions` to find the right number.")
            )
            return
        champion_id = str(champ.id)

        async with get_user_lock(uid):
            client = get_motor_client()
            async with await client.start_session() as session:
                async with session.start_transaction():
                    try:
                        raid = await join_raid(uid, raid_id, champion_id, session)
                    except RaidError as e:
                        await interaction.followup.send(embed=error_embed(str(e)))
                        return

        await interaction.followup.send(
            embed=success_embed(
                f"You joined the raid with {champ.name} [{champ.rank}]! ({len(raid.player_ids)}/5 players)"
            )
        )

    @app_commands.command(name="raid-start", description="Start your raid (leader only).")
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
                    async with session.start_transaction():
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
        winner_text = "🏆 Victory!" if result.winner == 0 else ("💀 Defeat" if result.winner == 1 else "⏳ Draw")

        embed = discord.Embed(
            title=f"Raid Complete — {winner_text}",
            description=f"Battle lasted {result.rounds} rounds.",
            color=COLOR_SUCCESS if result.winner == 0 else COLOR_DANGER,
        )

        log_lines = [l for l in outcome["battle_log"] if l.strip()][-10:]
        if log_lines:
            embed.add_field(name="Battle Log", value="\n".join(log_lines)[:1000], inline=False)

        await interaction.followup.send(embed=embed)

        if result.winner == 0:
            for player_id, rewards in outcome["player_rewards"].items():
                if rewards.get("already_rewarded"):
                    continue
                # Try to mention the player
                try:
                    member = interaction.guild.get_member(int(player_id))
                    mention = member.mention if member else f"<@{player_id}>"
                except Exception:
                    mention = f"<@{player_id}>"
                await interaction.followup.send(
                    content=mention,
                    embed=reward_embed(rewards, "🎁 Your Raid Rewards"),
                )


async def setup(bot: commands.Bot):
    await bot.add_cog(RaidCog(bot))
