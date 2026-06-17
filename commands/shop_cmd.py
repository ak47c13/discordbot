"""Shop command — pull champions/items/runes and buy tokens with gold."""
import discord
from discord import app_commands
from discord.ext import commands

from models.user import User
from services.shop_service import ShopError, buy_token_bundle, TOKEN_BUNDLES, PULL_COSTS
from services.summon_service import (
    summon_single, summon_multi, SummonError,
    get_weekly_champion_pool, get_weekly_item_pool, get_weekly_rune_category,
)
from utils.embeds import (
    error_embed, success_embed, build_summon_result_embed,
    SummonRevealView, COLOR_INFO, COLOR_GOLD,
)
from utils.locks import get_user_lock
from utils.db_session import get_motor_client

DDRAGON_LOADING = "https://ddragon.leagueoflegends.com/cdn/img/champion/loading/{riot_id}_0.jpg"


# ---------------------------------------------------------------------------
# Panel builders
# ---------------------------------------------------------------------------

def _champion_panel_embed(user_tokens: int, user_gold: int) -> discord.Embed:
    from data.champion_regions import (
        current_region, REGION_DISPLAY_NAMES, REGION_LORE,
        CHAMPION_REGIONS, REGION_BANNER_CHAMPION,
    )
    from engine.skills import ALL_CHAMPION_NAMES

    region_key = current_region()
    region_name = REGION_DISPLAY_NAMES.get(region_key, region_key)
    lore = REGION_LORE.get(region_key, "")
    champs = [c for c in CHAMPION_REGIONS.get(region_key, []) if c in ALL_CHAMPION_NAMES]
    banner_champ = REGION_BANNER_CHAMPION.get(region_key, "Garen")

    from services.summon_service import days_until_rotation as _dur
    from data.champion_regions import days_until_rotation
    days_left = days_until_rotation()

    embed = discord.Embed(
        title=f"Champion Summon — {region_name}",
        description=f"*{lore}*",
        color=COLOR_GOLD,
    )
    embed.set_image(url=DDRAGON_LOADING.format(riot_id=banner_champ))
    embed.add_field(
        name="This Week's Champions (80% chance)",
        value=", ".join(champs) if champs else "—",
        inline=False,
    )
    embed.add_field(name="Tokens", value=str(user_tokens), inline=True)
    embed.add_field(name="Gold",   value=f"{user_gold:,}", inline=True)
    embed.add_field(name="Rotates in", value=f"{days_left:.1f} days", inline=True)
    embed.set_footer(text="1× pull = 1 token  |  10× pull = 10 tokens (+1 bonus)")
    return embed


def _item_panel_embed(user_tokens: int, user_gold: int) -> discord.Embed:
    category_name, item_pool = get_weekly_item_pool()
    items_list = ", ".join(name for name, _, _ in item_pool)
    from data.champion_regions import days_until_rotation
    days_left = days_until_rotation()

    embed = discord.Embed(
        title=f"Item Summon — {category_name}",
        description=f"This week's pool focuses on **{category_name}** — items that boost your champion's {category_name.lower()} stats.",
        color=0x4488FF,
    )
    embed.add_field(name="Items in Pool", value=items_list, inline=False)
    embed.add_field(name="Tokens", value=str(user_tokens), inline=True)
    embed.add_field(name="Gold",   value=f"{user_gold:,}", inline=True)
    embed.add_field(name="Rotates in", value=f"{days_left:.1f} days", inline=True)
    embed.add_field(name="Ranks", value="F → S (rarity determined by pull luck)", inline=False)
    embed.set_footer(text="1× pull = 1 token  |  10× pull = 10 tokens (+1 bonus)")
    return embed


def _rune_panel_embed(user_tokens: int, user_gold: int) -> discord.Embed:
    category_name, cat = get_weekly_rune_category()
    stats_list = "  ·  ".join(s.replace("_", " ").title() for s in cat["stats"])
    from data.champion_regions import days_until_rotation
    days_left = days_until_rotation()

    embed = discord.Embed(
        title=f"Rune Summon — {category_name}",
        description=cat["description"],
        color=0xAA44FF,
    )
    embed.add_field(name="Featured Stats", value=stats_list, inline=False)
    embed.add_field(name="Tokens", value=str(user_tokens), inline=True)
    embed.add_field(name="Gold",   value=f"{user_gold:,}", inline=True)
    embed.add_field(name="Rotates in", value=f"{days_left:.1f} days", inline=True)
    embed.add_field(name="Ranks", value="F → S (rarity determined by pull luck)", inline=False)
    embed.set_footer(text="1× pull = 1 token  |  10× pull = 10 tokens (+1 bonus)")
    return embed


def _token_panel_embed(user_tokens: int, user_gold: int) -> discord.Embed:
    embed = discord.Embed(
        title="Buy Summon Tokens",
        description="Exchange gold for summon tokens used across all pull categories.",
        color=COLOR_GOLD,
    )
    embed.add_field(name="Your Tokens", value=str(user_tokens), inline=True)
    embed.add_field(name="Your Gold",   value=f"{user_gold:,}", inline=True)
    embed.add_field(name="​", value="​", inline=True)
    for b in TOKEN_BUNDLES:
        embed.add_field(
            name=b["label"],
            value=f"{b['gold']:,} gold",
            inline=True,
        )
    return embed


