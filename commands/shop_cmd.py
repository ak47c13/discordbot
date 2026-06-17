"""Shop command — buy summon tokens with gold, and pull champions/items/runes."""
import discord
from discord import app_commands
from discord.ext import commands

from models.user import User
from services.shop_service import ShopError, buy_token_bundle, TOKEN_BUNDLES, PULL_COSTS
from services.summon_service import summon_single, summon_multi, SummonError
from utils.embeds import (
    error_embed, success_embed, build_summon_result_embed,
    SummonRevealView, COLOR_INFO, COLOR_GOLD,
)
from utils.locks import get_user_lock
from utils.db_session import get_motor_client


# ---------------------------------------------------------------------------
# Helper: build the main shop embed
# ---------------------------------------------------------------------------

def _shop_main_embed(region_name: str, user_tokens: int, user_gold: int) -> discord.Embed:
    embed = discord.Embed(
        title="🛒 Shop",
        description=(
            f"**Weekly Champion Region:** {region_name}\n\n"
            f"💰 Gold: **{user_gold:,}** | 🎟️ Tokens: **{user_tokens}**\n\n"
            "Select a category below to browse pulls or buy tokens."
        ),
        color=COLOR_GOLD,
    )
    embed.add_field(
        name="Pull Costs",
        value="Single pull: **1 token** | 10× pull: **10 tokens**",
        inline=False,
    )
    embed.add_field(
        name="Token Bundles",
        value="\n".join(
            f"`{i}` {b['label']} — {b['gold']:,} gold → {b['tokens']} tokens"
            for i, b in enumerate(TOKEN_BUNDLES)
        ),
        inline=False,
    )
    return embed


# ---------------------------------------------------------------------------
# Category select menu
# ---------------------------------------------------------------------------

class ShopCategorySelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="⚔️ Champions",  value="champion", description="Pull champion cards"),
            discord.SelectOption(label="🎒 Items",      value="item",     description="Pull item cards"),
            discord.SelectOption(label="🔮 Runes",      value="rune",     description="Pull rune cards"),
            discord.SelectOption(label="🪙 Buy Tokens", value="tokens",   description="Exchange gold for summon tokens"),
        ]
        super().__init__(placeholder="Choose a category…", options=options)

    async def callback(self, interaction: discord.Interaction):
        view: ShopView = self.view  # type: ignore
        category = self.values[0]
        if category == "tokens":
            await view.show_token_bundles(interaction)
        else:
            await view.show_pull_panel(interaction, category)


# ---------------------------------------------------------------------------
# Pull panel (single / 10×)
# ---------------------------------------------------------------------------

class PullView(discord.ui.View):
    def __init__(self, pool_type: str, user_id: int):
        super().__init__(timeout=120)
        self.pool_type = pool_type
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your shop.", ephemeral=True)
            return False
        return True

    async def _do_pull(self, interaction: discord.Interaction, multi: bool):
        await interaction.response.defer(ephemeral=True)
        uid = str(interaction.user.id)
        lock = get_user_lock(uid)
        async with lock:
            client = get_motor_client()
            async with await client.start_session() as session:
                try:
                    if multi:
                        results = await summon_multi(uid, session, pool_type=self.pool_type)
                        view = SummonRevealView(results, interaction.user.id)
                        await interaction.followup.send(
                            embed=view.build_page_embed(), view=view, ephemeral=True
                        )
                    else:
                        result = await summon_single(uid, session, pool_type=self.pool_type)
                        embed = build_summon_result_embed(result)
                        await interaction.followup.send(embed=embed, ephemeral=True)
                except SummonError as e:
                    await interaction.followup.send(embed=error_embed(str(e)), ephemeral=True)

    @discord.ui.button(label="1× Pull (1 token)", style=discord.ButtonStyle.primary)
    async def single_pull(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._do_pull(interaction, multi=False)

    @discord.ui.button(label="10× Pull (10 tokens)", style=discord.ButtonStyle.success)
    async def multi_pull(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._do_pull(interaction, multi=True)


# ---------------------------------------------------------------------------
# Token bundle panel
# ---------------------------------------------------------------------------

class TokenBundleView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=120)
        self.user_id = user_id
        for i, bundle in enumerate(TOKEN_BUNDLES):
            btn = discord.ui.Button(
                label=f"{bundle['label']} — {bundle['gold']:,}g",
                style=discord.ButtonStyle.primary,
                custom_id=f"bundle_{i}",
                row=i // 2,
            )
            btn.callback = self._make_callback(i)
            self.add_item(btn)

    def _make_callback(self, index: int):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("This isn't your shop.", ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True)
            uid = str(interaction.user.id)
            lock = get_user_lock(uid)
            async with lock:
                client = get_motor_client()
                async with await client.start_session() as session:
                    try:
                        res = await buy_token_bundle(uid, index, session=session)
                        embed = success_embed(
                            f"Bought **{res['tokens_gained']} token(s)** for **{res['gold_spent']:,} gold**!",
                            title="🪙 Purchase Complete",
                        )
                        await interaction.followup.send(embed=embed, ephemeral=True)
                    except ShopError as e:
                        await interaction.followup.send(embed=error_embed(str(e)), ephemeral=True)
        return callback


# ---------------------------------------------------------------------------
# Main shop view (with category select)
# ---------------------------------------------------------------------------

class ShopView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.add_item(ShopCategorySelect())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your shop.", ephemeral=True)
            return False
        return True

    async def show_pull_panel(self, interaction: discord.Interaction, pool_type: str):
        label = {"champion": "⚔️ Champion", "item": "🎒 Item", "rune": "🔮 Rune"}.get(pool_type, pool_type.title())
        embed = discord.Embed(
            title=f"{label} Pulls",
            description=(
                f"Single pull costs **{PULL_COSTS[pool_type + '_single']} token**.\n"
                f"10× pull costs **{PULL_COSTS[pool_type + '_multi']} tokens**."
            ),
            color=COLOR_INFO,
        )
        # rune pulls fall back to item pool (rune summon not yet built)
        actual_pool = "item" if pool_type == "rune" else pool_type
        view = PullView(actual_pool, self.user_id)
        await interaction.response.edit_message(embed=embed, view=view)

    async def show_token_bundles(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🪙 Buy Summon Tokens",
            description="\n".join(
                f"`{i}` **{b['label']}** — {b['gold']:,} gold → {b['tokens']} token(s)"
                for i, b in enumerate(TOKEN_BUNDLES)
            ),
            color=COLOR_GOLD,
        )
        view = TokenBundleView(self.user_id)
        await interaction.response.edit_message(embed=embed, view=view)


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class ShopCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="shop", description="Open the shop to pull champions/items or buy tokens.")
    async def shop(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user = await User.get_or_create(str(interaction.user.id), interaction.user.display_name)

        from services.summon_service import get_weekly_champion_pool
        region_name, _ = get_weekly_champion_pool()

        embed = _shop_main_embed(region_name, user.summon_tokens, user.gold)
        view = ShopView(interaction.user.id)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ShopCog(bot))
