import discord
from discord import app_commands
from discord.ext import commands

from models.user import User
from models.item import ItemInstance
from utils.embeds import (
    item_embed, error_embed, success_embed, ConfirmView, RerollPreviewView,
    get_item_by_number, COLOR_WARNING, COLOR_INFO, COLOR_SUCCESS, COLOR_DANGER,
)
from utils.locks import get_user_lock
from utils.db_session import get_motor_client
from services.blacksmith_service import (
    enhance_item,
    clear_item,
    reroll_secondary_full,
    accept_reroll_full,
    reroll_secondary_value,
    accept_reroll_value,
    BlacksmithError,
)
from config.game_config import (
    ENHANCEMENT_SAFE_MAX,
    enhancement_gold_cost,
    clearing_gold_cost,
    REROLL_FULL_COST,
    REROLL_VALUE_COST,
)


class BlacksmithCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="enhance", description="Enhance an item (+1 level). Above +7 risks destruction.")
    @app_commands.describe(number="Item list number (see /items)", use_seal="Use a Blacksmith's Seal to protect against destruction")
    async def enhance(self, interaction: discord.Interaction, number: int, use_seal: bool = False):
        await interaction.response.defer()
        uid = str(interaction.user.id)

        itm = await get_item_by_number(uid, number)
        if itm is None or itm.owner_id != uid:
            await interaction.followup.send(
                embed=error_embed("Item not found.", "Use `/items` to find the right number."),
                ephemeral=True,
            )
            return
        item_id = str(itm.id)

        current = itm.enhancement
        gold_cost = enhancement_gold_cost(current)
        is_risky = current >= ENHANCEMENT_SAFE_MAX

        desc = (
            f"Enhance **{itm.name} [{itm.rank}] +{current}** → **+{current + 1}**\n"
            f"Cost: **{gold_cost} gold**\n"
        )
        if is_risky:
            from config.game_config import ENHANCEMENT_SUCCESS_RATE
            rate = int(ENHANCEMENT_SUCCESS_RATE[current] * 100)
            desc += (
                f"⚠️ **RISKY ENHANCEMENT** — {rate}% success chance\n"
                f"❌ Failure will **permanently destroy** the item"
                + (" unless protected by a Seal." if not use_seal else ".")
            )
            if use_seal:
                desc += "\n🔏 **Blacksmith's Seal will be consumed** (protects on failure)."
        else:
            desc += "✅ Safe enhancement range — item cannot be destroyed."

        embed = discord.Embed(title="⚒️ Confirm Enhancement", description=desc, color=COLOR_WARNING if is_risky else COLOR_INFO)
        view = ConfirmView()
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        await view.wait()

        if not view.confirmed:
            await interaction.followup.send(embed=discord.Embed(title="Enhancement cancelled.", color=COLOR_INFO), ephemeral=True)
            return

        async with get_user_lock(uid):
            client = get_motor_client()
            async with await client.start_session() as session:
                async with session.start_transaction():
                    try:
                        result = await enhance_item(uid, item_id, use_seal, session)
                    except BlacksmithError as e:
                        await interaction.followup.send(embed=error_embed(str(e)), ephemeral=True)
                        return

        if result["destroyed"]:
            embed = discord.Embed(
                title="💥 Item Destroyed!",
                description=f"**{itm.name} [{itm.rank}] +{current}** was destroyed in the enhancement attempt.",
                color=COLOR_DANGER,
            )
        elif result["success"]:
            embed = discord.Embed(
                title="✅ Enhancement Success!",
                description=f"**{itm.name} [{itm.rank}]** is now **+{result['new_level']}**!",
                color=COLOR_SUCCESS,
            )
            if result["seal_used"]:
                embed.add_field(name="🔏 Seal Used", value="Blacksmith's Seal was consumed.", inline=False)
        else:
            embed = discord.Embed(
                title="❌ Enhancement Failed",
                description=f"The enhancement failed. **{itm.name}** remains at **+{current}**.",
                color=COLOR_DANGER,
            )
            if result["seal_used"]:
                embed.add_field(name="🔏 Seal Used", value="Seal protected the item from destruction.", inline=False)

        await interaction.followup.send(embed=embed)

    @app_commands.command(name="clear", description="Reset an item to +0 (costs gold, no refund).")
    @app_commands.describe(number="Item list number (see /items)")
    async def clear(self, interaction: discord.Interaction, number: int):
        await interaction.response.defer()
        uid = str(interaction.user.id)

        itm = await get_item_by_number(uid, number)
        if itm is None or itm.owner_id != uid:
            await interaction.followup.send(
                embed=error_embed("Item not found.", "Use `/items` to find the right number."),
                ephemeral=True,
            )
            return
        item_id = str(itm.id)
        if itm.enhancement == 0:
            await interaction.followup.send(embed=error_embed("Item is already +0."), ephemeral=True)
            return

        gold_cost = clearing_gold_cost(itm.rank, itm.enhancement)
        embed = discord.Embed(
            title="🔨 Confirm Clear",
            description=(
                f"Reset **{itm.name} [{itm.rank}] +{itm.enhancement}** to **+0**\n"
                f"Cost: **{gold_cost} gold**\n"
                f"⚠️ All enhancement progress is **permanently lost**.\n"
                f"✅ Secondary stat is preserved. Item becomes fusible again."
            ),
            color=COLOR_WARNING,
        )
        view = ConfirmView()
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        await view.wait()

        if not view.confirmed:
            await interaction.followup.send(embed=discord.Embed(title="Clear cancelled.", color=COLOR_INFO), ephemeral=True)
            return

        async with get_user_lock(uid):
            client = get_motor_client()
            async with await client.start_session() as session:
                async with session.start_transaction():
                    try:
                        result = await clear_item(uid, item_id, session)
                    except BlacksmithError as e:
                        await interaction.followup.send(embed=error_embed(str(e)), ephemeral=True)
                        return

        await interaction.followup.send(
            embed=success_embed(f"{result.name} [{result.rank}] cleared to +0. (-{gold_cost} gold)"),
        )

    @app_commands.command(name="reroll", description="Reroll secondary stat (full: changes type+value).")
    @app_commands.describe(number="Item list number (see /items)")
    async def reroll(self, interaction: discord.Interaction, number: int):
        await interaction.response.defer()
        uid = str(interaction.user.id)

        itm = await get_item_by_number(uid, number)
        if itm is None or itm.owner_id != uid:
            await interaction.followup.send(
                embed=error_embed("Item not found.", "Use `/items` to find the right number."),
                ephemeral=True,
            )
            return
        item_id = str(itm.id)

        cost = REROLL_FULL_COST[itm.rank]
        # Generate preview (no gold deducted yet)
        client = get_motor_client()
        async with await client.start_session() as session:
            try:
                preview = await reroll_secondary_full(uid, item_id, session)
            except BlacksmithError as e:
                await interaction.followup.send(embed=error_embed(str(e)), ephemeral=True)
                return

        embed = discord.Embed(title="🎲 Reroll Preview", color=COLOR_INFO)
        embed.add_field(
            name="Current",
            value=f"{preview['old_type']}: {preview['old_value']/10:.1f}",
            inline=True,
        )
        embed.add_field(
            name="New Roll",
            value=f"{preview['new_type']}: {preview['new_value']/10:.1f}",
            inline=True,
        )
        embed.add_field(name="Cost", value=f"{cost} gold", inline=False)
        embed.set_footer(text="Accept to apply and pay. Reject to keep current stat.")

        view = RerollPreviewView()
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        await view.wait()

        if not view.accepted:
            await interaction.followup.send(embed=discord.Embed(title="Reroll cancelled — kept old stat.", color=COLOR_INFO), ephemeral=True)
            return

        async with get_user_lock(uid):
            async with await client.start_session() as session:
                async with session.start_transaction():
                    try:
                        result = await accept_reroll_full(
                            uid, item_id,
                            preview["new_type"], preview["new_value"],
                            session,
                        )
                    except BlacksmithError as e:
                        await interaction.followup.send(embed=error_embed(str(e)), ephemeral=True)
                        return

        await interaction.followup.send(embed=item_embed(result, "✅ Reroll Applied"))

    @app_commands.command(name="refine", description="Reroll secondary stat value only (keeps stat type).")
    @app_commands.describe(number="Item list number (see /items)")
    async def refine(self, interaction: discord.Interaction, number: int):
        await interaction.response.defer()
        uid = str(interaction.user.id)

        itm = await get_item_by_number(uid, number)
        if itm is None or itm.owner_id != uid:
            await interaction.followup.send(
                embed=error_embed("Item not found.", "Use `/items` to find the right number."),
                ephemeral=True,
            )
            return
        item_id = str(itm.id)

        cost = REROLL_VALUE_COST[itm.rank]
        client = get_motor_client()
        async with await client.start_session() as session:
            try:
                preview = await reroll_secondary_value(uid, item_id, session)
            except BlacksmithError as e:
                await interaction.followup.send(embed=error_embed(str(e)), ephemeral=True)
                return

        embed = discord.Embed(title="🎲 Refine Preview", color=COLOR_INFO)
        embed.add_field(name="Stat Type", value=preview["stat_type"], inline=False)
        embed.add_field(name="Current Value", value=f"{preview['old_value']/10:.1f}", inline=True)
        embed.add_field(name="New Value",     value=f"{preview['new_value']/10:.1f}", inline=True)
        embed.add_field(name="Cost",          value=f"{cost} gold",  inline=False)

        view = RerollPreviewView()
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        await view.wait()

        if not view.accepted:
            await interaction.followup.send(embed=discord.Embed(title="Refine cancelled.", color=COLOR_INFO), ephemeral=True)
            return

        async with get_user_lock(uid):
            async with await client.start_session() as session:
                async with session.start_transaction():
                    try:
                        result = await accept_reroll_value(uid, item_id, preview["new_value"], session)
                    except BlacksmithError as e:
                        await interaction.followup.send(embed=error_embed(str(e)), ephemeral=True)
                        return

        await interaction.followup.send(embed=item_embed(result, "✅ Refine Applied"))


    @app_commands.command(name="build", description="Craft an item from its components. Browse with the menu or type a name directly.")
    @app_commands.describe(item_name="Optional: type item name directly (e.g. Infinity Edge). Leave blank to browse.")
    async def build(self, interaction: discord.Interaction, item_name: str = ""):
        await interaction.response.defer()
        uid = str(interaction.user.id)

        if not item_name:
            from collections import Counter
            from data.item_recipes import COMPONENT_RECIPES, COMPLETED_RECIPES

            # Fetch all available (unequipped, unlocked, not in trade/market) items
            available_items = await ItemInstance.find(
                ItemInstance.owner_id == uid,
                ItemInstance.equipped_to == None,
                ItemInstance.locked == False,
                ItemInstance.in_trade == False,
                ItemInstance.in_market == False,
            ).to_list()

            # Build {item_name: count} inventory dict
            inventory: Counter = Counter(itm.name for itm in available_items)

            # Check all recipes for craftability
            all_recipes = {**COMPONENT_RECIPES, **COMPLETED_RECIPES}
            craftable: dict[str, dict] = {}
            for recipe_name, recipe in all_recipes.items():
                needed = Counter(recipe["components"])
                if all(inventory[comp] >= cnt for comp, cnt in needed.items()):
                    craftable[recipe_name] = recipe

            if not craftable:
                await interaction.followup.send(
                    embed=error_embed(
                        "Nothing craftable yet.",
                        "You don't have the components to craft anything yet. Earn items from dungeons and hunts.",
                    ),
                    ephemeral=True,
                )
                return

            # Count craftable per category
            component_craftable = {k: v for k, v in craftable.items() if k in COMPONENT_RECIPES}
            category_counts: dict[str, int] = {}
            for cat_key, (cat_label, item_set) in _BUILD_CATEGORIES.items():
                if cat_key == "components":
                    category_counts[cat_key] = len(component_craftable)
                else:
                    category_counts[cat_key] = len([k for k in craftable if k in item_set])

            desc_lines = []
            for cat_key, (cat_label, _) in _BUILD_CATEGORIES.items():
                cnt = category_counts.get(cat_key, 0)
                if cnt > 0:
                    desc_lines.append(f"**{cat_label}:** {cnt} craftable")

            embed = discord.Embed(
                title="Blacksmith — Craft Item",
                description=(
                    "You can craft the following:\n\n" + "\n".join(desc_lines) +
                    "\n\nPick a category to see your options."
                ),
                color=0xFFAA00,
            )
            view = _BuildCategoryView(uid, craftable)
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            return

        # Direct craft by name
        await _do_build(interaction, uid, item_name)


