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
from services.item_service import fuse_items, bulk_fuse_items, ItemFusionError
from services.bulk_service import bulk_sell_items, BulkSellError
from config.game_config import ITEM_FUSION_COST, RANKS, SELL_PRICE_ITEM


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

    @app_commands.command(name="fuse-items", description="Fuse 3 identical same-rank +0 items into 1 of next rank.")
    @app_commands.describe(name="Item name", rank="Item rank (F/E/D/C/B/A)")
    async def fuse_items_cmd(self, interaction: discord.Interaction, name: str, rank: str):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        rank = rank.upper()

        if rank == "S":
            await interaction.followup.send(
                embed=error_embed("S-rank items cannot be fused."), ephemeral=True
            )
            return
        if rank not in RANKS:
            await interaction.followup.send(
                embed=error_embed("Invalid rank.", "Use one of F/E/D/C/B/A."), ephemeral=True
            )
            return

        # Auto-select 3 matching +0 available, non-favorite items.
        candidates = await ItemInstance.find(
            ItemInstance.owner_id == uid,
            ItemInstance.name == name,
            ItemInstance.rank == rank,
        ).to_list()
        usable = [i for i in candidates if i.is_fusible and not getattr(i, "favorite", False)]
        if len(usable) < 3:
            await interaction.followup.send(
                embed=error_embed(
                    f"Not enough fusible {name} [{rank}] (+0) items. Have {len(usable)}, need 3.",
                    "Items must be +0, unlocked, non-favorite, and not equipped/traded/listed.",
                ),
                ephemeral=True,
            )
            return

        trio = usable[:3]
        ids = [str(i.id) for i in trio]
        next_rank = RANKS[RANKS.index(rank) + 1]
        cost = ITEM_FUSION_COST[next_rank]

        embed = discord.Embed(
            title="🔨 Confirm Item Fusion",
            description=(
                f"Fuse **3x {name} [{rank}] +0** → **{name} [{next_rank}] +0**\n"
                f"Cost: **{cost} gold**\n"
                f"⚠️ The 3 source items will be **permanently consumed**.\n"
                f"⚠️ Result gets a **new secondary stat roll**."
            ),
            color=COLOR_WARNING,
        )

        view = ConfirmView()
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        await view.wait()

        if not view.confirmed:
            await interaction.followup.send(embed=discord.Embed(title="Fusion cancelled.", color=COLOR_INFO), ephemeral=True)
            return

        async with get_user_lock(uid):
            client = get_motor_client()
            async with await client.start_session() as session:
                async with session.start_transaction():
                    try:
                        result = await fuse_items(uid, ids, session)
                    except ItemFusionError as e:
                        await interaction.followup.send(embed=error_embed(str(e)), ephemeral=True)
                        return

        await interaction.followup.send(embed=item_embed(result, "✨ Item Fusion Result"), ephemeral=True)

    @app_commands.command(name="lock-item", description="Lock or unlock an item to protect it.")
    @app_commands.describe(number="Item list number (see /items)")
    async def lock_item(self, interaction: discord.Interaction, number: int):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        itm = await get_item_by_number(uid, number)
        if itm is None or itm.owner_id != uid:
            await interaction.followup.send(embed=error_embed("Item not found."), ephemeral=True)
            return
        itm.locked = not itm.locked
        await itm.save()
        state = "🔒 locked" if itm.locked else "🔓 unlocked"
        await interaction.followup.send(embed=success_embed(f"{itm.name} +{itm.enhancement} is now {state}."), ephemeral=True)

    @app_commands.command(name="favorite-item", description="Toggle favorite on an item.")
    @app_commands.describe(number="Item list number (see /items)")
    async def favorite_item(self, interaction: discord.Interaction, number: int):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        itm = await get_item_by_number(uid, number)
        if itm is None or itm.owner_id != uid:
            await interaction.followup.send(embed=error_embed("Item not found."), ephemeral=True)
            return
        new_state = not getattr(itm, "favorite", False)
        itm.favorite = new_state
        await itm.save()
        state = "⭐ favorited" if new_state else "unfavorited"
        await interaction.followup.send(embed=success_embed(f"{itm.name} is now {state}."), ephemeral=True)

    @app_commands.command(name="items-bulk-fuse", description="Fuse many identical +0 items at once (count must be a multiple of 3).")
    @app_commands.describe(name="Item name", rank="Source rank", count="How many to consume (multiple of 3)")
    async def bulk_fuse_items_cmd(self, interaction: discord.Interaction, name: str, rank: str, count: int):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        rank = rank.upper()
        if count <= 0 or count % 3 != 0:
            await interaction.followup.send(embed=error_embed("Count must be a positive multiple of 3."), ephemeral=True)
            return
        if rank == "S":
            await interaction.followup.send(embed=error_embed("S-rank items cannot be fused."), ephemeral=True)
            return
        next_rank = RANKS[RANKS.index(rank) + 1]
        produced = count // 3

        embed = discord.Embed(
            title="🔨 Confirm Bulk Item Fusion",
            description=f"Fuse **{count}x {name} [{rank}] +0** → **{produced}x {name} [{next_rank}]**?",
            color=COLOR_WARNING,
        )
        view = ConfirmView()
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        await view.wait()
        if not view.confirmed:
            await interaction.followup.send(embed=discord.Embed(title="Bulk fusion cancelled.", color=COLOR_INFO), ephemeral=True)
            return

        async with get_user_lock(uid):
            client = get_motor_client()
            async with await client.start_session() as session:
                async with session.start_transaction():
                    try:
                        created = await bulk_fuse_items(uid, name, rank, count, session)
                    except ItemFusionError as e:
                        await interaction.followup.send(embed=error_embed(str(e)), ephemeral=True)
                        return

        await interaction.followup.send(embed=success_embed(f"✨ Created {len(created)}x {name} [{next_rank}]!"), ephemeral=True)

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

        await interaction.followup.send(embed=success_embed(f"Sold {res['sold']} item(s) for {res['gold']} gold."), ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ItemsCog(bot))
