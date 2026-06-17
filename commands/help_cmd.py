import discord
from discord import app_commands
from discord.ext import commands

from utils.embeds import COLOR_INFO


HELP_TOPICS: dict[str, tuple[str, list[str]]] = {
    "getting-started": (
        "Getting Started",
        [
            "Welcome! Here's the core gameplay loop:\n\n"
            "1. **/start** — register and claim starter rewards\n"
            "2. **/summon** — spend tokens to pull champions, items, and runes\n"
            "3. **/champion-select** — set your active champion for battle\n"
            "4. **/dungeon-enter** — fight through floors and earn loot\n"
            "5. **/fuse-champions** — combine duplicates into stronger ranks\n\n"
            "Use **/daily** every day for free summon tokens.\n"
            "Use **/profile** to see your resources and **/stamina** to track energy.",
        ],
    ),
    "champions": (
        "Champions",
        [
            "**Ranks:** F → E → D → C → B → A → S (higher is stronger)\n\n"
            "**Fusion:** Combine 3 identical same-rank champions into 1 of the next rank.\n"
            "• `/fuse-champions <name> <rank>` — fuses your 3 lowest-level copies\n"
            "• `/champions-bulk-fuse <name> <rank> <count>` — fuse many at once\n"
            "• `/champions-duplicates` — see which champions are fusion-ready\n\n"
            "**Leveling:** `/levelup <number>` spends gold to raise a champion's level.\n"
            "Each rank has its own max level.\n\n"
            "**Protect:** `/lock-champion` and `/champion-favorite` shield champions "
            "from selling and fusing.",
        ],
    ),
    "items": (
        "Items",
        [
            "Items are equipped to champions for stat bonuses and passives.\n\n"
            "• `/items` — view your inventory (each item has a number)\n"
            "• `/equip <item_number> <champion_number> <slot>` — equip (up to 5 per champion)\n"
            "• `/fuse-items <name> <rank>` — combine 3 +0 items into the next rank\n"
            "• `/lock-item`, `/favorite-item` — protect items\n\n"
            "Each item has a **main stat**, a **passive**, and a **secondary stat** "
            "that can be rerolled at the blacksmith.",
        ],
    ),
    "blacksmith": (
        "Blacksmith",
        [
            "Improve your items:\n\n"
            "• **/enhance <number>** — +1 enhancement level (boosts main stat).\n"
            "  +0 to +7 is safe. +8 and above is RISKY — failure can destroy the item "
            "unless you use a Blacksmith's Seal.\n"
            "• **/clear <number>** — reset an item to +0 (keeps secondary stat, makes it fusible).\n"
            "• **/reroll <number>** — reroll secondary stat type AND value.\n"
            "• **/refine <number>** — reroll secondary stat value only (keeps type).\n\n"
            "Reroll and refine show a preview before you commit gold.",
        ],
    ),
    "combat": (
        "Combat",
        [
            "Battles are fully automatic. You select your champion; the engine fights.\n\n"
            "**Champion:** Use `/champion-select <id>` to set your active champion.\n"
            "Use `/skill set q/w/e` to choose which skill they use in battle.\n\n"
            "**Skills:** Each champion has Q/W/E basics and an R ultimate "
            "(auto-cast at 100 mana).\n\n"
            "**Dungeons:** Use `/dungeon-enter` to fight floor by floor. "
            "Progress is saved at checkpoints each floor.\n\n"
            "Battles play out round-by-round in a live message. Watch HP and mana update!",
        ],
    ),
    "economy": (
        "Economy",
        [
            "**Gold** — earned from hunts; spent on fusion, leveling, and blacksmith.\n"
            "**Summon Tokens** — spent on /summon; earned daily and from raids.\n\n"
            "**Market:** `/market-list-champion`, `/market-list-item`, `/market-browse`, "
            "`/market-search`, `/market-buy`, `/market-my-listings`, `/market-cancel`.\n"
            "Listings have a small fee; sales are taxed.\n\n"
            "**Trading:** `/trade-offer`, `/trade-accept`, `/trade-cancel`, `/trade-list` "
            "for direct player-to-player swaps.",
        ],
    ),
    "raids": (
        "Raids",
        [
            "Team up with up to 5 players against a powerful boss:\n\n"
            "• **/raid-create <zone>** — open a raid queue (you become leader)\n"
            "• **/raid-list** — see open raids and their IDs\n"
            "• **/raid-join <id> <champion_number>** — join with one champion\n"
            "• **/raid-start <id>** — leader starts the battle\n\n"
            "The boss scales with party size. Each player gets personal loot on victory.",
        ],
    ),
    "commands": (
        "Command List",
        [
            "**Account:** /start, /profile, /stamina, /daily, /leaderboard\n"
            "**Champions:** /champions, /champion-info, /fuse-champions, "
            "/champions-bulk-fuse, /champions-bulk-sell, /champions-duplicates, "
            "/levelup, /lock-champion, /champion-favorite\n"
            "**Items:** /items, /item-info, /fuse-items, /items-bulk-fuse, "
            "/items-bulk-sell, /lock-item, /favorite-item\n"
            "**Champion:** /champion-select, /skill, /runes, /champions, /champion-info\n"
            "**Blacksmith:** /enhance, /clear, /reroll, /refine\n"
            "**Combat:** /hunt, /raid-create, /raid-list, /raid-join, /raid-start\n"
            "**Economy:** /market-* , /trade-* , /summon, /summon-rates\n"
            "**Help:** /help",
        ],
    ),
}

TOPIC_LABELS = {
    "getting-started": "Getting Started",
    "champions": "Champions",
    "items": "Items",
    "blacksmith": "Blacksmith",
    "combat": "Combat",
    "economy": "Economy",
    "raids": "Raids",
    "commands": "Command List",
}


def _topic_embed(topic: str) -> discord.Embed:
    title, pages = HELP_TOPICS[topic]
    embed = discord.Embed(title=title, description=pages[0], color=COLOR_INFO)
    embed.set_footer(text="Pick another topic from the menu below.")
    return embed


def _main_embed() -> discord.Embed:
    embed = discord.Embed(
        title="Help",
        description=(
            "Welcome to the auto-battler RPG! Pick a topic below to learn more.\n\n"
            + "\n".join(f"• **{label}**" for label in TOPIC_LABELS.values())
        ),
        color=COLOR_INFO,
    )
    embed.set_footer(text="Use the menu below, or /help <topic>.")
    return embed


class HelpSelect(discord.ui.Select):
    def __init__(self, user_id: int):
        self.user_id = user_id
        options = [
            discord.SelectOption(label=label, value=key)
            for key, label in TOPIC_LABELS.items()
        ]
        super().__init__(placeholder="Choose a help topic…", options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This help menu isn't yours.", ephemeral=True)
            return
        await interaction.response.edit_message(embed=_topic_embed(self.values[0]), view=self.view)


class HelpView(discord.ui.View):
    def __init__(self, user_id: int, timeout: float = 180.0):
        super().__init__(timeout=timeout)
        self.add_item(HelpSelect(user_id))


class HelpCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="help", description="Learn how to play. Optionally pass a topic.")
    @app_commands.describe(topic="Specific help topic")
    @app_commands.choices(topic=[
        app_commands.Choice(name=label, value=key) for key, label in TOPIC_LABELS.items()
    ])
    async def help_cmd(self, interaction: discord.Interaction, topic: str = ""):
        await interaction.response.defer(ephemeral=True)
        view = HelpView(interaction.user.id)
        if topic and topic in HELP_TOPICS:
            embed = _topic_embed(topic)
        else:
            embed = _main_embed()
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(HelpCog(bot))
