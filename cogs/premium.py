import discord
import secrets
import time
import datetime
import stripe
import aiohttp
import asyncio
import traceback
from aiohttp import web
from discord.ext import commands, tasks
from discord import app_commands
from bot import Cyori
from utils import config as ui_config

# Stripe Configuration
# Price is in THB cents (e.g. 5000 = 50.00 THB)
PREMIUM_PLANS = {
    "1_month": {
        "name": "Premium (1 Month)",
        "days": 30,
        "price": 2900,  # 29 THB
        "description": "Premium access for 1 month. Saving 0 THB.",
    },
    "3_months": {
        "name": "Premium (3 Months)",
        "days": 90,
        "price": 7900,  # 79 THB
        "description": "Premium access for 3 months. Saving 8 THB.",
    },
    "6_months": {
        "name": "Premium (6 Months)",
        "days": 180,
        "price": 14900,  # 149 THB
        "description": "Premium access for 6 months. Saving 25 THB.",
    },
    "1_year": {
        "name": "Premium (1 Year)",
        "days": 365,
        "price": 28900,  # 289 THB
        "description": "Premium access for 1 year. Saving 59 THB.",
    },
    "lifetime": {
        "name": "Premium (Lifetime)",
        "days": 36500,  # ~100 years
        "price": 78900,  # 789 THB
        "description": "Lifetime access to all Premium features. Best value!",
    },
}


