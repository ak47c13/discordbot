import discord
from discord import app_commands
from discord.ext import commands
from collections import Counter

from models.user import User
from models.champion import ChampionInstance
from models.rune_page import RuneSlot
from models.rune_instance import RuneInstance
from utils.embeds import error_embed, success_embed
from utils.locks import get_user_lock
from data.rune_catalog import RUNE_CATALOG, can_equip_rune
from config.game_config import RUNE_RANK_MULTIPLIERS

COLOR_EMOJI = {"red": "🔴", "yellow": "🟡", "blue": "🔵", "quint": "💠"}
COLOR_ATTR = {"red": "reds", "yellow": "yellows", "blue": "blues", "quint": "quints"}

RANK_COLORS = {
    "F": 0x888888, "E": 0x4fde74, "D": 0x4f9ede,
    "C": 0xb04fde, "B": 0xde9c4f, "A": 0xde4f4f, "S": 0xffd700,
}


class RuneCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    runes = app_commands.Group(name="runes", description="Manage your rune page.")

    @runes.command(name="inventory", description="Show all runes you own.")
    @app_commands.describe(color="Filter by color (optional)")
    @app_commands.choices(color=[
        app_commands.Choice(name="All", value="all"),
        app_commands.Choice(name="Red (Marks)", value="red"),
        app_commands.Choice(name="Yellow (Seals)", value="yellow"),
        app_commands.Choice(name="Blue (Glyphs)", value="blue"),
        app_commands.Choice(name="Quint (Quintessences)", value="quint"),
    ])
    async def runes_inventory(self, interaction: discord.Interaction, color: str = "all"):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        user = await User.find_one(User.discord_id == uid)
        if not user:
            await interaction.followup.send(embed=error_embed("Not registered."), ephemeral=True)
            return

        instances = await RuneInstance.find(RuneInstance.owner_id == uid).to_list()
        if color != "all":
            instances = [i for i in instances if RUNE_CATALOG.get(i.rune_id, {}).get("color") == color]

        if not instances:
            await interaction.followup.send(
                embed=error_embed("No runes in your inventory.", "Pull runes from /shop type:Runes."),
                ephemeral=True,
            )
            return

        instances.sort(key=lambda i: (RUNE_CATALOG.get(i.rune_id, {}).get("color", ""), i.rank, i.rune_id))

        embed = discord.Embed(title="🧿 Rune Inventory", color=0x5865F2)
        embed.description = f"**{len(instances)} rune(s)** owned"

        by_color: dict[str, list] = {}
        for inst in instances:
            r = RUNE_CATALOG.get(inst.rune_id, {})
            c = r.get("color", "red")
            by_color.setdefault(c, []).append((inst, r))

        for c in ["red", "yellow", "blue", "quint"]:
            if c not in by_color:
                continue
            lines = []
            for inst, r in by_color[c]:
                mult = RUNE_RANK_MULTIPLIERS.get(inst.rank, 1.0)
                effective = r.get("value", 0) * mult
                stat_str = f"+{effective:.0f}" if effective == int(effective) else f"+{effective:.1f}"
                equipped_tag = " *(equipped)*" if inst.is_equipped else ""
                lines.append(
                    f"`#{inst.display_id}` **{r.get('name', inst.rune_id)}** [{inst.rank}]{equipped_tag}\n"
                    f"  {r.get('stat','').upper()} {stat_str} — {r.get('description','')}"
                )
            value = "\n".join(lines)
            if len(value) > 1024:
                value = value[:1020] + "…"
            embed.add_field(
                name=f"{COLOR_EMOJI[c]} {c.title()} ({len(by_color[c])})",
                value=value or "—",
                inline=False,
            )
        embed.set_footer(text="/runes set <color> <slot> <display_id>  ·  /runes view to see your page")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @runes.command(name="view", description="Show your rune page layout and total stat bonuses.")
    async def runes_view(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user = await User.find_one(User.discord_id == str(interaction.user.id))
        if not user:
            await interaction.followup.send(embed=error_embed("Not registered."), ephemeral=True)
            return
        rp = user.rune_page

        # Compute stat totals
        totals: dict = {}
        all_slots = list(rp.reds) + list(rp.yellows) + list(rp.blues) + list(rp.quints[:3])
        for slot in all_slots:
            if not slot.rune_id:
                continue
            r = RUNE_CATALOG.get(slot.rune_id)
            if not r:
                continue
            mult = RUNE_RANK_MULTIPLIERS.get(slot.rank, 1.0)
            val = r["value"] * mult
            totals[r["stat"]] = totals.get(r["stat"], 0) + val

        embed = discord.Embed(title="📖 Your Rune Page", color=0x5865F2)

        # Top section: stat totals
        if totals:
            lines = []
            for stat, val in sorted(totals.items()):
                disp = f"{val:.1f}" if val != int(val) else str(int(val))
                lines.append(f"**{stat}**: +{disp}")
            embed.description = "**📊 Stat Totals**\n" + "\n".join(lines)
        else:
            embed.description = "No runes equipped. Use `/runes set` to add runes."

        # Per-color slot layout
        for color, attr in [("red", "reds"), ("yellow", "yellows"), ("blue", "blues"), ("quint", "quints")]:
            slots = getattr(rp, attr)
            max_slots = 3 if color == "quint" else 9
            lines = []
            for i, slot in enumerate(slots[:max_slots], 1):
                if slot.rune_id:
                    r = RUNE_CATALOG.get(slot.rune_id)
                    name = r["name"] if r else slot.rune_id
                    lines.append(f"{i}. {name} [{slot.rank}]")
                else:
                    lines.append(f"{i}. *— empty —*")
            filled = sum(1 for s in slots[:max_slots] if s.rune_id)
            embed.add_field(
                name=f"{COLOR_EMOJI[color]} {color.title()} ({filled}/{max_slots})",
                value="\n".join(lines),
                inline=True,
            )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @runes.command(name="set", description="Equip an owned rune into a slot.")
    @app_commands.describe(color="red/yellow/blue/quint", slot="Slot number", display_id="Rune # from /runes inventory")
    @app_commands.choices(color=[
        app_commands.Choice(name="Red (Marks)", value="red"),
        app_commands.Choice(name="Yellow (Seals)", value="yellow"),
        app_commands.Choice(name="Blue (Glyphs)", value="blue"),
        app_commands.Choice(name="Quint (Quintessences)", value="quint"),
    ])
    async def runes_set(self, interaction: discord.Interaction, color: str, slot: int, display_id: int):
        await interaction.response.defer()
        uid = str(interaction.user.id)
        max_slots = 3 if color == "quint" else 9
        if not 1 <= slot <= max_slots:
            await interaction.followup.send(embed=error_embed(f"Slot must be 1–{max_slots} for {color}."), ephemeral=True)
            return

        # Find owned rune by display_id
        inst = await RuneInstance.find_one(RuneInstance.owner_id == uid, RuneInstance.display_id == display_id)
        if inst is None:
            await interaction.followup.send(
                embed=error_embed(f"Rune #{display_id} not found in your inventory.", "Use `/runes inventory` to see your runes."),
                ephemeral=True,
            )
            return

        rune = RUNE_CATALOG.get(inst.rune_id)
        if not rune:
            await interaction.followup.send(embed=error_embed("Unknown rune data."), ephemeral=True)
            return
        if rune["color"] != color:
            await interaction.followup.send(
                embed=error_embed(f"That rune is a **{rune['color']}** rune, not {color}."), ephemeral=True
            )
            return

        async with get_user_lock(uid):
            user = await User.find_one(User.discord_id == uid)
            if not user:
                await interaction.followup.send(embed=error_embed("Not registered."), ephemeral=True)
                return
            if user.active_champion_id:
                champ = await ChampionInstance.get(user.active_champion_id)
                if champ and not can_equip_rune(inst.rune_id, champ.rank):
                    await interaction.followup.send(
                        embed=error_embed(f"This rune requires **{rune['rank_req']}** rank. Your champion is [{champ.rank}]."),
                        ephemeral=True,
                    )
                    return

            # Unmark any previously equipped instance in this exact slot
            old_slot = getattr(user.rune_page, COLOR_ATTR[color])[slot - 1]
            if old_slot.instance_id:
                old_inst = await RuneInstance.find_one(
                    RuneInstance.owner_id == uid,
                    RuneInstance.display_id == 0,  # find by instance_id instead
                )
                # Find by str(id)
                from beanie import PydanticObjectId
                try:
                    prev = await RuneInstance.get(PydanticObjectId(old_slot.instance_id))
                    if prev:
                        prev.is_equipped = False
                        await prev.save()
                except Exception:
                    pass

            getattr(user.rune_page, COLOR_ATTR[color])[slot - 1] = RuneSlot(
                rune_id=inst.rune_id,
                instance_id=str(inst.id),
                rank=inst.rank,
            )
            await user.save()

            inst.is_equipped = True
            await inst.save()

        mult = RUNE_RANK_MULTIPLIERS.get(inst.rank, 1.0)
        effective = rune["value"] * mult
        eff_str = f"{effective:.0f}" if effective == int(effective) else f"{effective:.1f}"
        await interaction.followup.send(
            embed=success_embed(
                f"Slot {slot} ({color}) → **{rune['name']} [{inst.rank}]**\n"
                f"{rune['stat'].upper()} +{eff_str} — {rune['description']}"
            ),
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
        await interaction.response.defer()
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
            old_slot = getattr(user.rune_page, COLOR_ATTR[color])[slot - 1]
            if old_slot.instance_id:
                from beanie import PydanticObjectId
                try:
                    prev = await RuneInstance.get(PydanticObjectId(old_slot.instance_id))
                    if prev:
                        prev.is_equipped = False
                        await prev.save()
                except Exception:
                    pass
            getattr(user.rune_page, COLOR_ATTR[color])[slot - 1] = RuneSlot()
            await user.save()
        await interaction.followup.send(embed=success_embed(f"Slot {slot} ({color}) cleared."))


async def setup(bot):
    await bot.add_cog(RuneCog(bot))
