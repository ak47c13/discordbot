import discord
from discord import app_commands
from discord.ext import commands
from models.user import User
from models.champion import ChampionInstance
from utils.embeds import error_embed, success_embed
from utils.locks import get_user_lock
from data.champion_skills import CHAMPION_SKILLS

SKILL_LABELS = {"q": "Q", "w": "W", "e": "E", "r": "R (Ultimate)"}
SKILL_EMOJI = {"q": "\U0001f5e1️", "w": "\U0001f6e1️", "e": "\U0001f300", "r": "\U0001f4a5"}

MECHANIC_LABELS = {
    "execute":        "Execute",
    "stack_damage":   "Stacking damage",
    "reset_on_kill":  "Mana reset on kill",
    "armor_shred":    "Armor shred",
    "drain":          "Drain (lifesteal)",
    "mark_detonate":  "Mark & detonate",
}


def _build_skill_detail(s: dict, rank: str = None) -> str:
    """Build the italic detail line shown under each skill description."""
    coeff = s.get("coeff", 0)
    dmg = s.get("damage_type", "none")
    hits = s.get("hits", 1)
    mana = s.get("mana_gain", 0)

    parts = [f"{coeff*100:.0f}% ATK {dmg}"]
    if hits > 1:
        parts[0] += f" × {hits} hits"
    if mana:
        parts.append(f"+{mana} mana")

    # Status effect
    status = s.get("status")
    if status:
        chance = s.get("status_chance", 1.0)
        dur = s.get("status_duration", 1)
        parts.append(f"{status} {chance*100:.0f}% ({dur}t)")

    # Mechanic
    mechanic = s.get("mechanic")
    if mechanic:
        label = MECHANIC_LABELS.get(mechanic, mechanic)
        mv = s.get("mechanic_value")
        if mv is not None:
            if mechanic == "execute":
                parts.append(f"{label} <{mv*100:.0f}% HP")
            elif mechanic == "stack_damage":
                parts.append(f"{label} +{mv*100:.0f}%/stack")
            elif mechanic == "armor_shred":
                parts.append(f"{label} {mv*100:.0f}%")
            elif mechanic == "mark_detonate":
                parts.append(f"{label} {mv}×")
            else:
                parts.append(f"{label} ({mv})")
        else:
            parts.append(label)

    # Heal / shield
    if s.get("heal_coeff"):
        parts.append(f"Heals {s['heal_coeff']*100:.0f}%")
    if s.get("shield_coeff"):
        parts.append(f"Shield {s['shield_coeff']*100:.0f}%")

    # Rank tier note
    if rank:
        from engine.skill_factory import RANK_ORDER
        rank_idx = RANK_ORDER.index(rank) if rank in RANK_ORDER else 0
        tier_note = None
        if rank_idx >= RANK_ORDER.index("A") and s.get("prestige"):
            tier_note = "Prestige tier active"
        elif rank_idx >= RANK_ORDER.index("C") and s.get("advanced"):
            tier_note = "Advanced tier active"
        if tier_note:
            parts.append(f"*{tier_note}*")

    return " • ".join(parts)


class SkillCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    skill_group = app_commands.Group(name="skill", description="Manage your active skill.")

    @skill_group.command(name="view", description="Show all 4 skills for your active champion.")
    async def skill_view(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        user = await User.find_one(User.discord_id == uid)
        if not user or not user.active_champion_id:
            await interaction.followup.send(embed=error_embed("No active champion. Use `/champion-select` first."), ephemeral=True)
            return
        champ = await ChampionInstance.get(user.active_champion_id)
        if not champ:
            await interaction.followup.send(embed=error_embed("Active champion not found."), ephemeral=True)
            return
        skills = CHAMPION_SKILLS.get(champ.name, {})
        rank = champ.rank
        embed = discord.Embed(title=f"⚔️ {champ.name} — Skills", color=0x5865F2)
        for key in ("q", "w", "e", "r"):
            s = skills.get(key, {})
            active_marker = " ← **ACTIVE**" if key == user.active_skill else ""
            if key == "r":
                active_marker = " *(fires at 100 mana)*"
            name_line = f"{SKILL_EMOJI[key]} **{SKILL_LABELS[key]}: {s.get('name', '?')}**{active_marker}"
            desc = s.get("description", "No description.")
            detail = _build_skill_detail(s, rank)

            # Tier upgrade hints
            upgrades = []
            from engine.skill_factory import RANK_ORDER
            rank_idx = RANK_ORDER.index(rank) if rank in RANK_ORDER else 0
            if rank_idx < RANK_ORDER.index("C") and s.get("advanced"):
                adv = s["advanced"]
                hints = []
                if "coeff" in adv:
                    hints.append(f"{adv['coeff']*100:.0f}% ATK")
                if "hits" in adv:
                    hints.append(f"×{adv['hits']} hits")
                if "mechanic_value" in adv:
                    hints.append("stronger mechanic")
                if "status_chance" in adv:
                    hints.append(f"{adv['status_chance']*100:.0f}% {s.get('status','status')}")
                if hints:
                    upgrades.append(f"📈 Rank C: {', '.join(hints)}")
            if rank_idx < RANK_ORDER.index("A") and s.get("prestige"):
                pre = s["prestige"]
                hints = []
                if "coeff" in pre:
                    hints.append(f"{pre['coeff']*100:.0f}% ATK")
                if "hits" in pre:
                    hints.append(f"×{pre['hits']} hits")
                if "mechanic_value" in pre:
                    hints.append("stronger mechanic")
                if "status_chance" in pre:
                    hints.append(f"{pre['status_chance']*100:.0f}% {s.get('status','status')}")
                if hints:
                    upgrades.append(f"✨ Rank A: {', '.join(hints)}")

            value = f"{desc}\n*{detail}*"
            if upgrades:
                value += "\n" + "\n".join(upgrades)
            embed.add_field(name=name_line, value=value, inline=False)
        embed.set_footer(text=f"Rank {rank} — upgrades unlock at C (Advanced) and A (Prestige)")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @skill_group.command(name="set", description="Choose which basic skill (Q/W/E) your champion uses each round.")
    async def skill_set(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        user = await User.find_one(User.discord_id == uid)
        if not user or not user.active_champion_id:
            await interaction.followup.send(embed=error_embed("No active champion. Use `/champion-select` first."), ephemeral=True)
            return
        champ = await ChampionInstance.get(user.active_champion_id)
        if not champ:
            await interaction.followup.send(embed=error_embed("Active champion not found."), ephemeral=True)
            return
        skills = CHAMPION_SKILLS.get(champ.name, {})

        options = []
        for key in ("q", "w", "e"):
            s = skills.get(key, {})
            name = s.get("name", key.upper())
            desc = s.get("description", "")
            coeff = s.get("coeff", 0)
            dmg = s.get("damage_type", "none")
            hits = s.get("hits", 1)
            detail = f"{coeff*100:.0f}% ATK {dmg}"
            if hits > 1:
                detail += f" ×{hits}"
            label = f"{key.upper()}: {name}"
            option_desc = f"{desc[:80]}{'…' if len(desc) > 80 else ''} [{detail}]"
            options.append(discord.SelectOption(
                label=label,
                value=key,
                description=option_desc[:100],
                default=(key == user.active_skill),
            ))

        embed = discord.Embed(
            title=f"{champ.name} — Set Active Skill",
            description="Your basic skill fires every round when mana < 100. Pick which one to use:",
            color=0x5865F2,
        )
        for key in ("q", "w", "e"):
            s = skills.get(key, {})
            active = " ← active" if key == user.active_skill else ""
            detail = _build_skill_detail(s)
            embed.add_field(
                name=f"**{key.upper()}: {s.get('name', '?')}**{active}",
                value=f"{s.get('description', '')}\n*{detail}*",
                inline=False,
            )
        embed.set_footer(text="R (Ultimate) always fires automatically at 100 mana — it cannot be changed.")

        view = _SkillSetView(uid, champ.id, options)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)


class _SkillSetView(discord.ui.View):
    def __init__(self, uid: str, champ_id, options: list[discord.SelectOption]):
        super().__init__(timeout=60)
        self.uid = uid
        select = discord.ui.Select(placeholder="Pick a skill…", options=options)
        select.callback = self._on_select
        self.add_item(select)
        self._select = select

    async def _on_select(self, interaction: discord.Interaction):
        if str(interaction.user.id) != self.uid:
            await interaction.response.send_message("This isn't your menu.", ephemeral=True)
            return
        skill = self._select.values[0]
        async with get_user_lock(self.uid):
            user = await User.find_one(User.discord_id == self.uid)
            champ = await ChampionInstance.get(user.active_champion_id)
            skills = CHAMPION_SKILLS.get(champ.name, {})
            s = skills.get(skill, {})
            user.active_skill = skill
            await user.save()
        embed = discord.Embed(
            title=f"Active skill set to {SKILL_LABELS[skill]}: {s.get('name', '?')}",
            description=s.get("description", ""),
            color=0x00CC44,
        )
        embed.set_footer(text="This skill fires each round when mana < 100.")
        await interaction.response.edit_message(embed=embed, view=None)


async def setup(bot):
    await bot.add_cog(SkillCog(bot))
