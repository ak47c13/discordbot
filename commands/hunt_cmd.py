import discord
from discord import app_commands
from discord.ext import commands

from models.user import User
from utils.embeds import reward_embed, error_embed
from utils.locks import get_user_lock
from utils.db_session import get_motor_client
from utils.idempotency import is_already_processed, mark_processed
from services.hunt_service import run_hunt, HuntError
from config.game_config import HUNT_ZONES


class HuntCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="hunt", description="Send your team on a hunt.")
    @app_commands.describe(zone="Zone to hunt in")
    @app_commands.choices(zone=[
        app_commands.Choice(name=v["name"], value=k)
        for k, v in HUNT_ZONES.items()
    ])
    async def hunt(self, interaction: discord.Interaction, zone: str):
        await interaction.response.defer()
        uid = str(interaction.user.id)

        # Idempotency guard
        iid = str(interaction.id)
        if await is_already_processed(iid):
            await interaction.followup.send(embed=error_embed("This command was already processed."))
            return

        await User.get_or_create(uid, interaction.user.display_name)

        async with get_user_lock(uid):
            client = get_motor_client()
            async with await client.start_session() as session:
                async with session.start_transaction():
                    try:
                        outcome = await run_hunt(uid, zone, session)
                    except HuntError as e:
                        await interaction.followup.send(embed=error_embed(str(e)))
                        return

        await mark_processed(iid, f"hunt:{zone}")

        result = outcome["battle_result"]
        zone_name = outcome["zone"]
        is_boss = outcome["is_boss"]
        is_elite = outcome["is_elite"]

        # Battle summary embed
        enemy_type = "🐉 Boss" if is_boss else ("⚡ Elite" if is_elite else "👹 Mob")
        winner_text = "🏆 Victory!" if result.winner == 0 else ("💀 Defeat" if result.winner == 1 else "⏳ Draw")

        embed = discord.Embed(
            title=f"{zone_name} — {enemy_type}",
            description=f"**{winner_text}** in {result.rounds} rounds.",
            color=0x00CC44 if result.winner == 0 else 0xFF0000,
        )

        # Truncated battle log (last 10 lines)
        log_lines = [l for l in outcome["battle_log"] if l.strip()][-10:]
        if log_lines:
            embed.add_field(
                name="⚔️ Battle Log (last 10 lines)",
                value="\n".join(log_lines)[:1000],
                inline=False,
            )

        await interaction.followup.send(embed=embed)

        if result.winner == 0 and outcome["rewards"]["gold"] > 0:
            await interaction.followup.send(
                embed=reward_embed(outcome["rewards"], f"🎁 Hunt Rewards — {zone_name}")
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(HuntCog(bot))
