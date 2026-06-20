import discord
from discord import app_commands
from discord.ext import commands

from beanie import PydanticObjectId
from models.user import User
from models.trade import TradeOffer
from models.champion import ChampionInstance
from models.item import ItemInstance
from utils.embeds import error_embed, success_embed, COLOR_INFO, COLOR_WARNING, get_champion_by_number, get_item_by_number
from utils.locks import get_user_lock
from services.trade_service import create_trade, accept_trade, cancel_trade, TradeError


async def _resolve_champion_numbers(uid: str, numbers: list[int]) -> tuple[list[str], str]:
    ids = []
    for n in numbers:
        c = await get_champion_by_number(uid, n)
        if c is None:
            return [], f"Champion #{n} not found. Use /champions to see your list."
        ids.append(str(c.id))
    return ids, ""


async def _resolve_item_numbers(uid: str, numbers: list[int]) -> tuple[list[str], str]:
    ids = []
    for n in numbers:
        itm = await get_item_by_number(uid, n)
        if itm is None:
            return [], f"Item #{n} not found. Use /items to see your list."
        ids.append(str(itm.id))
    return ids, ""


def _parse_numbers(s: str) -> list[int] | None:
    if not s or not s.strip():
        return []
    try:
        return [int(x.strip()) for x in s.split(",") if x.strip()]
    except ValueError:
        return None


def _detail(gold, champ_names, item_names):
    lines = []
    if gold:
        lines.append(f"{gold:,} gold")
    lines.extend(f"• {n}" for n in champ_names)
    lines.extend(f"• {n}" for n in item_names)
    return "\n".join(lines) or "nothing"


def _summ(gold, champ_ids, item_ids):
    parts = []
    if gold:
        parts.append(f"{gold:,} gold")
    if champ_ids:
        parts.append(f"{len(champ_ids)} champion(s)")
    if item_ids:
        parts.append(f"{len(item_ids)} item(s)")
    return ", ".join(parts) or "nothing"


def _trade_embed(trade_id: str, initiator_mention: str, target_mention: str,
                 offer_text: str, want_text: str, status: str = "pending") -> discord.Embed:
    colors = {"pending": COLOR_WARNING, "completed": 0x00CC44, "cancelled": 0x888888}
    titles = {"pending": "🤝 Trade Offer", "completed": "✅ Trade Completed", "cancelled": "❌ Trade Cancelled"}
    embed = discord.Embed(title=titles.get(status, "🤝 Trade"), color=colors.get(status, COLOR_WARNING))
    embed.add_field(name=f"{initiator_mention} offers", value=offer_text, inline=True)
    embed.add_field(name=f"wants from {target_mention}", value=want_text, inline=True)
    if status == "pending":
        embed.set_footer(text=f"Trade ID: {trade_id}")
    return embed


