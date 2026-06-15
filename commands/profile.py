import discord
from discord import app_commands
from discord.ext import commands

from models.user import User
from models.champion import ChampionInstance
from models.team import Team
from utils.embeds import error_embed
from utils.image_gen import generate_team_banner


class ProfileCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="profile", description="View your profile and resources.")
    async def profile(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user = await User.get_or_create(
            str(interaction.user.id), interaction.user.display_name
        )
        embed = discord.Embed(
            title=f"📜 {interaction.user.display_name}'s Profile",
            color=0x5865F2,
        )
        embed.add_field(name="💰 Gold",           value=str(user.gold),          inline=True)
        embed.add_field(name="🎟️ Summon Tokens",  value=str(user.summon_tokens), inline=True)
        embed.add_field(name="⚡ Stamina",         value=f"{user.stamina}/{user.max_stamina}", inline=True)
        seals = getattr(user, "blacksmith_seals", 0)
        embed.add_field(name="🔏 Blacksmith Seals", value=str(seals), inline=True)
        embed.set_footer(text=f"Joined: {user.created_at.strftime('%Y-%m-%d')}")

        # Attach the user's team banner if they have champions equipped.
        team = await Team.get_or_create(str(interaction.user.id))
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
            color=0xFFD700,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ProfileCog(bot))
