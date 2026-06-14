import discord
from discord import app_commands
from discord.ext import commands

from models.user import User
from models.raid import RaidQueue
from utils.embeds import reward_embed, error_embed, success_embed
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
            title=f"⚔️ Raid Queue Created — {HUNT_ZONES[zone]['name']}",
            description=(
                f"Players can join with `/raid-join {raid.id}`\n"
                f"Leader starts with `/raid-start {raid.id}`\n"
                f"Max 5 players."
            ),
            color=0x5865F2,
        )
        embed.add_field(name="Raid ID", value=f"`{raid.id}`", inline=False)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="raid-join", description="Join an existing raid queue.")
    @app_commands.describe(raid_id="Raid ID", champion_id="Your champion ID for this raid")
    async def raid_join(self, interaction: discord.Interaction, raid_id: str, champion_id: str):
        await interaction.response.defer()
        uid = str(interaction.user.id)
        await User.get_or_create(uid, interaction.user.display_name)

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
                f"You joined the raid! ({len(raid.player_ids)}/5 players)"
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

        async with get_user_lock(uid):
            client = get_motor_client()
            async with await client.start_session() as session:
                async with session.start_transaction():
                    try:
                        outcome = await start_raid(uid, raid_id, session)
                    except RaidError as e:
                        await interaction.followup.send(embed=error_embed(str(e)))
                        return

        await mark_processed(iid, f"raid_start:{raid_id}")

        result = outcome["battle_result"]
        winner_text = "🏆 Victory!" if result.winner == 0 else ("💀 Defeat" if result.winner == 1 else "⏳ Draw")

        embed = discord.Embed(
            title=f"Raid Complete — {winner_text}",
            description=f"Battle lasted {result.rounds} rounds.",
            color=0x00CC44 if result.winner == 0 else 0xFF0000,
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