async def _do_build(interaction: discord.Interaction, uid: str, item_name: str, msg=None):
    """Shared craft logic used by both the UI flow and direct name input."""
    from data.item_recipes import ITEM_RECIPES
    from utils.embeds import ConfirmView, item_embed

    matched = next((k for k in ITEM_RECIPES if k.lower() == item_name.lower()), None)
    if matched is None:
        candidates = [k for k in ITEM_RECIPES if k.lower().startswith(item_name.lower())]
        if len(candidates) == 1:
            matched = candidates[0]
        else:
            hint = ", ".join(candidates[:8]) if candidates else "Use /recipes to browse all craftable items."
            embed = error_embed(f"No recipe found for **{item_name}**.", hint)
            if msg:
                await msg.edit(embed=embed, view=None)
            else:
                await interaction.followup.send(embed=embed, ephemeral=True)
            return

    recipe = ITEM_RECIPES[matched]
    components_needed = recipe["components"]

    async with get_user_lock(uid):
        items_to_consume = []
        missing = []
        for comp_name in components_needed:
            found = await ItemInstance.find_one(
                ItemInstance.owner_id == uid,
                ItemInstance.name == comp_name,
                ItemInstance.equipped_to == None,
                ItemInstance.locked == False,
                ItemInstance.in_trade == False,
                ItemInstance.in_market == False,
            )
            if found:
                items_to_consume.append(found)
            else:
                missing.append(comp_name)

        if missing:
            have_lines = [f"✅ {c}" for c in components_needed if c not in missing]
            miss_lines = [f"❌ {c}" for c in missing]
            embed = error_embed(
                f"Missing components for **{matched}**.",
                "\n".join(have_lines + miss_lines),
            )
            if msg:
                await msg.edit(embed=embed, view=None)
            else:
                await interaction.followup.send(embed=embed, ephemeral=True)
            return

        rank_order = ["F", "E", "D", "C", "B", "A", "S"]
        comp_ranks = [itm.rank for itm in items_to_consume]
        output_rank = min(comp_ranks, key=lambda r: rank_order.index(r))

        gold_cost = recipe.get("gold_cost", 0)
        user = await User.find_one(User.discord_id == uid)
        if user.gold < gold_cost:
            embed = error_embed(f"Need {gold_cost:,} gold to craft. You have {user.gold:,}.")
            if msg:
                await msg.edit(embed=embed, view=None)
            else:
                await interaction.followup.send(embed=embed, ephemeral=True)
            return

        comp_list = "\n".join(f"• {itm.name} [{itm.rank}]" for itm in items_to_consume)
        confirm_embed = discord.Embed(
            title=f"Craft: {matched} [{output_rank}]",
            description=(
                f"**Components consumed:**\n{comp_list}\n\n"
                f"**Gold cost:** {gold_cost:,}\n"
                f"**Output rank:** [{output_rank}] (lowest component rank)\n\n"
                "This cannot be undone."
            ),
            color=0xFFAA00,
        )
        view = ConfirmView()
        if msg:
            await msg.edit(embed=confirm_embed, view=view)
            view.message = msg
        else:
            msg = await interaction.followup.send(embed=confirm_embed, view=view, ephemeral=True, wait=True)
            view.message = msg
        await view.wait()

        if not view.confirmed:
            await msg.edit(embed=error_embed("Craft cancelled."), view=None)
            return

        for itm in items_to_consume:
            await itm.delete()
        user.gold -= gold_cost
        await user.save()

        from services.item_service import grant_item
        crafted = await grant_item(uid, matched, output_rank, recipe["stat_type"], recipe["passive"])

    from utils.embeds import item_embed
    embed = item_embed(crafted, f"Crafted: {matched}")
    embed.description = recipe["description"]
    await msg.edit(embed=embed, view=None)


