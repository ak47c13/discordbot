import discord
from discord import app_commands
from discord.ext import commands

from models.user import User
from utils.embeds import error_embed, success_embed, progress_bar, COLOR_INFO
from utils.locks import get_user_lock
from utils.db_session import get_motor_client
from utils.idempotency import is_already_processed, mark_processed
from services.summon_service import summon_single, summon_multi, SummonError
from config.game_config import (
    SUMMON_TOKEN_COST, SUMMON_MULTI_COST, AURA_COLOR_BY_RANK, SUMMON_RATES,
)


class SummonCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="summon", description="Summon a champion or item using summon tokens.")
    @app_commands.describe(multi="Do 10 summons at once (costs 950 tokens instead of 1000)")
    async def summon(self, interaction: discord.Interaction, multi: bool = False):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)

        iid = str(interaction.id)
        if await is_already_processed(iid):
            await interaction.followup.send(embed=error_embed("Already processed."), ephemeral=True)
            return

        await User.get_or_create(uid, interaction.user.display_name)

        async with get_user_lock(uid):
            client = get_motor_client()
            async with await client.start_session() as session:
                async with session.start_transaction():
                    try:
                        if multi:
                            results = await summon_multi(uid, session)
                        else:
                            results = [await summon_single(uid, session)]
                    except SummonError as e:
                        await interaction.followup.send(embed=error_embed(str(e)), ephemeral=True)
                        return

        await mark_processed(iid, f"summon:{'multi' if multi else 'single'}")

        title = "🎰 10x Summon Results" if multi else "🎰 Summon Result"
        embed = discord.Embed(title=title, color=COLOR_INFO)

        for r in results:
            if r["type"] == "champion":
                rank = r["rank"]
                color = AURA_COLOR_BY_RANK.get(rank, 0xFFFFFF)
                embed.add_field(
                    name=f"🏆 Champion [{rank}]",
                    value=f"**{r['name']}**",
                    inline=True,
                )
            elif r["type"] == "item":
                embed.add_field(
                    name=f"⚔️ Item [{r['rank']}]",
                    value=f"**{r['name']}**",
                    inline=True,
                )
            elif r["type"] == "gold":
                embed.add_field(name="💰 Gold", value=str(r["amount"]), inline=True)
            elif r["type"] == "enhance_mat":
                embed.add_field(name="🔧 Enhance Mat", value=f"x{r['amount']}", inline=True)
            elif r["type"] == "reroll_mat":
                embed.add_field(name="🎲 Reroll Mat", value=f"x{r['amount']}", inline=True)
            elif r["type"] == "seal":
                embed.add_field(name="🔏 Blacksmith's Seal!", value="x1 — RARE!", inline=True)

        embed.set_footer(text=f"Cost: {SUMMON_MULTI_COST if multi else SUMMON_TOKEN_COST} summon tokens")
        await interaction.followup.send(embed=embed, ephemeral=True)

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