def _shop_main_embed(user_tokens: int, user_gold: int) -> discord.Embed:
    region_name, _ = get_weekly_champion_pool()
    item_name, _   = get_weekly_item_pool()
    rune_name, _   = get_weekly_rune_category()

    embed = discord.Embed(
        title="Shop",
        description="Pick a category to view this week's pool and pull.",
        color=COLOR_GOLD,
    )
    embed.add_field(name="Tokens", value=str(user_tokens), inline=True)
    embed.add_field(name="Gold",   value=f"{user_gold:,}", inline=True)
    embed.add_field(name="​", value="​", inline=True)
    embed.add_field(name="Champions", value=f"Region: **{region_name}**", inline=True)
    embed.add_field(name="Items",     value=f"Category: **{item_name}**",  inline=True)
    embed.add_field(name="Runes",     value=f"Path: **{rune_name}**",      inline=True)
    embed.set_footer(text="1× = 1 token  |  10× = 10 tokens (+1 bonus pull)  |  500g = 1 token")
    return embed


# ---------------------------------------------------------------------------
# Pull view (shared across all categories)
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
        async with get_user_lock(uid):
            client = get_motor_client()
            async with await client.start_session() as session:
                try:
                    if multi:
                        results = await summon_multi(uid, session, pool_type=self.pool_type)
                        view = SummonRevealView(results, interaction.user.id)
                        await interaction.followup.send(embed=view.build_page_embed(), view=view, ephemeral=True)
                    else:
                        result = await summon_single(uid, session, pool_type=self.pool_type)
                        embed = build_summon_result_embed(result)
                        await interaction.followup.send(embed=embed, ephemeral=True)
                except SummonError as e:
                    await interaction.followup.send(embed=error_embed(str(e)), ephemeral=True)

    @discord.ui.button(label="1× Pull (1 token)", style=discord.ButtonStyle.primary)
    async def single_pull(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._do_pull(interaction, multi=False)

    @discord.ui.button(label="10× Pull — 10 tokens (+1 bonus)", style=discord.ButtonStyle.success)
    async def multi_pull(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._do_pull(interaction, multi=True)

    @discord.ui.button(label="Back to Shop", style=discord.ButtonStyle.secondary)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = await User.get_or_create(str(interaction.user.id), interaction.user.display_name)
        embed = _shop_main_embed(user.summon_tokens, user.gold)
        view = ShopView(interaction.user.id)
        await interaction.response.edit_message(embed=embed, view=view)


# ---------------------------------------------------------------------------
# Token bundle view
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
            )
            btn.callback = self._make_callback(i)
            self.add_item(btn)

        back = discord.ui.Button(label="Back to Shop", style=discord.ButtonStyle.secondary)
        async def _back(interaction: discord.Interaction):
            user = await User.get_or_create(str(interaction.user.id), interaction.user.display_name)
            await interaction.response.edit_message(
                embed=_shop_main_embed(user.summon_tokens, user.gold),
                view=ShopView(interaction.user.id),
            )
        back.callback = _back
        self.add_item(back)

    def _make_callback(self, index: int):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("This isn't your shop.", ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True)
            uid = str(interaction.user.id)
            async with get_user_lock(uid):
                client = get_motor_client()
                async with await client.start_session() as session:
                    try:
                        res = await buy_token_bundle(uid, index, session=session)
                        embed = success_embed(
                            f"Bought **{res['tokens_gained']} token(s)** for **{res['gold_spent']:,} gold**!",
                            title="Purchase Complete",
                        )
                        await interaction.followup.send(embed=embed, ephemeral=True)
                    except ShopError as e:
                        await interaction.followup.send(embed=error_embed(str(e)), ephemeral=True)
        return callback


# ---------------------------------------------------------------------------
# Main shop view
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


class ShopCategorySelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Champions", value="champion", description="Region-of-the-week champion pulls"),
            discord.SelectOption(label="Items",     value="item",     description="Category-of-the-week item pulls"),
            discord.SelectOption(label="Runes",     value="rune",     description="Path-of-the-week rune pulls"),
            discord.SelectOption(label="Buy Tokens", value="tokens",  description="Exchange gold for summon tokens"),
        ]
        super().__init__(placeholder="Choose a category…", options=options)

    async def callback(self, interaction: discord.Interaction):
        view: ShopView = self.view  # type: ignore
        uid = str(interaction.user.id)
        user = await User.get_or_create(uid, interaction.user.display_name)
        category = self.values[0]

        if category == "champion":
            embed = _champion_panel_embed(user.summon_tokens, user.gold)
            pull_view = PullView("champion", interaction.user.id)
            await interaction.response.edit_message(embed=embed, view=pull_view)
        elif category == "item":
            embed = _item_panel_embed(user.summon_tokens, user.gold)
            pull_view = PullView("item", interaction.user.id)
            await interaction.response.edit_message(embed=embed, view=pull_view)
        elif category == "rune":
            embed = _rune_panel_embed(user.summon_tokens, user.gold)
            pull_view = PullView("rune", interaction.user.id)
            await interaction.response.edit_message(embed=embed, view=pull_view)
        else:
            embed = _token_panel_embed(user.summon_tokens, user.gold)
            await interaction.response.edit_message(embed=embed, view=TokenBundleView(interaction.user.id))


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class ShopCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="shop", description="Open the shop — pull champions, items, and runes.")
    async def shop(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user = await User.get_or_create(str(interaction.user.id), interaction.user.display_name)
        embed = _shop_main_embed(user.summon_tokens, user.gold)
        view = ShopView(interaction.user.id)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ShopCog(bot))
