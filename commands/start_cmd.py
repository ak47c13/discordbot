import discord
from discord import app_commands
from discord.ext import commands

from models.user import User
from utils.embeds import error_embed, COLOR_INFO
from utils.locks import get_user_lock
from config.game_config import STARTER_SUMMON_TOKENS, STARTER_GOLD
from utils.db_session import get_motor_client


class AlreadyRegisteredError(Exception):
    pass


async def register_user(discord_id: str, username: str) -> User:
    user = await User.find_one(User.discord_id == discord_id)
    if user and user.registered:
        raise AlreadyRegisteredError("You're already registered!")
    if not user:
        user = User(discord_id=discord_id, username=username)
    user.registered = True
    user.champion_tokens = getattr(user, "champion_tokens", 0) + STARTER_SUMMON_TOKENS
    user.gold += STARTER_GOLD
    if user.id is None:
        await user.insert()
    else:
        await user.save()
    return user


async def _do_free_pulls(discord_id: str, pool_type: str) -> list[dict]:
    from services.summon_service import _roll_summon
    client = get_motor_client()
    results = []
    async with await client.start_session() as session:
        for _ in range(10):
            r = await _roll_summon(discord_id, session, pool_type=pool_type)
            results.append(r)
    return results


def _results_to_lines(results: list[dict]) -> list[str]:
    lines = []
    for r in results:
        rtype = r.get("type", "")
        if rtype == "rune":
            lines.append(f"**{r['name']}** [{r.get('rank', 'F')}] Rune  #{r.get('display_id', '?')}")
        elif rtype == "item":
            lines.append(f"**{r['name']}** [{r.get('rank', 'F')}] {r.get('stat_type', '').upper()} Gear")
        elif rtype == "champion":
            lines.append(f"**{r['name']}** [{r.get('rank', 'F')}] Champion")
        else:
            lines.append(f"{r.get('name', '?')} [{r.get('rank', '')}]")
    return lines


def _welcome_embed(claimed: list[str]) -> discord.Embed:
    def status(key):
        return "~~Free 10x~~  ✅" if key in claimed else "**Free 10x**"

    embed = discord.Embed(
        title="⚔️ Welcome to LoLAuto RPG!",
        description=(
            "You've received **{tokens} Summon Tokens** and **{gold:,} Gold** to get started.\n\n"
            "Claim your three free 10-pulls below — each one is yours to keep!\n\n"
            "🏆 {champ}\n"
            "🔮 {rune}\n"
            "⚔️ {item}"
        ).format(
            tokens=STARTER_SUMMON_TOKENS,
            gold=STARTER_GOLD,
            champ=status("champion"),
            rune=status("rune"),
            item=status("item"),
        ),
        color=0x5865F2,
    )
    embed.add_field(
        name="Quick Start",
        value=(
            "1. Claim your pulls below\n"
            "2. `/champion-select` — pick your active champion\n"
            "3. `/dungeon-enter` — start fighting!\n"
            "4. `/skill set` — choose your combat skill (Q/W/E)"
        ),
        inline=False,
    )
    embed.set_footer(text="Champions rank F→S · Fuse 3 of the same rank to promote")
    return embed


class _StarterView(discord.ui.View):
    def __init__(self, user_id: int, discord_id: str, claimed: list[str]):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.discord_id = discord_id
        self.claimed = list(claimed)
        self._refresh_buttons()

    def _refresh_buttons(self):
        for child in list(self.children):
            self.remove_item(child)

        champ_btn = discord.ui.Button(
            label="🏆 10x Champion Pull" if "champion" not in self.claimed else "✅ Champions Claimed",
            style=discord.ButtonStyle.primary if "champion" not in self.claimed else discord.ButtonStyle.secondary,
            custom_id="starter_champion",
            disabled="champion" in self.claimed,
        )
        champ_btn.callback = self._claim_champion
        self.add_item(champ_btn)

        rune_btn = discord.ui.Button(
            label="🔮 10x Rune Pull" if "rune" not in self.claimed else "✅ Runes Claimed",
            style=discord.ButtonStyle.primary if "rune" not in self.claimed else discord.ButtonStyle.secondary,
            custom_id="starter_rune",
            disabled="rune" in self.claimed,
        )
        rune_btn.callback = self._claim_rune
        self.add_item(rune_btn)

        item_btn = discord.ui.Button(
            label="⚔️ 10x Gear Pull" if "item" not in self.claimed else "✅ Gear Claimed",
            style=discord.ButtonStyle.primary if "item" not in self.claimed else discord.ButtonStyle.secondary,
            custom_id="starter_item",
            disabled="item" in self.claimed,
        )
        item_btn.callback = self._claim_item
        self.add_item(item_btn)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("These aren't your starter pulls!", ephemeral=True)
            return False
        return True

    async def _claim(self, interaction: discord.Interaction, pool_type: str):
        # Re-check DB to prevent double-claim
        user = await User.find_one(User.discord_id == self.discord_id)
        if not user or pool_type in (user.starter_pulls_claimed or []):
            await interaction.response.send_message("Already claimed!", ephemeral=True)
            return

        await interaction.response.defer()

        try:
            results = await _do_free_pulls(self.discord_id, pool_type)
        except Exception as e:
            await interaction.followup.send(embed=error_embed(f"Pull failed: {e}"), ephemeral=True)
            return

        # Mark claimed
        user = await User.find_one(User.discord_id == self.discord_id)
        if pool_type not in user.starter_pulls_claimed:
            user.starter_pulls_claimed.append(pool_type)
            await user.save()
        self.claimed = list(user.starter_pulls_claimed)

        # Update the welcome embed + disable the button
        self._refresh_buttons()
        await interaction.message.edit(embed=_welcome_embed(self.claimed), view=self)

        # Show pull results
        lines = _results_to_lines(results)
        labels = {"champion": "🏆 Champion", "rune": "🔮 Rune", "item": "⚔️ Gear"}
        result_embed = discord.Embed(
            title=f"Free 10x {labels.get(pool_type, pool_type)} Pull Results",
            description="\n".join(f"• {l}" for l in lines),
            color=0xFFD700,
        )
        await interaction.followup.send(embed=result_embed)

    async def _claim_champion(self, interaction: discord.Interaction):
        await self._claim(interaction, "champion")

    async def _claim_rune(self, interaction: discord.Interaction):
        await self._claim(interaction, "rune")

    async def _claim_item(self, interaction: discord.Interaction):
        await self._claim(interaction, "item")


class StartCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="start", description="Register and begin your adventure!")
    async def start(self, interaction: discord.Interaction):
        await interaction.response.defer()
        uid = str(interaction.user.id)

        async with get_user_lock(uid):
            try:
                await register_user(uid, interaction.user.display_name)
            except AlreadyRegisteredError:
                await interaction.followup.send(
                    embed=error_embed("You're already registered! Use /profile to check your account."),
                    ephemeral=True,
                )
                return

        user = await User.find_one(User.discord_id == uid)
        claimed = list(user.starter_pulls_claimed) if user else []
        embed = _welcome_embed(claimed)
        view = _StarterView(interaction.user.id, uid, claimed)
        await interaction.followup.send(embed=embed, view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(StartCog(bot))
