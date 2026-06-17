import discord
from discord import app_commands
from discord.ext import commands

from models.user import User
from models.champion import ChampionInstance
from models.item import ItemInstance
from utils.embeds import (
    error_embed, progress_bar, apply_stamina_regen, stamina_full_in,
    COLOR_INFO, COLOR_GOLD,
)
from utils.image_gen import DDRAGON_LOADING, _riot_id_from_name
from config.game_config import (
    STAMINA_REGEN_SECONDS,
    CHAMPION_BASE_STATS,
    CHAMPION_GROWTH_STATS,
    AURA_COLOR_BY_RANK,
)


def _champ_stats(champ) -> dict:
    rank, level = champ.rank, champ.level
    base = CHAMPION_BASE_STATS.get(rank, {})
    growth = CHAMPION_GROWTH_STATS.get(rank, {})
    return {
        "hp":  int(base.get("hp",  0) + growth.get("hp",  0) * (level - 1)),
        "atk": int(base.get("atk", 0) + growth.get("atk", 0) * (level - 1)),
        "def": int(base.get("def", 0) + growth.get("def", 0) * (level - 1)),
        "spd": int(base.get("spd", 0)),
    }


async def _build_profile_embed(target: discord.User | discord.Member, profile_user: User) -> discord.Embed:
    # Pick embed colour based on active champion rank, fallback to blue
    color = COLOR_INFO

    champ = None
    if profile_user.active_champion_id:
        champ = await ChampionInstance.get(profile_user.active_champion_id)
    if champ:
        color = AURA_COLOR_BY_RANK.get(champ.rank, COLOR_INFO)

    embed = discord.Embed(
        title=f"📜 {target.display_name}'s Profile",
        color=color,
    )

    # ── Economy row ────────────────────────────────────────────────
    seals = getattr(profile_user, "blacksmith_seals", 0)
    embed.add_field(name="💰 Gold",             value=f"{profile_user.gold:,}",        inline=True)
    embed.add_field(name="🎟️ Summon Tokens",    value=str(profile_user.summon_tokens), inline=True)
    embed.add_field(name="🔏 Blacksmith Seals", value=str(seals),                      inline=True)

    # ── Stamina ────────────────────────────────────────────────────
    bar = progress_bar(profile_user.stamina, profile_user.max_stamina)
    embed.add_field(
        name="⚡ Stamina",
        value=f"{profile_user.stamina}/{profile_user.max_stamina}  {bar}\nFull in: {stamina_full_in(profile_user)}",
        inline=False,
    )

    # ── Active champion block ──────────────────────────────────────
    if champ:
        riot_id = champ.riot_id or _riot_id_from_name(champ.name)
        embed.set_thumbnail(url=DDRAGON_LOADING.format(riot_id=riot_id))

        stats = _champ_stats(champ)

        embed.add_field(
            name=f"⚔️ {champ.name} [{champ.rank}] Lv.{champ.level}  •  #{champ.display_id}",
            value=(
                f"❤️ **HP** {stats['hp']:,}　"
                f"⚔️ **ATK** {stats['atk']:,}　"
                f"🛡️ **DEF** {stats['def']:,}　"
                f"💨 **SPD** {stats['spd']}"
            ),
            inline=False,
        )

        # Extended stats from runes (if any are non-default)
        rp = getattr(profile_user, "rune_page", None)
        ext_lines = []
        if rp:
            from services.rune_service import apply_rune_bonuses
            from engine.combat import CombatUnit
            # Build a dummy unit to compute rune bonuses
            dummy = CombatUnit(
                unit_id="preview", name=champ.name, rank=champ.rank, level=champ.level,
                position=1, team=0,
                hp=stats["hp"], hp_max=stats["hp"],
                atk=float(stats["atk"]), def_stat=float(stats["def"]),
                spd=stats["spd"],
            )
            apply_rune_bonuses(dummy, rp, champ.level)
            if dummy.crit_chance > 0:
                ext_lines.append(f"🎯 **Crit** {dummy.crit_chance:.1f}%")
            if getattr(dummy, "crit_dmg", 1.75) != 1.75:
                ext_lines.append(f"💥 **Crit DMG** {dummy.crit_dmg:.2f}×")
            if dummy.armor_pen > 0:
                ext_lines.append(f"🔱 **Arm Pen** {int(dummy.armor_pen)}")
            if dummy.magic_pen > 0:
                ext_lines.append(f"🔮 **Mag Pen** {int(dummy.magic_pen)}")
            if dummy.lifesteal > 0:
                ext_lines.append(f"🩸 **Lifesteal** {dummy.lifesteal*100:.1f}%")
            if getattr(dummy, "dodge_chance", 0) > 0:
                ext_lines.append(f"💨 **Dodge** {dummy.dodge_chance*100:.1f}%")
            if getattr(dummy, "attack_speed", 1.0) != 1.0:
                ext_lines.append(f"⚡ **Atk Spd** {dummy.attack_speed:.2f}×")
        if ext_lines:
            embed.add_field(name="✨ Rune Bonuses", value="  ".join(ext_lines), inline=False)

        # Rune page slots
        if rp:
            reds    = sum(1 for s in rp.reds    if s.rune_id)
            yellows = sum(1 for s in rp.yellows if s.rune_id)
            blues   = sum(1 for s in rp.blues   if s.rune_id)
            quints  = sum(1 for s in rp.quints  if s.rune_id)
            embed.add_field(
                name="💎 Rune Page",
                value=(
                    f"🔴 {reds}/9　🟡 {yellows}/9　🔵 {blues}/9　⚪ {quints}/3"
                ),
                inline=False,
            )

        # Equipped items
        items = await ItemInstance.find(ItemInstance.equipped_to == str(champ.id)).to_list()
        if items:
            item_lines = [f"Slot {itm.equipment_slot}: **{itm.name}** [{itm.rank}] +{itm.enhancement}" for itm in items]
            embed.add_field(name="🎒 Equipped Items", value="\n".join(item_lines), inline=False)
        else:
            embed.add_field(name="🎒 Equipped Items", value="None equipped", inline=False)
    else:
        embed.add_field(
            name="⚔️ Active Champion",
            value="None — use `/champion-select <id>` to set one.",
            inline=False,
        )

    # ── Footer ─────────────────────────────────────────────────────
    champ_count = await ChampionInstance.find(ChampionInstance.owner_id == str(target.id)).count()
    embed.set_footer(
        text=f"⚔️ {champ_count} champions  •  🏆 {getattr(profile_user, 'raids_completed', 0)} raids  •  Joined {profile_user.created_at.strftime('%Y-%m-%d')}"
    )
    return embed


class ProfileCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="profile", description="View your profile and resources.")
    @app_commands.describe(user="Player whose profile to view (defaults to you)")
    async def profile(self, interaction: discord.Interaction, user: discord.Member | None = None):
        await interaction.response.defer(ephemeral=True)
        target = user or interaction.user
        is_self = target.id == interaction.user.id

        profile_user = await User.get_or_create(str(target.id), target.display_name)
        if is_self and apply_stamina_regen(profile_user):
            await profile_user.save()

        embed = await _build_profile_embed(target, profile_user)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="stamina", description="Check your stamina and regeneration.")
    async def stamina(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user = await User.get_or_create(str(interaction.user.id), interaction.user.display_name)
        if apply_stamina_regen(user):
            await user.save()

        mins = STAMINA_REGEN_SECONDS // 60
        bar = progress_bar(user.stamina, user.max_stamina)
        embed = discord.Embed(
            title="⚡ Stamina",
            description=(
                f"**{user.stamina} / {user.max_stamina}**\n{bar}\n\n"
                f"Regenerates 1 per {mins} minutes.\n"
                f"Full in: {stamina_full_in(user)}"
            ),
            color=COLOR_INFO,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="leaderboard", description="View the top players.")
    @app_commands.describe(type="Leaderboard type")
    @app_commands.choices(type=[
        app_commands.Choice(name="gold", value="gold"),
        app_commands.Choice(name="champions", value="champions"),
        app_commands.Choice(name="raids", value="raids"),
    ])
    async def leaderboard(self, interaction: discord.Interaction, type: str = "gold"):
        await interaction.response.defer(ephemeral=True)

        if type == "gold":
            users = await User.find(User.registered == True).sort(-User.gold).limit(10).to_list()
            rows = [f"**{i}.** {u.username} — 💰 {u.gold:,} gold" for i, u in enumerate(users, 1)]
            title = "🏆 Leaderboard — Gold"
        elif type == "raids":
            users = await User.find(User.registered == True).sort(-User.raids_completed).limit(10).to_list()
            rows = [f"**{i}.** {u.username} — 🏆 {getattr(u, 'raids_completed', 0)} raids" for i, u in enumerate(users, 1)]
            title = "🏆 Leaderboard — Raids Completed"
        else:
            users = await User.find(User.registered == True).to_list()
            counts = []
            for u in users:
                cnt = await ChampionInstance.find(ChampionInstance.owner_id == u.discord_id).count()
                counts.append((u.username, cnt))
            counts.sort(key=lambda x: -x[1])
            rows = [f"**{i}.** {name} — ⚔️ {cnt} champions" for i, (name, cnt) in enumerate(counts[:10], 1)]
            title = "🏆 Leaderboard — Champions"

        if not rows:
            await interaction.followup.send(embed=error_embed("No players on the leaderboard yet."), ephemeral=True)
            return

        embed = discord.Embed(title=title, description="\n".join(rows), color=COLOR_GOLD)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="daily", description="Claim your daily summon token reward.")
    async def daily(self, interaction: discord.Interaction):
        from datetime import datetime, timezone, timedelta
        await interaction.response.defer(ephemeral=True)
        user = await User.get_or_create(
            str(interaction.user.id), interaction.user.display_name
        )
        now = datetime.now(timezone.utc)
        if user.last_daily and (now - user.last_daily) < timedelta(hours=20):
            remaining = timedelta(hours=20) - (now - user.last_daily)
            h, rem = divmod(int(remaining.total_seconds()), 3600)
            m = rem // 60
            await interaction.followup.send(
                embed=error_embed(f"Daily already claimed. Next in {h}h {m}m."),
                ephemeral=True,
            )
            return
        from config.game_config import DAILY_SUMMON_TOKENS
        user.summon_tokens += DAILY_SUMMON_TOKENS
        user.last_daily = now
        await user.save()
        embed = discord.Embed(
            title="🎁 Daily Reward",
            description=f"+{DAILY_SUMMON_TOKENS} Summon Tokens!",
            color=COLOR_GOLD,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ProfileCog(bot))