# ---------------------------------------------------------------------------
# Build UI — category picker → item select → craft confirm
# ---------------------------------------------------------------------------

# Categorise completed items by thematic role (for the select menus)
_BUILD_CATEGORIES: dict[str, tuple[str, set[str]]] = {
    "attack":    ("Attack / Marksman", {
        "Infinity Edge", "Immortal Shieldbow", "Phantom Dancer", "Runaan's Hurricane",
        "Kraken Slayer", "Blade of the Ruined King", "Manamune", "Guardian Angel",
    }),
    "fighter":   ("Fighter / Bruiser", {
        "Trinity Force", "Ravenous Hydra", "Death's Dance", "Black Cleaver",
        "Titanic Hydra", "Sterak's Gage", "Heartsteel",
    }),
    "magic":     ("Magic / Mage", {
        "Rabadon's Deathcap", "Luden's Companion", "Shadowflame", "Void Staff",
        "Nashor's Tooth", "Liandry's Anguish", "Morellonomicon", "Archangel's Staff",
        "Rod of Ages", "Rylai's Crystal Scepter", "Zhonya's Hourglass",
        "Banshee's Veil", "Horizon Focus",
    }),
    "defense":   ("Defense / Tank", {
        "Sunfire Aegis", "Thornmail", "Frozen Heart", "Gargoyle Stoneplate",
        "Randuin's Omen", "Dead Man's Plate", "Warmog's Armor", "Spirit Visage",
        "Force of Nature", "Abyssal Mask", "Jak'Sho the Protean",
    }),
    "components": ("Component Recipes", set()),  # populated dynamically
}


