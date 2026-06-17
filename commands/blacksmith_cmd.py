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
        await interaction.response.defer(ephemeral=True)
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

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="clear", description="Reset an item to +0 (costs gold, no refund).")
    @app_commands.describe(number="Item list number (see /items)")
    async def clear(self, interaction: discord.Interaction, number: int):
        await interaction.response.defer(ephemeral=True)
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
            ephemeral=True,
        )

    @app_commands.command(name="reroll", description="Reroll secondary stat (full: changes type+value).")
    @app_commands.describe(number="Item list number (see /items)")
    async def reroll(self, interaction: discord.Interaction, number: int):
        await interaction.response.defer(ephemeral=True)
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

        await interaction.followup.send(embed=item_embed(result, "✅ Reroll Applied"), ephemeral=True)

    @app_commands.command(name="refine", description="Reroll secondary stat value only (keeps stat type).")
    @app_commands.describe(number="Item list number (see /items)")
    async def refine(self, interaction: discord.Interaction, number: int):
        await interaction.response.defer(ephemeral=True)
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

        await interaction.followup.send(embed=item_embed(result, "✅ Refine Applied"), ephemeral=True)


    @app_commands.command(name="build", description="Craft a completed item from its components.")
    @app_commands.describe(item_name="Name of the completed item to craft (e.g. Infinity Edge)")
    async def build(self, interaction: discord.Interaction, item_name: str):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)

        from data.item_recipes import ITEM_RECIPES
        # Case-insensitive match
        matched = next((k for k in ITEM_RECIPES if k.lower() == item_name.lower()), None)
        if matched is None:
            craftable = "\n".join(f"• {k}" for k in sorted(ITEM_RECIPES))
            await interaction.followup.send(
                embed=error_embed(
                    f"No recipe for **{item_name}**.",
                    f"Craftable items:\n{craftable}",
                ),
                ephemeral=True,
            )
            return

        recipe = ITEM_RECIPES[matched]
        components_needed = recipe["components"]

        # Find one unequipped, unlocked, non-traded copy of each component
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
                all_lines = "\n".join(have_lines + miss_lines)
                await interaction.followup.send(
                    embed=error_embed(
                        f"Missing components for **{matched}**.",
                        all_lines,
                    ),
                    ephemeral=True,
                )
                return

            # Determine output rank — use the lowest rank among components
            rank_order = ["F", "E", "D", "C", "B", "A", "S"]
            comp_ranks = [itm.rank for itm in items_to_consume]
            output_rank = min(comp_ranks, key=lambda r: rank_order.index(r))

            # Confirm embed before consuming
            from utils.embeds import ConfirmView
            gold_cost = recipe.get("gold_cost", 0)

            from models.user import User
            user = await User.find_one(User.discord_id == uid)
            if user.gold < gold_cost:
                await interaction.followup.send(
                    embed=error_embed(f"Need {gold_cost:,} gold to craft. You have {user.gold:,}."),
                    ephemeral=True,
                )
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
            msg = await interaction.followup.send(embed=confirm_embed, view=view, ephemeral=True, wait=True)
            view.message = msg
            await view.wait()

            if not view.confirmed:
                await msg.edit(embed=error_embed("Craft cancelled."), view=None)
                return

            # Consume components and charge gold
            for itm in items_to_consume:
                await itm.delete()
            user.gold -= gold_cost
            await user.save()

            # Grant the crafted item
            from services.item_service import grant_item
            crafted = await grant_item(
                uid,
                matched,
                output_rank,
                recipe["stat_type"],
                recipe["passive"],
            )

        from utils.embeds import item_embed
        embed = item_embed(crafted, f"Crafted: {matched}")
        embed.description = recipe["description"]
        await msg.edit(embed=embed, view=None)

    @app_commands.command(name="recipes", description="Browse all craftable items and their components.")
    async def recipes(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        from data.item_recipes import ITEM_RECIPES
        embed = discord.Embed(
            title="Blacksmith Recipes",
            description="Craft completed items from components. Output rank = lowest component rank.\nComponents drop commonly from dungeons and raids.",
            color=0xFFAA00,
        )
        for name, recipe in ITEM_RECIPES.items():
            comps = " + ".join(recipe["components"])
            embed.add_field(
                name=f"{name}  [{recipe['stat_type'].upper()}]  {recipe['gold_cost']:,}g",
                value=f"{comps}\n*{recipe['description']}*",
                inline=False,
            )
        embed.set_footer(text="Use /build <item_name> to craft")
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(BlacksmithCog(bot))
