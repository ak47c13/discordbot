import discord
from discord import app_commands
from discord.ext import commands
from models.user import User
from models.champion import ChampionInstance
from utils.embeds import error_embed, success_embed, get_champion_by_number
from utils.locks import get_user_lock
from data.champion_skills import CHAMPION_SKILLS


class ChampionSelectCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="champion-select", description="Set your active champion for battles.")
    @app_commands.describe(number="Champion list number (see /roster)")
    async def champion_select(self, interaction: discord.Interaction, number: int):
        await interaction.response.defer()
        uid = str(interaction.user.id)
        async with get_user_lock(uid):
            user = await User.find_one(User.discord_id == uid)
            if not user:
                await interaction.followup.send(embed=error_embed("Not registered."), ephemeral=True)
                return
            champ = await get_champion_by_number(uid, number)
            if not champ or champ.owner_id != uid:
                await interaction.followup.send(embed=error_embed("Champion not found."), ephemeral=True)
                return
            # Deactivate previous active champion
            if user.active_champion_id and user.active_champion_id != str(champ.id):
                prev = await ChampionInstance.get(user.active_champion_id)
                if prev:
                    prev.is_active = False
                    await prev.save()
            user.active_champion_id = str(champ.id)
            user.active_skill = "q"
            champ.is_active = True
            await champ.save()
            await user.save()

        rank, lvl = champ.rank, champ.level
        skills = CHAMPION_SKILLS.get(champ.name, {})
        q = skills.get("q", {})
        embed = discord.Embed(
            title=f"⚔️ {champ.name} [{rank}] selected!",
            description=f"Lv.{lvl} • Active skill: **Q — {q.get('name', '?')}**",
            color=0x5865F2,
        )
        embed.add_field(
            name="\U0001f4a1 Tip",
            value="Use `/skill view` to see all 4 skills. Use `/skill set w` or `/skill set e` to change active skill.",
            inline=False,
        )
        riot_id = getattr(champ, "riot_id", "") or champ.name.replace(" ", "").replace("'", "")
        embed.set_thumbnail(url=f"https://ddragon.leagueoflegends.com/cdn/img/champion/loading/{riot_id}_0.jpg")
        await interaction.followup.send(embed=embed)


async def setup(bot):
    await bot.add_cog(ChampionSelectCog(bot))
