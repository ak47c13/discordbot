import discord
from discord import app_commands
from discord.ext import commands

from models.user import User
from models.market import MarketListing
from models.champion import ChampionInstance
from models.item import ItemInstance
from utils.embeds import champion_embed, item_embed, error_embed, success_embed, ConfirmView
from utils.locks import get_user_lock
from utils.db_session import get_motor_client
from utils.idempotency import is_already_processed, mark_processed
from services.market_service import (
    list_champion, list_item, buy_listing, cancel_listing, MarketError
)
from config.game_config import MARKET_LISTING_FEE_PCT, MARKET_TAX_PCT
import math


class MarketCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="market-list-champion", description="List a champion on the market.")
    @app_commands.describe(champion_id="Champion ID", price="Price in gold")
    async def market_list_champion(self, interaction: discord.Interaction, champion_id: str, price: int):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)

        if price <= 0:
            await interaction.followup.send(embed=error_embed("Price must be positive."), ephemeral=True)
            return

        fee = max(1, math.ceil(price * MARKET_LISTING_FEE_PCT))
        embed = discord.Embed(
            title="🏪 Confirm Market Listing",
            description=f"List champion for **{price} gold**\nListing fee: **{fee} gold** (non-refundable)",
            color=0xFF8800,
        )
        view = ConfirmView()
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        await view.wait()
        if not view.confirmed:
            await interaction.followup.send(embed=discord.Embed(title="Listing cancelled.", color=0x888888), ephemeral=True)
            return

        async with get_user_lock(uid):
            client = get_motor_client()
            async with await client.start_session() as session:
                async with session.start_transaction():
                    try:
                        listing = await list_champion(uid, champion_id, price, session)
                    except MarketError as e:
                        await interaction.followup.send(embed=error_embed(str(e)), ephemeral=True)
                        return

        await interaction.followup.send(
            embed=success_embed(f"Champion listed for {price} gold. Listing ID: `{listing.id}`"),
            ephemeral=True,
        )

    @app_commands.command(name="market-list-item", description="List an item on the market.")
    @app_commands.describe(item_id="Item ID", price="Price in gold")
    async def market_list_item(self, interaction: discord.Interaction, item_id: str, price: int):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)

        if price <= 0:
            await interaction.followup.send(embed=error_embed("Price must be positive."), ephemeral=True)
            return

        fee = max(1, math.ceil(price * MARKET_LISTING_FEE_PCT))
        embed = discord.Embed(
            title="🏪 Confirm Market Listing",
            description=f"List item for **{price} gold**\nListing fee: **{fee} gold** (non-refundable)",
            color=0xFF8800,
        )
        view = ConfirmView()
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        await view.wait()
        if not view.confirmed:
            await interaction.followup.send(embed=discord.Embed(title="Listing cancelled.", color=0x888888), ephemeral=True)
            return

        async with get_user_lock(uid):
            client = get_motor_client()
            async with await client.start_session() as session:
                async with session.start_transaction():
                    try:
                        listing = await list_item(uid, item_id, price, session)
                    except MarketError as e:
                        await interaction.followup.send(embed=error_embed(str(e)), ephemeral=True)
                        return

        await interaction.followup.send(
            embed=success_embed(f"Item listed for {price} gold. Listing ID: `{listing.id}`"),
            ephemeral=True,
        )

    @app_commands.command(name="market-browse", description="Browse active market listings.")
    async def market_browse(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        listings = await MarketListing.find(MarketListing.status == "active").limit(10).to_list()
        if not listings:
            await interaction.followup.send(embed=error_embed("No active listings."), ephemeral=True)
            return

        embed = discord.Embed(title="🏪 Market Listings", color=0xFFD700)
        for lst in listings:
            if lst.champion_id:
                c = await ChampionInstance.get(lst.champion_id)
                if c:
                    embed.add_field(
                        name=f"[Champion] {c.name} [{c.rank}] Lv.{c.level}",
                        value=f"Price: **{lst.price} gold** | ID: `{lst.id}`",
                        inline=False,
                    )
            elif lst.item_id:
                itm = await ItemInstance.get(lst.item_id)
                if itm:
                    embed.add_field(
                        name=f"[Item] {itm.name} [{itm.rank}] +{itm.enhancement}",
                        value=f"Price: **{lst.price} gold** | ID: `{lst.id}`",
                        inline=False,
                    )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="market-buy", description="Buy a market listing.")
    @app_commands.describe(listing_id="Listing ID")
    async def market_buy(self, interaction: discord.Interaction, listing_id: str):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)

        iid = str(interaction.id)
        if await is_already_processed(iid):
            await interaction.followup.send(embed=error_embed("Already processed."), ephemeral=True)
            return

        listing = await MarketListing.get(listing_id)
        if listing is None or listing.status != "active":
            await interaction.followup.send(embed=error_embed("Listing not found or no longer available."), ephemeral=True)
            return

        tax = max(1, math.ceil(listing.price * MARKET_TAX_PCT))
        embed = discord.Embed(
            title="🏪 Confirm Purchase",
            description=(
                f"Price: **{listing.price} gold**\n"
                f"Market tax: **{tax} gold** (paid by seller)\n"
                f"You pay: **{listing.price} gold**"
            ),
            color=0xFF8800,
        )
        view = ConfirmView()
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        await view.wait()
        if not view.confirmed:
            await interaction.followup.send(embed=discord.Embed(title="Purchase cancelled.", color=0x888888), ephemeral=True)
            return

        async with get_user_lock(uid):
            client = get_motor_client()
            async with await client.start_session() as session:
                async with session.start_transaction():
                    try:
                        result = await buy_listing(uid, listing_id, session)
                    except MarketError as e:
                        await interaction.followup.send(embed=error_embed(str(e)), ephemeral=True)
                        return

        await mark_processed(iid, f"market_buy:{listing_id}")
        await interaction.followup.send(
            embed=success_embed(f"Purchase complete! Paid {listing.price} gold."),
            ephemeral=True,
        )

    @app_commands.command(name="market-cancel", description="Cancel your market listing.")
    @app_commands.describe(listing_id="Listing ID")
    async def market_cancel(self, interaction: discord.Interaction, listing_id: str):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)

        async with get_user_lock(uid):
            client = get_motor_client()
            async with await client.start_session() as session:
                async with session.start_transaction():
                    try:
                        await cancel_listing(uid, listing_id, session)
                    except MarketError as e:
                        await interaction.followup.send(embed=error_embed(str(e)), ephemeral=True)
                        return

        await interaction.followup.send(
            embed=success_embed("Listing cancelled. Note: listing fee is not refunded."),
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(MarketCog(bot))
