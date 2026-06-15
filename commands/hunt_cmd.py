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

        # Run setup (validation, stamina, simulation) under the user lock and a
        # transaction. The round-by-round reveal (which sleeps) runs afterward;
        # rewards are granted atomically inside the presentation service.
        async with get_user_lock(uid):
            client = get_motor_client()
            async with await client.start_session() as session:
                async with session.start_transaction():
                    try:
                        await start_hunt(uid, zone, session, discord_channel=interaction.channel)
                    except HuntError as e:
                        await interaction.followup.send(embed=error_embed(str(e)))
                        return

        await mark_processed(iid, f"hunt:{zone}")
        # The battle message and reward message are sent by the presentation
        # service. Acknowledge the deferred interaction and show remaining stamina.
        try:
            fresh = await User.find_one(User.discord_id == uid)
            stamina_line = ""
            if fresh is not None:
                stamina_line = f"\n⚡ Stamina remaining: {fresh.stamina}/{fresh.max_stamina}"
            await interaction.followup.send(
                embed=success_embed("Battle started — watch the message above!" + stamina_line),
                ephemeral=True,
            )
        except Exception:
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(HuntCog(bot))
