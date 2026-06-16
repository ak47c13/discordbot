import discord
from discord import app_commands
from discord.ext import commands

from models.user import User
from models.champion import ChampionInstance
from models.item import ItemInstance
from models.team import Team
from utils.embeds import (
    champion_embed, item_embed, error_embed, success_embed,
    get_champion_by_number, get_item_by_number, COLOR_INFO,
)
from utils.locks import get_user_lock
from config.game_config import TEAM_SIZE
from utils.image_gen import generate_team_banner


class TeamCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="team", description="View your current team formation.")
    async def team_view(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await User.get_or_create(str(interaction.user.id), interaction.user.display_name)
        team = await Team.get_or_create(str(interaction.user.id))

        embed = discord.Embed(title="⚔️ Your Team Formation", color=COLOR_INFO)

        # Resolve all slots
        slot_data = []
        team_champs = []
        for idx, slot_id in enumerate(team.slots):
            if slot_id is None:
                slot_data.append(None)
            else:
                champ = await ChampionInstance.get(slot_id)
                slot_data.append(champ)
                if champ:
                    team_champs.append({
                        "name": champ.name,
                        "rank": champ.rank,
                        "level": champ.level,
                        "riot_id": champ.riot_id or "",
                    })

        # Front row (slots 1-2): DEF bonus
        front_lines = []
        for i in range(2):
            champ = slot_data[i] if i < len(slot_data) else None
            if champ:
                front_lines.append(f"**{i+1}.** {champ.name} [{champ.rank}] Lv.{champ.level}")
            else:
                front_lines.append(f"**{i+1}.** *— Empty —*")
        embed.add_field(
            name="🛡️ Front Row — DEF +10%",
            value="\n".join(front_lines),
            inline=False,
        )

        # Back row (slots 3-5): ATK bonus
        back_lines = []
        for i in range(2, 5):
            champ = slot_data[i] if i < len(slot_data) else None
            if champ:
                back_lines.append(f"**{i+1}.** {champ.name} [{champ.rank}] Lv.{champ.level}")
            else:
                back_lines.append(f"**{i+1}.** *— Empty —*")
        embed.add_field(
            name="⚔️ Back Row — ATK +5%",
            value="\n".join(back_lines),
            inline=False,
        )

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

    @app_commands.command(name="team-add", description="Add a champion to your team by slot (1-5).")
    @app_commands.describe(number="Champion list number (see /champions)", slot="Formation slot 1-5")
    async def team_add(self, interaction: discord.Interaction, number: int, slot: int):
        await interaction.response.defer(ephemeral=True)
        if not 1 <= slot <= TEAM_SIZE:
            await interaction.followup.send(embed=error_embed("Slot must be 1–5."), ephemeral=True)
            return

        uid = str(interaction.user.id)
        async with get_user_lock(uid):
            champ = await get_champion_by_number(uid, number)
            if champ is None or champ.owner_id != uid:
                await interaction.followup.send(embed=error_embed("Champion not found."), ephemeral=True)
                return
            champion_id = str(champ.id)
            if champ.in_trade or champ.in_market:
                await interaction.followup.send(embed=error_embed("Champion is in a trade or market listing."), ephemeral=True)
                return

            team = await Team.get_or_create(uid)

            # Remove champion from any existing slot first
            for i, s in enumerate(team.slots):
                if s == champion_id:
                    old_champ = await ChampionInstance.get(s)
                    if old_champ:
                        old_champ.equipped_in_team = None
                        old_champ.formation_slot = None
                        await old_champ.save()
                    team.slots[i] = None

            # Remove whoever is in target slot
            existing_id = team.slots[slot - 1]
            if existing_id:
                old = await ChampionInstance.get(existing_id)
                if old:
                    old.equipped_in_team = None
                    old.formation_slot = None
                    await old.save()

            team.slots[slot - 1] = champion_id
            champ.equipped_in_team = str(team.id)
            champ.formation_slot = slot
            await champ.save()
            await team.save()

        await interaction.followup.send(
            embed=success_embed(f"{champ.name} [{champ.rank}] placed in slot {slot}."),
            ephemeral=True,
        )

    @app_commands.command(name="team-remove", description="Remove a champion from your team by slot.")
    @app_commands.describe(slot="Formation slot 1-5")
    async def team_remove(self, interaction: discord.Interaction, slot: int):
        await interaction.response.defer(ephemeral=True)
        if not 1 <= slot <= TEAM_SIZE:
            await interaction.followup.send(embed=error_embed("Slot must be 1–5."), ephemeral=True)
            return

        uid = str(interaction.user.id)
        async with get_user_lock(uid):
            team = await Team.get_or_create(uid)
            existing_id = team.slots[slot - 1]
            if not existing_id:
                await interaction.followup.send(embed=error_embed("Slot is already empty."), ephemeral=True)
                return

            champ = await ChampionInstance.get(existing_id)
            if champ:
                champ.equipped_in_team = None
                champ.formation_slot = None
                await champ.save()

            team.slots[slot - 1] = None
            await team.save()

        await interaction.followup.send(
            embed=success_embed(f"Slot {slot} cleared."),
            ephemeral=True,
        )

    formation = app_commands.Group(name="formation", description="Manage your team formation positions.")

    @formation.command(name="view", description="Show your current 5-slot formation.")
    async def formation_view(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        await User.get_or_create(uid, interaction.user.display_name)
        team = await Team.get_or_create(uid)

        embed = discord.Embed(title="🛡️ Formation", color=COLOR_INFO)
        for idx, slot in enumerate(team.slots):
            pos = idx + 1
            row = "Front (DEF +10%)" if pos <= 2 else "Back (ATK +5%)"
            if slot is None:
                embed.add_field(name=f"Slot {pos} — {row}", value="*Empty*", inline=False)
            else:
                champ = await ChampionInstance.get(slot)
                label = f"**{champ.name}** [{champ.rank}] Lv.{champ.level}" if champ else "*Missing*"
                embed.add_field(name=f"Slot {pos} — {row}", value=label, inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @formation.command(name="set", description="Move a champion in your team to a specific slot (1-5).")
    @app_commands.describe(slot="Target slot 1-5", number="Champion list number (see /champions)")
    async def formation_set(self, interaction: discord.Interaction, slot: int, number: int):
        await interaction.response.defer(ephemeral=True)
        if not 1 <= slot <= TEAM_SIZE:
            await interaction.followup.send(embed=error_embed("Slot must be 1–5."), ephemeral=True)
            return

        uid = str(interaction.user.id)
        async with get_user_lock(uid):
            champ = await get_champion_by_number(uid, number)
            if champ is None or champ.owner_id != uid:
                await interaction.followup.send(embed=error_embed("Champion not found."), ephemeral=True)
                return
            champion_id = str(champ.id)

            team = await Team.get_or_create(uid)
            if champion_id not in team.slots:
                await interaction.followup.send(
                    embed=error_embed("That champion is not in your team. Use /team-add first."),
                    ephemeral=True,
                )
                return

            cur_idx = team.slots.index(champion_id)
            target_idx = slot - 1

            # Swap whatever is in the target slot with the champion's current slot.
            occupant_id = team.slots[target_idx]
            team.slots[target_idx] = champion_id
            team.slots[cur_idx] = occupant_id

            champ.formation_slot = slot
            await champ.save()
            if occupant_id:
                occ = await ChampionInstance.get(occupant_id)
                if occ:
                    occ.formation_slot = cur_idx + 1
                    await occ.save()
            await team.save()

        await interaction.followup.send(
            embed=success_embed(f"{champ.name} moved to slot {slot}."),
            ephemeral=True,
        )

    @app_commands.command(name="equip", description="Equip an item to a champion.")
    @app_commands.describe(item_number="Item list number (see /items)", champion_number="Champion list number (see /champions)", slot="Equipment slot 1-5")
    async def equip(self, interaction: discord.Interaction, item_number: int, champion_number: int, slot: int):
        await interaction.response.defer(ephemeral=True)
        if not 1 <= slot <= 5:
            await interaction.followup.send(embed=error_embed("Equipment slot must be 1–5."), ephemeral=True)
            return

        uid = str(interaction.user.id)
        async with get_user_lock(uid):
            itm = await get_item_by_number(uid, item_number)
            if itm is None or itm.owner_id != uid:
                await interaction.followup.send(embed=error_embed("Item not found or not owned by you."), ephemeral=True)
                return
            if itm.in_trade or itm.in_market:
                await interaction.followup.send(embed=error_embed("Item is in a trade or listing."), ephemeral=True)
                return

            champ = await get_champion_by_number(uid, champion_number)
            if champ is None or champ.owner_id != uid:
                await interaction.followup.send(embed=error_embed("Champion not found."), ephemeral=True)
                return
            champion_id = str(champ.id)

            # Check champion doesn't already have 5 items in that slot
            existing_in_slot = await ItemInstance.find_one(
                ItemInstance.equipped_to == champion_id,
                ItemInstance.equipment_slot == slot,
            )
            if existing_in_slot:
                # Unequip existing
                existing_in_slot.equipped_to = None
                existing_in_slot.equipment_slot = None
                await existing_in_slot.save()

            # Count total items on champion
            item_count = await ItemInstance.find(
                ItemInstance.equipped_to == champion_id
            ).count()
            if item_count >= 5 and not existing_in_slot:
                await interaction.followup.send(embed=error_embed("Champion already has 5 items equipped."), ephemeral=True)
                return

            # Unequip item from previous champion if needed
            if itm.equipped_to:
                itm.equipped_to = None
                itm.equipment_slot = None

            itm.equipped_to = champion_id
            itm.equipment_slot = slot
            await itm.save()

        await interaction.followup.send(
            embed=success_embed(f"{itm.name} +{itm.enhancement} equipped to {champ.name} in slot {slot}."),
            ephemeral=True,
        )

    @app_commands.command(name="unequip", description="Unequip an item from a champion.")
    @app_commands.describe(item_number="Item list number (see /items)")
    async def unequip(self, interaction: discord.Interaction, item_number: int):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        async with get_user_lock(uid):
            itm = await get_item_by_number(uid, item_number)
            if itm is None or itm.owner_id != uid:
                await interaction.followup.send(embed=error_embed("Item not found."), ephemeral=True)
                return
            if not itm.equipped_to:
                await interaction.followup.send(embed=error_embed("Item is not equipped."), ephemeral=True)
                return
            itm.equipped_to = None
            itm.equipment_slot = None
            await itm.save()

        await interaction.followup.send(
            embed=success_embed(f"{itm.name} unequipped."),
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(TeamCog(bot))
