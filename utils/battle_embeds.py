"""
Battle presentation embed builders and interactive views.
"""
from __future__ import annotations
import discord

from config.game_config import (
    BOSS_PORTRAIT_RIOT_IDS,
    RAID_BOSS_PORTRAIT_RIOT_ID,
    HUNT_ZONES,
)


DIVIDER = "─────────────────────────────"

# Zone display-name -> zone key (HUNT_ZONES stores display names in "name")
_ZONE_NAME_TO_KEY = {cfg["name"]: key for key, cfg in HUNT_ZONES.items()}


def _zone_key(battle_session) -> str:
    zone = getattr(battle_session, "zone", "") or ""
    if zone in HUNT_ZONES:
        return zone
    return _ZONE_NAME_TO_KEY.get(zone, "")


def _boss_portrait_url(battle_session) -> str:
    """Riot Data Dragon loading-screen art for this battle's boss."""
    if getattr(battle_session, "battle_type", "") == "raid":
        riot_id = RAID_BOSS_PORTRAIT_RIOT_ID
    else:
        riot_id = BOSS_PORTRAIT_RIOT_IDS.get(_zone_key(battle_session), "")
    if not riot_id:
        return ""
    return f"https://ddragon.leagueoflegends.com/cdn/img/champion/loading/{riot_id}_0.jpg"


def progress_bar(current, maximum, length: int = 16) -> str:
    if maximum <= 0:
        return "░" * length
    ratio = max(0.0, min(1.0, current / maximum))
    filled = round(ratio * length)
    return "█" * filled + "░" * (length - filled)


def hp_display(current, maximum) -> str:
    return f"{int(current):,} / {int(maximum):,}\n{progress_bar(current, maximum)}"


def mana_compact(mana_states: dict) -> str:
    lines = []
    for name, mana in mana_states.items():
        if mana >= 100:
            lines.append(f"{name[:8]} ✨ULT")
        else:
            lines.append(f"{name[:8]} {mana}/100")
    return "\n".join(lines)


def champion_status_icon(hp, hp_max) -> str:
    if hp == 0:
        return "☠️"
    if hp_max <= 0:
        return "🔴"
    ratio = hp / hp_max
    if ratio > 0.6:
        return "🟢"
    if ratio > 0.3:
        return "🟡"
    return "🔴"


def _title_for(battle_type: str, zone_name: str) -> str:
    if battle_type == "boss":
        return "🏰 BOSS BATTLE"
    if battle_type == "raid":
        return "🔴 RAID"
    return f"⚔️ {zone_name} Battle"


def build_initial_embed(zone_name, player_names, enemy_name, battle_type, banner_url="", zone_key="") -> discord.Embed:
    embed = discord.Embed(
        title=_title_for(battle_type, zone_name),
        description="⚙️ Preparing for battle...",
        color=0x5865F2,
    )
    roster = "\n".join(f"• {n}" for n in player_names) or "—"
    embed.add_field(name="⚔️ Your Team", value=roster, inline=True)
    embed.add_field(name="🐲 Enemy", value=enemy_name or "—", inline=True)
    if banner_url:
        embed.set_image(url=banner_url)
    # Boss portrait thumbnail from the start
    if battle_type == "raid":
        riot_id = RAID_BOSS_PORTRAIT_RIOT_ID
    else:
        riot_id = BOSS_PORTRAIT_RIOT_IDS.get(zone_key, "")
    if riot_id:
        embed.set_thumbnail(
            url=f"https://ddragon.leagueoflegends.com/cdn/img/champion/loading/{riot_id}_0.jpg"
        )
    return embed


def build_battle_embed(battle_session, round_snapshot, zone_name, player_names, banner_url="") -> discord.Embed:
    rs = round_snapshot
    # Recent events from last 2 rounds
    rounds = battle_session.simulated_rounds
    idx = rs["round"] - 1
    recent = []
    for r in rounds[max(0, idx - 1): idx + 1]:
        recent.extend(r.get("events", []))
    recent_text = "\n".join(recent[-8:]) or "—"

    desc = (
        f"{DIVIDER}\n"
        f"**Enemy**\n{hp_display(rs['enemy_hp'], rs['enemy_hp_max'])}\n\n"
        f"**Your Team**\n{hp_display(rs['player_hp'], rs['player_hp_max'])}\n"
        f"{DIVIDER}\n"
        f"Round {rs['round']} / {battle_session.max_rounds}\n\n"
        f"**Recent Events:**\n{recent_text}\n"
        f"{DIVIDER}\n"
        f"**Mana:**\n{mana_compact(rs.get('mana_states', {}))}"
    )
    embed = discord.Embed(
        title=_title_for(battle_session.battle_type, zone_name),
        description=desc[:4000],
        color=0xE67E22,
    )
    embed.set_footer(text=f"{battle_session.id} | {battle_session.status}")
    if banner_url:
        embed.set_image(url=banner_url)
    return embed


def build_final_embed(battle_session, final_snapshot, zone_name, winner, banner_url="") -> discord.Embed:
    rs = final_snapshot or {}
    if winner == 0:
        title = "🏆 VICTORY"
        color = 0x00CC44
    else:
        title = "💀 DEFEAT"
        color = 0xFF0000
    desc = (
        f"{DIVIDER}\n"
        f"**Enemy**\n{hp_display(rs.get('enemy_hp', 0), rs.get('enemy_hp_max', 0))}\n\n"
        f"**Your Team**\n{hp_display(rs.get('player_hp', 0), rs.get('player_hp_max', 0))}\n"
        f"{DIVIDER}"
    )
    embed = discord.Embed(title=title, description=desc[:4000], color=color)
    embed.set_footer(text=f"{battle_session.id} | {battle_session.status}")
    if banner_url:
        embed.set_image(url=banner_url)
    return embed


# ---------------------------------------------------------------------------
# Cancel battle interactive view
# ---------------------------------------------------------------------------
class _ConfirmCancelView(discord.ui.View):
    def __init__(self, battle_session_id: str, owner_id: str, timeout: float = 30.0):
        super().__init__(timeout=timeout)
        self.battle_session_id = battle_session_id
        self.owner_id = owner_id

    @discord.ui.button(label="Confirm Cancel", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.owner_id:
            await interaction.response.send_message("Only the battle owner can cancel.", ephemeral=True)
            return
        from services.battle_presentation_service import cancel_battle
        ok = await cancel_battle(self.battle_session_id, "CANCELLED_BY_USER", session=None)
        msg = "Battle cancelled. No rewards granted." if ok else "Battle already finished."
        self.stop()
        await interaction.response.edit_message(content=msg, embed=None, view=None)

    @discord.ui.button(label="Continue Battle", style=discord.ButtonStyle.secondary)
    async def keep(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="Battle continues.", embed=None, view=None)


class CancelBattleView(discord.ui.View):
    def __init__(self, battle_session_id: str, owner_id: str = "", timeout: float | None = None):
        super().__init__(timeout=timeout)
        self.battle_session_id = battle_session_id
        self.owner_id = owner_id

    @discord.ui.button(label="❌ Cancel Battle", style=discord.ButtonStyle.danger)
    async def cancel_battle_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.owner_id and str(interaction.user.id) != self.owner_id:
            await interaction.response.send_message("Only the battle owner can cancel.", ephemeral=True)
            return
        embed = discord.Embed(
            title="Cancel this battle?",
            description="Cancel this battle? You will receive no rewards.",
            color=0xFF0000,
        )
        view = _ConfirmCancelView(self.battle_session_id, self.owner_id or str(interaction.user.id))
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
