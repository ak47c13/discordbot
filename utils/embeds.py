"""
Centralised Discord embed builders.
"""
from __future__ import annotations
import discord
from config.game_config import AURA_COLOR_BY_RANK, get_aura, ENHANCEMENT_MULTIPLIER


# ---------------------------------------------------------------------------
# Standard embed colors
# ---------------------------------------------------------------------------
COLOR_INFO      = 0x5865F2   # Discord blurple — general info
COLOR_SUCCESS   = 0x00CC44   # Green — success, rewards
COLOR_WARNING   = 0xFF8800   # Orange — needs confirmation
COLOR_DANGER    = 0xFF3333   # Red — errors, destruction
COLOR_GOLD      = 0xFFD700   # Gold — currency, rewards
COLOR_RANK = {
    "F": 0x888888, "E": 0x44BB44, "D": 0x4488FF,
    "C": 0xAA44FF, "B": 0xFF4444, "A": 0xFFAA00, "S": 0xCC44FF,
}


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
    if getattr(itm, "favorite", False): flags.append("⭐ Fav")
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
        if getattr(itm, "favorite", False): flags.append("⭐")
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

    @discord.ui.button(label="◀ Previous", style=discord.ButtonStyle.secondary)
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


# ---------------------------------------------------------------------------
# Summon reveal
# ---------------------------------------------------------------------------
_SUMMON_RANK_ORDER = {"F": 0, "E": 1, "D": 2, "C": 3, "B": 4, "A": 5, "S": 6}
_SUMMON_RANK_LABEL = {
    "F": "Common", "E": "Uncommon", "D": "Rare",
    "C": "Epic", "B": "Legendary", "A": "Mythic", "S": "Divine",
}
_SUMMON_STAT_EMOJI = {"atk": "⚔️", "def": "🛡️", "hp": "❤️"}
_SUMMON_REWARD_EMOJI = {"gold": "💰", "enhance_mat": "🔨", "reroll_mat": "🎲", "seal": "🔒"}


def _summon_title_prefix(rank: str) -> str:
    if rank == "B":
        return "⭐ Rare Pull! "
    if rank == "A":
        return "🌟 EPIC PULL! "
    if rank == "S":
        return "💎 LEGENDARY PULL! "
    return ""


def build_summon_result_embed(r: dict, footer: str = "") -> discord.Embed:
    """Build a detailed single-result embed (champion / item / reward)."""
    rtype = r["type"]
    rank = r.get("rank", "F")
    title_prefix = _summon_title_prefix(rank)
    color = COLOR_RANK.get(rank, 0x888888)

    if rtype == "champion":
        name = r["name"]
        from data.champion_roster import CHAMPION_ROSTER
        roster = CHAMPION_ROSTER.get(name, {})
        title_text = r.get("title") or roster.get("title", "The Unknown")
        role = (r.get("role") or roster.get("role", "fighter")).title()
        riot_id = r.get("riot_id") or roster.get("riot_id", name.replace(" ", "").replace("'", ""))

        from config.game_config import CHAMPION_BASE_STATS
        stats = CHAMPION_BASE_STATS.get(rank, {})

        embed = discord.Embed(
            title=f"{title_prefix}🎴 {name}",
            description=(
                f"*{title_text}*\n\n"
                f"**{_SUMMON_RANK_LABEL.get(rank, rank)} [{rank}] {role}**\n\n"
                f"❤️ HP: **{stats.get('hp', '?'):,}**\n"
                f"⚔️ ATK: **{stats.get('atk', '?')}**\n"
                f"🛡️ DEF: **{stats.get('def', '?')}**\n"
                f"💨 SPD: **{stats.get('spd', '?')}**"
            ),
            color=color,
        )
        embed.set_image(
            url=f"https://ddragon.leagueoflegends.com/cdn/img/champion/loading/{riot_id}_0.jpg"
        )
    elif rtype == "item":
        name = r["name"]
        stat_type = r.get("stat_type", "atk")
        passive = r.get("passive", "")
        secondary = r.get("secondary_stat", "")
        secondary_val = r.get("secondary_val", 0)
        embed = discord.Embed(
            title=f"{title_prefix}🎒 {name}",
            description=(
                f"**{_SUMMON_RANK_LABEL.get(rank, rank)} [{rank}] Item**\n\n"
                f"{_SUMMON_STAT_EMOJI.get(stat_type, '📊')} Main Stat: **{stat_type.upper()}**\n"
                f"✨ Passive: **{passive.replace('_passive', '').replace('_', ' ').title()}**\n"
                f"📊 Secondary: **{secondary.replace('_', ' ').title()} +{secondary_val/10:.1f}%**"
            ),
            color=color,
        )
    else:
        emoji = _SUMMON_REWARD_EMOJI.get(rtype, "🎁")
        amount = r.get("amount", 1)
        label = rtype.replace("_", " ").title()
        embed = discord.Embed(
            title=f"{emoji} {label}",
            description=f"You received **{amount}x {label}**!",
            color=0xFFD700,
        )

    if footer:
        embed.set_footer(text=footer)
    return embed


