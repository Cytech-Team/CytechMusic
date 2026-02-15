import discord
from discord.ext import commands
from discord import app_commands
import stripe
import time
import datetime
import aiohttp
from aiohttp import web
import asyncio # Added asyncio
from bot import Cyori, collection_myasync
from utils import config as ui_config

# Stripe Configuration
# Price is in THB cents (e.g. 5000 = 50.00 THB)
# You can adjust these prices
PREMIUM_PLANS = {
    "1_month": {
        "name": "Premium (1 Month)",
        "days": 30,
        "price": 2900,  # 29 THB
        "description": "Premium access for 1 month. Saving 0 THB."
    },
    "3_months": {
        "name": "Premium (3 Months)",
        "days": 90,
        "price": 7900, # 79 THB
        "description": "Premium access for 3 months. Saving 8 THB."
    },
    "6_months": {
        "name": "Premium (6 Months)",
        "days": 180,
        "price": 14900, # 149 THB
        "description": "Premium access for 6 months. Saving 25 THB."
    },
    "1_year": {
        "name": "Premium (1 Year)",
        "days": 365, 
        "price": 28900, # 289 THB
        "description": "Premium access for 1 year. Saving 59 THB."
    },
    "lifetime": {
        "name": "Premium (Lifetime)",
        "days": 36500, # ~100 years
        "price": 78900, # 789 THB
        "description": "Lifetime access to all Premium features. Best value!"
    }
}

