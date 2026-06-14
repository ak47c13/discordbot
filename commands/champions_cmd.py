import discord
from discord import app_commands
from discord.ext import commands

from models.user import User
from models.champion import ChampionInstance
from utils.embeds import champion_embed, error_embed, success_embed, ConfirmView
from utils.locks import get_user_lock
from utils.db_session import get_motor_client
from services.champion_service import (
    fuse_champions, bulk_fuse_champions, level_up_champion, FusionError,
)
from services.bulk_service import bulk_sell_champions, BulkSellError
from config.game_config import CHAMPION_FUSION_COST, RANKS, SELL_PRICE_CHAMPION


class ChampionsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="champions", description="View your champion inventory.")
    @app_commands.describe(rank="Filter by rank (F/E/D/C/B/A/S)", name="Filter by champion name")
    async def champions(self, interaction: discord.Interaction, rank: str = "", name: str = ""):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        await User.get_or_create(uid, interaction.user.display_name)

        query = ChampionInstance.find(ChampionInstance.owner_id == uid)
        if rank:
            query = ChampionInstance.find(ChampionInstance.owner_id == uid, ChampionInstance.rank == rank.upper())
        champs = await query.to_list()

        if name:
            champs = [c for c in champs if name.lower() in c.name.lower()]

        if not champs:
            await interaction.followup.send(embed=error_embed("No champions found."), ephemeral=True)
            return

        # Paginate: show first 10
        embed = discord.Embed(title=f"🏆 Your Champions ({len(champs)} total)", color=0x5865F2)
        for c in champs[:10]:
            status = []
            if c.equipped_in_team: status.append("⚔️")
            if c.locked:           status.append("🔒")
            if c.in_market:        status.append("🏪")
            if c.in_trade:         status.append("🤝")
            embed.add_field(
                name=f"{' '.join(status)} {c.name} [{c.rank}] Lv.{c.level}",
                value=f"ID: `{c.id}`",
                inline=False,
            )
        if len(champs) > 10:
            embed.set_footer(text=f"Showing 10 of {len(champs)}. Use /champions with filters.")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="champion-info", description="View details of a specific champion.")
    @app_commands.describe(champion_id="Champion ID")
    async def champion_info(self, interaction: discord.Interaction, champion_id: str):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        c = await ChampionInstance.get(champion_id)
        if c is None or c.owner_id != uid:
            await interaction.followup.send(embed=error_embed("Champion not found."), ephemeral=True)
            return
        await interaction.followup.send(embed=champion_embed(c, "Champion Details"), ephemeral=True)

    @app_commands.command(name="fuse-champions", description="Fuse 3 identical same-rank champions into 1 of next rank.")
    @app_commands.describe(id1="Champion 1 ID", id2="Champion 2 ID", id3="Champion 3 ID")
    async def fuse_champs(self, interaction: discord.Interaction, id1: str, id2: str, id3: str):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)

        # Preview before confirm
        ids = [id1, id2, id3]
        if len(set(ids)) != 3:
            await interaction.followup.send(embed=error_embed("Cannot use the same champion twice."), ephemeral=True)
            return

        champs = []
        for cid in ids:
            c = await ChampionInstance.get(cid)
            if c is None or c.owner_id != uid:
                await interaction.followup.send(embed=error_embed(f"Champion {cid} not found."), ephemeral=True)
                return
            champs.append(c)

        if len({c.name for c in champs}) != 1 or len({c.rank for c in champs}) != 1:
            await interaction.followup.send(
                embed=error_embed("All 3 champions must have the same name and rank."),
                ephemeral=True,
            )
            return

        current_rank = champs[0].rank
        if current_rank == "S":
            await interaction.followup.send(embed=error_embed("S-rank champions cannot be fused."), ephemeral=True)
            return

        next_rank = RANKS[RANKS.index(current_rank) + 1]
        cost = CHAMPION_FUSION_COST[next_rank]

        embed = discord.Embed(
            title="🔮 Confirm Fusion",
            description=(
                f"Fuse **3x {champs[0].name} [{current_rank}]** → **{champs[0].name} [{next_rank}]**\n"
                f"Cost: **{cost} gold**\n"
                f"⚠️ The 3 source champions will be **permanently consumed**.\n"
                f"⚠️ Result starts at **Level 1**."
            ),
            color=0xFF8800,
        )

        view = ConfirmView()
        msg = await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        await view.wait()

        if not view.confirmed:
            await interaction.followup.send(embed=discord.Embed(title="Fusion cancelled.", color=0x888888), ephemeral=True)
            return

        async with get_user_lock(uid):
            client = get_motor_client()
            async with await client.start_session() as session:
                async with session.start_transaction():
                    try:
                        result = await fuse_champions(uid, ids, session)
                    except FusionError as e:
                        await interaction.followup.send(embed=error_embed(str(e)), ephemeral=True)
                        return

        await interaction.followup.send(
            embed=success_embed(
                f"✨ **{result.name} [{result.rank}]** created! Starts at Level 1."
            ),
            ephemeral=True,
        )

    @app_commands.command(name="champions-bulk-fuse", description="Fuse many identical champions at once (count must be a multiple of 3).")
    @app_commands.describe(name="Champion name", rank="Source rank", count="How many to consume (multiple of 3)")
    async def bulk_fuse_champs(self, interaction: discord.Interaction, name: str, rank: str, count: int):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        rank = rank.upper()
        if count <= 0 or count % 3 != 0:
            await interaction.followup.send(embed=error_embed("Count must be a positive multiple of 3."), ephemeral=True)
            return
        if rank == "S":
            await interaction.followup.send(embed=error_embed("S-rank champions cannot be fused."), ephemeral=True)
            return
        next_rank = RANKS[RANKS.index(rank) + 1]
        produced = count // 3

        embed = discord.Embed(
            title="🔮 Confirm Bulk Fusion",
            description=(
                f"Fuse **{count}x {name} [{rank}]** → **{produced}x {name} [{next_rank}]**?\n"
                f"⚠️ Source champions will be permanently consumed."
            ),
            color=0xFF8800,
        )
        view = ConfirmView()
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        await view.wait()
        if not view.confirmed:
            await interaction.followup.send(embed=discord.Embed(title="Bulk fusion cancelled.", color=0x888888), ephemeral=True)
            return

        async with get_user_lock(uid):
            client = get_motor_client()
            async with await client.start_session() as session:
                async with session.start_transaction():
                    try:
                        created = await bulk_fuse_champions(uid, name, rank, count, session)
                    except FusionError as e:
                        await interaction.followup.send(embed=error_embed(str(e)), ephemeral=True)
                        return

        await interaction.followup.send(
            embed=success_embed(f"✨ Created {len(created)}x {name} [{next_rank}]!"),
            ephemeral=True,
        )

    @app_commands.command(name="champions-bulk-sell", description="Sell all unlocked, non-favorite, non-equipped champions of a rank.")
    @app_commands.describe(rank="Rank to sell", name="Optional champion name filter")
    async def bulk_sell_champs(self, interaction: discord.Interaction, rank: str, name: str = ""):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        rank = rank.upper()
        filters = {"rank": rank, "name": name or None}

        # Preview: count matching
        champs = await ChampionInstance.find(ChampionInstance.owner_id == uid, ChampionInstance.rank == rank).to_list()
        matches = [
            c for c in champs
            if (not name or c.name == name)
            and not c.locked and not getattr(c, "favorite", False)
            and not c.in_trade and not c.in_market and c.equipped_in_team is None
        ]
        if not matches:
            await interaction.followup.send(embed=error_embed("No sellable champions match."), ephemeral=True)
            return
        gold = len(matches) * SELL_PRICE_CHAMPION.get(rank, 0)

        embed = discord.Embed(
            title="💰 Confirm Bulk Sell",
            description=f"Sell **{len(matches)}** champion(s) for **{gold} gold**?",
            color=0xFF8800,
        )
        view = ConfirmView()
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        await view.wait()
        if not view.confirmed:
            await interaction.followup.send(embed=discord.Embed(title="Sell cancelled.", color=0x888888), ephemeral=True)
            return

        async with get_user_lock(uid):
            client = get_motor_client()
            async with await client.start_session() as session:
                async with session.start_transaction():
                    try:
                        res = await bulk_sell_champions(uid, filters, session)
                    except BulkSellError as e:
                        await interaction.followup.send(embed=error_embed(str(e)), ephemeral=True)
                        return

        await interaction.followup.send(
            embed=success_embed(f"Sold {res['sold']} champion(s) for {res['gold']} gold."),
            ephemeral=True,
        )

    @app_commands.command(name="champion-favorite", description="Toggle the favorite flag on a champion.")
    @app_commands.describe(champion_id="Champion ID")
    async def favorite_champ(self, interaction: discord.Interaction, champion_id: str):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        c = await ChampionInstance.get(champion_id)
        if c is None or c.owner_id != uid:
            await interaction.followup.send(embed=error_embed("Champion not found."), ephemeral=True)
            return
        c.favorite = not getattr(c, "favorite", False)
        await c.save()
        state = "⭐ favorited" if c.favorite else "unfavorited"
        await interaction.followup.send(embed=success_embed(f"{c.name} [{c.rank}] is now {state}."), ephemeral=True)

    @app_commands.command(name="levelup", description="Level up a champion (costs gold).")
    @app_commands.describe(champion_id="Champion ID")
    async def levelup(self, interaction: discord.Interaction, champion_id: str):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        from config.game_config import LEVEL_UP_GOLD_COST

        async with get_user_lock(uid):
            client = get_motor_client()
            async with await client.start_session() as session:
                async with session.start_transaction():
                    try:
                        c = await level_up_champion(uid, champion_id, session)
                    except ValueError as e:
                        await interaction.followup.send(embed=error_embed(str(e)), ephemeral=True)
                        return

        await interaction.followup.send(
            embed=success_embed(f"{c.name} [{c.rank}] is now Level {c.level}! (-{LEVEL_UP_GOLD_COST} gold)"),
            ephemeral=True,
        )

    @app_commands.command(name="lock-champion", description="Lock or unlock a champion to protect it.")
    @app_commands.describe(champion_id="Champion ID")
    async def lock_champion(self, interaction: discord.Interaction, champion_id: str):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        c = await ChampionInstance.get(champion_id)
        if c is None or c.owner_id != uid:
            await interaction.followup.send(embed=error_embed("Champion not found."), ephemeral=True)
            return
        c.locked = not c.locked
        await c.save()
        state = "🔒 locked" if c.locked else "🔓 unlocked"
        await interaction.followup.send(
            embed=success_embed(f"{c.name} [{c.rank}] is now {state}."),
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(ChampionsCog(bot))
