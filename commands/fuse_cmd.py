"""Unified /fuse command — bulk-fuse all eligible champions, items, or runes."""
import discord
from discord import app_commands
from discord.ext import commands
from collections import defaultdict

from models.user import User
from models.champion import ChampionInstance
from models.item import ItemInstance
from models.rune_instance import RuneInstance
from models.rune_page import RuneSlot
from utils.embeds import error_embed, ConfirmView, COLOR_WARNING, COLOR_SUCCESS, COLOR_INFO
from utils.locks import get_user_lock
from utils.db_session import get_motor_client
from services.champion_service import fuse_champions, FusionError
from services.item_service import fuse_items, ItemFusionError
from services.rune_service import grant_rune
from data.rune_catalog import RUNE_CATALOG
from config.game_config import RANKS, CHAMPION_FUSION_COST, ITEM_FUSION_COST


async def _auto_fuse_all_champions(uid: str, session) -> dict:
    """Fuse all eligible champion groups across every fusible rank. Returns result summary."""
    results: dict[str, int] = defaultdict(int)  # next_rank -> count created
    for rank in RANKS[:-1]:  # F through A
        next_rank = RANKS[RANKS.index(rank) + 1]
        while True:
            candidates = await ChampionInstance.find(
                ChampionInstance.owner_id == uid,
                ChampionInstance.rank == rank,
            ).to_list()
            by_name: dict[str, list] = defaultdict(list)
            for c in candidates:
                if c.is_available and not getattr(c, "favorite", False):
                    by_name[c.name].append(c)
            did_any = False
            for name, pool in by_name.items():
                pool.sort(key=lambda c: c.level)
                while len(pool) >= 3:
                    trio = pool[:3]
                    pool = pool[3:]
                    try:
                        await fuse_champions(uid, [str(c.id) for c in trio], session)
                        results[f"{name} [{next_rank}]"] += 1
                        did_any = True
                    except FusionError:
                        break
            if not did_any:
                break
    return dict(results)


async def _auto_fuse_all_runes(uid: str, session) -> dict:
    """Fuse 3 same rune_id + same rank → 1 of the next rank. Returns result summary."""
    rank_order = RANKS  # F E D C B A S
    results: dict[str, int] = defaultdict(int)
    for rank in rank_order[:-1]:
        next_rank = rank_order[rank_order.index(rank) + 1]
        while True:
            instances = await RuneInstance.find(
                RuneInstance.owner_id == uid,
                RuneInstance.rank == rank,
                RuneInstance.is_equipped == False,
            ).to_list()
            by_rune: dict[str, list] = defaultdict(list)
            for inst in instances:
                by_rune[inst.rune_id].append(inst)
            did_any = False
            for rune_id, pool in by_rune.items():
                while len(pool) >= 3:
                    trio = pool[:3]
                    pool = pool[3:]
                    for consumed in trio:
                        await consumed.delete(session=session)
                    new_inst = await grant_rune(uid, rune_id, next_rank, session)
                    rune = RUNE_CATALOG.get(rune_id, {})
                    label = f"{rune.get('name', rune_id)} [{next_rank}]"
                    results[label] += 1
                    did_any = True
            if not did_any:
                break
    return dict(results)


async def _auto_fuse_all_items(uid: str, session) -> dict:
    """Fuse all eligible item groups across every fusible rank. Returns result summary."""
    results: dict[str, int] = defaultdict(int)
    for rank in RANKS[:-1]:
        next_rank = RANKS[RANKS.index(rank) + 1]
        while True:
            candidates = await ItemInstance.find(
                ItemInstance.owner_id == uid,
                ItemInstance.rank == rank,
            ).to_list()
            by_name: dict[str, list] = defaultdict(list)
            for i in candidates:
                if i.is_fusible and not getattr(i, "favorite", False):
                    by_name[i.name].append(i)
            did_any = False
            for name, pool in by_name.items():
                while len(pool) >= 3:
                    trio = pool[:3]
                    pool = pool[3:]
                    try:
                        await fuse_items(uid, [str(i.id) for i in trio], session)
                        results[f"{name} [{next_rank}]"] += 1
                        did_any = True
                    except ItemFusionError:
                        break
            if not did_any:
                break
    return dict(results)


class FuseCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="fuse", description="Bulk-fuse all eligible champions or items across every rank.")
    @app_commands.describe(type="What to fuse")
    @app_commands.choices(type=[
        app_commands.Choice(name="Champions", value="champions"),
        app_commands.Choice(name="Items", value="items"),
        app_commands.Choice(name="Runes", value="runes"),
    ])
    async def fuse(self, interaction: discord.Interaction, type: str):
        await interaction.response.defer()
        uid = str(interaction.user.id)
        await User.get_or_create(uid, interaction.user.display_name)

        if type == "champions":
            # Preview: count fusible groups
            all_champs = await ChampionInstance.find(ChampionInstance.owner_id == uid).to_list()
            fusible: dict[tuple, int] = defaultdict(int)
            for c in all_champs:
                if c.rank != "S" and c.is_available and not getattr(c, "favorite", False):
                    fusible[(c.name, c.rank)] += 1
            groups = [(n, r, cnt) for (n, r), cnt in fusible.items() if cnt >= 3]
            if not groups:
                await interaction.followup.send(
                    embed=error_embed("No fusible champions found.", "Need 3+ copies of the same champion and rank (non-favorite, unlocked)."),
                )
                return
            total_fusions = sum(cnt // 3 for _, _, cnt in groups)
            preview_lines = []
            for name, rank, cnt in sorted(groups, key=lambda x: (RANKS.index(x[1]), x[0])):
                next_rank = RANKS[RANKS.index(rank) + 1]
                n = cnt // 3
                preview_lines.append(f"• {name} [{rank}] ×{cnt // 3 * 3} → **{n}x [{next_rank}]**")
            embed = discord.Embed(
                title="🔮 Bulk Fuse — Champions",
                description=(
                    "\n".join(preview_lines[:20]) +
                    (f"\n…and {len(preview_lines) - 20} more groups" if len(preview_lines) > 20 else "") +
                    f"\n\n**{total_fusions} fusion(s)** will run across all ranks.\n"
                    "⚠️ Lowest-level copies consumed. Favorites and locked champions are skipped."
                ),
                color=COLOR_WARNING,
            )
            view = ConfirmView()
            await interaction.followup.send(embed=embed, view=view)
            await view.wait()
            if not view.confirmed:
                await interaction.followup.send(embed=discord.Embed(title="Fusion cancelled.", color=COLOR_INFO))
                return

            async with get_user_lock(uid):
                client = get_motor_client()
                async with await client.start_session() as session:
                    async with session.start_transaction():
                        results = await _auto_fuse_all_champions(uid, session)

            if not results:
                await interaction.followup.send(embed=error_embed("No fusions completed."))
                return

            lines = [f"✨ **{label}** ×{cnt}" for label, cnt in sorted(results.items())]
            total = sum(results.values())
            result_embed = discord.Embed(
                title="🔮 Fusion Complete — Champions",
                description="\n".join(lines[:25]) + f"\n\n**{total} champion(s) created.**",
                color=COLOR_SUCCESS,
            )
            await interaction.followup.send(embed=result_embed)

        elif type == "items":
            all_items = await ItemInstance.find(ItemInstance.owner_id == uid).to_list()
            fusible: dict[tuple, int] = defaultdict(int)
            for i in all_items:
                if i.rank != "S" and i.is_fusible and not getattr(i, "favorite", False):
                    fusible[(i.name, i.rank)] += 1
            groups = [(n, r, cnt) for (n, r), cnt in fusible.items() if cnt >= 3]
            if not groups:
                await interaction.followup.send(
                    embed=error_embed("No fusible items found.", "Need 3+ copies of the same +0 item and rank (non-favorite, unlocked)."),
                )
                return
            total_fusions = sum(cnt // 3 for _, _, cnt in groups)
            preview_lines = []
            for name, rank, cnt in sorted(groups, key=lambda x: (RANKS.index(x[1]), x[0])):
                next_rank = RANKS[RANKS.index(rank) + 1]
                n = cnt // 3
                preview_lines.append(f"• {name} [{rank}] ×{cnt // 3 * 3} → **{n}x [{next_rank}]**")
            embed = discord.Embed(
                title="🔨 Bulk Fuse — Items",
                description=(
                    "\n".join(preview_lines[:20]) +
                    (f"\n…and {len(preview_lines) - 20} more groups" if len(preview_lines) > 20 else "") +
                    f"\n\n**{total_fusions} fusion(s)** will run.\n"
                    "⚠️ Items must be +0. Favorites and locked items are skipped."
                ),
                color=COLOR_WARNING,
            )
            view = ConfirmView()
            await interaction.followup.send(embed=embed, view=view)
            await view.wait()
            if not view.confirmed:
                await interaction.followup.send(embed=discord.Embed(title="Fusion cancelled.", color=COLOR_INFO))
                return

            async with get_user_lock(uid):
                client = get_motor_client()
                async with await client.start_session() as session:
                    async with session.start_transaction():
                        results = await _auto_fuse_all_items(uid, session)

            if not results:
                await interaction.followup.send(embed=error_embed("No fusions completed."))
                return

            lines = [f"✨ **{label}** ×{cnt}" for label, cnt in sorted(results.items())]
            total = sum(results.values())
            result_embed = discord.Embed(
                title="🔨 Fusion Complete — Items",
                description="\n".join(lines[:25]) + f"\n\n**{total} item(s) created.**",
                color=COLOR_SUCCESS,
            )
            await interaction.followup.send(embed=result_embed)

        elif type == "runes":
            all_runes = await RuneInstance.find(
                RuneInstance.owner_id == uid,
                RuneInstance.is_equipped == False,
            ).to_list()
            # Count fusible groups (3+ same rune_id + rank, non-S)
            fusible: dict[tuple, int] = defaultdict(int)
            for inst in all_runes:
                if inst.rank != "S":
                    fusible[(inst.rune_id, inst.rank)] += 1
            groups = [(rid, r, cnt) for (rid, r), cnt in fusible.items() if cnt >= 3]
            if not groups:
                await interaction.followup.send(
                    embed=error_embed("No fusible runes found.", "Need 3+ copies of the same rune at the same rank (unequipped, non-S)."),
                )
                return
            total_fusions = sum(cnt // 3 for _, _, cnt in groups)
            preview_lines = []
            for rune_id, rank, cnt in sorted(groups, key=lambda x: (RANKS.index(x[1]), x[0])):
                next_rank = RANKS[RANKS.index(rank) + 1]
                n = cnt // 3
                rune_name = RUNE_CATALOG.get(rune_id, {}).get("name", rune_id)
                preview_lines.append(f"• {rune_name} [{rank}] ×{cnt // 3 * 3} → **{n}x [{next_rank}]**")
            embed = discord.Embed(
                title="🧿 Bulk Fuse — Runes",
                description=(
                    "\n".join(preview_lines[:20]) +
                    (f"\n…and {len(preview_lines) - 20} more groups" if len(preview_lines) > 20 else "") +
                    f"\n\n**{total_fusions} fusion(s)** will run.\n"
                    "⚠️ 3 same rune + rank → 1 of the next rank. Equipped runes are skipped."
                ),
                color=COLOR_WARNING,
            )
            view = ConfirmView()
            await interaction.followup.send(embed=embed, view=view)
            await view.wait()
            if not view.confirmed:
                await interaction.followup.send(embed=discord.Embed(title="Fusion cancelled.", color=COLOR_INFO))
                return

            async with get_user_lock(uid):
                client = get_motor_client()
                async with await client.start_session() as session:
                    async with session.start_transaction():
                        results = await _auto_fuse_all_runes(uid, session)

            if not results:
                await interaction.followup.send(embed=error_embed("No fusions completed."))
                return

            lines = [f"✨ **{label}** ×{cnt}" for label, cnt in sorted(results.items())]
            total = sum(results.values())
            result_embed = discord.Embed(
                title="🧿 Fusion Complete — Runes",
                description="\n".join(lines[:25]) + f"\n\n**{total} rune(s) created.**",
                color=COLOR_SUCCESS,
            )
            await interaction.followup.send(embed=result_embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(FuseCog(bot))