class Payment(commands.Cog):
    def __init__(self, bot: Cyori):
        self.bot = bot
        self.webhook_secret = ui_config.STRIPE_WEBHOOK_SECRET
        
        if ui_config.STRIPE_API_KEY:
            stripe.api_key = ui_config.STRIPE_API_KEY.strip()
        
        from utils.config import DEPRECATED_MODE
        if DEPRECATED_MODE:
             return

        # Log Initial Status
        if self.webhook_secret:
            print("✅ Payment System: Manual Secret Loaded (Secure Mode)")
        else:
            print("⏳ Payment System: Initializing Auto-Sync Webhook...")

        # Register Webhook Route
        # Register Webhook Route
        if self.bot.web_app:
            # Check for existing route to prevent RuntimeError on reload
            has_route = False
            for route in self.bot.web_app.router.routes():
                if route.method == "POST" and route.resource.canonical == "/stripe/webhook":
                     has_route = True
                     break
            
            if not has_route:
                self.bot.web_app.router.add_post('/stripe/webhook', self.stripe_webhook)

    async def cog_load(self):
        # Trigger Auto-Setup if needed
        if not self.webhook_secret and ui_config.STRIPE_API_KEY:
             self.bot.loop.create_task(self.auto_setup_webhook())

    async def auto_setup_webhook(self):
        """Automatically create/sync webhook on Stripe"""
        try:
            # Determine Target URL (Priority: Proxy > Domain)
            if ui_config.STRIPE_PROXY_URL:
                # If we're using the new integrated proxy, the webhook endpoint is simply the proxy URL
                target_url = ui_config.STRIPE_PROXY_URL
                print(f"🔄 Stripe Auto-Sync: Using Proxy URL: {target_url}")
            else:
                target_url = f"{ui_config.DOMAIN_URL}/stripe/webhook"
            
            # Validation: Stripe Live Mode requires HTTPS
            if "http://" in target_url and "localhost" not in target_url and "127.0.0.1" not in target_url:
                 print(f"⚠️ Stripe Auto-Sync Skipped: {target_url} is not HTTPS.")
                 print("   - Stripe requires HTTPS for live webhooks.")
                 print("   - Please set STRIPE_PROXY_URL in .env or config.")
                 return

            print(f"🔄 Stripe Auto-Sync: Checking webhooks for {target_url}")
            
            # 1. List existing endpoints
            endpoints = stripe.WebhookEndpoint.list(limit=16)
            
            # 2. Find and Delete duplicates (Cleanup)
            for ep in endpoints.data:
                if ep.url == target_url:
                    print(f"   - Deleting old webhook: {ep.id}")
                    stripe.WebhookEndpoint.delete(ep.id)
            
            # 3. Create NEW Webhook
            new_ep = stripe.WebhookEndpoint.create(
                url=target_url,
                enabled_events=['checkout.session.completed'],
            )
            
            # 4. Set Secret
            self.webhook_secret = new_ep.secret
            print(f"✅ Stripe Auto-Sync: Success! Created new webhook ({new_ep.id})")
            print(f"   - Secret: {self.webhook_secret} (Active for this session)")
            
        except Exception as e:
            print(f"❌ Stripe Auto-Sync Failed: {e}")
            print("   - Fallback: System will accept webhooks WITHOUT verification (Dev Mode)")

    async def stripe_webhook(self, request: web.Request):
        """Handler for Stripe Webhooks"""
        payload = await request.text()
        
        # Check if we should enforce signature verification
        if self.webhook_secret and 'Stripe-Signature' in request.headers:
            sig_header = request.headers.get('Stripe-Signature')
            try:
                event = stripe.Webhook.construct_event(
                    payload, sig_header, self.webhook_secret
                )
            except ValueError:
                return web.Response(status=400, text="Invalid payload")
            except stripe.error.SignatureVerificationError:
                return web.Response(status=400, text="Invalid signature")
        else:
            # If no secret provided OR no signature header (Proxy Case), trust the payload (LESS SECURE)
            import json
            try:
                event = json.loads(payload)
            except:
                return web.Response(status=400, text="Invalid JSON")

        # Handle Events
        if event['type'] == 'checkout.session.completed':
            session = event['data']['object']
            await self.handle_checkout_success(session)

        return web.Response(status=200)

    async def handle_checkout_success(self, session):
        """Process successful payment"""
        metadata = session.get('metadata', {})
        user_id = metadata.get('user_id')
        days = int(metadata.get('days', 0))
        plan_name = metadata.get('plan_name', 'Premium')

        if not user_id:
            return

        try:
            user_id = str(user_id)
            data = await collection_myasync.find_one({}) or {}
            users = data.get("users", {})
            user_data = users.get(user_id, {})
            current_expire = user_data.get("premium_expire", 0)
            
            # Lifetime Check
            if days >= 36500: # 100 years -> Lifetime
                await collection_myasync.update_one(
                    {}, 
                    {"$set": {
                        f"users.{user_id}.premium": True,
                        f"users.{user_id}.premium_plan": plan_name,
                        f"users.{user_id}.premium_plan_id": session.get('metadata', {}).get('plan_id', 'lifetime')
                    }}, 
                    upsert=True
                )
            else:
                now = time.time()
                # If already active, add time. If expired, start from now.
                start_time = max(current_expire, now)
                new_expire = start_time + (days * 24 * 3600)

                await collection_myasync.update_one(
                    {}, 
                    {"$set": {
                        f"users.{user_id}.premium_expire": new_expire,
                         f"users.{user_id}.premium_plan": plan_name,
                         f"users.{user_id}.premium_plan_id": session.get('metadata', {}).get('plan_id', '1_month')
                    }}, 
                    upsert=True
                )
            
            print(f"✅ Payment Success: Granted {days} days to {user_id}")
            
            # Send DM if possible (we verify via ID, so we need to fetch user)
            try:
                user = await self.bot.fetch_user(int(user_id))
                # Try to guess lang from shared guilds, fallback to en
                lang = "en" 
                # Improving lang detection for DM is hard, default EN or try to find a mutual guild
                
                embed = discord.Embed(
                    title=self.bot.i18n.get("payment_success_title", lang),
                    description=self.bot.i18n.get("payment_success_desc", lang, plan_name=plan_name),
                    color=ui_config.SUCCESS_COLOR
                )
                if days >= 36500:
                    embed.add_field(name="Status", value=self.bot.i18n.get("payment_status_lifetime", lang), inline=True)
                else:
                    exp_date = datetime.datetime.fromtimestamp(new_expire).strftime('%d/%m/%Y %H:%M')
                    embed.add_field(name=self.bot.i18n.get("payment_days_added", lang), value=f"+{days} Days", inline=True)
                    embed.add_field(name=self.bot.i18n.get("payment_expires_on", lang), value=exp_date, inline=True)
                
                await user.send(embed=embed)
            except:
                pass

        except Exception as e:
            print(f"❌ Error handling payment for {user_id}: {e}")

    @app_commands.command(name="buy", description="Buy Premium via Stripe / ซื้อพรีเมียม")
    @app_commands.describe(plan="Select a premium plan / เลือกแผนพรีเมียม")
    @app_commands.choices(plan=[
        app_commands.Choice(name="1 Month - 29 THB (Save 0)", value="1_month"),
        app_commands.Choice(name="3 Months - 79 THB (Save 8)", value="3_months"),
        app_commands.Choice(name="6 Months - 149 THB (Save 25)", value="6_months"),
        app_commands.Choice(name="1 Year - 289 THB (Save 59)", value="1_year"),
        app_commands.Choice(name="Lifetime - 789 THB (Best Value!)", value="lifetime")
    ])
    async def buy(self, interaction: discord.Interaction, plan: app_commands.Choice[str]):
        if not ui_config.STRIPE_API_KEY:
             return await interaction.response.send_message("❌ Payment system is not configured.", ephemeral=True)

        plan_id = plan.value
        selected_plan = PREMIUM_PLANS.get(plan_id)
        
        if not selected_plan:
            return await interaction.response.send_message("❌ Invalid plan selected.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        try:
            domain = ui_config.DOMAIN_URL
            
            checkout_session = stripe.checkout.Session.create(
                payment_method_types=['card', 'promptpay'], # Added PromptPay for Thai context
                line_items=[{
                    'price_data': {
                        'currency': 'thb',
                        'product_data': {
                            'name': selected_plan['name'],
                            'description': selected_plan['description'],
                            'images': [self.bot.user.display_avatar.url] if self.bot.user else [],
                        },
                        'unit_amount': selected_plan['price'],
                    },
                    'quantity': 1,
                }],
                metadata={
                    'user_id': str(interaction.user.id),
                    'plan_id': plan_id,
                    'days': str(selected_plan['days']),
                    'plan_name': selected_plan['name']
                },
                mode='payment',
                success_url='https://cyori.pages.dev/success.html',
                cancel_url='https://cyori.pages.dev/premium.html',
            )
            
            
            lang = await self.bot.get_lang(interaction.guild_id) if interaction.guild else "en"
            
            embed = discord.Embed(
                title=self.bot.i18n.get("payment_title", lang),
                description=self.bot.i18n.get("payment_desc", lang, plan_name=selected_plan['name']),
                color=ui_config.EMBED_COLOR
            )
            embed.add_field(name=self.bot.i18n.get("payment_price", lang), value=f"{selected_plan['price'] / 100:.2f} THB", inline=True)
            embed.add_field(name=self.bot.i18n.get("payment_valid_time", lang), value="1 Hour", inline=True)
            
            view = discord.ui.View()
            view.add_item(discord.ui.Button(label=self.bot.i18n.get("payment_button", lang), url=checkout_session.url, style=discord.ButtonStyle.url))
            
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)

        except Exception as e:
            await interaction.followup.send(f"❌ Error creating checkout session: {e}", ephemeral=True)
            print(f"Stripe Error: {e}")

async def setup(bot: Cyori):
    await bot.add_cog(Payment(bot))
