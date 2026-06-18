import discord
from discord import app_commands
from discord.ext import commands

from models.user import User
from models.item import ItemInstance
from utils.embeds import (
    item_embed, error_embed, success_embed, ConfirmView,
    PaginatedItemView, get_item_by_number,
    COLOR_WARNING, COLOR_INFO,
)
from utils.locks import get_user_lock
from utils.db_session import get_motor_client
from services.bulk_service import bulk_sell_items, BulkSellError
from config.game_config import RANKS, SELL_PRICE_ITEM


class ItemProtectView(discord.ui.View):
    def __init__(self, item, user_id):
        super().__init__(timeout=60)
        self.item = item
        self.user_id = user_id

    def _build_embed(self):
        i = self.item
        fav = "⭐ Yes" if getattr(i, "favorite", False) else "—"
        locked = "🔒 Yes" if i.locked else "—"
        return discord.Embed(
            title=f"{i.name} [{i.rank}] +{i.enhancement}  #{i.display_id}",
            description=f"**Favorite:** {fav}\n**Locked:** {locked}",
            color=0x5865F2,
        )

    @discord.ui.button(label="Toggle Favorite ⭐", style=discord.ButtonStyle.secondary)
    async def toggle_fav(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not your item.", ephemeral=True)
            return
        self.item.favorite = not getattr(self.item, "favorite", False)
        await self.item.save()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    @discord.ui.button(label="Toggle Lock 🔒", style=discord.ButtonStyle.secondary)
    async def toggle_lock(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not your item.", ephemeral=True)
            return
        self.item.locked = not self.item.locked
        await self.item.save()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)


class ItemsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="items", description="View your item inventory.")
    @app_commands.describe(rank="Filter by rank", name="Filter by name")
    async def items_list(self, interaction: discord.Interaction, rank: str = "", name: str = ""):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        await User.get_or_create(uid, interaction.user.display_name)

        query = ItemInstance.find(ItemInstance.owner_id == uid)
        items = await query.to_list()

        if rank:
            items = [i for i in items if i.rank == rank.upper()]
        if name:
            items = [i for i in items if name.lower() in i.name.lower()]

        if not items:
            await interaction.followup.send(embed=error_embed("No items found."), ephemeral=True)
            return

        view = PaginatedItemView(items, interaction.user.id)
        await interaction.followup.send(embed=view.current_embed(), view=view, ephemeral=True)

    @app_commands.command(name="item-info", description="View details of a specific item.")
    @app_commands.describe(number="Item list number (see /items)")
    async def item_info(self, interaction: discord.Interaction, number: int):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        itm = await get_item_by_number(uid, number)
        if itm is None or itm.owner_id != uid:
            await interaction.followup.send(embed=error_embed("Item not found."), ephemeral=True)
            return
        await interaction.followup.send(embed=item_embed(itm, "Item Details"), ephemeral=True)

    @app_commands.command(name="item-protect", description="Toggle favorite or lock status on an item.")
    @app_commands.describe(number="Item list number (see /items)")
    async def item_protect(self, interaction: discord.Interaction, number: int):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        itm = await get_item_by_number(uid, number)
        if itm is None or itm.owner_id != uid:
            await interaction.followup.send(embed=error_embed("Item not found."), ephemeral=True)
            return
        view = ItemProtectView(itm, interaction.user.id)
        await interaction.followup.send(embed=view._build_embed(), view=view, ephemeral=True)

    @app_commands.command(name="items-bulk-sell", description="Sell all unlocked, non-favorite, non-equipped items of a rank.")
    @app_commands.describe(rank="Rank to sell", name="Optional item name filter")
    async def bulk_sell_items_cmd(self, interaction: discord.Interaction, rank: str, name: str = ""):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        rank = rank.upper()
        filters = {"rank": rank, "name": name or None}

        items = await ItemInstance.find(ItemInstance.owner_id == uid, ItemInstance.rank == rank).to_list()
        matches = [
            i for i in items
            if (not name or i.name == name)
            and not i.locked and not getattr(i, "favorite", False)
            and not i.in_trade and not i.in_market and i.equipped_to is None
        ]
        if not matches:
            await interaction.followup.send(embed=error_embed("No sellable items match."), ephemeral=True)
            return
        gold = len(matches) * SELL_PRICE_ITEM.get(rank, 0)

        embed = discord.Embed(
            title="💰 Confirm Bulk Sell",
            description=f"Sell **{len(matches)}** item(s) for **{gold} gold**?",
            color=COLOR_WARNING,
        )
        view = ConfirmView()
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        await view.wait()
        if not view.confirmed:
            await interaction.followup.send(embed=discord.Embed(title="Sell cancelled.", color=COLOR_INFO), ephemeral=True)
            return

        async with get_user_lock(uid):
            client = get_motor_client()
            async with await client.start_session() as session:
                async with session.start_transaction():
                    try:
                        res = await bulk_sell_items(uid, filters, session)
                    except BulkSellError as e:
                        await interaction.followup.send(embed=error_embed(str(e)), ephemeral=True)
                        return

        await interaction.followup.send(embed=success_embed(f"Sold {res['sold']} item(s) for {res['gold']} gold."))


    @app_commands.command(name="items-equipped", description="Show all items currently equipped on your champions.")
    async def items_equipped(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        equipped = await ItemInstance.find(
            ItemInstance.owner_id == uid,
            ItemInstance.equipped_to != None,
        ).to_list()
        if not equipped:
            await interaction.followup.send(
                embed=error_embed("No items are equipped. Use `/equip <item_number> <champion_number> <slot>` to equip one."),
                ephemeral=True,
            )
            return

        # Group by champion
        from models.champion import ChampionInstance
        champ_ids = list({i.equipped_to for i in equipped if i.equipped_to})
        champ_map = {}
        for cid in champ_ids:
            from beanie import PydanticObjectId
            c = await ChampionInstance.get(PydanticObjectId(cid))
            if c:
                champ_map[cid] = c

        embed = discord.Embed(
            title="Equipped Items",
            description=f"**{len(equipped)}** item(s) equipped across **{len(champ_map)}** champion(s).\n\nUse `/equip` to equip · `/unequip` to remove",
            color=0x5865F2,
        )
        for champ in champ_map.values():
            champ_items = [i for i in equipped if i.equipped_to == str(champ.id)]
            champ_items.sort(key=lambda i: i.equipment_slot or 0)
            lines = []
            for itm in champ_items:
                slot = itm.equipment_slot or "?"
                stat = int(itm.main_stat_base * (1 + (itm.enhancement * 0.1)))
                lines.append(f"Slot {slot}: **{itm.name}** [{itm.rank}] +{itm.enhancement} ({itm.main_stat_type.upper()} {stat})")
            embed.add_field(
                name=f"{champ.name} [{champ.rank}] Lv.{champ.level}  #{champ.display_id}",
                value="\n".join(lines) if lines else "—",
                inline=False,
            )
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ItemsCog(bot))