class TradeOfferView(discord.ui.View):
    """Persistent view attached to the public trade offer message."""

    def __init__(self, trade_id: str, initiator_id: int, target_id: int):
        super().__init__(timeout=None)  # persistent — survives bot restart
        self.trade_id = trade_id
        self.initiator_id = initiator_id
        self.target_id = target_id

    @discord.ui.button(label="✅ Accept", style=discord.ButtonStyle.success, custom_id="trade_accept_btn")
    async def accept_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.target_id:
            await interaction.response.send_message("This trade isn't addressed to you.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        initiator_id = str(self.initiator_id)

        # Acquire both locks in consistent order to prevent deadlock
        first_id, second_id = sorted([uid, initiator_id])
        try:
            async with get_user_lock(first_id):
                async with get_user_lock(second_id):
                    from utils.db_session import get_motor_client
                    client = get_motor_client()
                    async with await client.start_session() as session:
                        async with session.start_transaction():
                            trade = await accept_trade(self.trade_id, uid, session)
        except TradeError as e:
            await interaction.followup.send(embed=error_embed(str(e)), ephemeral=True)
            return
        except Exception as e:
            await interaction.followup.send(embed=error_embed(f"Trade failed: {e}"), ephemeral=True)
            return

        # Update the public embed to show completed
        for child in self.children:
            child.disabled = True
        new_embed = discord.Embed(
            title="✅ Trade Completed",
            description=f"<@{self.initiator_id}> and {interaction.user.mention} completed a trade.",
            color=0x00CC44,
        )
        await interaction.message.edit(embed=new_embed, view=self)
        await interaction.followup.send(embed=success_embed("Trade accepted!"), ephemeral=True)

    @discord.ui.button(label="❌ Decline", style=discord.ButtonStyle.danger, custom_id="trade_decline_btn")
    async def decline_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Either party can cancel
        if interaction.user.id not in (self.initiator_id, self.target_id):
            await interaction.response.send_message("This trade isn't yours.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)

        try:
            async with get_user_lock(uid):
                await cancel_trade(self.trade_id, uid, None)
        except TradeError as e:
            await interaction.followup.send(embed=error_embed(str(e)), ephemeral=True)
            return
        except Exception as e:
            await interaction.followup.send(embed=error_embed(f"Cancel failed: {e}"), ephemeral=True)
            return

        for child in self.children:
            child.disabled = True
        new_embed = discord.Embed(
            title="❌ Trade Cancelled",
            description=f"Trade cancelled by {interaction.user.mention}.",
            color=0x888888,
        )
        await interaction.message.edit(embed=new_embed, view=self)
        await interaction.followup.send(embed=success_embed("Trade cancelled."), ephemeral=True)


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
        # Defer ephemerally for validation
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        target_id = str(target.id)

        if uid == target_id:
            await interaction.followup.send(embed=error_embed("Cannot trade with yourself."), ephemeral=True)
            return

        my_champ_nums   = _parse_numbers(my_champions)
        their_champ_nums = _parse_numbers(their_champions)
        my_item_nums    = _parse_numbers(my_items)
        their_item_nums = _parse_numbers(their_items)

        for val, label in [
            (my_champ_nums, "my_champions"), (their_champ_nums, "their_champions"),
            (my_item_nums,  "my_items"),     (their_item_nums,  "their_items"),
        ]:
            if val is None:
                await interaction.followup.send(
                    embed=error_embed(f"Invalid format for {label}. Use comma-separated numbers e.g. `1,2`."),
                    ephemeral=True,
                )
                return

        my_champ_ids, err = await _resolve_champion_numbers(uid, my_champ_nums)
        if err:
            await interaction.followup.send(embed=error_embed(err), ephemeral=True)
            return
        my_item_ids, err = await _resolve_item_numbers(uid, my_item_nums)
        if err:
            await interaction.followup.send(embed=error_embed(err), ephemeral=True)
            return
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

        # Build friendly name previews
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

        my_champ_names   = await _champ_names(my_champ_ids)
        their_champ_names = await _champ_names(their_champ_ids)
        my_item_names    = await _item_names(my_item_ids)
        their_item_names = await _item_names(their_item_ids)

        offer_text = _detail(my_gold, my_champ_names, my_item_names)
        want_text  = _detail(their_gold, their_champ_names, their_item_names)

        # Create the trade in DB
        try:
            async with get_user_lock(uid):
                trade = await create_trade(
                    uid, target_id,
                    my_champ_ids, my_item_ids, my_gold,
                    their_champ_ids, their_item_ids, their_gold,
                    None,
                )
        except TradeError as e:
            await interaction.followup.send(embed=error_embed(str(e)), ephemeral=True)
            return
        except Exception as e:
            await interaction.followup.send(embed=error_embed(f"Trade creation failed: {e}"), ephemeral=True)
            return

        # Post the public offer embed with Accept/Decline buttons
        view = TradeOfferView(str(trade.id), interaction.user.id, target.id)
        embed = _trade_embed(
            str(trade.id),
            interaction.user.mention, target.mention,
            offer_text, want_text,
        )
        # Use channel.send directly — most reliable way to post a public message
        # from a command that deferred ephemerally
        try:
            await interaction.channel.send(content=target.mention, embed=embed, view=view)
            await interaction.followup.send(embed=success_embed("Trade offer posted!"), ephemeral=True)
        except Exception:
            # Fallback: if channel.send fails, tell the user the trade ID
            await interaction.followup.send(
                embed=success_embed(
                    f"Trade created! Trade ID: `{trade.id}`\n"
                    f"Tell {target.mention} to run `/trade-accept {trade.id}`"
                ),
                ephemeral=True,
            )

    @app_commands.command(name="trade-accept", description="Accept a trade offer by ID (fallback).")
    @app_commands.describe(trade_id="Trade ID from /trade-list")
    async def trade_accept(self, interaction: discord.Interaction, trade_id: str):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)

        try:
            trade_doc = await TradeOffer.get(PydanticObjectId(trade_id))
        except Exception:
            trade_doc = None
        if trade_doc is None or trade_doc.target_id != uid or trade_doc.status != "pending":
            await interaction.followup.send(
                embed=error_embed("Trade not found or not addressed to you. Use /trade-list to check."),
                ephemeral=True,
            )
            return

        try:
            async with get_user_lock(uid):
                await accept_trade(trade_id, uid, None)
        except TradeError as e:
            await interaction.followup.send(embed=error_embed(str(e)), ephemeral=True)
            return
        except Exception as e:
            await interaction.followup.send(embed=error_embed(f"Trade failed: {e}"), ephemeral=True)
            return

        await interaction.followup.send(embed=success_embed("✅ Trade completed!"), ephemeral=True)

    @app_commands.command(name="trade-cancel", description="Cancel a trade offer.")
    @app_commands.describe(trade_id="Trade ID from /trade-list")
    async def trade_cancel(self, interaction: discord.Interaction, trade_id: str):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)

        try:
            async with get_user_lock(uid):
                await cancel_trade(trade_id, uid, None)
        except TradeError as e:
            await interaction.followup.send(embed=error_embed(str(e)), ephemeral=True)
            return
        except Exception as e:
            await interaction.followup.send(embed=error_embed(f"Cancel failed: {e}"), ephemeral=True)
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
                role, other = "incoming ← action needed", t.initiator_id
                you_give = _summ(t.target_gold,    t.target_champion_ids,    t.target_item_ids)
                you_get  = _summ(t.initiator_gold, t.initiator_champion_ids, t.initiator_item_ids)
            embed.add_field(
                name=f"[{role}] with <@{other}>",
                value=f"You give: {you_give}\nYou get: {you_get}\nID: `{t.id}`",
                inline=False,
            )
        embed.set_footer(text="/trade-accept <id> · /trade-cancel <id>")
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(TradeCog(bot))
