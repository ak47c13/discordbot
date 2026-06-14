import discord
from discord import app_commands
from discord.ext import commands

from models.user import User
from utils.embeds import error_embed, success_embed, ConfirmView
from utils.locks import get_user_lock
from utils.db_session import get_motor_client
from services.trade_service import create_trade, accept_trade, cancel_trade, TradeError


class TradeCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="trade-offer", description="Offer a trade to another player.")
    @app_commands.describe(
        target="Target player",
        my_gold="Gold you offer",
        their_gold="Gold you want",
        my_champions="Comma-separated champion IDs you offer",
        their_champions="Comma-separated champion IDs you want",
        my_items="Comma-separated item IDs you offer",
        their_items="Comma-separated item IDs you want",
    )
    async def trade_offer(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        my_gold: int = 0,
        their_gold: int = 0,
        my_champions: str = "",
        their_champions: str = "",
        my_items: str = "",
        their_items: str = "",
    ):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        target_id = str(target.id)

        if uid == target_id:
            await interaction.followup.send(embed=error_embed("Cannot trade with yourself."), ephemeral=True)
            return

        def parse_ids(s: str) -> list[str]:
            return [x.strip() for x in s.split(",") if x.strip()] if s else []

        my_champ_ids = parse_ids(my_champions)
        their_champ_ids = parse_ids(their_champions)
        my_item_ids = parse_ids(my_items)
        their_item_ids = parse_ids(their_items)

        embed = discord.Embed(title="🤝 Confirm Trade Offer", color=0xFF8800)
        embed.add_field(name="You Offer", value=f"Gold: {my_gold}\nChampions: {my_champ_ids or 'none'}\nItems: {my_item_ids or 'none'}", inline=True)
        embed.add_field(name="You Want",  value=f"Gold: {their_gold}\nChampions: {their_champ_ids or 'none'}\nItems: {their_item_ids or 'none'}", inline=True)
        embed.add_field(name="Target", value=target.mention, inline=False)

        view = ConfirmView()
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        await view.wait()
        if not view.confirmed:
            await interaction.followup.send(embed=discord.Embed(title="Trade cancelled.", color=0x888888), ephemeral=True)
            return

        async with get_user_lock(uid):
            client = get_motor_client()
            async with await client.start_session() as session:
                async with session.start_transaction():
                    try:
                        trade = await create_trade(
                            uid, target_id,
                            my_champ_ids, my_item_ids, my_gold,
                            their_champ_ids, their_item_ids, their_gold,
                            session,
                        )
                    except TradeError as e:
                        await interaction.followup.send(embed=error_embed(str(e)), ephemeral=True)
                        return

        await interaction.followup.send(
            embed=success_embed(
                f"Trade offer sent to {target.mention}!\n"
                f"Trade ID: `{trade.id}`\n"
                f"They can accept with `/trade-accept {trade.id}`"
            ),
            ephemeral=True,
        )
        # Notify the target
        try:
            await target.send(
                embed=discord.Embed(
                    title="🤝 Trade Offer Received",
                    description=(
                        f"{interaction.user.display_name} wants to trade!\n"
                        f"Use `/trade-accept {trade.id}` to accept or `/trade-cancel {trade.id}` to decline."
                    ),
                    color=0x5865F2,
                )
            )
        except discord.Forbidden:
            pass

    @app_commands.command(name="trade-accept", description="Accept a trade offer.")
    @app_commands.describe(trade_id="Trade ID")
    async def trade_accept(self, interaction: discord.Interaction, trade_id: str):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)

        async with get_user_lock(uid):
            client = get_motor_client()
            async with await client.start_session() as session:
                async with session.start_transaction():
                    try:
                        trade = await accept_trade(trade_id, uid, session)
                    except TradeError as e:
                        await interaction.followup.send(embed=error_embed(str(e)), ephemeral=True)
                        return

        await interaction.followup.send(embed=success_embed("✅ Trade completed successfully!"), ephemeral=True)

    @app_commands.command(name="trade-cancel", description="Cancel or decline a trade.")
    @app_commands.describe(trade_id="Trade ID")
    async def trade_cancel(self, interaction: discord.Interaction, trade_id: str):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)

        async with get_user_lock(uid):
            client = get_motor_client()
            async with await client.start_session() as session:
                async with session.start_transaction():
                    try:
                        await cancel_trade(trade_id, uid, session)
                    except TradeError as e:
                        await interaction.followup.send(embed=error_embed(str(e)), ephemeral=True)
                        return

        await interaction.followup.send(embed=success_embed("Trade cancelled."), ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(TradeCog(bot))
