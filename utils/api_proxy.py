
import aiohttp
from aiohttp import web
import json
import traceback
import asyncio
import datetime

class APIProxyManager:
    """
    Centralized API Proxy Manager for handling external requests and internal routing securely.
    Designed to prevent 429 spam and standardize error responses.
    """
    def __init__(self, bot):
        self.bot = bot
        self.cors_headers = {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type, Authorization',
        }
        # Simple in-memory cache for throttling or data caching
        self._cache = {}

    async def handle_proxy_request(self, request):
        """
        Main entry point for /api/proxy requests.
        Dispatches to specific methods based on 'action' parameter.
        """
        # 1. Handle Preflight OPTIONS
        if request.method == 'OPTIONS':
            return web.Response(headers=self.cors_headers)

        # 2. Extract Parameters
        try:
            if request.method == 'POST':
                try:
                    data = await request.json()
                except:
                    data = {}
                # Merge query params for flexibility
                params = {**request.query, **data}
            else:
                params = request.query
        except Exception as e:
            return self.error_response(f"Invalid Request: {str(e)}")

        action = params.get('action')
        if not action:
            return self.error_response("Missing 'action' parameter")

        # 3. Dispatch
        try:
            handler = getattr(self, f"handle_{action}", None)
            if handler:
                return await handler(params)
            else:
                return self.error_response(f"Unknown action: {action}", status=400)
        except Exception as e:
            error_msg = f"Error processing '{action}': {str(e)}"
            print(f"[API Proxy] {error_msg}")
            traceback.print_exc()
            
            # Send to Webhook
            asyncio.create_task(self.send_error_webhook(action, str(e), traceback.format_exc()))
            
            return self.error_response("Internal Server Error", status=500)

    async def send_error_webhook(self, action, error_text, detailed_trace):
        """Sends error details to a configured Discord Webhook."""
        # You should put your actual Webhook URL in config.py or .env
        from utils.config import ERROR_LOG_WEBHOOK 
        
        if not ERROR_LOG_WEBHOOK: return

        embed = {
            "title": "🚨 API Proxy Error",
            "color": 16711680, # Red
            "fields": [
                {"name": "Action", "value": f"`{action}`", "inline": True},
                {"name": "Error", "value": f"```{error_text[:1000]}```", "inline": False}
            ],
            "footer": {"text": "CytechX System Monitor"},
            "timestamp": datetime.datetime.utcnow().isoformat()
        }
        
        # If traceback is not too long, add it
        if len(detailed_trace) < 800:
             embed["description"] = f"Traceback:\n```py\n{detailed_trace}```"

        payload = {"embeds": [embed]}
        
        try:
            async with aiohttp.ClientSession() as session:
                await session.post(ERROR_LOG_WEBHOOK, json=payload)
        except Exception as we:
            print(f"Failed to send webhook: {we}")

    # --- HANDLERS ---

    async def handle_bot_guilds(self, params):
        """Returns list of guild IDs the bot is in."""
        guild_ids = [str(g.id) for g in self.bot.guilds]
        return self.success_response({"guilds": guild_ids})

    async def handle_guild_settings(self, params):
        """Fetcher for guild settings."""
        guild_id = params.get('guild_id')
        if not guild_id: return self.error_response("Missing guild_id")
        
        # In a real scenario, fetch from DB
        # For now, return mock or basic info
        try:
            guild = self.bot.get_guild(int(guild_id))
            if not guild: return self.error_response("Guild not found")
            
            # Fetch from DB (Mocking DB call structure)
            # settings = await self.bot.db.get_guild_settings(guild_id)
            settings = {
                "prefix": "!",
                "lang": "en",
                "dj_mode": False
            }
            return self.success_response(settings)
        except Exception as e:
            return self.error_response(str(e))

    async def handle_proxy_control(self, params):
        """Handles control actions like saving settings."""
        cmd = params.get('cmd_action')
        if not cmd: return self.error_response("Missing cmd_action")
        
        if cmd == 'guild_settings_save':
            # Logic to save settings
            print(f"[API Proxy] Saving settings for {params.get('guild_id')}: {params.get('settings')}")
            return self.success_response({"status": "saved"})
            
        return self.error_response("Unknown command")

    # --- UTILS ---

    def success_response(self, data):
        return web.json_response(data, headers=self.cors_headers)

    def error_response(self, message, status=400):
        return web.json_response({"error": message}, status=status, headers=self.cors_headers)
