"""Item equip/unequip commands."""
import discord
from discord import app_commands
from discord.ext import commands

from models.item import ItemInstance
from utils.embeds import (
    item_embed, error_embed, success_embed,
    get_champion_by_number, get_item_by_number,
)
from utils.locks import get_user_lock


class TeamCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="equip", description="Equip an item to a champion.")
    @app_commands.describe(
        item_number="Item list number (see /items)",
        champion_number="Champion list number (see /champions)",
        slot="Equipment slot 1-6",
    )
    async def equip(self, interaction: discord.Interaction, item_number: int, champion_number: int, slot: int):
        await interaction.response.defer(ephemeral=True)
        if not 1 <= slot <= 6:
            await interaction.followup.send(embed=error_embed("Equipment slot must be 1–6."), ephemeral=True)
            return

        uid = str(interaction.user.id)
        async with get_user_lock(uid):
            itm = await get_item_by_number(uid, item_number)
            if itm is None or itm.owner_id != uid:
                await interaction.followup.send(embed=error_embed("Item not found or not owned by you."), ephemeral=True)
                return
            if itm.in_trade or itm.in_market:
                await interaction.followup.send(embed=error_embed("Item is in a trade or listing."), ephemeral=True)
                return

            champ = await get_champion_by_number(uid, champion_number)
            if champ is None or champ.owner_id != uid:
                await interaction.followup.send(embed=error_embed("Champion not found."), ephemeral=True)
                return
            champion_id = str(champ.id)

            # If something is already in this slot, unequip it first
            existing_in_slot = await ItemInstance.find_one(
                ItemInstance.equipped_to == champion_id,
                ItemInstance.equipment_slot == slot,
            )
            if existing_in_slot:
                existing_in_slot.equipped_to = None
                existing_in_slot.equipment_slot = None
                await existing_in_slot.save()

            # Count total items on champion (after clearing the slot)
            item_count = await ItemInstance.find(
                ItemInstance.equipped_to == champion_id
            ).count()
            if item_count >= 6 and not existing_in_slot:
                await interaction.followup.send(embed=error_embed("Champion already has 6 items equipped."), ephemeral=True)
                return

            # Unequip item from previous champion if needed
            if itm.equipped_to:
                itm.equipped_to = None
                itm.equipment_slot = None

            itm.equipped_to = champion_id
            itm.equipment_slot = slot
            await itm.save()

        await interaction.followup.send(
            embed=success_embed(f"{itm.name} +{itm.enhancement} equipped to {champ.name} in slot {slot}."),
            ephemeral=True,
        )

    @app_commands.command(name="unequip", description="Unequip an item from a champion.")
    @app_commands.describe(item_number="Item list number (see /items)")
    async def unequip(self, interaction: discord.Interaction, item_number: int):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        async with get_user_lock(uid):
            itm = await get_item_by_number(uid, item_number)
            if itm is None or itm.owner_id != uid:
                await interaction.followup.send(embed=error_embed("Item not found."), ephemeral=True)
                return
            if not itm.equipped_to:
                await interaction.followup.send(embed=error_embed("Item is not equipped."), ephemeral=True)
                return
            itm.equipped_to = None
            itm.equipment_slot = None
            await itm.save()

        await interaction.followup.send(
            embed=success_embed(f"{itm.name} unequipped."),
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(TeamCog(bot))