class _BuildCategoryView(discord.ui.View):
    def __init__(self, uid: str, craftable: dict):
        super().__init__(timeout=120)
        self.uid = uid
        self.craftable = craftable  # pre-computed {item_name: recipe} the user can actually craft

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.uid:
            await interaction.response.send_message("Not your menu.", ephemeral=True)
            return False
        return True

    async def _show_items(self, interaction: discord.Interaction, category_key: str):
        from data.item_recipes import COMPONENT_RECIPES
        label, item_set = _BUILD_CATEGORIES[category_key]

        if category_key == "components":
            recipes = {k: v for k, v in self.craftable.items() if k in COMPONENT_RECIPES}
        else:
            recipes = {k: v for k, v in self.craftable.items() if k in item_set}

        if not recipes:
            await interaction.response.send_message(
                f"You don't have the components to craft any **{label}** items yet.",
                ephemeral=True,
            )
            return

        options = [
            discord.SelectOption(
                label=name[:100],
                value=name[:100],
                description=(", ".join(r["components"]))[:100],
            )
            for name, r in recipes.items()
        ]
        embed = discord.Embed(
            title=f"Craft — {label}",
            description=f"Select an item to craft. {len(options)} recipe(s) available.",
            color=0xFFAA00,
        )
        view = _BuildItemSelectView(self.uid, options, self.craftable)
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Attack / Marksman", style=discord.ButtonStyle.primary,  custom_id="build_cat_attack")
    async def cat_attack(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._show_items(interaction, "attack")

    @discord.ui.button(label="Fighter / Bruiser",  style=discord.ButtonStyle.primary,  custom_id="build_cat_fighter")
    async def cat_fighter(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._show_items(interaction, "fighter")

    @discord.ui.button(label="Magic / Mage",       style=discord.ButtonStyle.primary,  custom_id="build_cat_magic")
    async def cat_magic(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._show_items(interaction, "magic")

    @discord.ui.button(label="Defense / Tank",     style=discord.ButtonStyle.secondary, custom_id="build_cat_defense")
    async def cat_defense(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._show_items(interaction, "defense")

    @discord.ui.button(label="Component Recipes",  style=discord.ButtonStyle.secondary, custom_id="build_cat_components")
    async def cat_components(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._show_items(interaction, "components")


class _BuildItemSelectView(discord.ui.View):
    def __init__(self, uid: str, options: list[discord.SelectOption], craftable: dict):
        super().__init__(timeout=120)
        self.uid = uid
        self.craftable = craftable
        select = discord.ui.Select(
            placeholder="Choose an item to craft...",
            options=options[:25],
            custom_id="build_item_pick",
        )
        select.callback = self._on_select
        self.add_item(select)
        back = discord.ui.Button(label="Back", style=discord.ButtonStyle.secondary, custom_id="build_back")
        back.callback = self._on_back
        self.add_item(back)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.uid:
            await interaction.response.send_message("Not your menu.", ephemeral=True)
            return False
        return True

    async def _on_select(self, interaction: discord.Interaction):
        item_name = interaction.data["values"][0]
        msg = interaction.message
        await interaction.response.defer()
        await _do_build(interaction, self.uid, item_name, msg=msg)

    async def _on_back(self, interaction: discord.Interaction):
        from data.item_recipes import COMPONENT_RECIPES
        component_craftable = {k: v for k, v in self.craftable.items() if k in COMPONENT_RECIPES}
        category_counts: dict[str, int] = {}
        for cat_key, (cat_label, item_set) in _BUILD_CATEGORIES.items():
            if cat_key == "components":
                category_counts[cat_key] = len(component_craftable)
            else:
                category_counts[cat_key] = len([k for k in self.craftable if k in item_set])

        desc_lines = []
        for cat_key, (cat_label, _) in _BUILD_CATEGORIES.items():
            cnt = category_counts.get(cat_key, 0)
            if cnt > 0:
                desc_lines.append(f"**{cat_label}:** {cnt} craftable")

        embed = discord.Embed(
            title="Blacksmith — Craft Item",
            description=(
                "You can craft the following:\n\n" + "\n".join(desc_lines) +
                "\n\nPick a category to see your options."
            ),
            color=0xFFAA00,
        )
        await interaction.response.edit_message(embed=embed, view=_BuildCategoryView(self.uid, self.craftable))

    @app_commands.command(name="recipes", description="Browse all craftable items by tier.")
    @app_commands.describe(tier="Which tier to show")
    @app_commands.choices(tier=[
        app_commands.Choice(name="Completed Items (end-game)",           value="completed"),
        app_commands.Choice(name="Component Recipes (basics → advanced)", value="components"),
    ])
    async def recipes(self, interaction: discord.Interaction, tier: str = "completed"):
        await interaction.response.defer(ephemeral=True)
        from data.item_recipes import COMPONENT_RECIPES, COMPLETED_RECIPES

        recipes = COMPLETED_RECIPES if tier == "completed" else COMPONENT_RECIPES
        title = "Completed Item Recipes" if tier == "completed" else "Component Build Paths"
        desc = (
            "End-game items. Craft from advanced components at `/build <name>`.\nOutput rank = lowest component rank."
            if tier == "completed" else
            "Turn basic drops into advanced components at `/build <name>`."
        )

        # Discord embed field limit is 25 — paginate into two messages if needed
        items_list = list(recipes.items())
        for batch_start in range(0, len(items_list), 20):
            batch = items_list[batch_start:batch_start + 20]
            embed = discord.Embed(
                title=f"{title} ({len(recipes)} total)",
                description=desc if batch_start == 0 else f"*(continued — {batch_start + 1}–{batch_start + len(batch)})*",
                color=0xFFAA00 if tier == "completed" else 0x4488FF,
            )
            for name, recipe in batch:
                comps = " + ".join(recipe["components"])
                embed.add_field(
                    name=f"**{name}**  [{recipe['stat_type'].upper()}]  {recipe['gold_cost']:,}g",
                    value=f"{comps}\n*{recipe['description']}*",
                    inline=False,
                )
            embed.set_footer(text="/build <item_name> to craft")
            await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(BlacksmithCog(bot))
