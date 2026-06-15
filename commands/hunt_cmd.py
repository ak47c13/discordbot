import discord
from discord import app_commands
from discord.ext import commands

from models.user import User
from utils.embeds import reward_embed, error_embed, success_embed
from utils.locks import get_user_lock
from utils.db_session import get_motor_client
from utils.idempotency import is_already_processed, mark_processed
from services.hunt_service import run_hunt, start_hunt, HuntError
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

        # start_hunt manages its own short-lived transactions internally:
        #   1. atomic setup (validate + deduct stamina)
        #   2. CPU-only simulation + round-by-round reveal (NO transaction, sleeps)
        #   3. reward granting in its own transaction
        # This keeps any single transaction short so MongoDB Atlas does not abort
        # it as a long-running transaction (TransientTransactionError).
        try:
            async with get_user_lock(uid):
                try:
                    # The initial battle message is sent via interaction.followup,
                    # which resolves the deferred "Bot is thinking..." state
                    # immediately while keeping the message editable for the reveal.
                    await start_hunt(
                        uid, zone, None,
                        discord_channel=interaction.channel,
                        followup=interaction.followup,
                    )
                except HuntError as e:
                    await interaction.followup.send(embed=error_embed(str(e)))
                    return
        except Exception as e:
            # Always resolve the interaction so it never hangs on "thinking".
            try:
                await interaction.followup.send(
                    embed=error_embed("Something went wrong starting your hunt.", str(e)[:200])
                )
            except Exception:
                pass
            return

        await mark_processed(iid, f"hunt:{zone}")


async def setup(bot: commands.Bot):
    await bot.add_cog(HuntCog(bot))
