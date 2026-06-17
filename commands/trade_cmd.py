import discord
from discord import app_commands
from discord.ext import commands

from beanie import PydanticObjectId
from models.user import User
from models.trade import TradeOffer
from models.champion import ChampionInstance
from models.item import ItemInstance
from utils.embeds import error_embed, success_embed, ConfirmView, COLOR_INFO, COLOR_WARNING, get_champion_by_number, get_item_by_number
from utils.locks import get_user_lock
from utils.db_session import get_motor_client
from services.trade_service import create_trade, accept_trade, cancel_trade, TradeError


async def _resolve_champion_numbers(uid: str, numbers: list[int]) -> tuple[list[str], str]:
    """Convert display_id numbers to champion instance ID strings.
    Returns (ids, error_message). error_message is empty on success.
    """
    ids = []
    for n in numbers:
        c = await get_champion_by_number(uid, n)
        if c is None:
            return [], f"Champion #{n} not found. Use /champions to see your list."
        ids.append(str(c.id))
    return ids, ""


async def _resolve_item_numbers(uid: str, numbers: list[int]) -> tuple[list[str], str]:
    """Convert display_id numbers to item instance ID strings."""
    ids = []
    for n in numbers:
        itm = await get_item_by_number(uid, n)
        if itm is None:
            return [], f"Item #{n} not found. Use /items to see your list."
        ids.append(str(itm.id))
    return ids, ""


def _parse_numbers(s: str) -> list[int] | None:
    """Parse comma-separated integers. Returns None on parse error."""
    if not s or not s.strip():
        return []
    try:
        return [int(x.strip()) for x in s.split(",") if x.strip()]
    except ValueError:
        return None


def _summ(gold, champ_ids, item_ids):
    parts = []
    if gold:
        parts.append(f"{gold:,} gold")
    if champ_ids:
        parts.append(f"{len(champ_ids)} champion(s)")
    if item_ids:
        parts.append(f"{len(item_ids)} item(s)")
    return ", ".join(parts) or "nothing"


class TradeCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="trade-offer", description="Offer a trade to another player.")
    @app_commands.describe(
        target="Target player",
        my_gold="Gold you offer",
        their_gold="Gold you want in return",
        my_champions="Your champion numbers to offer (e.g. 1,3)",
        their_champions="Their champion numbers you want (e.g. 2)",
        my_items="Your item numbers to offer (e.g. 1,2)",
        their_items="Their item numbers you want (e.g. 3)",
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

        # Parse numbers
        my_champ_nums = _parse_numbers(my_champions)
        their_champ_nums = _parse_numbers(their_champions)
        my_item_nums = _parse_numbers(my_items)
        their_item_nums = _parse_numbers(their_items)

        for val, label in [
            (my_champ_nums, "my_champions"),
            (their_champ_nums, "their_champions"),
            (my_item_nums, "my_items"),
            (their_item_nums, "their_items"),
        ]:
            if val is None:
                await interaction.followup.send(
                    embed=error_embed(f"Invalid format for {label}. Use comma-separated numbers e.g. `1,2,3`."),
                    ephemeral=True,
                )
                return

        # Resolve your champions/items by display number
        my_champ_ids, err = await _resolve_champion_numbers(uid, my_champ_nums)
        if err:
            await interaction.followup.send(embed=error_embed(err), ephemeral=True)
            return

        my_item_ids, err = await _resolve_item_numbers(uid, my_item_nums)
        if err:
            await interaction.followup.send(embed=error_embed(err), ephemeral=True)
            return

        # Resolve target's champions/items by their display number
        their_champ_ids, err = await _resolve_champion_numbers(target_id, their_champ_nums)
        if err:
            await interaction.followup.send(embed=error_embed(f"Target: {err}"), ephemeral=True)
            return

        their_item_ids, err = await _resolve_item_numbers(target_id, their_item_nums)
        if err:
            await interaction.followup.send(embed=error_embed(f"Target: {err}"), ephemeral=True)
            return

        if not any([my_gold, their_gold, my_champ_ids, their_champ_ids, my_item_ids, their_item_ids]):
            await interaction.followup.send(embed=error_embed("Trade must include at least one item, champion, or gold."), ephemeral=True)
            return

        # Build friendly names for preview
        async def _champ_names(ids):
            names = []
            for cid in ids:
                c = await ChampionInstance.get(PydanticObjectId(cid))
                names.append(f"{c.name} [{c.rank}]" if c else cid)
            return names

        async def _item_names(ids):
            names = []
            for iid in ids:
                itm = await ItemInstance.get(PydanticObjectId(iid))
                names.append(f"{itm.name} [{itm.rank}]" if itm else iid)
            return names

        my_champ_names = await _champ_names(my_champ_ids)
        their_champ_names = await _champ_names(their_champ_ids)
        my_item_names = await _item_names(my_item_ids)
        their_item_names = await _item_names(their_item_ids)

        def _detail(gold, champs, items):
            lines = []
            if gold:
                lines.append(f"{gold:,} gold")
            lines.extend(f"• {n}" for n in champs)
            lines.extend(f"• {n}" for n in items)
            return "\n".join(lines) or "nothing"

        embed = discord.Embed(title="🤝 Confirm Trade Offer", color=COLOR_WARNING)
        embed.add_field(name="You Offer", value=_detail(my_gold, my_champ_names, my_item_names), inline=True)
        embed.add_field(name="You Want",  value=_detail(their_gold, their_champ_names, their_item_names), inline=True)
        embed.add_field(name="To", value=target.mention, inline=False)

        view = ConfirmView()
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        await view.wait()
        if not view.confirmed:
            await interaction.followup.send(embed=discord.Embed(title="Trade cancelled.", color=COLOR_INFO), ephemeral=True)
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
                f"They can accept with `/trade-accept {trade.id}`"
            ),
            ephemeral=True,
        )

        # Notify in channel so target sees the ping
        notify_embed = discord.Embed(
            title="🤝 Trade Offer",
            description=(
                f"{interaction.user.mention} → {target.mention}\n\n"
                f"**Offer:** {_detail(my_gold, my_champ_names, my_item_names)}\n"
                f"**Wants:** {_detail(their_gold, their_champ_names, their_item_names)}\n\n"
                f"Accept: `/trade-accept {trade.id}`\n"
                f"Decline: `/trade-cancel {trade.id}`"
            ),
            color=COLOR_WARNING,
        )
        await interaction.channel.send(content=target.mention, embed=notify_embed)

    @app_commands.command(name="trade-accept", description="Accept a trade offer.")
    @app_commands.describe(trade_id="Trade ID from the trade notification")
    async def trade_accept(self, interaction: discord.Interaction, trade_id: str):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)

        try:
            trade_doc = await TradeOffer.get(PydanticObjectId(trade_id))
        except Exception:
            trade_doc = None
        if trade_doc is None or trade_doc.target_id != uid or trade_doc.status != "pending":
            await interaction.followup.send(
                embed=error_embed(
                    "Trade not found or not addressed to you.",
                    "Use `/trade-list` to see your pending trades."
                ),
                ephemeral=True,
            )
            return

        you_give = _summ(trade_doc.target_gold, trade_doc.target_champion_ids, trade_doc.target_item_ids)
        you_get  = _summ(trade_doc.initiator_gold, trade_doc.initiator_champion_ids, trade_doc.initiator_item_ids)
        embed = discord.Embed(
            title="🤝 Confirm Trade",
            description=(
                f"Accept trade from <@{trade_doc.initiator_id}>?\n"
                f"**You give:** {you_give}\n"
                f"**You receive:** {you_get}\n"
                f"⚠️ This cannot be undone."
            ),
            color=COLOR_WARNING,
        )
        view = ConfirmView()
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        await view.wait()
        if not view.confirmed:
            await interaction.followup.send(embed=discord.Embed(title="Trade declined.", color=COLOR_INFO), ephemeral=True)
            return

        async with get_user_lock(uid):
            client = get_motor_client()
            async with await client.start_session() as session:
                async with session.start_transaction():
                    try:
                        await accept_trade(trade_id, uid, session)
                    except TradeError as e:
                        await interaction.followup.send(embed=error_embed(str(e)), ephemeral=True)
                        return

        await interaction.followup.send(embed=success_embed("✅ Trade completed!"), ephemeral=True)
        # Announce in channel
        await interaction.channel.send(
            embed=discord.Embed(
                title="✅ Trade Completed",
                description=f"<@{trade_doc.initiator_id}> and {interaction.user.mention} completed a trade.",
                color=0x00CC44,
            )
        )

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

    @app_commands.command(name="trade-list", description="View your pending trades.")
    async def trade_list(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        trades = await TradeOffer.find(TradeOffer.status == "pending").to_list()
        mine = [t for t in trades if uid in (t.initiator_id, t.target_id)]
        if not mine:
            await interaction.followup.send(embed=error_embed("You have no pending trades."), ephemeral=True)
            return

        embed = discord.Embed(title="🤝 Pending Trades", color=COLOR_INFO)
        for t in mine:
            if t.initiator_id == uid:
                role, other = "outgoing", t.target_id
                you_give = _summ(t.initiator_gold, t.initiator_champion_ids, t.initiator_item_ids)
                you_get  = _summ(t.target_gold,    t.target_champion_ids,    t.target_item_ids)
            else:
                role, other = "incoming", t.initiator_id
                you_give = _summ(t.target_gold,    t.target_champion_ids,    t.target_item_ids)
                you_get  = _summ(t.initiator_gold, t.initiator_champion_ids, t.initiator_item_ids)
            embed.add_field(
                name=f"[{role}] with <@{other}> — `{t.id}`",
                value=f"You give: {you_give}\nYou receive: {you_get}",
                inline=False,
            )
        embed.set_footer(text="Use /trade-accept <id> or /trade-cancel <id>")
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(TradeCog(bot))
