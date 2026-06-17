import discord
from discord import app_commands
from discord.ext import commands

from models.user import User
from utils.embeds import error_embed, TutorialView, COLOR_INFO, build_summon_result_embed
from utils.locks import get_user_lock
from config.game_config import STARTER_SUMMON_TOKENS, STARTER_GOLD
from utils.db_session import get_motor_client


class AlreadyRegisteredError(Exception):
    """Raised when a user that is already registered runs /start again."""


FREE_RUNE_PULLS = 3
FREE_GEAR_PULLS = 1


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


async def do_starter_pulls(discord_id: str) -> list[dict]:
    """Perform FREE starter pulls (no token cost) for a new user.

    Returns list of summon result dicts.
    """
    from services.summon_service import _roll_summon
    client = get_motor_client()
    results = []
    async with await client.start_session() as session:
        for _ in range(FREE_RUNE_PULLS):
            r = await _roll_summon(discord_id, session, pool_type="rune")
            results.append(r)
        for _ in range(FREE_GEAR_PULLS):
            r = await _roll_summon(discord_id, session, pool_type="item")
            results.append(r)
    return results


def build_tutorial_pages() -> list[discord.Embed]:
    pages_text = [
        (
            "Welcome to LoLAuto RPG!",
            "You've received:\n"
            "• 10 Summon Tokens (enough for a 10-pull)\n"
            "• 5,000 Gold\n"
            "• 3 Free Rune Pulls + 1 Free Gear Pull (see your DMs below)\n\n"
            "This is an auto-battler RPG based on League of Legends champions.\n"
            "You collect champions, equip gear and runes, and watch them fight automatically.\n\n"
            "[1/5] Use the buttons below to continue.",
        ),
        (
            "Champions",
            "• Use /shop → Champions to pull champions with tokens\n"
            "• Champions rank up: F → E → D → C → B → A → S\n"
            "• Fuse 3 identical same-rank champions to get one of the next rank\n"
            "• Use /champions to view your collection\n\n"
            "Each champion has 4 skills:\n"
            "• Q / W / E — basic skills (one fires each round, your choice)\n"
            "• R — ultimate, fires automatically at 100 Mana\n\n"
            "[2/5]",
        ),
        (
            "Combat & Dungeons",
            "• Use /champion-select <id> to set your active champion\n"
            "• Use /skill set to choose which basic skill (Q/W/E) fires each round\n"
            "• Use /dungeon-enter to fight through floors and earn gold\n\n"
            "Each floor costs 1 Stamina. Stamina refills over time (1 every 6 min). "
            "Check it with /stamina.\n\n"
            "Combat is fully automatic — no input needed during battle!\n\n"
            "[3/5]",
        ),
        (
            "Gear & Runes",
            "• Gear (items) and Runes both come in ranks F → S\n"
            "• Pull gear and runes from /shop\n"
            "• Equip up to 6 items per champion with /equip\n"
            "• Equip runes with /runes set (check /runes catalog for IDs)\n"
            "• Enhance items +0 → +15 at /blacksmith enhance\n"
            "• +0 to +7: Safe  |  +8 to +15: RISKY — fails destroy the item!\n"
            "• Fuse 3 identical +0 items of same rank for a higher rank\n\n"
            "[4/5]",
        ),
        (
            "Economy & Raids",
            "• /market — buy and sell champions and items with other players\n"
            "• /trade — direct player-to-player trades\n"
            "• /raid queue — team up with up to 4 players for raid bosses\n"
            "• /shop — pull champions, gear, and runes; buy tokens with gold\n"
            "• /profile — view your stats, gold, and tokens\n\n"
            "Ready to start? Head to /shop and spend your 10 tokens on a champion pull!\n\n"
            "[5/5]",
        ),
    ]
    return [
        discord.Embed(title=title, description=desc, color=COLOR_INFO)
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

        # Free starter pulls (no token cost)
        try:
            pull_results = await do_starter_pulls(uid)
        except Exception:
            pull_results = []

        pages = build_tutorial_pages()
        view = TutorialView(pages, interaction.user.id)
        await interaction.followup.send(embed=pages[0], view=view, ephemeral=True)

        # Show free pull results as a followup
        if pull_results:
            from utils.embeds import build_summon_result_embed
            lines = []
            for r in pull_results:
                rtype = r.get("type", "")
                if rtype == "rune":
                    tier_label = {1: "Common", 2: "Uncommon", 3: "Rare"}.get(r.get("tier", 1), "Common")
                    lines.append(f"**{r['name']}** ({tier_label} Rune) — {r['description']}")
                elif rtype == "item":
                    lines.append(f"**{r['name']}** [{r.get('rank','F')}] {r.get('stat_type','').upper()} Gear")
                else:
                    lines.append(f"{rtype}: {r}")
            starter_embed = discord.Embed(
                title="Your Free Starter Pulls",
                description=(
                    f"**{FREE_RUNE_PULLS}× Free Rune Pulls + {FREE_GEAR_PULLS}× Free Gear Pull**\n\n"
                    + "\n".join(f"• {l}" for l in lines)
                    + "\n\nUse `/runes catalog` and `/runes set` to equip your runes.\n"
                    + "Use `/items equip` to equip your gear."
                ),
                color=0xAA44FF,
            )
            await interaction.followup.send(embed=starter_embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(StartCog(bot))
