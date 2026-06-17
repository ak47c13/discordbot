import discord
from discord import app_commands
from discord.ext import commands

from models.user import User
from models.champion import ChampionInstance
from utils.embeds import (
    error_embed, progress_bar, apply_stamina_regen, stamina_full_in,
    COLOR_INFO, COLOR_GOLD,
)
from utils.image_gen import generate_team_banner
from config.game_config import (
    STAMINA_REGEN_SECONDS,
    CHAMPION_BASE_STATS,
    CHAMPION_GROWTH_STATS,
)


# ---------------------------------------------------------------------------
# Champion Stats button view
# ---------------------------------------------------------------------------

class ProfileView(discord.ui.View):
    """Attached to the profile message; offers a '📋 Stats' button."""

    def __init__(self, active_champ_id: str | None, owner_id: int, timeout: float = 120.0):
        super().__init__(timeout=timeout)
        self.active_champ_id = active_champ_id
        self.owner_id = owner_id
        # Disable the button if there's no active champion
        self.stats_btn.disabled = active_champ_id is None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This profile isn't yours.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="📋 Champion Stats", style=discord.ButtonStyle.secondary)
    async def stats_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        champ = await ChampionInstance.get(self.active_champ_id)
        if champ is None:
            await interaction.followup.send(
                embed=error_embed("Active champion not found."), ephemeral=True
            )
            return

        rank = champ.rank
        level = champ.level
        base = CHAMPION_BASE_STATS.get(rank, {})
        growth = CHAMPION_GROWTH_STATS.get(rank, {})
        atk = base.get("atk", 0) + growth.get("atk", 0) * (level - 1)
        hp = base.get("hp", 0) + growth.get("hp", 0) * (level - 1)
        def_val = base.get("def", 0) + growth.get("def", 0) * (level - 1)
        spd = base.get("spd", 0)

        from config.game_config import AURA_COLOR_BY_RANK
        color = AURA_COLOR_BY_RANK.get(rank, COLOR_INFO)

        embed = discord.Embed(
            title=f"📋 {champ.name} [{rank}] — Champion Stats",
            color=color,
        )
        embed.add_field(name="Level", value=str(level), inline=True)
        embed.add_field(name="Display ID", value=f"#{champ.display_id}", inline=True)
        embed.add_field(name="​", value="​", inline=True)
        embed.add_field(name="❤️ HP",  value=str(int(hp)),      inline=True)
        embed.add_field(name="⚔️ ATK", value=str(int(atk)),     inline=True)
        embed.add_field(name="🛡️ DEF", value=str(int(def_val)), inline=True)
        embed.add_field(name="💨 SPD", value=str(spd),          inline=True)

        # Equipped items
        from models.item import ItemInstance
        items = await ItemInstance.find(
            ItemInstance.equipped_to == str(champ.id)
        ).to_list()
        if items:
            item_lines = [f"Slot {itm.equipment_slot}: **{itm.name}** [{itm.rank}] +{itm.enhancement}" for itm in items]
            embed.add_field(name="🎒 Equipped Items", value="\n".join(item_lines), inline=False)
        else:
            embed.add_field(name="🎒 Equipped Items", value="None", inline=False)

        # Rune page summary — fetch from user
        owner_user = await User.find_one(User.discord_id == str(self.owner_id))
        if owner_user and owner_user.rune_page:
            rp = owner_user.rune_page
            reds_filled    = sum(1 for s in rp.reds    if s.rune_id)
            yellows_filled = sum(1 for s in rp.yellows if s.rune_id)
            blues_filled   = sum(1 for s in rp.blues   if s.rune_id)
            quints_filled  = sum(1 for s in rp.quints  if s.rune_id)
            rune_summary = (
                f"🔴 Reds: {reds_filled}/9\n"
                f"🟡 Yellows: {yellows_filled}/9\n"
                f"🔵 Blues: {blues_filled}/9\n"
                f"⚪ Quints: {quints_filled}/3"
            )
            embed.add_field(name="💎 Rune Page", value=rune_summary, inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)


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

        embed = discord.Embed(
            title=f"📜 {target.display_name}'s Profile",
            color=COLOR_INFO,
        )
        embed.add_field(name="💰 Gold",           value=str(profile_user.gold),          inline=True)
        embed.add_field(name="🎟️ Summon Tokens",  value=str(profile_user.summon_tokens), inline=True)
        seals = getattr(profile_user, "blacksmith_seals", 0)
        embed.add_field(name="🔏 Blacksmith Seals", value=str(seals), inline=True)

        bar = progress_bar(profile_user.stamina, profile_user.max_stamina)
        embed.add_field(
            name="⚡ Stamina",
            value=(
                f"{profile_user.stamina} / {profile_user.max_stamina}\n{bar}\n"
                f"Full in: {stamina_full_in(profile_user)}"
            ),
            inline=False,
        )
        embed.add_field(name="🏆 Raids Completed", value=str(getattr(profile_user, "raids_completed", 0)), inline=True)

        champ_count = await ChampionInstance.find(ChampionInstance.owner_id == str(target.id)).count()
        embed.add_field(name="⚔️ Champions", value=str(champ_count), inline=True)
        embed.set_footer(text=f"Joined: {profile_user.created_at.strftime('%Y-%m-%d')}")

        # Attach the user's active champion banner.
        profile_user_data = await User.find_one(User.discord_id == str(target.id))
        team_champs = []
        if profile_user_data and profile_user_data.active_champion_id:
            champ = await ChampionInstance.get(profile_user_data.active_champion_id)
            if champ:
                team_champs.append({
                    "name": champ.name,
                    "rank": champ.rank,
                    "level": champ.level,
                    "riot_id": champ.riot_id or "",
                })

        active_champ_id = profile_user_data.active_champion_id if profile_user_data else None
        view = ProfileView(active_champ_id, interaction.user.id) if is_self else None

        if team_champs:
            try:
                buf = await generate_team_banner(team_champs)
                file = discord.File(buf, filename="team.png")
                embed.set_image(url="attachment://team.png")
                await interaction.followup.send(embed=embed, file=file, view=view, ephemeral=True)
                return
            except Exception:
                pass
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

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
        else:  # champions
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
