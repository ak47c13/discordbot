import asyncio
import os
import traceback

import discord
from discord.ext import commands
from dotenv import load_dotenv

from database.connection import init_db

load_dotenv()

GUILD_ID = int(os.environ.get("GUILD_ID", 0))

COGS = [
    "commands.profile",
    "commands.team_cmd",
    "commands.champions_cmd",
    "commands.items_cmd",
    "commands.blacksmith_cmd",
    "commands.hunt_cmd",
    "commands.raid_cmd",
    "commands.market_cmd",
    "commands.trade_cmd",
    "commands.summon_cmd",
]


class AutoBattlerBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await init_db()
        for cog in COGS:
            try:
                await self.load_extension(cog)
                print(f"  ✓ Loaded {cog}")
            except Exception as e:
                print(f"  ✗ Failed to load {cog}: {e}")
                traceback.print_exc()

        # Sync slash commands to the guild for instant propagation
        if GUILD_ID:
            guild = discord.Object(id=GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            print(f"  ✓ Slash commands synced to guild {GUILD_ID}")
        else:
            await self.tree.sync()
            print("  ✓ Slash commands synced globally")

    async def on_ready(self):
        print(f"\n🤖 {self.user} is online!")
        print(f"   Guilds: {[g.name for g in self.guilds]}")
        await self.change_presence(
            activity=discord.Game(name="Auto-Battler RPG | /hunt")
        )

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
                    embed=discord.Embed(title="❌ Error", description=msg, color=0xFF0000),
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    embed=discord.Embed(title="❌ Error", description=msg, color=0xFF0000),
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
