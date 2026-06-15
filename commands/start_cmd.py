import discord
from discord import app_commands
from discord.ext import commands

from models.user import User
from utils.embeds import error_embed, TutorialView
from utils.locks import get_user_lock
from config.game_config import STARTER_SUMMON_TOKENS, STARTER_GOLD


class AlreadyRegisteredError(Exception):
    """Raised when a user that is already registered runs /start again."""


async def register_user(discord_id: str, username: str) -> User:
    """Register a user, granting starter rewards.

    Raises AlreadyRegisteredError if the user is already registered.
    """
    user = await User.find_one(User.discord_id == discord_id)
    if user and user.registered:
        raise AlreadyRegisteredError("You're already registered!")

    if not user:
        user = User(discord_id=discord_id, username=username)

    user.registered = True
    user.summon_tokens += STARTER_SUMMON_TOKENS
    user.gold += STARTER_GOLD

    if user.id is None:
        await user.insert()
    else:
        await user.save()
    return user


def build_tutorial_pages() -> list[discord.Embed]:
    pages_text = [
        (
            "🎮 Welcome to LoLAuto RPG!",
            "You've received:\n"
            "• 10 Summon Tokens (enough for 1x10 pull)\n"
            "• 500 Gold\n\n"
            "This is an auto-battler RPG based on League of Legends champions.\n"
            "You collect champions, build teams, and watch them fight automatically.\n\n"
            "[1/5] Use the buttons below to continue.",
        ),
        (
            "⚔️ Champions",
            "• Use /summon multi to do your first 10-pull and get champions\n"
            "• Champions come in ranks: F → E → D → C → B → A → S\n"
            "• Fuse 3 identical same-rank champions to get one of the next rank\n"
            "• Use /champions to view your collection\n\n"
            "Champions have 2 skills:\n"
            "• Basic Skill — used when Mana < 100\n"
            "• Ultimate Skill — used automatically at 100 Mana\n\n"
            "[2/5]",
        ),
        (
            "🛡️ Teams & Combat",
            "• Use /team set to build a team of up to 5 champions\n"
            "• Use /formation set to arrange front row (positions 1-2) and back row (3-5)\n"
            "• Front row gets +10% Defense, back row gets +5% Attack\n"
            "• Use /hunt to send your team to fight and earn rewards\n\n"
            "Combat is fully automatic — no input needed during battle!\n\n"
            "[3/5]",
        ),
        (
            "⚒️ Items & Blacksmith",
            "• Items drop from hunts and summons\n"
            "• Equip up to 5 items per champion with /items equip\n"
            "• Enhance items +0 → +15 at /blacksmith enhance\n"
            "• +0 to +7: Safe (item never destroyed on fail)\n"
            "• +8 to +15: RISKY — failed attempts destroy the item!\n"
            "• Use a Blacksmith's Seal to protect against destruction\n"
            "• Fuse 3 identical +0 items of same rank for a higher rank\n\n"
            "[4/5]",
        ),
        (
            "🏪 Economy & Raids",
            "• /market — buy and sell champions and items with other players\n"
            "• /trade — direct player-to-player trades\n"
            "• /raid queue — team up with up to 4 other players for raid bosses\n"
            "• /summon single or /summon multi — spend tokens for champions and items\n"
            "• /profile — view your stats, gold, and tokens\n\n"
            "Ready to start? Try /summon multi for your first 10 pulls!\n\n"
            "[5/5]",
        ),
    ]
    return [
        discord.Embed(title=title, description=desc, color=0x5865F2)
        for title, desc in pages_text
    ]


class StartCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="start", description="Register and begin your adventure!")
    async def start(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)

        async with get_user_lock(uid):
            try:
                await register_user(uid, interaction.user.display_name)
            except AlreadyRegisteredError:
                await interaction.followup.send(
                    embed=error_embed("You're already registered!"),
                    ephemeral=True,
                )
                return

        pages = build_tutorial_pages()
        view = TutorialView(pages, interaction.user.id)
        await interaction.followup.send(embed=pages[0], view=view, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(StartCog(bot))
