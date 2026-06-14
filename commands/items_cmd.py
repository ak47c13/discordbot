import discord
from discord import app_commands
from discord.ext import commands

from models.user import User
from models.item import ItemInstance
from utils.embeds import item_embed, error_embed, success_embed, ConfirmView
from utils.locks import get_user_lock
from utils.db_session import get_motor_client
from services.item_service import fuse_items, ItemFusionError
from config.game_config import ITEM_FUSION_COST, RANKS


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

        embed = discord.Embed(title=f"⚔️ Your Items ({len(items)} total)", color=0x5865F2)
        for itm in items[:10]:
            from config.game_config import get_aura
            aura = get_aura(itm.enhancement)
            status = []
            if itm.equipped_to: status.append("⚔️")
            if itm.locked:      status.append("🔒")
            if itm.favorited:   status.append("⭐")
            if itm.in_market:   status.append("🏪")
            if itm.in_trade:    status.append("🤝")
            embed.add_field(
                name=f"{' '.join(status)}{aura} {itm.name} [{itm.rank}] +{itm.enhancement}",
                value=f"ID: `{itm.id}`",
                inline=False,
            )
        if len(items) > 10:
            embed.set_footer(text=f"Showing 10 of {len(items)}.")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="item-info", description="View details of a specific item.")
    @app_commands.describe(item_id="Item ID")
    async def item_info(self, interaction: discord.Interaction, item_id: str):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        itm = await ItemInstance.get(item_id)
        if itm is None or itm.owner_id != uid:
            await interaction.followup.send(embed=error_embed("Item not found."), ephemeral=True)
            return
        await interaction.followup.send(embed=item_embed(itm, "Item Details"), ephemeral=True)

    @app_commands.command(name="fuse-items", description="Fuse 3 identical same-rank +0 items into 1 of next rank.")
    @app_commands.describe(id1="Item 1 ID", id2="Item 2 ID", id3="Item 3 ID")
    async def fuse_items_cmd(self, interaction: discord.Interaction, id1: str, id2: str, id3: str):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        ids = [id1, id2, id3]

        if len(set(ids)) != 3:
            await interaction.followup.send(embed=error_embed("Cannot use the same item twice."), ephemeral=True)
            return

        items = []
        for iid in ids:
            itm = await ItemInstance.get(iid)
            if itm is None or itm.owner_id != uid:
                await interaction.followup.send(embed=error_embed(f"Item {iid} not found."), ephemeral=True)
                return
            items.append(itm)

        if not all(i.enhancement == 0 for i in items):
            await interaction.followup.send(
                embed=error_embed(
                    "All items must be +0. Enhanced items must be cleared at the blacksmith first."
                ),
                ephemeral=True,
            )
            return

        if len({i.name for i in items}) != 1 or len({i.rank for i in items}) != 1:
            await interaction.followup.send(embed=error_embed("All 3 items must have the same name and rank."), ephemeral=True)
            return

        current_rank = items[0].rank
        if current_rank == "S":
            await interaction.followup.send(embed=error_embed("S-rank items cannot be fused."), ephemeral=True)
            return

        next_rank = RANKS[RANKS.index(current_rank) + 1]
        cost = ITEM_FUSION_COST[next_rank]

        embed = discord.Embed(
            title="🔨 Confirm Item Fusion",
            description=(
                f"Fuse **3x {items[0].name} [{current_rank}] +0** → **{items[0].name} [{next_rank}] +0**\n"
                f"Cost: **{cost} gold**\n"
                f"⚠️ The 3 source items will be **permanently consumed**.\n"
                f"⚠️ Result gets a **new secondary stat roll**."
            ),
            color=0xFF8800,
        )

        view = ConfirmView()
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        await view.wait()

        if not view.confirmed:
            await interaction.followup.send(embed=discord.Embed(title="Fusion cancelled.", color=0x888888), ephemeral=True)
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
    @app_commands.describe(item_id="Item ID")
    async def lock_item(self, interaction: discord.Interaction, item_id: str):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        itm = await ItemInstance.get(item_id)
        if itm is None or itm.owner_id != uid:
            await interaction.followup.send(embed=error_embed("Item not found."), ephemeral=True)
            return
        itm.locked = not itm.locked
        await itm.save()
        state = "🔒 locked" if itm.locked else "🔓 unlocked"
        await interaction.followup.send(embed=success_embed(f"{itm.name} +{itm.enhancement} is now {state}."), ephemeral=True)

    @app_commands.command(name="favorite-item", description="Toggle favorite on an item.")
    @app_commands.describe(item_id="Item ID")
    async def favorite_item(self, interaction: discord.Interaction, item_id: str):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        itm = await ItemInstance.get(item_id)
        if itm is None or itm.owner_id != uid:
            await interaction.followup.send(embed=error_embed("Item not found."), ephemeral=True)
            return
        itm.favorited = not itm.favorited
        await itm.save()
        state = "⭐ favorited" if itm.favorited else "unfavorited"
        await interaction.followup.send(embed=success_embed(f"{itm.name} is now {state}."), ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ItemsCog(bot))
