"""
Centralised Discord embed builders.
"""
from __future__ import annotations
import discord
from config.game_config import AURA_COLOR_BY_RANK, get_aura, ENHANCEMENT_MULTIPLIER


def champion_embed(champ, title: str = "Champion") -> discord.Embed:
    from config.game_config import CHAMPION_BASE_STATS, CHAMPION_GROWTH_STATS, RANK_INDEX
    rank = champ.rank
    lvl = champ.level
    base = CHAMPION_BASE_STATS[rank]
    growth = CHAMPION_GROWTH_STATS[rank]
    hp  = base["hp"]  + growth["hp"]  * (lvl - 1)
    atk = base["atk"] + growth["atk"] * (lvl - 1)
    dfn = base["def"] + growth["def"] * (lvl - 1)

    color = AURA_COLOR_BY_RANK.get(rank, 0xFFFFFF)
    embed = discord.Embed(
        title=f"{title}: {champ.name} [{rank}]",
        color=color,
    )
    embed.add_field(name="Level", value=str(lvl), inline=True)
    embed.add_field(name="HP",    value=str(int(hp)),  inline=True)
    embed.add_field(name="ATK",   value=str(int(atk)), inline=True)
    embed.add_field(name="DEF",   value=str(int(dfn)), inline=True)

    flags = []
    if champ.locked:         flags.append("🔒 Locked")
    if champ.in_trade:       flags.append("🤝 In Trade")
    if champ.in_market:      flags.append("🏪 Listed")
    if champ.equipped_in_team: flags.append("⚔️ In Team")
    if flags:
        embed.add_field(name="Status", value=" | ".join(flags), inline=False)

    return embed


def item_embed(itm, title: str = "Item") -> discord.Embed:
    rank = itm.rank
    enh = itm.enhancement
    aura = get_aura(enh)
    color = AURA_COLOR_BY_RANK.get(rank, 0xFFFFFF)
    mult = ENHANCEMENT_MULTIPLIER.get(enh, 0.0)
    eff_stat = int(itm.main_stat_base * (1 + mult))

    embed = discord.Embed(
        title=f"{title}: {aura}{itm.name} [{rank}] +{enh}",
        color=color,
    )
    embed.add_field(
        name=f"Main Stat ({itm.main_stat_type.upper()})",
        value=f"{eff_stat} ({itm.main_stat_base} base, +{int(mult*100)}%)",
        inline=False,
    )
    embed.add_field(name="Passive", value=itm.passive_name, inline=True)
    embed.add_field(
        name="Secondary",
        value=f"{itm.secondary_stat_type}: {itm.secondary_stat_value/10:.1f}",
        inline=True,
    )

    flags = []
    if itm.locked:       flags.append("🔒 Locked")
    if itm.favorited:    flags.append("⭐ Fav")
    if itm.in_trade:     flags.append("🤝 In Trade")
    if itm.in_market:    flags.append("🏪 Listed")
    if itm.equipped_to:  flags.append("⚔️ Equipped")
    if flags:
        embed.add_field(name="Status", value=" | ".join(flags), inline=False)

    return embed


def reward_embed(rewards: dict, title: str = "Rewards") -> discord.Embed:
    embed = discord.Embed(title=title, color=0xFFD700)
    if rewards.get("gold"):
        embed.add_field(name="💰 Gold", value=str(rewards["gold"]), inline=True)
    if rewards.get("seals"):
        embed.add_field(name="🔏 Blacksmith's Seal", value=str(rewards["seals"]), inline=True)
    if rewards.get("summon_tokens"):
        embed.add_field(name="🎟️ Summon Tokens", value=str(rewards["summon_tokens"]), inline=True)
    if rewards.get("champions"):
        lines = [f"• {c['name']} [{c['rank']}]" for c in rewards["champions"]]
        embed.add_field(name="🏆 Champions", value="\n".join(lines), inline=False)
    if rewards.get("items"):
        lines = [f"• {i['name']} [{i['rank']}]" for i in rewards["items"]]
        embed.add_field(name="⚔️ Items", value="\n".join(lines), inline=False)
    return embed


RANK_ORDER = {"S": 6, "A": 5, "B": 4, "C": 3, "D": 2, "E": 1, "F": 0}


def sort_champions(champions):
    return sorted(champions, key=lambda c: (-RANK_ORDER.get(c.rank, 0), -c.level, c.name))


def sort_items(items):
    return sorted(items, key=lambda i: (-RANK_ORDER.get(i.rank, 0), -i.enhancement, i.name))


async def get_champion_by_number(owner_id: str, number: int):
    """Get a champion by its 1-based position in the sorted list."""
    from models.champion import ChampionInstance
    all_champs = await ChampionInstance.find(ChampionInstance.owner_id == owner_id).to_list()
    sorted_champs = sort_champions(all_champs)
    if 1 <= number <= len(sorted_champs):
        return sorted_champs[number - 1]
    return None


async def get_item_by_number(owner_id: str, number: int):
    """Get an item by its 1-based position in the sorted list."""
    from models.item import ItemInstance
    all_items = await ItemInstance.find(ItemInstance.owner_id == owner_id).to_list()
    sorted_items = sort_items(all_items)
    if 1 <= number <= len(sorted_items):
        return sorted_items[number - 1]
    return None


PAGE_SIZE = 10


