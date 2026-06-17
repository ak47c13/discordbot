import asyncio
import os
import traceback

import discord
from discord.ext import commands
from dotenv import load_dotenv

from database.connection import init_db
from models.battle_session import BattleSession
from models.user import User
from services.battle_presentation_service import (
    cancel_battle,
    resume_battle_presentation,
)

load_dotenv()

GUILD_ID = int(os.environ.get("GUILD_ID", 0))
# Comma-separated extra guild IDs to also sync commands to instantly
_EXTRA_GUILDS = [
    int(g) for g in os.environ.get("EXTRA_GUILD_IDS", "").split(",") if g.strip()
]
GUILD_IDS = ([GUILD_ID] if GUILD_ID else []) + _EXTRA_GUILDS

COGS = [
    "commands.start_cmd",
    "commands.profile",
    "commands.champion_select_cmd",
    "commands.skill_cmd",
    "commands.rune_cmd",
    "commands.champions_cmd",
    "commands.items_cmd",
    "commands.team_cmd",
    "commands.blacksmith_cmd",
    "commands.dungeon_cmd",
    "commands.raid_cmd",
    "commands.market_cmd",
    "commands.trade_cmd",
    "commands.help_cmd",
    "commands.glossary_cmd",
    "commands.shop_cmd",
]


class AutoBattlerBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = True
        intents.messages = True
        super().__init__(command_prefix="!", intents=intents)

    async def require_registration(self, interaction: discord.Interaction) -> bool:
        # Allow /start and /help through always
        if interaction.command and interaction.command.name in ("start", "help"):
            return True
        # Check registration
        user = await User.find_one(User.discord_id == str(interaction.user.id))
        if not user or not user.registered:
            await interaction.response.send_message(
                "❌ You haven't registered yet! Use `/start` to begin your adventure.",
                ephemeral=True,
            )
            return False
        return True

    async def setup_hook(self):
        await init_db()
        from data.champion_skills import validate_champion_skills
        validate_champion_skills()
        self.tree.interaction_check = self.require_registration
        for cog in COGS:
            try:
                await self.load_extension(cog)
                print(f"  ✓ Loaded {cog}")
            except Exception as e:
                print(f"  ✗ Failed to load {cog}: {e}")
                traceback.print_exc()

        # Sync slash commands to all configured guilds for instant propagation
        if GUILD_IDS:
            for gid in GUILD_IDS:
                guild = discord.Object(id=gid)
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
                print(f"  ✓ Slash commands synced to guild {gid}")
        else:
            await self.tree.sync()
            print("  ✓ Slash commands synced globally")

    async def on_ready(self):
        print(f"\n🤖 {self.user} is online!")
        print(f"   Guilds: {[g.name for g in self.guilds]}")
        await self.change_presence(
            activity=discord.Game(name="Auto-Battler RPG | /dungeon-enter")
        )

        # Resume any ACTIVE battle sessions that lost their worker on restart.
        try:
            active_sessions = await BattleSession.find(
                BattleSession.status == "ACTIVE"
            ).to_list()
            for bs in active_sessions:
                if bs.displayed_round_count < bs.simulated_round_count:
                    asyncio.create_task(resume_battle_presentation(bs, self))
        except Exception as e:
            print(f"   ⚠️ Battle recovery failed: {e}")

    async def on_message_delete(self, message):
        # Cancel a battle if its presentation message is deleted.
        try:
            session = await BattleSession.find_one(
                BattleSession.message_id == str(message.id),
                BattleSession.status == "ACTIVE",
            )
            if session:
                await cancel_battle(
                    str(session.id), "CANCELLED_MESSAGE_DELETED", session=None
                )
        except Exception:
            pass

    async def on_app_command_error(
        self,
        interaction: discord.Interaction,
        error: discord.app_commands.AppCommandError,
    ):
        msg = f"An unexpected error occurred: {type(error).__name__}"
        print(f"Command error: {error}")
        traceback.print_exc()
        try:
            if interaction.response.is_done():
                await interaction.followup.send(
                    embed=discord.Embed(title="❌ Error", description=msg, color=0xFF3333),
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    embed=discord.Embed(title="❌ Error", description=msg, color=0xFF3333),
                    ephemeral=True,
                )
        except Exception:
            pass


def main():
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN not set in environment.")

    bot = AutoBattlerBot()
    asyncio.run(bot.start(token))


if __name__ == "__main__":
    main()
