import discord
from discord import app_commands
from discord.ext import commands

from models.user import User
from models.market import MarketListing
from models.champion import ChampionInstance
from models.item import ItemInstance
from utils.embeds import (
    champion_embed, item_embed, error_embed, success_embed, ConfirmView,
    get_champion_by_number, get_item_by_number,
    COLOR_INFO, COLOR_WARNING, COLOR_GOLD,
)
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
    @app_commands.describe(champion_number="Champion list number (see /champions)", price="Price in gold")
    async def market_list_champion(self, interaction: discord.Interaction, champion_number: int, price: int):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)

        if price <= 0:
            await interaction.followup.send(embed=error_embed("Price must be positive."), ephemeral=True)
            return

        champ = await get_champion_by_number(uid, champion_number)
        if champ is None or champ.owner_id != uid:
            await interaction.followup.send(
                embed=error_embed("Champion not found.", "Use `/champions` to find the right number."),
                ephemeral=True,
            )
            return
        champion_id = str(champ.id)

        fee = max(1, math.ceil(price * MARKET_LISTING_FEE_PCT))
        embed = discord.Embed(
            title="🏪 Confirm Market Listing",
            description=f"List champion for **{price} gold**\nListing fee: **{fee} gold** (non-refundable)",
            color=COLOR_WARNING,
        )
        view = ConfirmView()
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        await view.wait()
        if not view.confirmed:
            await interaction.followup.send(embed=discord.Embed(title="Listing cancelled.", color=COLOR_INFO), ephemeral=True)
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
    @app_commands.describe(item_number="Item list number (see /items)", price="Price in gold")
    async def market_list_item(self, interaction: discord.Interaction, item_number: int, price: int):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)

        if price <= 0:
            await interaction.followup.send(embed=error_embed("Price must be positive."), ephemeral=True)
            return

        itm = await get_item_by_number(uid, item_number)
        if itm is None or itm.owner_id != uid:
            await interaction.followup.send(
                embed=error_embed("Item not found.", "Use `/items` to find the right number."),
                ephemeral=True,
            )
            return
        item_id = str(itm.id)

        fee = max(1, math.ceil(price * MARKET_LISTING_FEE_PCT))
        embed = discord.Embed(
            title="🏪 Confirm Market Listing",
            description=f"List item for **{price} gold**\nListing fee: **{fee} gold** (non-refundable)",
            color=COLOR_WARNING,
        )
        view = ConfirmView()
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        await view.wait()
        if not view.confirmed:
            await interaction.followup.send(embed=discord.Embed(title="Listing cancelled.", color=COLOR_INFO), ephemeral=True)
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

        embed = discord.Embed(title="🏪 Market Listings", color=COLOR_GOLD)
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
            color=COLOR_WARNING,
        )
        view = ConfirmView()
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        await view.wait()
        if not view.confirmed:
            await interaction.followup.send(embed=discord.Embed(title="Purchase cancelled.", color=COLOR_INFO), ephemeral=True)
            return

        async with get_user_lock(uid):
            client = get_motor_client()
            async with await client.start_session() as session:
                async with session.start_transaction():
                    if await is_already_processed(iid):
                        await interaction.followup.send(embed=error_embed("Already processed."), ephemeral=True)
                        return
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

    async def _listing_label(self, lst) -> tuple[str, str] | None:
        """Return (name_line, rank) for a listing, or None if backing asset gone."""
        if lst.champion_id:
            c = await ChampionInstance.get(lst.champion_id)
            if c:
                return f"[Champion] {c.name} [{c.rank}] Lv.{c.level}", c.rank
        elif lst.item_id:
            itm = await ItemInstance.get(lst.item_id)
            if itm:
                return f"[Item] {itm.name} [{itm.rank}] +{itm.enhancement}", itm.rank
        return None

    @app_commands.command(name="market-my-listings", description="View your active market listings.")
    async def market_my_listings(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        listings = await MarketListing.find(
            MarketListing.seller_id == uid,
            MarketListing.status == "active",
        ).to_list()
        if not listings:
            await interaction.followup.send(embed=error_embed("You have no active listings."), ephemeral=True)
            return

        embed = discord.Embed(title="🏪 Your Listings", color=COLOR_GOLD)
        for lst in listings:
            label = await self._listing_label(lst)
            if label is None:
                continue
            embed.add_field(
                name=label[0],
                value=f"Price: **{lst.price} gold** | ID: `{lst.id}`",
                inline=False,
            )
        embed.set_footer(text="Use /market-cancel <listing_id> to remove a listing")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="market-search", description="Search market listings by name, type, or price.")
    @app_commands.describe(name="Name filter", type="champion or item", max_price="Maximum price")
    @app_commands.choices(type=[
        app_commands.Choice(name="champion", value="champion"),
        app_commands.Choice(name="item", value="item"),
    ])
    async def market_search(
        self,
        interaction: discord.Interaction,
        name: str = "",
        type: str = "",
        max_price: int = 0,
    ):
        await interaction.response.defer(ephemeral=True)
        listings = await MarketListing.find(MarketListing.status == "active").to_list()

        matched = []
        for lst in listings:
            if type == "champion" and not lst.champion_id:
                continue
            if type == "item" and not lst.item_id:
                continue
            if max_price and lst.price > max_price:
                continue
            label = await self._listing_label(lst)
            if label is None:
                continue
            if name and name.lower() not in label[0].lower():
                continue
            matched.append((lst, label[0]))

        if not matched:
            await interaction.followup.send(embed=error_embed("No listings match your search."), ephemeral=True)
            return

        view = MarketSearchView(matched, interaction.user.id)
        await interaction.followup.send(embed=view.current_embed(), view=view, ephemeral=True)


class MarketSearchView(discord.ui.View):
    PAGE_SIZE = 8

    def __init__(self, matched, user_id: int, timeout: float = 120.0):
        super().__init__(timeout=timeout)
        self.matched = matched
        self.user_id = user_id
        self.index = 0
        self.total_pages = max(1, (len(matched) + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
        self._refresh_buttons()

    def current_embed(self) -> discord.Embed:
        start = self.index * self.PAGE_SIZE
        chunk = self.matched[start:start + self.PAGE_SIZE]
        embed = discord.Embed(
            title=f"🔎 Market Search — Page {self.index + 1}/{self.total_pages}",
            color=COLOR_GOLD,
        )
        for lst, label in chunk:
            embed.add_field(
                name=label,
                value=f"Price: **{lst.price} gold** | ID: `{lst.id}`",
                inline=False,
            )
        embed.set_footer(text="Use /market-buy <listing_id> to purchase")
        return embed

    def _refresh_buttons(self):
        self.prev_button.disabled = self.index <= 0
        self.next_button.disabled = self.index >= self.total_pages - 1

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This search isn't yours.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.index > 0:
            self.index -= 1
        self._refresh_buttons()
        await interaction.response.edit_message(embed=self.current_embed(), view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.primary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.index < self.total_pages - 1:
            self.index += 1
        self._refresh_buttons()
        await interaction.response.edit_message(embed=self.current_embed(), view=self)


async def setup(bot: commands.Bot):
    await bot.add_cog(MarketCog(bot))
