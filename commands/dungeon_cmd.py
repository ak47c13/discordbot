"""
Dungeon commands — floor-by-floor progression through LoL-region dungeons.
"""
from __future__ import annotations
import random

import discord
from discord import app_commands
from discord.ext import commands

from models.user import User
from models.team import Team
from models.dungeon import Dungeon, DungeonProgress
from utils.embeds import error_embed, success_embed, info_embed, ConfirmView
from utils.locks import get_user_lock
from utils.idempotency import is_already_processed, mark_processed
from services import dungeon_service
from services.dungeon_service import DungeonError
from config.game_config import DUNGEON_STAMINA_COST


PASSIVE_DESCRIPTIONS = {
    "garen_passive": "Garen regenerates 5% max HP each round.",
    "darius_passive": "Darius gains +8% ATK each round (Hemorrhage).",
    "irelia_passive": "Heals 20% max HP whenever one of her allies dies.",
    "sejuani_passive": "At round 3, freezes your highest-ATK unit for 1 round.",
    "jarvan_passive": "Starts with a shield worth 25% max HP.",
    "swain_passive": "Drains 8% of your team's HP at the end of each round.",
    "yasuo_passive": "50% chance to block each incoming hit.",
    "tryndamere_passive": "Survives at 1 HP for 2 rounds after dying (Undying Rage).",
    "chogath_passive": "Permanently gains +5% max HP each round (Feast).",
    "mordekaiser_passive": "Defeated champions rise to fight for him.",
    "jayce_passive": "Alternates cannon (high ATK) and hammer (high DEF) forms.",
    "gangplank_passive": "At rounds 5/10/15, blasts your team for 15% current HP.",
}

HAZARD_DESCRIPTIONS = {
    "wound": "Your team enters at 70% HP.",
    "berserker": "Enemies: +30% ATK, -20% DEF.",
    "armored": "Enemies: +40% DEF.",
    "speed_seal": "All units' SPD set to 50.",
    "double_strike": "Enemies strike twice.",
}


async def _team_champion_ids(owner_id: str) -> list[str]:
    team = await Team.get_or_create(owner_id)
    return [str(s) for s in team.slots if s is not None]


async def _dungeon_choices(current: str) -> list[app_commands.Choice[str]]:
    dungeons = await Dungeon.find(Dungeon.is_active == True).to_list()  # noqa: E712
    cur = (current or "").lower()
    out = []
    for d in sorted(dungeons, key=lambda x: x.total_floors):
        if cur in d.name.lower() or cur in d.slug.lower():
            out.append(app_commands.Choice(name=f"{d.emoji} {d.name} [{d.total_floors}F]", value=d.slug))
        if len(out) >= 25:
            break
    return out


def _rewards_lines(rewards: dict) -> str:
    lines = []
    if rewards.get("gold"):
        lines.append(f"💰 {rewards['gold']} gold")
    if rewards.get("xp"):
        lines.append(f"✨ {rewards['xp']} XP")
    if rewards.get("rune_shards"):
        lines.append(f"🔮 {rewards['rune_shards']} rune shard")
    if rewards.get("rune_fragments"):
        lines.append(f"💎 {rewards['rune_fragments']} rune fragment")
    for lv in rewards.get("leveled", []):
        lines.append(f"⬆️ {lv['name']} reached Lv.{lv['level']}!")
    bonus = rewards.get("bonus")
    if bonus:
        label = "🎉 First Clear Bonus" if bonus.get("type") == "first_clear" else "📅 Daily Clear Bonus"
        b = []
        if bonus.get("gold"):
            b.append(f"{bonus['gold']} gold")
        if bonus.get("summon_tokens"):
            b.append(f"{bonus['summon_tokens']} tokens")
        lines.append(f"{label}: {', '.join(b)}")
    return "\n".join(lines) if lines else "—"


class DungeonCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---------------------------------------------------------------
    @app_commands.command(name="dungeon-list", description="View all dungeons and your progress.")
    async def dungeon_list(self, interaction: discord.Interaction):
        await interaction.response.defer()
        uid = str(interaction.user.id)
        dungeons = await Dungeon.find(Dungeon.is_active == True).to_list()  # noqa: E712
        dungeons.sort(key=lambda d: (d.total_floors, d.name))
        progresses = {
            p.dungeon_slug: p
            for p in await DungeonProgress.find(DungeonProgress.owner_id == uid).to_list()
        }
        completed_lens = {
            (await Dungeon.find_one(Dungeon.slug == s)).total_floors
            for s, p in progresses.items() if p.completions > 0
        }
        completed_slugs = {s for s, p in progresses.items() if p.completions > 0}

        embed = discord.Embed(title="🗺️ Dungeon Map", color=0x5865F2)
        for d in dungeons:
            prog = progresses.get(d.slug)
            locked = self._is_locked(d, completed_slugs, completed_lens)
            if locked:
                status = "🔒 Locked"
                unlock = self._unlock_text(d)
                val = f"Recommended: {d.recommended_rank} | Boss: {d.boss_name}\n{unlock}"
            else:
                hf = prog.highest_floor if prog else 0
                mark = "✅" if (prog and prog.completions > 0) else "⭐"
                status = f"{mark} Floor {hf}/{d.total_floors}"
                val = f"Recommended: {d.recommended_rank} | Boss: {d.boss_name}"
            embed.add_field(
                name=f"{d.emoji} {d.name} [{d.total_floors}F] — {status}",
                value=val,
                inline=False,
            )
        await interaction.followup.send(embed=embed)

    def _is_locked(self, d: Dungeon, completed_slugs: set, completed_lens: set) -> bool:
        req = d.unlock_req
        if not req:
            return False
        if req == "ANY_20":
            return 20 not in completed_lens
        if req == "ANY_40":
            return 40 not in completed_lens
        return req not in completed_slugs

    def _unlock_text(self, d: Dungeon) -> str:
        req = d.unlock_req
        if req == "ANY_20":
            return "Unlock: Clear any 20F dungeon"
        if req == "ANY_40":
            return "Unlock: Clear any 40F dungeon"
        return f"Unlock: Clear {req.replace('-', ' ').title()}"

    # ---------------------------------------------------------------
    @app_commands.command(name="dungeon-enter", description="Enter a dungeon and fight floor by floor.")
    @app_commands.describe(dungeon_name="Dungeon to enter", floor_override="Optional floor to start at")
    async def dungeon_enter(self, interaction: discord.Interaction, dungeon_name: str, floor_override: int | None = None):
        await interaction.response.defer()
        uid = str(interaction.user.id)
        iid = str(interaction.id)
        if await is_already_processed(iid):
            await interaction.followup.send(embed=error_embed("Already processed."))
            return
        await User.get_or_create(uid, interaction.user.display_name)

        dungeon = await Dungeon.find_one(Dungeon.slug == dungeon_name)
        if dungeon is None:
            await interaction.followup.send(embed=error_embed("Dungeon not found."))
            return

        ok, reason = await dungeon_service.can_enter_dungeon(uid, dungeon_name, None)
        if not ok:
            await interaction.followup.send(embed=error_embed(reason))
            return

        prog = await dungeon_service.get_or_create_progress(uid, dungeon_name, None)
        floor_num = floor_override if floor_override else (prog.highest_floor + 1)
        floor_num = max(1, min(floor_num, dungeon.total_floors))
        # Cannot skip ahead beyond highest cleared + 1 (unless within checkpoint)
        if floor_override and floor_override > prog.highest_floor + 1 and floor_override > prog.checkpoint_floor + 1:
            await interaction.followup.send(embed=error_embed(
                f"You can't jump to floor {floor_override}. Highest reached: {prog.highest_floor}."))
            return

        champ_ids = await _team_champion_ids(uid)
        if not champ_ids:
            await interaction.followup.send(embed=error_embed("Your team is empty. Use /team-add."))
            return

        try:
            async with get_user_lock(uid):
                await self._run_floor(interaction, uid, dungeon_name, floor_num, champ_ids)
        except DungeonError as e:
            await interaction.followup.send(embed=error_embed(str(e)))
            return
        await mark_processed(iid, f"dungeon:{dungeon_name}:{floor_num}")

    async def _run_floor(self, interaction, uid, slug, floor_num, champ_ids):
        from services.battle_presentation_service import (
            simulate_and_store, start_presentation, advance_and_display,
        )
        units = await dungeon_service.build_floor_units(uid, slug, floor_num, champ_ids, None)
        player_units = units["player_units"]
        enemy_units = units["enemy_units"]
        seed = random.randint(0, 2 ** 31)

        battle_type = "boss" if units["boss_floor"] else "hunt"
        zone_label = f"{units['dungeon_name']} — Floor {floor_num}"
        enemy_name = enemy_units[0].name if enemy_units else "Enemy"

        bs = await simulate_and_store(
            owner_id=uid, zone=zone_label,
            player_units=player_units, enemy_units=enemy_units,
            battle_type=battle_type, entry_cost={"stamina": DUNGEON_STAMINA_COST},
            session=None,
        )
        won = bs.winner == 0

        async def _reward_fn():
            r = await dungeon_service.grant_floor_rewards(
                uid, slug, floor_num, champ_ids, won, bs.battle_seed, None)
            return r

        message = await start_presentation(
            bs, interaction.channel, [u.name for u in player_units], enemy_name,
            followup=interaction.followup,
        )
        await advance_and_display(str(bs.id), message, reward_fn=_reward_fn)

        # On loss, the presentation pipeline does NOT call reward_fn (it only
        # fires on victory), so grant the loss outcome (checkpoint reset) here.
        if not won:
            await dungeon_service.grant_floor_rewards(
                uid, slug, floor_num, champ_ids, won, bs.battle_seed, None)

        if won:
            res = await DungeonProgress.find_one(
                DungeonProgress.owner_id == uid, DungeonProgress.dungeon_slug == slug)
            next_floor = floor_num + 1 if floor_num < units["total_floors"] else None
            title = f"🏆 Floor {floor_num} Cleared!"
            if next_floor is None:
                title = f"👑 {units['dungeon_name']} CONQUERED!"
            embed = discord.Embed(title=title, color=0x00CC44)
            embed.description = f"Checkpoint: Floor {res.checkpoint_floor}"
            if next_floor:
                view = _NextFloorView(self, uid, slug, next_floor, champ_ids, interaction.user.id)
                await interaction.followup.send(embed=embed, view=view)
            else:
                await interaction.followup.send(embed=embed)
        else:
            res = await DungeonProgress.find_one(
                DungeonProgress.owner_id == uid, DungeonProgress.dungeon_slug == slug)
            embed = discord.Embed(
                title="💀 Defeated",
                description=f"You fell on Floor {floor_num}. Restarting from checkpoint Floor {res.checkpoint_floor}.",
                color=0xFF3333,
            )
            await interaction.followup.send(embed=embed)

    # ---------------------------------------------------------------
    @app_commands.command(name="dungeon-status", description="View your dungeon progress.")
    @app_commands.describe(dungeon_name="Optional: a specific dungeon")
    async def dungeon_status(self, interaction: discord.Interaction, dungeon_name: str | None = None):
        await interaction.response.defer()
        uid = str(interaction.user.id)
        user = await User.find_one(User.discord_id == uid)
        from utils.embeds import apply_stamina_regen
        if user and apply_stamina_regen(user):
            await user.save()

        if dungeon_name:
            d = await Dungeon.find_one(Dungeon.slug == dungeon_name)
            if d is None:
                await interaction.followup.send(embed=error_embed("Dungeon not found."))
                return
            prog = await DungeonProgress.find_one(
                DungeonProgress.owner_id == uid, DungeonProgress.dungeon_slug == dungeon_name)
            hf = prog.highest_floor if prog else 0
            cp = prog.checkpoint_floor if prog else 0
            comp = prog.completions if prog else 0
            embed = discord.Embed(title=f"{d.emoji} {d.name} — Status", color=0x5865F2)
            embed.add_field(name="Floor", value=f"{hf}/{d.total_floors}", inline=True)
            embed.add_field(name="Checkpoint", value=str(cp), inline=True)
            embed.add_field(name="Completions", value=str(comp), inline=True)
            embed.add_field(name="Stamina", value=f"{user.stamina}/{user.max_stamina}" if user else "—", inline=True)
            await interaction.followup.send(embed=embed)
            return

        progresses = await DungeonProgress.find(DungeonProgress.owner_id == uid).to_list()
        embed = discord.Embed(title="🗺️ Your Dungeon Progress", color=0x5865F2)
        embed.description = f"⚡ Stamina: {user.stamina}/{user.max_stamina}" if user else ""
        if not progresses:
            embed.add_field(name="No progress yet", value="Use /dungeon-enter to begin.", inline=False)
        for p in progresses:
            d = await Dungeon.find_one(Dungeon.slug == p.dungeon_slug)
            if d is None:
                continue
            mark = "✅" if p.completions > 0 else "⭐"
            embed.add_field(
                name=f"{d.emoji} {d.name}",
                value=f"{mark} Floor {p.highest_floor}/{d.total_floors} | Checkpoint {p.checkpoint_floor} | x{p.completions}",
                inline=False,
            )
        await interaction.followup.send(embed=embed)

    # ---------------------------------------------------------------
    @app_commands.command(name="dungeon-flee", description="Leave a dungeon (progress saved at checkpoint).")
    @app_commands.describe(dungeon_name="Dungeon to flee")
    async def dungeon_flee(self, interaction: discord.Interaction, dungeon_name: str):
        uid = str(interaction.user.id)
        d = await Dungeon.find_one(Dungeon.slug == dungeon_name)
        if d is None:
            await interaction.response.send_message(embed=error_embed("Dungeon not found."), ephemeral=True)
            return
        prog = await dungeon_service.get_or_create_progress(uid, dungeon_name, None)
        view = ConfirmView()
        await interaction.response.send_message(
            embed=info_embed(
                f"Flee {d.name}? Your progress is saved at checkpoint floor {prog.checkpoint_floor}.",
                "🏃 Confirm Flee"),
            view=view,
        )
        await view.wait()
        if not view.confirmed:
            await interaction.edit_original_response(embed=info_embed("Stayed in the dungeon."), view=None)
            return
        result = await dungeon_service.flee_dungeon(uid, dungeon_name, None)
        await interaction.edit_original_response(
            embed=success_embed(
                f"You left {d.name}. Progress saved at checkpoint floor {result['checkpoint_floor']}.",
                "🏃 Fled"),
            view=None,
        )

    # ---------------------------------------------------------------
    @app_commands.command(name="dungeon-info", description="View details about a dungeon.")
    @app_commands.describe(dungeon_name="Dungeon to inspect")
    async def dungeon_info(self, interaction: discord.Interaction, dungeon_name: str):
        await interaction.response.defer()
        d = await Dungeon.find_one(Dungeon.slug == dungeon_name)
        if d is None:
            await interaction.followup.send(embed=error_embed("Dungeon not found."))
            return
        from models.dungeon import DungeonFloor
        floors = await DungeonFloor.find(DungeonFloor.dungeon_slug == dungeon_name).to_list()
        hazards = sorted({f.hazard for f in floors if f.hazard})

        embed = discord.Embed(
            title=f"{d.emoji} {d.name}",
            description=d.description or "—",
            color=0x5865F2,
        )
        embed.add_field(name="Floors", value=str(d.total_floors), inline=True)
        embed.add_field(name="Recommended Rank", value=d.recommended_rank, inline=True)
        embed.add_field(name="Boss", value=d.boss_name, inline=True)
        embed.add_field(
            name="Boss Passive",
            value=PASSIVE_DESCRIPTIONS.get(d.boss_passive, d.boss_passive or "—"),
            inline=False,
        )
        if hazards:
            embed.add_field(
                name="Hazards",
                value="\n".join(f"• **{h}** — {HAZARD_DESCRIPTIONS.get(h, '')}" for h in hazards),
                inline=False,
            )
        embed.add_field(
            name="Drop Table",
            value="💰 Gold • ✨ XP • 🔮 Rune Shards (10%) • 💎 Rune Fragments (2%)",
            inline=False,
        )
        await interaction.followup.send(embed=embed)

    # ---------------------------------------------------------------
    @app_commands.command(name="dungeon-leaderboard", description="Top players in a dungeon.")
    @app_commands.describe(dungeon_name="Dungeon to rank")
    async def dungeon_leaderboard(self, interaction: discord.Interaction, dungeon_name: str):
        await interaction.response.defer()
        d = await Dungeon.find_one(Dungeon.slug == dungeon_name)
        if d is None:
            await interaction.followup.send(embed=error_embed("Dungeon not found."))
            return
        progresses = await DungeonProgress.find(DungeonProgress.dungeon_slug == dungeon_name).to_list()
        progresses.sort(key=lambda p: (-p.highest_floor, -p.completions))
        top = progresses[:10]
        lines = []
        for i, p in enumerate(top, 1):
            u = await User.find_one(User.discord_id == p.owner_id)
            name = u.username if u else p.owner_id
            done = "✅" if p.completions > 0 else ""
            lines.append(f"#{i} {name} — Floor {p.highest_floor}/{d.total_floors} {done}")
        embed = discord.Embed(
            title=f"🏆 {d.name} — Leaderboard",
            description="\n".join(lines) if lines else "No challengers yet.",
            color=0xFFD700,
        )
        await interaction.followup.send(embed=embed)

    # ---------------------------------------------------------------
    # Autocompletes
    @dungeon_enter.autocomplete("dungeon_name")
    async def _ac_enter(self, interaction, current: str):
        return await _dungeon_choices(current)

    @dungeon_status.autocomplete("dungeon_name")
    async def _ac_status(self, interaction, current: str):
        return await _dungeon_choices(current)

    @dungeon_flee.autocomplete("dungeon_name")
    async def _ac_flee(self, interaction, current: str):
        return await _dungeon_choices(current)

    @dungeon_info.autocomplete("dungeon_name")
    async def _ac_info(self, interaction, current: str):
        return await _dungeon_choices(current)

    @dungeon_leaderboard.autocomplete("dungeon_name")
    async def _ac_lb(self, interaction, current: str):
        return await _dungeon_choices(current)


class _NextFloorView(discord.ui.View):
    def __init__(self, cog, uid, slug, next_floor, champ_ids, user_id, timeout=120.0):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.uid = uid
        self.slug = slug
        self.next_floor = next_floor
        self.champ_ids = champ_ids
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This run isn't yours.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="➡️ Next Floor", style=discord.ButtonStyle.primary)
    async def next_floor_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        for c in self.children:
            c.disabled = True
        await interaction.response.edit_message(view=self)
        ok, reason = await dungeon_service.can_enter_dungeon(self.uid, self.slug, None)
        if not ok:
            await interaction.followup.send(embed=error_embed(reason))
            return
        from utils.locks import get_user_lock
        try:
            async with get_user_lock(self.uid):
                await self.cog._run_floor(interaction, self.uid, self.slug, self.next_floor, self.champ_ids)
        except DungeonError as e:
            await interaction.followup.send(embed=error_embed(str(e)))


async def setup(bot: commands.Bot):
    await bot.add_cog(DungeonCog(bot))
