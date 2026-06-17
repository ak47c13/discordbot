"""
Glossary — browse champions, runes, skills, and items.
All read-only reference. No DB queries except for autocomplete.
"""
import discord
from discord import app_commands
from discord.ext import commands

DDRAGON = "https://ddragon.leagueoflegends.com/cdn/img/champion/loading/{riot_id}_0.jpg"
PAGE = 15  # entries per page for list views


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rank_color(rank: str) -> int:
    return {
        "F": 0x888888, "E": 0x44BB44, "D": 0x4488FF,
        "C": 0xAA44FF, "B": 0xFF8800, "A": 0xFF3333, "S": 0xFFD700,
    }.get(rank, 0x888888)


def _tier_label(tier: int) -> str:
    return {1: "Common (F/E)", 2: "Uncommon (D/C)", 3: "Rare (B/A/S)"}.get(tier, "")


def _role_emoji(role: str) -> str:
    return {
        "fighter": "⚔️", "tank": "🛡️", "mage": "🔮",
        "assassin": "🗡️", "marksman": "🏹", "support": "💚",
    }.get(role.lower(), "❓")


# ---------------------------------------------------------------------------
# Champion glossary
# ---------------------------------------------------------------------------

def _champion_list_embed(champs: list[tuple[str, dict]], page: int, query: str = "") -> discord.Embed:
    total = len(champs)
    pages = max(1, (total + PAGE - 1) // PAGE)
    page = max(0, min(page, pages - 1))
    chunk = champs[page * PAGE:(page + 1) * PAGE]

    title = f"Champion Glossary ({total})"
    if query:
        title += f" — \"{query}\""

    embed = discord.Embed(title=title, color=0x5865F2)
    lines = []
    for name, data in chunk:
        role = data.get("role", "fighter")
        lines.append(f"{_role_emoji(role)} **{name}** — *{data.get('title', '')}*  `{role}`")
    embed.description = "\n".join(lines)
    embed.set_footer(text=f"Page {page + 1}/{pages}  ·  /glossary champion <name> for details")
    return embed


def _champion_detail_embed(name: str) -> discord.Embed | None:
    from data.champion_roster import CHAMPION_ROSTER
    from data.champion_skills import CHAMPION_SKILLS
    from config.game_config import CHAMPION_BASE_STATS

    data = CHAMPION_ROSTER.get(name)
    if data is None:
        return None

    role = data.get("role", "fighter")
    riot_id = data.get("riot_id", name.replace(" ", ""))
    skills = CHAMPION_SKILLS.get(name, {})

    embed = discord.Embed(
        title=f"{_role_emoji(role)} {name}",
        description=f"*{data.get('title', '')}*\n`{role.title()}`",
        color=0x5865F2,
    )
    embed.set_thumbnail(url=DDRAGON.format(riot_id=riot_id))

    # Base stats (F rank baseline)
    base = CHAMPION_BASE_STATS.get("F", {})
    embed.add_field(
        name="Base Stats [F]",
        value=f"HP {base.get('hp', '?'):,}  ATK {base.get('atk', '?')}  DEF {base.get('def', '?')}  SPD {base.get('spd', '?')}",
        inline=False,
    )

    # Skills
    for key, label in [("q", "Q"), ("w", "W"), ("e", "E"), ("r", "R — Ultimate")]:
        s = skills.get(key)
        if not s:
            continue
        coeff = s.get("coeff", 0)
        hits = s.get("hits", 1)
        dmg = s.get("damage_type", "none")
        mana = s.get("mana_gain", 0)
        detail = f"{coeff*100:.0f}% ATK {dmg}"
        if hits > 1:
            detail += f" ×{hits}"
        if mana:
            detail += f" · +{mana} mana"
        status = s.get("status")
        if status:
            chance = int(s.get("status_chance", 1) * 100)
            dur = s.get("status_duration", 1)
            detail += f" · {chance}% {status} {dur}r"
        embed.add_field(
            name=f"**{label}: {s.get('name', '?')}**",
            value=f"{s.get('description', detail)}\n*{detail}*",
            inline=False,
        )

    return embed


# ---------------------------------------------------------------------------
# Rune glossary
# ---------------------------------------------------------------------------

_COLOR_EMOJI = {"red": "🔴", "yellow": "🟡", "blue": "🔵", "quint": "💠"}


def _rune_list_embed(color_filter: str = "all") -> discord.Embed:
    from data.rune_catalog import RUNE_CATALOG
    embed = discord.Embed(
        title="Rune Glossary",
        description="Use `/runes set <color> <slot> <rune_id>` to equip. Higher tiers require higher champion rank.",
        color=0xAA44FF,
    )
    by_color: dict[str, list] = {}
    for rid, r in RUNE_CATALOG.items():
        c = r["color"]
        if color_filter != "all" and c != color_filter:
            continue
        by_color.setdefault(c, []).append(r)

    for color in ["red", "yellow", "blue", "quint"]:
        if color not in by_color:
            continue
        lines = []
        for r in sorted(by_color[color], key=lambda x: x["tier"]):
            lines.append(
                f"`{r['id']}` **{r['name']}** — {r['description']} *(Tier {r['tier']}, req [{r['rank_req']}])*"
            )
        embed.add_field(
            name=f"{_COLOR_EMOJI[color]} {color.title()} ({len(lines)})",
            value="\n".join(lines)[:1024],
            inline=False,
        )
    return embed


# ---------------------------------------------------------------------------
# Item glossary — paginated (Discord hard limit: 25 fields per embed)
# ---------------------------------------------------------------------------

ITEMS_PER_PAGE = 10


def _item_recipe_embed(items: list[tuple[str, dict]], page: int, title: str, description: str, color: int) -> discord.Embed:
    total = len(items)
    pages = max(1, (total + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
    page = max(0, min(page, pages - 1))
    chunk = items[page * ITEMS_PER_PAGE:(page + 1) * ITEMS_PER_PAGE]

    embed = discord.Embed(
        title=f"{title} ({total})",
        description=description,
        color=color,
    )
    for name, recipe in chunk:
        comps = " + ".join(recipe["components"])
        embed.add_field(
            name=f"**{name}**  [{recipe['stat_type'].upper()}]  {recipe['gold_cost']:,}g",
            value=f"{comps}\n*{recipe['description']}*",
            inline=False,
        )
    embed.set_footer(text=f"Page {page + 1}/{pages}")
    return embed


def _item_flat_embed(items: dict[str, dict], title: str, description: str, color: int) -> discord.Embed:
    """For basic/advanced component lists that use description text (no fields)."""
    embed = discord.Embed(title=f"{title} ({len(items)})", description=description, color=color)
    lines = [f"**{n}** — {d['desc']}" for n, d in items.items()]
    embed.description += "\n\n" + "\n".join(lines)
    return embed


class _ItemRecipeView(discord.ui.View):
    def __init__(self, items: list[tuple[str, dict]], user_id: int, title: str, description: str, color: int):
        super().__init__(timeout=120)
        self.items = items
        self.user_id = user_id
        self.title = title
        self.description = description
        self.color = color
        self.page = 0
        self.total_pages = max(1, (len(items) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
        self._refresh()

    def _refresh(self):
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                if child.custom_id == "item_prev":
                    child.disabled = self.page == 0
                elif child.custom_id == "item_next":
                    child.disabled = self.page >= self.total_pages - 1

    def current_embed(self):
        return _item_recipe_embed(self.items, self.page, self.title, self.description, self.color)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not your glossary.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary, custom_id="item_prev")
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = max(0, self.page - 1)
        self._refresh()
        await interaction.response.edit_message(embed=self.current_embed(), view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary, custom_id="item_next")
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = min(self.total_pages - 1, self.page + 1)
        self._refresh()
        await interaction.response.edit_message(embed=self.current_embed(), view=self)


# ---------------------------------------------------------------------------
# Skill glossary — browse by champion name
# ---------------------------------------------------------------------------

def _skill_embed(champion_name: str) -> discord.Embed | None:
    from data.champion_skills import CHAMPION_SKILLS
    from data.champion_roster import CHAMPION_ROSTER

    skills = CHAMPION_SKILLS.get(champion_name)
    roster = CHAMPION_ROSTER.get(champion_name, {})
    if not skills:
        return None

    riot_id = roster.get("riot_id", champion_name.replace(" ", ""))
    embed = discord.Embed(
        title=f"Skills — {champion_name}",
        description=f"*{roster.get('title', '')}*",
        color=0x5865F2,
    )
    embed.set_thumbnail(url=DDRAGON.format(riot_id=riot_id))

    for key, label in [("q", "Q"), ("w", "W"), ("e", "E"), ("r", "R — Ultimate")]:
        s = skills.get(key)
        if not s:
            continue
        coeff = s.get("coeff", 0)
        hits = s.get("hits", 1)
        dmg = s.get("damage_type", "none")
        mana = s.get("mana_gain", 0)
        detail_parts = [f"{coeff*100:.0f}% ATK {dmg}"]
        if hits > 1:
            detail_parts.append(f"×{hits} hits")
        if mana:
            detail_parts.append(f"+{mana} mana")
        status = s.get("status")
        if status:
            chance = int(s.get("status_chance", 1) * 100)
            dur = s.get("status_duration", 1)
            detail_parts.append(f"{chance}% {status.replace('_', ' ')} {dur}r")
        detail = "  ·  ".join(detail_parts)
        active_note = "  ← pick with /skill set" if key in ("q", "w", "e") else "  ← fires at 100 mana"
        embed.add_field(
            name=f"**{label}: {s.get('name', '?')}**{active_note}",
            value=f"{s.get('description', '—')}\n*{detail}*",
            inline=False,
        )
    return embed


# ---------------------------------------------------------------------------
# Pagination view
# ---------------------------------------------------------------------------

class _ChampListView(discord.ui.View):
    def __init__(self, champs: list, user_id: int, query: str = ""):
        super().__init__(timeout=120)
        self.champs = champs
        self.user_id = user_id
        self.query = query
        self.page = 0
        self.total_pages = max(1, (len(champs) + PAGE - 1) // PAGE)
        self._refresh()

    def _refresh(self):
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                if item.custom_id == "prev":
                    item.disabled = self.page == 0
                elif item.custom_id == "next":
                    item.disabled = self.page >= self.total_pages - 1

    def current_embed(self):
        return _champion_list_embed(self.champs, self.page, self.query)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not your glossary.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary, custom_id="prev")
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = max(0, self.page - 1)
        self._refresh()
        await interaction.response.edit_message(embed=self.current_embed(), view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary, custom_id="next")
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = min(self.total_pages - 1, self.page + 1)
        self._refresh()
        await interaction.response.edit_message(embed=self.current_embed(), view=self)


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class GlossaryCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    glossary = app_commands.Group(name="glossary", description="Browse game reference — champions, runes, skills, items.")

    # ── Champions ──────────────────────────────────────────────────────────

    @glossary.command(name="champions", description="Browse all champions, or look up one by name.")
    @app_commands.describe(name="Champion name to look up (leave blank to browse all)", role="Filter by role")
    @app_commands.choices(role=[
        app_commands.Choice(name="All", value="all"),
        app_commands.Choice(name="Fighter", value="fighter"),
        app_commands.Choice(name="Tank", value="tank"),
        app_commands.Choice(name="Mage", value="mage"),
        app_commands.Choice(name="Assassin", value="assassin"),
        app_commands.Choice(name="Marksman", value="marksman"),
        app_commands.Choice(name="Support", value="support"),
    ])
    async def glossary_champions(self, interaction: discord.Interaction, name: str = "", role: str = "all"):
        await interaction.response.defer(ephemeral=True)
        from data.champion_roster import CHAMPION_ROSTER

        if name:
            matched = next((k for k in CHAMPION_ROSTER if k.lower() == name.lower()), None)
            if matched is None:
                # fuzzy: starts-with match
                candidates = [k for k in CHAMPION_ROSTER if k.lower().startswith(name.lower())]
                if len(candidates) == 1:
                    matched = candidates[0]
                elif candidates:
                    await interaction.followup.send(
                        embed=discord.Embed(
                            description="Multiple matches: " + ", ".join(f"**{c}**" for c in candidates[:10]),
                            color=0x5865F2,
                        ),
                        ephemeral=True,
                    )
                    return
                else:
                    await interaction.followup.send(
                        embed=discord.Embed(description=f"No champion named **{name}**.", color=0xFF4444),
                        ephemeral=True,
                    )
                    return
            embed = _champion_detail_embed(matched)
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        champs = sorted(CHAMPION_ROSTER.items(), key=lambda x: x[0])
        if role != "all":
            champs = [(n, d) for n, d in champs if d.get("role", "") == role]

        view = _ChampListView(champs, interaction.user.id, query=role if role != "all" else "")
        await interaction.followup.send(embed=view.current_embed(), view=view, ephemeral=True)

    # ── Runes ──────────────────────────────────────────────────────────────

    @glossary.command(name="runes", description="Browse all runes by color.")
    @app_commands.describe(color="Filter by rune color")
    @app_commands.choices(color=[
        app_commands.Choice(name="All", value="all"),
        app_commands.Choice(name="Red (Marks)", value="red"),
        app_commands.Choice(name="Yellow (Seals)", value="yellow"),
        app_commands.Choice(name="Blue (Glyphs)", value="blue"),
        app_commands.Choice(name="Quint (Quintessences)", value="quint"),
    ])
    async def glossary_runes(self, interaction: discord.Interaction, color: str = "all"):
        await interaction.response.defer(ephemeral=True)
        embed = _rune_list_embed(color)
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── Skills ─────────────────────────────────────────────────────────────

    @glossary.command(name="skills", description="Look up a champion's Q/W/E/R skills.")
    @app_commands.describe(champion="Champion name")
    async def glossary_skills(self, interaction: discord.Interaction, champion: str):
        await interaction.response.defer(ephemeral=True)
        from data.champion_skills import CHAMPION_SKILLS
        from data.champion_roster import CHAMPION_ROSTER

        matched = next((k for k in CHAMPION_SKILLS if k.lower() == champion.lower()), None)
        if matched is None:
            candidates = [k for k in CHAMPION_ROSTER if k.lower().startswith(champion.lower())]
            if len(candidates) == 1:
                matched = candidates[0]
            elif candidates:
                await interaction.followup.send(
                    embed=discord.Embed(
                        description="Multiple matches: " + ", ".join(f"**{c}**" for c in candidates[:10]),
                        color=0x5865F2,
                    ),
                    ephemeral=True,
                )
                return
            else:
                await interaction.followup.send(
                    embed=discord.Embed(description=f"No champion named **{champion}**.", color=0xFF4444),
                    ephemeral=True,
                )
                return

        embed = _skill_embed(matched)
        if embed is None:
            await interaction.followup.send(
                embed=discord.Embed(description=f"No skill data for **{matched}**.", color=0xFF4444),
                ephemeral=True,
            )
            return
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── Items ──────────────────────────────────────────────────────────────

    @glossary.command(name="items", description="Browse items — completed, components, or build recipes.")
    @app_commands.describe(category="What to show")
    @app_commands.choices(category=[
        app_commands.Choice(name="Completed Items — craft targets",          value="completed"),
        app_commands.Choice(name="Component Recipes — build advanced from basics", value="component_recipes"),
        app_commands.Choice(name="Basic Components — common drops",          value="basic"),
        app_commands.Choice(name="Advanced Components — mid-tier drops",     value="advanced"),
    ])
    async def glossary_items(self, interaction: discord.Interaction, category: str = "completed"):
        await interaction.response.defer(ephemeral=True)
        from data.item_recipes import COMPONENT_RECIPES, COMPLETED_RECIPES, BASIC_COMPONENTS, ADVANCED_COMPONENTS

        if category == "completed":
            items = list(COMPLETED_RECIPES.items())
            view = _ItemRecipeView(
                items, interaction.user.id,
                title="Item Glossary — Completed Items",
                description="Craft at `/build <name>`. Output rank = lowest component rank. Very rare drops.",
                color=0xFFAA00,
            )
            await interaction.followup.send(embed=view.current_embed(), view=view, ephemeral=True)

        elif category == "component_recipes":
            items = list(COMPONENT_RECIPES.items())
            view = _ItemRecipeView(
                items, interaction.user.id,
                title="Item Glossary — Component Recipes",
                description="Build advanced components from basics at `/build <name>`.",
                color=0x4488FF,
            )
            await interaction.followup.send(embed=view.current_embed(), view=view, ephemeral=True)

        elif category == "basic":
            embed = _item_flat_embed(
                BASIC_COMPONENTS,
                title="Item Glossary — Basic Components",
                description="Most common drops from dungeons, raids, and shop. Use these as building blocks.",
                color=0x888888,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

        else:  # advanced
            embed = _item_flat_embed(
                ADVANCED_COMPONENTS,
                title="Item Glossary — Advanced Components",
                description="Crafted from basics or drop mid-tier. Used as inputs for completed items.",
                color=0x44AAFF,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(GlossaryCog(bot))