class RenewalView(discord.ui.View):
    def __init__(self, bot, user_id):
        super().__init__(timeout=None)
        self.bot = bot
        self.user_id = user_id

    @discord.ui.button(
        label="Renew Premium / ต่ออายุ", style=discord.ButtonStyle.green, emoji="💎"
    )
    async def renew_callback(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        premium_cog = self.bot.get_cog("Premium")
        if not premium_cog:
            return await interaction.response.send_message(
                "❌ Premium system unavailable.", ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)

        # Determine plan to renew
        user_data = await self.bot.db_manager.get_user(self.user_id)
        plan_id = user_data.get(
            "premium_plan_id", "1_month"
        )  # Default to 1 month if unknown

        try:
            url = await premium_cog.create_checkout_link(interaction.user, plan_id)

            # Create a simple view with the link
            view = discord.ui.View()
            view.add_item(
                discord.ui.Button(
                    label="Pay Now / จ่ายเงิน", url=url, style=discord.ButtonStyle.url
                )
            )

            await interaction.followup.send(
                f"Renewing **{plan_id}** plan:", view=view, ephemeral=True
            )

        except Exception as e:
            await interaction.followup.send(
                f"❌ Error generating link: {e}", ephemeral=True
            )


class Premium(commands.Cog):
    def __init__(self, bot: Cyori):
        self.bot = bot
        self.webhook_secret = ui_config.STRIPE_WEBHOOK_SECRET

        if ui_config.STRIPE_API_KEY:
            stripe.api_key = ui_config.STRIPE_API_KEY.strip()

        # Register Webhook Route
        if self.bot.web_app:
            has_route = False
            for route in self.bot.web_app.router.routes():
                if route.method == "POST" and (
                    hasattr(route.resource, "canonical")
                    and route.resource.canonical == "/stripe/webhook"
                ):
                    has_route = True
                    break

            if not has_route:
                self.bot.web_app.router.add_post("/stripe/webhook", self.stripe_webhook)

        self.check_premium_expiry.start()

    async def cog_load(self):
        # Trigger Auto-Setup if needed
        if not self.webhook_secret and ui_config.STRIPE_API_KEY:
            self.bot.loop.create_task(self.auto_setup_webhook())

    def cog_unload(self):
        self.check_premium_expiry.cancel()

    # =========================================================================
    # WEBHOOK & PAYMENT LOGIC
    # =========================================================================

    async def auto_setup_webhook(self):
        try:
            if ui_config.STRIPE_PROXY_URL:
                target_url = ui_config.STRIPE_PROXY_URL
            else:
                target_url = f"{ui_config.DOMAIN_URL}/stripe/webhook"

            if (
                "http://" in target_url
                and "localhost" not in target_url
                and "127.0.0.1" not in target_url
            ):
                return

            endpoints = stripe.WebhookEndpoint.list(limit=16)
            for ep in endpoints.data:
                if ep.url == target_url:
                    stripe.WebhookEndpoint.delete(ep.id)

            new_ep = stripe.WebhookEndpoint.create(
                url=target_url,
                enabled_events=["checkout.session.completed"],
            )
            self.webhook_secret = new_ep.secret
            print(f"✅ Stripe Webhook synced: {new_ep.id}")
        except Exception as e:
            print(f"❌ Stripe Auto-Sync Failed: {e}")

    async def stripe_webhook(self, request: web.Request):
        payload = await request.text()
        if self.webhook_secret and "Stripe-Signature" in request.headers:
            sig_header = request.headers.get("Stripe-Signature")
            try:
                event = stripe.Webhook.construct_event(
                    payload, sig_header, self.webhook_secret
                )
            except Exception:
                return web.Response(status=400)
        else:
            try:
                event = await request.json()
            except Exception:
                return web.Response(status=400)

        if event["type"] == "checkout.session.completed":
            session = event["data"]["object"]
            await self.handle_checkout_success(session)

        return web.Response(status=200)

    async def handle_checkout_success(self, session):
        metadata = session.get("metadata", {})
        user_id = metadata.get("user_id")
        days = int(metadata.get("days", 0))
        plan_name = metadata.get("plan_name", "Premium")

        if not user_id:
            return

        try:
            user_id = str(user_id)
            user_data = await self.bot.db_manager.get_user(user_id)
            current_expire = user_data.get("premium_expire", 0)

            if days >= 36500:
                await self.bot.db_manager.update_user(
                    user_id,
                    {
                        "premium": True,
                        "premium_plan": plan_name,
                        "premium_plan_id": metadata.get("plan_id", "lifetime"),
                    },
                )
            else:
                now = time.time()
                start_time = max(current_expire, now)
                new_expire = start_time + (days * 24 * 3600)
                await self.bot.db_manager.update_user(
                    user_id,
                    {
                        "premium_expire": new_expire,
                        "premium_plan": plan_name,
                        "premium_plan_id": metadata.get("plan_id", "1_month"),
                    },
                )

            try:
                user = await self.bot.fetch_user(int(user_id))
                lang = "en"
                embed = discord.Embed(
                    title=self.bot.i18n.get("payment_success_title", lang),
                    description=self.bot.i18n.get(
                        "payment_success_desc", lang, plan_name=plan_name
                    ),
                    color=ui_config.SUCCESS_COLOR,
                )
                await user.send(embed=embed)
            except Exception:
                pass
        except Exception as e:
            print(f"❌ Payment handling error: {e}")

    async def create_checkout_link(self, user, plan_id):
        selected_plan = PREMIUM_PLANS.get(plan_id)
        if not selected_plan:
            raise ValueError("Invalid plan")

        checkout_session = stripe.checkout.Session.create(
            payment_method_types=["card", "promptpay"],
            line_items=[
                {
                    "price_data": {
                        "currency": "thb",
                        "product_data": {
                            "name": selected_plan["name"],
                            "description": selected_plan["description"],
                        },
                        "unit_amount": selected_plan["price"],
                    },
                    "quantity": 1,
                }
            ],
            metadata={
                "user_id": str(user.id),
                "plan_id": plan_id,
                "days": str(selected_plan["days"]),
                "plan_name": selected_plan["name"],
            },
            mode="payment",
            success_url=ui_config.STRIPE_SUCCESS_URL,
            cancel_url=ui_config.STRIPE_CANCEL_URL,
        )
        return checkout_session.url

    # =========================================================================
    # EXPIRY LOGIC
    # =========================================================================

    @tasks.loop(minutes=5)
    async def check_premium_expiry(self):
        try:
            data = await self.bot.db_manager._fetch_root()
            users_data = data.get("users", {})
            now = time.time()
            updates = {}
            for uid_str, u_data in users_data.items():
                expire = u_data.get("premium_expire")
                if expire and isinstance(expire, (int, float)) and now > expire:
                    try:
                        user = await self.bot.fetch_user(int(uid_str))
                        if user:
                            view = RenewalView(self.bot, uid_str)
                            lang = "en"
                            embed = discord.Embed(
                                title="⚠️ Premium Expired / พรีเมียมหมดอายุ",
                                description=self.bot.i18n.get(
                                    "premium_expired_msg", lang
                                ),
                                color=ui_config.ERROR_COLOR,
                            )
                            await user.send(embed=embed, view=view)
                    except Exception:
                        pass

                    try:
                        from bot import SOURCE_GUILD_ID, SYNC_ROLE_ID

                        for guild in self.bot.guilds:
                            if guild.id == SOURCE_GUILD_ID:
                                continue
                            role = guild.get_role(SYNC_ROLE_ID)
                            if not role:
                                continue
                            member = guild.get_member(
                                int(uid_str)
                            ) or await guild.fetch_member(int(uid_str))
                            if member and role in member.roles:
                                await member.remove_roles(
                                    role, reason="Premium Expired"
                                )
                    except Exception:
                        pass
                    updates[f"users.{uid_str}.premium_expire"] = ""
                    updates[f"users.{uid_str}.premium"] = ""
            if updates:
                await self.bot.db_manager.collection.update_one({}, {"$unset": updates})
                await self.bot.db_manager.invalidate_cache()
        except Exception:
            pass

    @check_premium_expiry.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    async def _update_controller_if_playing(self, guild_id: int):
        player = None
        for p in self.bot.voice_clients:
            if p.guild.id == guild_id:
                player = p
                break
        if player and player.is_playing and hasattr(player, "update_controller"):
            try:
                await player.update_controller()
            except Exception:
                pass
        try:
            guild_data = await self.bot.db_manager.get_guild(guild_id)
            await self.bot.update_guild_embed(guild_data, guild_id=guild_id)
        except Exception:
            pass

    # =========================================================================
    # PREMIUM HYBRID GROUP
    # =========================================================================

    @commands.hybrid_group(
        name="premium", description="Premium System Commands / คำสั่งระบบพรีเมียม"
    )
    async def premium_group(self, ctx: commands.Context):
        """Main group for premium commands."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @premium_group.command(
        name="buy", description="Buy Premium via Stripe / ซื้อพรีเมียม"
    )
    @app_commands.describe(plan="Select a premium plan / เลือกแผนพรีเมียม")
    @app_commands.choices(
        plan=[
            app_commands.Choice(name="1 Month - 29 THB (Save 0)", value="1_month"),
            app_commands.Choice(name="3 Months - 79 THB (Save 8)", value="3_months"),
            app_commands.Choice(name="6 Months - 149 THB (Save 25)", value="6_months"),
            app_commands.Choice(name="1 Year - 289 THB (Save 59)", value="1_year"),
            app_commands.Choice(
                name="Lifetime - 789 THB (Best Value!)", value="lifetime"
            ),
        ]
    )
    async def buy(self, ctx: commands.Context, plan: str):
        if not ui_config.STRIPE_API_KEY:
            return await ctx.send(
                "❌ Payment system is not configured.", ephemeral=True
            )

        selected_plan = PREMIUM_PLANS.get(plan)
        if not selected_plan:
            return await ctx.send("❌ Invalid plan selected.", ephemeral=True)

        await ctx.defer(ephemeral=True)

        try:
            url = await self.create_checkout_link(ctx.author, plan)
            lang = await self.bot.get_lang(ctx.guild.id) if ctx.guild else "en"

            embed = discord.Embed(
                title=self.bot.i18n.get("payment_title", lang),
                description=self.bot.i18n.get(
                    "payment_desc", lang, plan_name=selected_plan["name"]
                ),
                color=ui_config.EMBED_COLOR,
            )
            embed.add_field(
                name=self.bot.i18n.get("payment_price", lang),
                value=f"{selected_plan['price'] / 100:.2f} THB",
                inline=True,
            )

            view = discord.ui.View()
            view.add_item(
                discord.ui.Button(
                    label=self.bot.i18n.get("payment_button", lang),
                    url=url,
                    style=discord.ButtonStyle.url,
                )
            )

            await ctx.send(embed=embed, view=view, ephemeral=True)
        except Exception as e:
            await ctx.send(f"❌ Error creating checkout: {e}", ephemeral=True)

    @premium_group.command(
        name="redeem", description="Redeem a Premium Key / เติมพรีเมียมด้วยคีย์"
    )
    async def redeem(self, ctx: commands.Context, key: str):
        await ctx.defer()
        lang = await self.bot.get_lang(ctx.guild.id) if ctx.guild else "en"
        key = key.strip().upper()
        data = await self.bot.db_manager._fetch_root()
        keys = data.get("premium_keys", {})
        if key not in keys:
            return await ctx.send(
                self.bot.i18n.get("premium_redeem_invalid", lang), ephemeral=True
            )

        days = keys[key]
        user_id = str(ctx.author.id)
        current_expire = data.get("users", {}).get(user_id, {}).get("premium_expire", 0)
        now = time.time()
        new_expire = max(current_expire, now) + (days * 24 * 3600)

        await self.bot.db_manager.collection.update_one(
            {},
            {
                "$set": {
                    f"users.{user_id}.premium_expire": new_expire,
                    f"users.{user_id}.premium_plan": f"{days} Days",
                },
                "$unset": {f"premium_keys.{key}": ""},
            },
        )
        await self.bot.db_manager.invalidate_cache()

        expire_str = datetime.datetime.fromtimestamp(new_expire).strftime(
            "%d/%m/%Y %H:%M"
        )
        await ctx.send(
            self.bot.i18n.get(
                "premium_redeem_success", lang, days=days, expire=expire_str
            )
        )
        if ctx.guild:
            await self._update_controller_if_playing(ctx.guild.id)

    @premium_group.command(
        name="status", description="Check your premium status / ตรวจสอบพรีเมียมของคุณ"
    )
    async def premium_status(self, ctx: commands.Context, user: discord.User = None):
        user = user or ctx.author
        u_info = await self.bot.db_manager.get_user(user.id)
        is_lifetime = u_info.get("premium", False)
        expire = u_info.get("premium_expire", 0)
        now = time.time()

        status = "Inactive ❌"
        expire_str = "N/A"
        if is_lifetime:
            status = "Lifetime ✅"
            expire_str = "Never"
        elif expire > now:
            status = "Active ✅"
            expire_str = datetime.datetime.fromtimestamp(expire).strftime(
                "%d/%m/%Y %H:%M"
            )

        embed = discord.Embed(title="Premium Status", color=ui_config.EMBED_COLOR)
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="User", value=user.mention)
        embed.add_field(name="Status", value=status)
        embed.add_field(name="Expires", value=expire_str)
        await ctx.send(embed=embed)

    # --- Owner Subcommands ---

    @premium_group.command(name="genkey")
    @commands.is_owner()
    async def genkey(self, ctx: commands.Context, days: int = 30, count: int = 1):
        lang = await self.bot.get_lang(ctx.guild.id) if ctx.guild else "en"
        new_keys = {}
        generated = []
        for _ in range(count):
            key = f"{secrets.token_hex(2)}-{secrets.token_hex(2)}-{secrets.token_hex(2)}".upper()
            new_keys[f"premium_keys.{key}"] = days
            generated.append(key)
        await self.bot.db_manager.collection.update_one(
            {}, {"$set": new_keys}, upsert=True
        )
        await self.bot.db_manager.invalidate_cache()
        msg = f"Generated {count} keys ({days} days):\n" + "\n".join(
            [f"`{k}`" for k in generated]
        )
        try:
            await ctx.author.send(msg)
            await ctx.send("✅ Sent keys to DM.")
        except Exception:
            await ctx.send(msg)

    @premium_group.command(name="stats")
    @commands.is_owner()
    async def premium_stats_cmd(self, ctx: commands.Context):
        data = await self.bot.db_manager._fetch_root()
        users = data.get("users", {})
        now = time.time()
        total = 0
        life = 0
        for u in users.values():
            if u.get("premium"):
                life += 1
                total += 1
            elif u.get("premium_expire", 0) > now:
                total += 1
        embed = discord.Embed(title="Premium Stats", color=ui_config.EMBED_COLOR)
        embed.add_field(name="Total Users", value=total)
        embed.add_field(name="Lifetime", value=life)
        await ctx.send(embed=embed)

    @premium_group.command(name="add")
    @commands.is_owner()
    async def premium_add_cmd(self, ctx: commands.Context, user_id: str):
        try:
            uid = int(user_id)
            await self.bot.db_manager.update_user(
                uid, {"premium": True, "premium_plan": "Lifetime"}
            )
            await ctx.send(f"✅ Added Lifetime Premium to `{uid}`")
        except Exception:
            await ctx.send("Invalid ID")

    @premium_group.command(name="remove")
    @commands.is_owner()
    async def premium_remove_cmd(self, ctx: commands.Context, user_id: str):
        try:
            uid = int(user_id)
            await self.bot.db_manager.collection.update_one(
                {},
                {
                    "$unset": {
                        f"users.{uid}.premium": "",
                        f"users.{uid}.premium_expire": "",
                    }
                },
            )
            await self.bot.db_manager.invalidate_cache()
            await ctx.send(f"❌ Removed Premium from `{uid}`")
        except Exception:
            await ctx.send("Invalid ID")

    # Branding remains standalone or move it too? Let's keep it hybrid command as requested.
    @commands.hybrid_command(
        name="branding", description="Customize Bot Theme / ปรับแต่งธีมบอท"
    )
    async def branding(
        self,
        ctx: commands.Context,
        nickname: str = None,
        color: str = None,
        banner: discord.Attachment = None,
        image: discord.Attachment = None,
        reset: bool = False,
    ):
        lang = await self.bot.get_lang(ctx.guild.id) if ctx.guild else "en"
        if ctx.author.id != ctx.guild.owner_id and not await self.bot.is_owner(
            ctx.author
        ):
            return await ctx.send(
                self.bot.i18n.get("premium_only_owner", lang), ephemeral=True
            )
        if not await self.bot.is_premium(ctx.author.id, guild_id=ctx.guild.id):
            return await ctx.send(
                self.bot.i18n.get("premium_only_feature", lang), ephemeral=True
            )

        await ctx.defer()
        guild_id = ctx.guild.id
        if reset:
            await self.bot.db_manager.collection.update_one(
                {},
                {
                    "$unset": {
                        f"guilds.{guild_id}.premium_image": "",
                        f"guilds.{guild_id}.premium_banner": "",
                        f"guilds.{guild_id}.color": "",
                    }
                },
            )
            await self.bot.db_manager.invalidate_cache()
            return await ctx.send("✅ Reset customization.")

        sets = {}
        if color and color.startswith("#"):
            sets[f"guilds.{guild_id}.color"] = int(color.lstrip("#"), 16)
        if banner:
            sets[f"guilds.{guild_id}.premium_banner"] = banner.url
        if image:
            sets[f"guilds.{guild_id}.premium_image"] = image.url

        if nickname:
            try:
                await ctx.guild.me.edit(nick=nickname)
            except Exception:
                pass

        if sets:
            await self.bot.db_manager.collection.update_one(
                {}, {"$set": sets}, upsert=True
            )
            await self.bot.db_manager.invalidate_cache()
        await ctx.send("✅ Branding updated.")
        await self._update_controller_if_playing(guild_id)


async def setup(bot: Cyori):
    await bot.add_cog(Premium(bot))
