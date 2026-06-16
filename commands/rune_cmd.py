import discord
from discord import app_commands
from discord.ext import commands
from models.user import User
from models.champion import ChampionInstance
from models.rune_page import RuneSlot
from utils.embeds import error_embed, success_embed
from utils.locks import get_user_lock
from data.rune_catalog import RUNE_CATALOG, can_equip_rune

COLOR_EMOJI = {"red": "🔴", "yellow": "🟡", "blue": "🔵", "quint": "💠"}
COLOR_ATTR = {"red": "reds", "yellow": "yellows", "blue": "blues", "quint": "quints"}


class RuneCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    runes = app_commands.Group(name="runes", description="Manage your rune page.")

    @runes.command(name="view", description="Show your current rune page.")
    async def runes_view(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user = await User.find_one(User.discord_id == str(interaction.user.id))
        if not user:
            await interaction.followup.send(embed=error_embed("Not registered."), ephemeral=True)
            return
        rp = user.rune_page
        embed = discord.Embed(title="📖 Your Rune Page", color=0x5865F2)
        for color, attr in [("red", "reds"), ("yellow", "yellows"), ("blue", "blues"), ("quint", "quints")]:
            slots = getattr(rp, attr)
            max_slots = 3 if color == "quint" else 9
            lines = []
            for i, slot in enumerate(slots[:max_slots], 1):
                if slot.rune_id:
                    r = RUNE_CATALOG.get(slot.rune_id)
                    lines.append(f"{i}. {r['name'] if r else slot.rune_id}")
                else:
                    lines.append(f"{i}. *— empty —*")
            filled = sum(1 for s in slots[:max_slots] if s.rune_id)
            embed.add_field(
                name=f"{COLOR_EMOJI[color]} {color.title()} ({filled}/{max_slots})",
                value="\n".join(lines),
                inline=True,
            )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @runes.command(name="page", description="Show total stat bonuses from your rune page.")
    async def runes_page(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user = await User.find_one(User.discord_id == str(interaction.user.id))
        if not user:
            await interaction.followup.send(embed=error_embed("Not registered."), ephemeral=True)
            return
        totals: dict = {}
        rp = user.rune_page
        all_slots = list(rp.reds) + list(rp.yellows) + list(rp.blues) + list(rp.quints[:3])
        for slot in all_slots:
            if not slot.rune_id:
                continue
            r = RUNE_CATALOG.get(slot.rune_id)
            if not r:
                continue
            totals[r["stat"]] = totals.get(r["stat"], 0) + r["value"]
        if not totals:
            embed = discord.Embed(
                title="📊 Rune Page Summary",
                description="No runes equipped. Use `/runes set` to add runes.",
                color=0x5865F2,
            )
        else:
            lines = [f"**{stat}**: +{val}" for stat, val in sorted(totals.items())]
            embed = discord.Embed(title="📊 Rune Page Summary", description="\n".join(lines), color=0x5865F2)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @runes.command(name="set", description="Equip a rune into a slot.")
    @app_commands.describe(color="red/yellow/blue/quint", slot="Slot number", rune_id="Rune ID (see /runes catalog)")
    @app_commands.choices(color=[
        app_commands.Choice(name="Red (Marks)", value="red"),
        app_commands.Choice(name="Yellow (Seals)", value="yellow"),
        app_commands.Choice(name="Blue (Glyphs)", value="blue"),
        app_commands.Choice(name="Quint (Quintessences)", value="quint"),
    ])
    async def runes_set(self, interaction: discord.Interaction, color: str, slot: int, rune_id: str):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        max_slots = 3 if color == "quint" else 9
        if not 1 <= slot <= max_slots:
            await interaction.followup.send(embed=error_embed(f"Slot must be 1–{max_slots} for {color}."), ephemeral=True)
            return
        rune = RUNE_CATALOG.get(rune_id)
        if not rune:
            await interaction.followup.send(embed=error_embed(f"Unknown rune: `{rune_id}`. Use `/runes catalog` to browse."), ephemeral=True)
            return
        if rune["color"] != color:
            await interaction.followup.send(embed=error_embed(f"That rune is a **{rune['color']}** rune, not {color}."), ephemeral=True)
            return
        async with get_user_lock(uid):
            user = await User.find_one(User.discord_id == uid)
            if not user:
                await interaction.followup.send(embed=error_embed("Not registered."), ephemeral=True)
                return
            if user.active_champion_id:
                champ = await ChampionInstance.get(user.active_champion_id)
                if champ and not can_equip_rune(rune_id, champ.rank):
                    await interaction.followup.send(embed=error_embed(f"This rune requires **{rune['rank_req']}** rank. Your champion is [{champ.rank}]."), ephemeral=True)
                    return
            getattr(user.rune_page, COLOR_ATTR[color])[slot - 1] = RuneSlot(rune_id=rune_id)
            await user.save()
        await interaction.followup.send(
            embed=success_embed(f"Slot {slot} ({color}) → **{rune['name']}** — {rune['description']}"),
            ephemeral=True,
        )

    @runes.command(name="clear", description="Remove a rune from a slot.")
    @app_commands.describe(color="red/yellow/blue/quint", slot="Slot number")
    @app_commands.choices(color=[
        app_commands.Choice(name="Red", value="red"),
        app_commands.Choice(name="Yellow", value="yellow"),
        app_commands.Choice(name="Blue", value="blue"),
        app_commands.Choice(name="Quint", value="quint"),
    ])
    async def runes_clear(self, interaction: discord.Interaction, color: str, slot: int):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        max_slots = 3 if color == "quint" else 9
        if not 1 <= slot <= max_slots:
            await interaction.followup.send(embed=error_embed(f"Slot must be 1–{max_slots}."), ephemeral=True)
            return
        async with get_user_lock(uid):
            user = await User.find_one(User.discord_id == uid)
            if not user:
                await interaction.followup.send(embed=error_embed("Not registered."), ephemeral=True)
                return
            getattr(user.rune_page, COLOR_ATTR[color])[slot - 1] = RuneSlot()
            await user.save()
        await interaction.followup.send(embed=success_embed(f"Slot {slot} ({color}) cleared."), ephemeral=True)

    @runes.command(name="catalog", description="Browse available runes.")
    @app_commands.describe(color="Filter by color (optional)")
    @app_commands.choices(color=[
        app_commands.Choice(name="All", value="all"),
        app_commands.Choice(name="Red (Marks)", value="red"),
        app_commands.Choice(name="Yellow (Seals)", value="yellow"),
        app_commands.Choice(name="Blue (Glyphs)", value="blue"),
        app_commands.Choice(name="Quint (Quintessences)", value="quint"),
    ])
    async def runes_catalog(self, interaction: discord.Interaction, color: str = "all"):
        await interaction.response.defer(ephemeral=True)
        runes_by_color: dict = {}
        for r in RUNE_CATALOG.values():
            if color == "all" or r["color"] == color:
                runes_by_color.setdefault(r["color"], []).append(r)
        embed = discord.Embed(title="📖 Rune Catalog", color=0x5865F2)
        for c in ["red", "yellow", "blue", "quint"]:
            if c not in runes_by_color:
                continue
            lines = [f"`{r['id']}` — {r['name']}: {r['description']} *(req: [{r['rank_req']}])*" for r in runes_by_color[c]]
            value = "\n".join(lines)[:1024]
            embed.add_field(name=f"{COLOR_EMOJI[c]} {c.title()}", value=value, inline=False)
        embed.set_footer(text="Use /runes set <color> <slot> <rune_id> to equip")
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(RuneCog(bot))
