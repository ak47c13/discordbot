import discord
from discord import app_commands
from discord.ext import commands

from models.user import User
from models.item import ItemInstance
from utils.embeds import item_embed, error_embed, success_embed, ConfirmView, RerollPreviewView
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
    @app_commands.describe(item_id="Item ID", use_seal="Use a Blacksmith's Seal to protect against destruction")
    async def enhance(self, interaction: discord.Interaction, item_id: str, use_seal: bool = False):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)

        itm = await ItemInstance.get(item_id)
        if itm is None or itm.owner_id != uid:
            await interaction.followup.send(embed=error_embed("Item not found."), ephemeral=True)
            return

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

        embed = discord.Embed(title="⚒️ Confirm Enhancement", description=desc, color=0xFF8800 if is_risky else 0x00AAFF)
        view = ConfirmView()
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        await view.wait()

        if not view.confirmed:
            await interaction.followup.send(embed=discord.Embed(title="Enhancement cancelled.", color=0x888888), ephemeral=True)
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
                color=0xFF0000,
            )
        elif result["success"]:
            embed = discord.Embed(
                title="✅ Enhancement Success!",
                description=f"**{itm.name} [{itm.rank}]** is now **+{result['new_level']}**!",
                color=0x00CC44,
            )
            if result["seal_used"]:
                embed.add_field(name="🔏 Seal Used", value="Blacksmith's Seal was consumed.", inline=False)
        else:
            embed = discord.Embed(
                title="❌ Enhancement Failed",
                description=f"The enhancement failed. **{itm.name}** remains at **+{current}**.",
                color=0xFF4400,
            )
            if result["seal_used"]:
                embed.add_field(name="🔏 Seal Used", value="Seal protected the item from destruction.", inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="clear", description="Reset an item to +0 (costs gold, no refund).")
    @app_commands.describe(item_id="Item ID")
    async def clear(self, interaction: discord.Interaction, item_id: str):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)

        itm = await ItemInstance.get(item_id)
        if itm is None or itm.owner_id != uid:
            await interaction.followup.send(embed=error_embed("Item not found."), ephemeral=True)
            return
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
            color=0xFF8800,
        )
        view = ConfirmView()
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        await view.wait()

        if not view.confirmed:
            await interaction.followup.send(embed=discord.Embed(title="Clear cancelled.", color=0x888888), ephemeral=True)
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
    @app_commands.describe(item_id="Item ID")
    async def reroll(self, interaction: discord.Interaction, item_id: str):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)

        itm = await ItemInstance.get(item_id)
        if itm is None or itm.owner_id != uid:
            await interaction.followup.send(embed=error_embed("Item not found."), ephemeral=True)
            return

        cost = REROLL_FULL_COST[itm.rank]
        # Generate preview (no gold deducted yet)
        client = get_motor_client()
        async with await client.start_session() as session:
            try:
                preview = await reroll_secondary_full(uid, item_id, session)
            except BlacksmithError as e:
                await interaction.followup.send(embed=error_embed(str(e)), ephemeral=True)
                return

        embed = discord.Embed(title="🎲 Reroll Preview", color=0xAA00FF)
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
            await interaction.followup.send(embed=discord.Embed(title="Reroll cancelled — kept old stat.", color=0x888888), ephemeral=True)
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
    @app_commands.describe(item_id="Item ID")
    async def refine(self, interaction: discord.Interaction, item_id: str):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)

        itm = await ItemInstance.get(item_id)
        if itm is None or itm.owner_id != uid:
            await interaction.followup.send(embed=error_embed("Item not found."), ephemeral=True)
            return

        cost = REROLL_VALUE_COST[itm.rank]
        client = get_motor_client()
        async with await client.start_session() as session:
            try:
                preview = await reroll_secondary_value(uid, item_id, session)
            except BlacksmithError as e:
                await interaction.followup.send(embed=error_embed(str(e)), ephemeral=True)
                return

        embed = discord.Embed(title="🎲 Refine Preview", color=0x00AAFF)
        embed.add_field(name="Stat Type", value=preview["stat_type"], inline=False)
        embed.add_field(name="Current Value", value=f"{preview['old_value']/10:.1f}", inline=True)
        embed.add_field(name="New Value",     value=f"{preview['new_value']/10:.1f}", inline=True)
        embed.add_field(name="Cost",          value=f"{cost} gold",  inline=False)

        view = RerollPreviewView()
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        await view.wait()

        if not view.accepted:
            await interaction.followup.send(embed=discord.Embed(title="Refine cancelled.", color=0x888888), ephemeral=True)
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


async def setup(bot: commands.Bot):
    await bot.add_cog(BlacksmithCog(bot))
