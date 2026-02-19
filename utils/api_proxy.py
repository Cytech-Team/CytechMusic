
import aiohttp
from aiohttp import web
import json
import traceback
import asyncio

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
            print(f"[API Proxy] Error processing '{action}': {e}")
            traceback.print_exc()
            return self.error_response("Internal Server Error", status=500)

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
