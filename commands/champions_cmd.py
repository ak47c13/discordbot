import discord
from discord import app_commands
from discord.ext import commands

from models.user import User
from models.champion import ChampionInstance
from utils.embeds import (
    champion_embed, error_embed, success_embed, ConfirmView,
    PaginatedChampionView, get_champion_by_number,
    COLOR_WARNING, COLOR_INFO, COLOR_SUCCESS,
)
from utils.locks import get_user_lock
from utils.db_session import get_motor_client
from services.champion_service import (
    fuse_champions, bulk_fuse_champions, level_up_champion, FusionError,
)
from services.bulk_service import bulk_sell_champions, BulkSellError
from config.game_config import CHAMPION_FUSION_COST, RANKS, SELL_PRICE_CHAMPION, CHAMPION_MAX_LEVEL, levelup_cost, levelup_cost_range
from utils.image_gen import DDRAGON_LOADING, _riot_id_from_name


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

        view = PaginatedChampionView(champs, interaction.user.id)
        await interaction.followup.send(embed=view.current_embed(), view=view, ephemeral=True)

    @app_commands.command(name="champion-info", description="View details of a specific champion.")
    @app_commands.describe(number="Champion list number (see /champions)")
    async def champion_info(self, interaction: discord.Interaction, number: int):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        c = await get_champion_by_number(uid, number)
        if c is None or c.owner_id != uid:
            await interaction.followup.send(embed=error_embed("Champion not found."), ephemeral=True)
            return
        embed = champion_embed(c, "Champion Details")
        riot_id = c.riot_id or _riot_id_from_name(c.name)
        embed.set_image(url=DDRAGON_LOADING.format(riot_id=riot_id))
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="fuse-champions", description="Fuse 3 identical same-rank champions into 1 of next rank.")
    @app_commands.describe(name="Champion name", rank="Champion rank (F/E/D/C/B/A)")
    async def fuse_champs(self, interaction: discord.Interaction, name: str, rank: str):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        rank = rank.upper()

        if rank == "S":
            await interaction.followup.send(embed=error_embed("S-rank champions cannot be fused."), ephemeral=True)
            return
        if rank not in RANKS:
            await interaction.followup.send(
                embed=error_embed("Invalid rank.", "Use one of F/E/D/C/B/A."), ephemeral=True
            )
            return

        # Auto-select the 3 lowest-level matching unlocked, non-favorite, available champions.
        candidates = await ChampionInstance.find(
            ChampionInstance.owner_id == uid,
            ChampionInstance.name == name,
            ChampionInstance.rank == rank,
        ).to_list()
        usable = [c for c in candidates if c.is_available and not getattr(c, "favorite", False)]
        usable.sort(key=lambda c: c.level)
        if len(usable) < 3:
            await interaction.followup.send(
                embed=error_embed(
                    f"Not enough fusible {name} [{rank}] champions. Have {len(usable)}, need 3.",
                    "Champions must be unlocked, non-favorite, and not equipped/traded/listed.",
                ),
                ephemeral=True,
            )
            return

        champs = usable[:3]
        ids = [str(c.id) for c in champs]

        current_rank = rank
        next_rank = RANKS[RANKS.index(current_rank) + 1]
        cost = CHAMPION_FUSION_COST[next_rank]

        preview_lines = "\n".join(f"• {c.name} [{c.rank}] Lv.{c.level}" for c in champs)
        embed = discord.Embed(
            title="🔮 Confirm Fusion",
            description=(
                f"These 3 (lowest level) will be used:\n{preview_lines}\n\n"
                f"Fuse **3x {champs[0].name} [{current_rank}]** → **{champs[0].name} [{next_rank}]**\n"
                f"Cost: **{cost} gold**\n"
                f"⚠️ The 3 source champions will be **permanently consumed**.\n"
                f"⚠️ Result starts at **Level 1**."
            ),
            color=COLOR_WARNING,
        )

        view = ConfirmView()
        msg = await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        await view.wait()

        if not view.confirmed:
            await interaction.followup.send(embed=discord.Embed(title="Fusion cancelled.", color=COLOR_INFO), ephemeral=True)
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
            and not c.in_trade and not c.in_market and not getattr(c, "is_active", False)
        ]
        if not matches:
            await interaction.followup.send(embed=error_embed("No sellable champions match."), ephemeral=True)
            return
        gold = len(matches) * SELL_PRICE_CHAMPION.get(rank, 0)

        embed = discord.Embed(
            title="💰 Confirm Bulk Sell",
            description=f"Sell **{len(matches)}** champion(s) for **{gold} gold**?",
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
                        res = await bulk_sell_champions(uid, filters, session)
                    except BulkSellError as e:
                        await interaction.followup.send(embed=error_embed(str(e)), ephemeral=True)
                        return

        await interaction.followup.send(
            embed=success_embed(f"Sold {res['sold']} champion(s) for {res['gold']} gold."),
            ephemeral=True,
        )

    @app_commands.command(name="champion-favorite", description="Toggle the favorite flag on a champion.")
    @app_commands.describe(number="Champion list number (see /champions)")
    async def favorite_champ(self, interaction: discord.Interaction, number: int):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        c = await get_champion_by_number(uid, number)
        if c is None or c.owner_id != uid:
            await interaction.followup.send(embed=error_embed("Champion not found."), ephemeral=True)
            return
        c.favorite = not getattr(c, "favorite", False)
        await c.save()
        state = "⭐ favorited" if c.favorite else "unfavorited"
        await interaction.followup.send(embed=success_embed(f"{c.name} [{c.rank}] is now {state}."), ephemeral=True)

    @app_commands.command(name="levelup", description="Level up a champion (costs gold).")
    @app_commands.describe(number="Champion display ID (see /champions)", times="Number of levels, or 'max' to spend all gold")
    async def levelup(self, interaction: discord.Interaction, number: int, times: str = "1"):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)

        # Parse times: integer or "max"
        times_lower = times.strip().lower()
        if times_lower == "max":
            requested = 9999
        else:
            try:
                requested = int(times_lower)
                if requested < 1:
                    raise ValueError
            except ValueError:
                await interaction.followup.send(
                    embed=error_embed("Enter a number of levels or 'max'."),
                    ephemeral=True,
                )
                return

        champ = await get_champion_by_number(uid, number)
        if champ is None or champ.owner_id != uid:
            await interaction.followup.send(
                embed=error_embed("Champion not found.", "Use `/champions` to see IDs."),
                ephemeral=True,
            )
            return

        max_lvl = CHAMPION_MAX_LEVEL.get(champ.rank, 20)
        if champ.level >= max_lvl:
            await interaction.followup.send(
                embed=error_embed(f"{champ.name} is already at max level {max_lvl} for rank {champ.rank}."),
                ephemeral=True,
            )
            return

        user = await User.get_or_create(uid, interaction.user.display_name)

        # Compute affordable levels (walk one by one to handle gold limit correctly)
        affordable = 0
        preview_cost = 0
        cap = min(requested, max_lvl - champ.level)
        for i in range(cap):
            c = levelup_cost(champ.rank, champ.level + i)
            if user.gold - preview_cost < c:
                break
            preview_cost += c
            affordable += 1

        if affordable == 0:
            cost_next = levelup_cost(champ.rank, champ.level)
            await interaction.followup.send(
                embed=error_embed(f"Need {cost_next:,} gold for the next level. You have {user.gold:,}."),
                ephemeral=True,
            )
            return

        actual = affordable
        total_cost = preview_cost
        target_lvl = champ.level + actual

        cap_note = " (rank cap)" if target_lvl >= max_lvl else ""
        gold_note = " (gold limit)" if requested > actual and target_lvl < max_lvl else ""
        embed = discord.Embed(
            title="Confirm Level Up",
            description=(
                f"Level up **{champ.name} [{champ.rank}]** "
                f"Lv.{champ.level} → Lv.{target_lvl}{cap_note}{gold_note}?\n"
                f"Cost: **{total_cost:,} gold** (you have {user.gold:,})"
            ),
            color=COLOR_WARNING,
        )
        view = ConfirmView()
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        await view.wait()
        if not view.confirmed:
            await interaction.followup.send(embed=discord.Embed(title="Level up cancelled.", color=COLOR_INFO), ephemeral=True)
            return

        champion_id = str(champ.id)
        async with get_user_lock(uid):
            client = get_motor_client()
            async with await client.start_session() as session:
                async with session.start_transaction():
                    try:
                        c, spent = await level_up_champion(uid, champion_id, session, times=actual)
                    except ValueError as e:
                        await interaction.followup.send(embed=error_embed(str(e)), ephemeral=True)
                        return

        at_cap = " (rank cap reached!)" if c.level >= max_lvl else ""
        await interaction.followup.send(
            embed=success_embed(f"{c.name} [{c.rank}] is now Level {c.level}{at_cap}! (-{spent:,} gold)"),
            ephemeral=True,
        )

    @app_commands.command(name="champions-duplicates", description="Find champions you have multiple copies of.")
    @app_commands.describe(rank="Optional rank filter (F/E/D/C/B/A/S)")
    async def champions_duplicates(self, interaction: discord.Interaction, rank: str = ""):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        await User.get_or_create(uid, interaction.user.display_name)

        champs = await ChampionInstance.find(ChampionInstance.owner_id == uid).to_list()
        if rank:
            champs = [c for c in champs if c.rank == rank.upper()]

        groups: dict[tuple, int] = {}
        for c in champs:
            groups[(c.name, c.rank)] = groups.get((c.name, c.rank), 0) + 1

        fusion_ready = sorted(
            [(n, r, cnt) for (n, r), cnt in groups.items() if cnt >= 3],
            key=lambda x: -x[2],
        )
        collecting = sorted(
            [(n, r, cnt) for (n, r), cnt in groups.items() if cnt == 2],
            key=lambda x: -x[2],
        )

        if not fusion_ready and not collecting:
            await interaction.followup.send(
                embed=error_embed("No duplicate champions found (need 2+ copies)."),
                ephemeral=True,
            )
            return

        embed = discord.Embed(title="🔁 Duplicate Champions", color=COLOR_SUCCESS if fusion_ready else COLOR_INFO)
        if fusion_ready:
            lines = [f"• **{n}** [{r}] ×{cnt}  ✅ fusion-ready" for n, r, cnt in fusion_ready]
            embed.add_field(name="Fusion-ready (3+ copies)", value="\n".join(lines)[:1024], inline=False)
        if collecting:
            lines = [f"• {n} [{r}] ×{cnt}" for n, r, cnt in collecting]
            embed.add_field(name="Collecting (2 copies)", value="\n".join(lines)[:1024], inline=False)
        embed.set_footer(text="Champions with 3+ copies can be fused with /fuse-champions")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="lock-champion", description="Lock or unlock a champion to protect it.")
    @app_commands.describe(number="Champion list number (see /champions)")
    async def lock_champion(self, interaction: discord.Interaction, number: int):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        c = await get_champion_by_number(uid, number)
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