def _champion_page_embed(champs, page: int) -> discord.Embed:
    total = len(champs)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    start = page * PAGE_SIZE
    chunk = champs[start:start + PAGE_SIZE]

    lines = []
    for i, c in enumerate(chunk, start=start + 1):
        flags = []
        if c.locked:                flags.append("🔒")
        if getattr(c, "favorite", False): flags.append("⭐")
        if c.equipped_in_team:      flags.append("⚔️")
        if c.in_market:             flags.append("🏪")
        if c.in_trade:              flags.append("🤝")
        suffix = ("  " + " ".join(flags)) if flags else ""
        lines.append(f"#{i:<3} {c.name}  [{c.rank}] Lv.{c.level}{suffix}")

    desc = "\n".join(lines) if lines else "*No champions.*"
    desc += (
        "\n\nUse `/champion-info <number>` to view details."
        "\nUse `/team-add <number> <slot>` to add to team."
    )
    embed = discord.Embed(
        title=f"🏆 Your Champions ({total} total) — Page {page + 1}/{total_pages}",
        description=desc,
        color=0x5865F2,
    )
    return embed


def _item_page_embed(items, page: int) -> discord.Embed:
    total = len(items)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    start = page * PAGE_SIZE
    chunk = items[start:start + PAGE_SIZE]

    lines = []
    for i, itm in enumerate(chunk, start=start + 1):
        flags = []
        if itm.locked:       flags.append("🔒")
        if itm.favorited:    flags.append("⭐")
        if itm.in_market:    flags.append("🏪")
        if itm.in_trade:     flags.append("🤝")
        if itm.equipped_to:
            flags.append(f"⚔️{itm.main_stat_type}")
        suffix = ("  " + " ".join(flags)) if flags else ""
        lines.append(f"#{i:<3} {itm.name}  [{itm.rank}] +{itm.enhancement}{suffix}")

    desc = "\n".join(lines) if lines else "*No items.*"
    desc += "\n\nUse `/item-info <number>` to view details."
    embed = discord.Embed(
        title=f"🎒 Your Items ({total} total) — Page {page + 1}/{total_pages}",
        description=desc,
        color=0x5865F2,
    )
    return embed


class _PaginatedView(discord.ui.View):
    def __init__(self, entries, user_id: int, embed_builder, timeout: float = 120.0):
        super().__init__(timeout=timeout)
        self.entries = entries
        self.user_id = user_id
        self._embed_builder = embed_builder
        self.index = 0
        self.total_pages = max(1, (len(entries) + PAGE_SIZE - 1) // PAGE_SIZE)
        self._refresh_buttons()

    def current_embed(self) -> discord.Embed:
        return self._embed_builder(self.entries, self.index)

    def _refresh_buttons(self):
        self.prev_button.disabled = self.index <= 0
        self.next_button.disabled = self.index >= self.total_pages - 1

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This list isn't yours.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.index > 0:
            self.index -= 1
        self._refresh_buttons()
        await interaction.response.edit_message(embed=self.current_embed(), view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.primary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.index < self.total_pages - 1:
            self.index += 1
        self._refresh_buttons()
        await interaction.response.edit_message(embed=self.current_embed(), view=self)


class PaginatedChampionView(_PaginatedView):
    def __init__(self, champions, user_id: int, timeout: float = 120.0):
        super().__init__(sort_champions(champions), user_id, _champion_page_embed, timeout)


class PaginatedItemView(_PaginatedView):
    def __init__(self, items, user_id: int, timeout: float = 120.0):
        super().__init__(sort_items(items), user_id, _item_page_embed, timeout)


def error_embed(message: str) -> discord.Embed:
    return discord.Embed(title="❌ Error", description=message, color=0xFF0000)


def success_embed(message: str, title: str = "✅ Success") -> discord.Embed:
    return discord.Embed(title=title, description=message, color=0x00CC44)


class ConfirmView(discord.ui.View):
    """Generic Confirm / Cancel button view for destructive actions."""

    def __init__(self, timeout: float = 30.0):
        super().__init__(timeout=timeout)
        self.confirmed: bool | None = None

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = True
        self.stop()
        await interaction.response.defer()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = False
        self.stop()
        await interaction.response.defer()


class TutorialView(discord.ui.View):
    """Paginated tutorial with Back / Next / Let's Go! buttons.

    Only the user who triggered /start may interact. Buttons update their
    disabled state to reflect the current page.
    """

    def __init__(self, pages: list[discord.Embed], user_id: int, timeout: float = 120.0):
        super().__init__(timeout=timeout)
        self.pages = pages
        self.user_id = user_id
        self.index = 0
        self._refresh_buttons()

    def _refresh_buttons(self):
        last = len(self.pages) - 1
        self.back_button.disabled = self.index == 0
        self.next_button.disabled = self.index >= last
        # "Let's Go!" only on the last page
        self.go_button.disabled = self.index != last

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This tutorial isn't yours. Use `/start` to begin your own.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="◀ Back", style=discord.ButtonStyle.secondary)
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.index > 0:
            self.index -= 1
        self._refresh_buttons()
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

    @discord.ui.button(label="▶ Next", style=discord.ButtonStyle.primary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.index < len(self.pages) - 1:
            self.index += 1
        self._refresh_buttons()
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

    @discord.ui.button(label="✅ Let's Go!", style=discord.ButtonStyle.success)
    async def go_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children:
            child.disabled = True
        self.stop()
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)


class RerollPreviewView(discord.ui.View):
    """Accept / Reject view for reroll preview."""

    def __init__(self, timeout: float = 60.0):
        super().__init__(timeout=timeout)
        self.accepted: bool | None = None

    @discord.ui.button(label="Accept New Roll", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.accepted = True
        self.stop()
        await interaction.response.defer()

    @discord.ui.button(label="Keep Old Roll", style=discord.ButtonStyle.secondary)
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.accepted = False
        self.stop()
        await interaction.response.defer()
