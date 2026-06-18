import discord
from discord import app_commands
from discord.ext import commands

from utils.embeds import progress_bar, COLOR_INFO
from config.game_config import (
    SUMMON_TOKEN_COST, SUMMON_MULTI_COST, SUMMON_RATES,
)


class SummonCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="summon-rates", description="View summon pull rates.")
    async def summon_rates(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        def line(label, prob):
            bar = progress_bar(prob, 0.30, 16)  # scale bars relative to max single rate
            return f"`{label:<3}` {bar}  {prob * 100:.1f}%"

        champs, items, other = [], [], []
        for key, prob in SUMMON_RATES.items():
            if prob <= 0:
                continue
            if key.startswith("champion_"):
                champs.append(line(key.split("_", 1)[1], prob))
            elif key.startswith("item_"):
                items.append(line(key.split("_", 1)[1], prob))
            else:
                other.append(f"`{key}` — {prob * 100:.1f}%")

        embed = discord.Embed(title="🎰 Summon Rates", color=COLOR_INFO)
        if champs:
            embed.add_field(name="Champions", value="\n".join(champs), inline=False)
        if items:
            embed.add_field(name="Items", value="\n".join(items), inline=False)
        if other:
            embed.add_field(name="Other", value="\n".join(other), inline=False)
        embed.set_footer(
            text=f"Single pull: {SUMMON_TOKEN_COST} tokens | 10x pull: {SUMMON_MULTI_COST} tokens"
        )
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(SummonCog(bot))
