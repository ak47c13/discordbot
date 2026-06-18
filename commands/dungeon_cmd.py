"""
Dungeon commands — floor-by-floor progression through LoL-region dungeons.
"""
from __future__ import annotations
import random

import discord
from discord import app_commands
from discord.ext import commands

from models.user import User
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


async def _active_champion_ids(owner_id: str) -> list[str]:
    user = await User.find_one(User.discord_id == owner_id)
    if not user or not user.active_champion_id:
        return []
    return [user.active_champion_id]


async def _dungeon_choices(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    """Autocomplete for commands that require an accessible dungeon (enter, status, flee)."""
    uid = str(interaction.user.id)
    dungeons = await Dungeon.find(Dungeon.is_active == True).to_list()  # noqa: E712
    dungeons.sort(key=lambda d: d.total_floors)

    progresses = await dungeon_service.get_all_progress(uid)
    completed_slugs = {p.dungeon_slug for p in progresses if p.completions > 0}

    cur = (current or "").lower()
    out = []
    for d in dungeons:
        # Only show maps the player has unlocked
        if d.unlock_req and d.unlock_req not in completed_slugs:
            continue
        if not cur or cur in d.name.lower() or cur in d.slug.lower():
            prog = next((p for p in progresses if p.dungeon_slug == d.slug), None)
            hf = prog.highest_floor if prog else 0
            label = f"{d.emoji} {d.name} [{hf}/{d.total_floors}F]"
            out.append(app_commands.Choice(name=label[:100], value=d.slug))
        if len(out) >= 25:
            break
    return out


async def _all_dungeon_choices(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    """Autocomplete for read-only commands (info, leaderboard) — shows ALL maps."""
    dungeons = await Dungeon.find(Dungeon.is_active == True).to_list()  # noqa: E712
    dungeons.sort(key=lambda d: d.total_floors)
    cur = (current or "").lower()
    out = []
    for d in dungeons:
        if not cur or cur in d.name.lower() or cur in d.slug.lower():
            label = f"{d.emoji} {d.name} [{d.total_floors}F] [Rec. {d.recommended_rank}]"
            out.append(app_commands.Choice(name=label[:100], value=d.slug))
        if len(out) >= 25:
            break
    return out


def _rewards_lines(rewards: dict) -> str:
    lines = []
    if rewards.get("gold"):
        lines.append(f"{rewards['gold']} gold")
    if rewards.get("xp"):
        lines.append(f"{rewards['xp']} XP")
    if rewards.get("rune"):
        r = rewards["rune"]
        lines.append(f"🧿 {r['name']} [{r['rank']}] Rune  #{r['display_id']}")
    for lv in rewards.get("leveled", []):
        lines.append(f"{lv['name']} reached Lv.{lv['level']}!")
    bonus = rewards.get("bonus")
    if bonus:
        label = "First Clear Bonus" if bonus.get("type") == "first_clear" else "Daily Clear Bonus"
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
    @app_commands.command(name="dungeon-list", description="View the dungeon map chain and your progress.")
    async def dungeon_list(self, interaction: discord.Interaction):
        await interaction.response.defer()
        uid = str(interaction.user.id)
        dungeons = await Dungeon.find(Dungeon.is_active == True).to_list()  # noqa: E712
        dungeons.sort(key=lambda d: d.total_floors)

        progresses = {
            p.dungeon_slug: p
            for p in await DungeonProgress.find(DungeonProgress.owner_id == uid).to_list()
        }
        completed_slugs = {s for s, p in progresses.items() if p.completions > 0}

        embed = discord.Embed(
            title="Dungeon Campaign",
            description="Clear each map to unlock the next. Progress saved at checkpoints every 10 floors.",
            color=0x5865F2,
        )

        for i, d in enumerate(dungeons):
            prog = progresses.get(d.slug)
            is_locked = d.unlock_req and d.unlock_req not in completed_slugs

            if is_locked:
                icon = "🔒"
                status = "Locked"
                val = f"Rec. Rank [{d.recommended_rank}] · {d.total_floors} floors · Boss: {d.boss_name}\nComplete the previous map to unlock."
            elif prog and prog.completions > 0:
                icon = "✅"
                status = f"Cleared  ×{prog.completions}"
                val = f"Rec. Rank [{d.recommended_rank}] · {d.total_floors} floors · Boss: {d.boss_name}"
            elif prog and prog.highest_floor > 0:
                icon = "⚔️"
                status = f"Floor {prog.highest_floor}/{d.total_floors} — In Progress"
                val = f"Rec. Rank [{d.recommended_rank}] · {d.total_floors} floors · Boss: {d.boss_name}\nCheckpoint: Floor {prog.checkpoint_floor}"
            else:
                icon = "▶️"
                status = "Ready to start"
                val = f"Rec. Rank [{d.recommended_rank}] · {d.total_floors} floors · Boss: {d.boss_name}"

            # Show connector arrow between maps
            connector = "  ↓\n" if i < len(dungeons) - 1 else ""
            embed.add_field(
                name=f"{icon} {d.emoji} {d.name} — {status}",
                value=val + (f"\n{connector}" if connector else ""),
                inline=False,
            )

        await interaction.followup.send(embed=embed)

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

        champ_ids = await _active_champion_ids(uid)
        if not champ_ids:
            await interaction.followup.send(embed=error_embed("No active champion. Use /champion-select first."))
            return

        try:
            async with get_user_lock(uid):
                await self._run_floor(interaction, uid, dungeon_name, floor_num, champ_ids)
        except DungeonError as e:
            await interaction.followup.send(embed=error_embed(str(e)))
            return
        await mark_processed(iid, f"dungeon:{dungeon_name}:{floor_num}")

    async def _run_floor(self, interaction, uid, slug, floor_num, champ_ids, existing_message=None, continuous=False):
        """Run one dungeon floor.

        Returns the battle message on success, None if the session was cancelled mid-fight.
        When *continuous* is True, skips the post-floor prompt (caller handles flow control).
        """
        from services.battle_presentation_service import (
            simulate_and_store, start_presentation, advance_and_display,
        )
        from models.battle_session import BattleSession
        from beanie import PydanticObjectId

        units = await dungeon_service.build_floor_units(uid, slug, floor_num, champ_ids, None)
        player_units = units["player_units"]
        enemy_units = units["enemy_units"]

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
            return await dungeon_service.grant_floor_rewards(
                uid, slug, floor_num, champ_ids, won, bs.battle_seed, None)

        message = await start_presentation(
            bs, interaction.channel, [u.name for u in player_units], enemy_name,
            followup=interaction.followup if existing_message is None else None,
            reuse_message=existing_message,
        )
        await advance_and_display(str(bs.id), message, reward_fn=_reward_fn)

        # Check if user hit Cancel during the fight
        bs_fresh = await BattleSession.get(bs.id)
        if bs_fresh and bs_fresh.status.startswith("CANCELLED"):
            return None

        # On loss, grant the loss outcome (checkpoint reset) here — reward_fn only fires on victory.
        if not won:
            await dungeon_service.grant_floor_rewards(
                uid, slug, floor_num, champ_ids, won, bs.battle_seed, None)

        if not continuous:
            # Single-floor mode: show result prompt with navigation buttons
            if won:
                res = await DungeonProgress.find_one(
                    DungeonProgress.owner_id == uid, DungeonProgress.dungeon_slug == slug)
                next_floor = floor_num + 1 if floor_num < units["total_floors"] else None
                title = f"Floor {floor_num} Cleared"
                if next_floor is None:
                    title = f"{units['dungeon_name']} Conquered!"
                embed = discord.Embed(title=title, color=0x00CC44)
                embed.description = f"Checkpoint: Floor {res.checkpoint_floor}"
                if next_floor:
                    view = _NextFloorView(self, uid, slug, floor_num, next_floor, champ_ids, interaction.user.id)
                    await interaction.followup.send(embed=embed, view=view)
                else:
                    view = _RepeatFloorView(self, uid, slug, floor_num, None, champ_ids, interaction.user.id)
                    await interaction.followup.send(embed=embed, view=view)
            else:
                res = await DungeonProgress.find_one(
                    DungeonProgress.owner_id == uid, DungeonProgress.dungeon_slug == slug)
                embed = discord.Embed(
                    title="Defeated",
                    description=f"You fell on Floor {floor_num}. Checkpoint: Floor {res.checkpoint_floor}.",
                    color=0xFF3333,
                )
                view = _RepeatFloorView(self, uid, slug, floor_num, res.checkpoint_floor, champ_ids, interaction.user.id)
                await interaction.followup.send(embed=embed, view=view)

        return message

    async def _run_repeat_continuous(self, interaction, uid, slug, floor_num, champ_ids):
        """Farm the same floor repeatedly until death, stamina runs out, or user stops."""
        runs = 0
        stop_reason = "out of stamina"
        battle_message = None

        while True:
            ok, reason = await dungeon_service.can_enter_dungeon(uid, slug, None)
            if not ok:
                stop_reason = "out of stamina"
                break

            try:
                result = await self._run_floor(
                    interaction, uid, slug, floor_num, champ_ids,
                    existing_message=battle_message, continuous=True,
                )
            except DungeonError as e:
                stop_reason = str(e)
                break

            if result is None:
                # User cancelled via Cancel button during the fight
                stop_reason = "cancelled"
                break

            battle_message = result

            prog = await dungeon_service.get_or_create_progress(uid, slug, None)
            if prog.highest_floor < floor_num:
                stop_reason = f"defeated on floor {floor_num}"
                break

            runs += 1

        embed = discord.Embed(
            title="Repeat Run Complete",
            description=f"**Floor {floor_num} runs:** {runs}\n**Stopped:** {stop_reason}",
            color=0x5865F2,
        )
        await interaction.followup.send(embed=embed)

    async def _run_continuous(self, interaction, uid, slug, start_floor, champ_ids):
        """Run floors back-to-back until death, stamina depletion, map clear, or user stops."""
        from models.dungeon import Dungeon
        dungeon = await Dungeon.find_one(Dungeon.slug == slug)
        total_floors = dungeon.total_floors if dungeon else 999

        floor_num = start_floor
        floors_cleared = 0
        stop_reason = "map cleared"
        battle_message = None

        while floor_num <= total_floors:
            ok, reason = await dungeon_service.can_enter_dungeon(uid, slug, None)
            if not ok:
                stop_reason = f"out of stamina"
                break

            try:
                result = await self._run_floor(
                    interaction, uid, slug, floor_num, champ_ids,
                    existing_message=battle_message, continuous=True,
                )
            except DungeonError as e:
                stop_reason = str(e)
                break

            if result is None:
                # User cancelled via Cancel button during the fight
                stop_reason = "cancelled"
                break

            battle_message = result

            prog = await dungeon_service.get_or_create_progress(uid, slug, None)
            if prog.highest_floor < floor_num:
                stop_reason = f"defeated on floor {floor_num}"
                break

            floors_cleared += 1
            floor_num += 1

        embed = discord.Embed(
            title="⏹ Continuous Run Complete",
            description=(
                f"**Floors cleared:** {floors_cleared}\n"
                f"**Stopped:** {stop_reason}"
            ),
            color=0x5865F2,
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
        embed = discord.Embed(title="Dungeon Progress", color=0x5865F2)
        embed.description = f"Stamina: {user.stamina}/{user.max_stamina}" if user else ""
        has_any = False
        for p in progresses:
            d = await Dungeon.find_one(Dungeon.slug == p.dungeon_slug)
            if d is None:
                continue  # orphaned progress from an old dungeon slug — skip silently
            has_any = True
            mark = "✅" if p.completions > 0 else "⭐"
            embed.add_field(
                name=f"{d.emoji} {d.name}",
                value=f"{mark} Floor {p.highest_floor}/{d.total_floors} | Checkpoint {p.checkpoint_floor} | ×{p.completions}",
                inline=False,
            )
        if not has_any:
            embed.add_field(name="No progress yet", value="Use /dungeon-enter to begin.", inline=False)
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
            value="Gold • XP • Rune Shards (10%) • Rune Fragments (2%)",
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
            title=f"{d.name} — Leaderboard",
            description="\n".join(lines) if lines else "No challengers yet.",
            color=0xFFD700,
        )
        await interaction.followup.send(embed=embed)

    # ---------------------------------------------------------------
    # Autocompletes
    @dungeon_enter.autocomplete("dungeon_name")
    async def _ac_enter(self, interaction, current: str):
        return await _dungeon_choices(interaction, current)

    @dungeon_status.autocomplete("dungeon_name")
    async def _ac_status(self, interaction, current: str):
        return await _dungeon_choices(interaction, current)

    @dungeon_flee.autocomplete("dungeon_name")
    async def _ac_flee(self, interaction, current: str):
        return await _dungeon_choices(interaction, current)

    @dungeon_info.autocomplete("dungeon_name")
    async def _ac_info(self, interaction, current: str):
        return await _all_dungeon_choices(interaction, current)

    @dungeon_leaderboard.autocomplete("dungeon_name")
    async def _ac_lb(self, interaction, current: str):
        return await _all_dungeon_choices(interaction, current)


class _RepeatFloorView(discord.ui.View):
    """View shown after defeat or dungeon clear — retry same floor or return to checkpoint."""
    def __init__(self, cog, uid, slug, floor_num, checkpoint_floor, champ_ids, user_id, timeout=120.0):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.uid = uid
        self.slug = slug
        self.floor_num = floor_num
        self.checkpoint_floor = checkpoint_floor
        self.champ_ids = champ_ids
        self.user_id = user_id

        # Hide checkpoint buttons if there's no meaningful checkpoint to go back to
        if not checkpoint_floor or checkpoint_floor >= floor_num:
            self.remove_item(self.checkpoint_btn)
            self.remove_item(self.farm_checkpoint_btn)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This run isn't yours.", ephemeral=True)
            return False
        return True

    async def _run(self, interaction, floor):
        ok, reason = await dungeon_service.can_enter_dungeon(self.uid, self.slug, None)
        if not ok:
            await interaction.followup.send(embed=error_embed(reason))
            return
        from utils.locks import get_user_lock
        try:
            async with get_user_lock(self.uid):
                await self.cog._run_floor(interaction, self.uid, self.slug, floor, self.champ_ids, continuous=False)
        except DungeonError as e:
            await interaction.followup.send(embed=error_embed(str(e)))

    @discord.ui.button(label="Retry Floor", style=discord.ButtonStyle.danger)
    async def repeat_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        for c in self.children:
            c.disabled = True
        await interaction.response.edit_message(view=self)
        await self._run(interaction, self.floor_num)

    @discord.ui.button(label="Back to Checkpoint", style=discord.ButtonStyle.secondary)
    async def checkpoint_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        for c in self.children:
            c.disabled = True
        await interaction.response.edit_message(view=self)
        await self._run(interaction, self.checkpoint_floor)

    @discord.ui.button(label="Farm Checkpoint", style=discord.ButtonStyle.success)
    async def farm_checkpoint_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        for c in self.children:
            c.disabled = True
        await interaction.response.edit_message(view=self)
        farm_floor = self.checkpoint_floor if self.checkpoint_floor and self.checkpoint_floor < self.floor_num else self.floor_num
        from utils.locks import get_user_lock
        try:
            async with get_user_lock(self.uid):
                await self.cog._run_repeat_continuous(interaction, self.uid, self.slug, farm_floor, self.champ_ids)
        except DungeonError as e:
            await interaction.followup.send(embed=error_embed(str(e)))


class _NextFloorView(discord.ui.View):
    def __init__(self, cog, uid, slug, current_floor, next_floor, champ_ids, user_id, timeout=120.0):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.uid = uid
        self.slug = slug
        self.current_floor = current_floor
        self.next_floor = next_floor
        self.champ_ids = champ_ids
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This run isn't yours.", ephemeral=True)
            return False
        return True

    async def _check_and_run(self, interaction, floor):
        ok, reason = await dungeon_service.can_enter_dungeon(self.uid, self.slug, None)
        if not ok:
            await interaction.followup.send(embed=error_embed(reason))
            return
        from utils.locks import get_user_lock
        try:
            async with get_user_lock(self.uid):
                await self.cog._run_floor(interaction, self.uid, self.slug, floor, self.champ_ids, continuous=False)
        except DungeonError as e:
            await interaction.followup.send(embed=error_embed(str(e)))

    @discord.ui.button(label="Repeat Floor", style=discord.ButtonStyle.secondary)
    async def repeat_floor_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        for c in self.children:
            c.disabled = True
        await interaction.response.edit_message(view=self)
        await self._check_and_run(interaction, self.current_floor)

    @discord.ui.button(label="Repeat Continuously", style=discord.ButtonStyle.secondary)
    async def repeat_continuous_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        for c in self.children:
            c.disabled = True
        await interaction.response.edit_message(view=self)
        from utils.locks import get_user_lock
        try:
            async with get_user_lock(self.uid):
                await self.cog._run_repeat_continuous(interaction, self.uid, self.slug, self.current_floor, self.champ_ids)
        except DungeonError as e:
            await interaction.followup.send(embed=error_embed(str(e)))

    @discord.ui.button(label="Next Floor", style=discord.ButtonStyle.primary)
    async def next_floor_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        for c in self.children:
            c.disabled = True
        await interaction.response.edit_message(view=self)
        await self._check_and_run(interaction, self.next_floor)

    @discord.ui.button(label="Run Continuously", style=discord.ButtonStyle.success)
    async def run_continuous_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        for c in self.children:
            c.disabled = True
        await interaction.response.edit_message(view=self)
        from utils.locks import get_user_lock
        try:
            async with get_user_lock(self.uid):
                await self.cog._run_continuous(interaction, self.uid, self.slug, self.next_floor, self.champ_ids)
        except DungeonError as e:
            await interaction.followup.send(embed=error_embed(str(e)))


async def setup(bot: commands.Bot):
    await bot.add_cog(DungeonCog(bot))
