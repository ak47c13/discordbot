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

    embed.set_footer(text=f"ID: {champ.id}")
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

    embed.set_footer(text=f"ID: {itm.id}")
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
