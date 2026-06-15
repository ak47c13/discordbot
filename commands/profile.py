import discord
from discord import app_commands
from discord.ext import commands

from models.user import User
from models.champion import ChampionInstance
from models.team import Team
from utils.embeds import (
    error_embed, progress_bar, apply_stamina_regen, stamina_full_in,
    COLOR_INFO, COLOR_GOLD,
)
from utils.image_gen import generate_team_banner
from config.game_config import STAMINA_REGEN_SECONDS


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

        # Attach the user's team banner if they have champions equipped.
        team = await Team.get_or_create(str(target.id))
        team_champs = []
        for slot in team.slots:
            if slot is None:
                continue
            champ = await ChampionInstance.get(slot)
            if champ:
                team_champs.append({
                    "name": champ.name,
                    "rank": champ.rank,
                    "level": champ.level,
                    "riot_id": champ.riot_id or "",
                })

        if team_champs:
            try:
                buf = await generate_team_banner(team_champs)
                file = discord.File(buf, filename="team.png")
                embed.set_image(url="attachment://team.png")
                await interaction.followup.send(embed=embed, file=file, ephemeral=True)
                return
            except Exception:
                pass
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