class SummonRevealView(discord.ui.View):
    def __init__(self, results: list[dict], user_id: int):
        super().__init__(timeout=120)
        self.results = self._sort_worst_first(results)
        self.user_id = user_id
        self.page = 0
        self._update_buttons()

    def _sort_worst_first(self, results):
        def sort_key(r):
            rank = r.get("rank", "F")
            rtype = 0 if r["type"] == "champion" else (1 if r["type"] == "item" else 2)
            return (_SUMMON_RANK_ORDER.get(rank, 0), rtype)
        return sorted(results, key=sort_key)

    def build_page_embed(self) -> discord.Embed:
        if self.page >= len(self.results):
            return self._build_summary_embed()
        r = self.results[self.page]
        footer = f"Pull {self.page + 1} / {len(self.results)} • Use ▶ to see next"
        return build_summon_result_embed(r, footer=footer)

    def _build_summary_embed(self) -> discord.Embed:
        from collections import Counter
        rank_counts = Counter(r.get("rank", "?") for r in self.results if r.get("rank"))
        lines = ["**Pull Summary**\n"]
        for rank in ["S", "A", "B", "C", "D", "E", "F"]:
            if rank in rank_counts and rank_counts[rank] > 0:
                lines.append(f"[{rank}] {_SUMMON_RANK_LABEL[rank]}: {rank_counts[rank]}x")
        best = max(
            self.results,
            key=lambda r: _SUMMON_RANK_ORDER.get(r.get("rank", "F"), 0),
            default=None,
        )
        if best:
            lines.append(f"\n✨ Best Pull: **{best.get('name', best['type'])}** [{best.get('rank', '?')}]")
        return discord.Embed(
            title="🎰 10-Pull Complete!",
            description="\n".join(lines),
            color=0xFFD700,
        )

    def _update_buttons(self):
        total_pages = len(self.results) + 1  # +1 for summary
        self.prev_btn.disabled = (self.page == 0)
        self.next_btn.disabled = (self.page >= total_pages - 1)
        self.page_btn.label = f"{self.page + 1}/{total_pages}"

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your summon!", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="◀ Previous", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = max(0, self.page - 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.build_page_embed(), view=self)

    @discord.ui.button(label="1/10", style=discord.ButtonStyle.secondary, disabled=True)
    async def page_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.primary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        total_pages = len(self.results) + 1
        self.page = min(total_pages - 1, self.page + 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.build_page_embed(), view=self)


def error_embed(message: str, hint: str = "") -> discord.Embed:
    """Standard error embed. Format: '❌ **Error:** {message}' with optional hint."""
    desc = f"**{message}**" if message.startswith("❌") else f"**Error:** {message}"
    if not message.startswith("❌"):
        desc = f"❌ {desc}"
    if hint:
        desc += f"\n\n💡 {hint}"
    return discord.Embed(description=desc, color=COLOR_DANGER)


def success_embed(message: str, title: str = "✅ Success") -> discord.Embed:
    return discord.Embed(title=title, description=message, color=COLOR_SUCCESS)


def info_embed(message: str, title: str = "") -> discord.Embed:
    return discord.Embed(title=title, description=message, color=COLOR_INFO)


def progress_bar(current: int, maximum: int, length: int = 16) -> str:
    if maximum <= 0:
        return "░" * length
    ratio = max(0.0, min(1.0, current / maximum))
    filled = round(ratio * length)
    return "█" * filled + "░" * (length - filled)


def apply_stamina_regen(user) -> bool:
    """Apply time-based stamina regeneration to a user in-memory.

    Returns True if the user's stamina/last_stamina_regen changed (caller should
    save). Does NOT save the document itself.
    """
    from datetime import datetime, timezone
    from config.game_config import STAMINA_REGEN_SECONDS

    if user.stamina >= user.max_stamina:
        # Keep the regen anchor fresh so we don't bank huge regen later.
        user.last_stamina_regen = datetime.now(timezone.utc)
        return False

    now = datetime.now(timezone.utc)
    last = user.last_stamina_regen or now
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    elapsed = (now - last).total_seconds()
    if elapsed <= 0:
        return False
    regen = int(elapsed // STAMINA_REGEN_SECONDS)
    if regen <= 0:
        return False
    new_stamina = min(user.max_stamina, user.stamina + regen)
    user.stamina = new_stamina
    # Advance the anchor by the consumed whole intervals (preserve remainder).
    from datetime import timedelta
    user.last_stamina_regen = last + timedelta(seconds=regen * STAMINA_REGEN_SECONDS)
    if user.stamina >= user.max_stamina:
        user.last_stamina_regen = now
    return True


def stamina_full_in(user) -> str:
    """Human-readable time until stamina is full."""
    from config.game_config import STAMINA_REGEN_SECONDS
    if user.stamina >= user.max_stamina:
        return "Full"
    missing = user.max_stamina - user.stamina
    secs = missing * STAMINA_REGEN_SECONDS
    h, rem = divmod(secs, 3600)
    m = rem // 60
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


class ConfirmView(discord.ui.View):
    """Generic Confirm / Cancel button view for destructive actions."""

    def __init__(self, timeout: float = 30.0):
        super().__init__(timeout=timeout)
        self.confirmed: bool | None = None
        self.message: discord.Message | None = None

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(
                    content="⏰ Confirmation expired. Run the command again.",
                    embed=None,
                    view=self,
                )
            except Exception:
                pass

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
