"""
CytechX API Proxy Manager
=========================
Centralised action dispatcher for /api/proxy endpoint.
All web→bot and bot→web communication routes through here.

Flow:
  Browser → Cloudflare Pages /api/proxy
          → VPS /api/proxy  (this file)
          → handle_<action>()
          → Response back to browser

WebSocket (realtime):
  Browser ↔ WSS /api/gateway (Cloudflare) ↔ WS /api/gateway (VPS)
"""

import aiohttp
from aiohttp import web
import json
import traceback
import asyncio
import datetime


class APIProxyManager:
    def __init__(self, bot):
        self.bot = bot
        from utils.lyrics import LyricsManager
        self.lyrics_manager = LyricsManager()
        self.cors_headers = {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type, Authorization',
        }

    # ──────────────────────────────────────────────────────
    # ENTRY POINT
    # ──────────────────────────────────────────────────────

    async def handle_proxy_request(self, request):
        """Main entry point for all /api/proxy requests."""
        if request.method == 'OPTIONS':
            return web.Response(headers=self.cors_headers)

        # Parse body / query params
        try:
            if request.method == 'POST':
                try:
                    data = await request.json()
                except Exception:
                    data = {}
                params = {**dict(request.query), **data}
            else:
                params = dict(request.query)
        except Exception as e:
            return self.error(f"Invalid request: {e}")

        action = params.get('action')
        if not action:
            return self.error("Missing 'action' parameter")

        # Dispatch to handler
        try:
            handler = getattr(self, f"handle_{action}", None)
            if handler:
                return await handler(params)
            return self.error(f"Unknown action: {action}", 400)
        except Exception as e:
            print(f"[API Proxy] Error in '{action}': {e}")
            traceback.print_exc()
            asyncio.create_task(
                self._send_error_webhook(action, str(e), traceback.format_exc())
            )
            return self.error("Internal Server Error", 500)

    # ──────────────────────────────────────────────────────
    # READ-ONLY HANDLERS  (Web → Bot, response only)
    # ──────────────────────────────────────────────────────

    async def handle_status(self, params):
        """Current music player state for a guild."""
        guild_id = params.get('guild_id')
        if not guild_id:
            return self.error("Missing guild_id")
        try:
            state = await self.bot.build_dashboard_state(int(guild_id))
            return self.ok(state)
        except Exception as e:
            return self.error(str(e))

    async def handle_bot_guilds(self, params):
        """List of guild IDs the bot is currently in."""
        return self.ok({"guilds": [str(g.id) for g in self.bot.guilds]})

    async def handle_find_voice(self, params):
        """Find which guild's voice channel a user is currently in."""
        uid = params.get('user_id')
        if not uid:
            return self.error("Missing user_id")
        try:
            target = int(uid)
            for guild in self.bot.guilds:
                m = guild.get_member(target)
                if m and m.voice and m.voice.channel:
                    return self.ok({
                        "found": True,
                        "guild_id": str(guild.id),
                        "guild_name": guild.name,
                        "channel_id": str(m.voice.channel.id)
                    })
            return self.ok({"found": False})
        except Exception as e:
            return self.error(str(e))

    async def handle_search(self, params):
        """Search for tracks via Lavalink."""
        q = params.get('q') or params.get('query')
        if not q:
            return self.ok({"results": []})
        try:
            import cytechlink
            node = list(cytechlink.NodePool._nodes.values())[0]
            results = await node.get_tracks(f"ytmsearch:{q}", requester=self.bot.user)
            res_list = results if isinstance(results, list) else getattr(results, 'tracks', [])
            tracks = [{
                "title": t.title, "author": t.author, "uri": t.uri,
                "thumbnail": t.thumbnail or "logo-circle.png",
                "length": t.length, "encoded": t.track_id
            } for t in res_list[:20]]
            return self.ok({"results": tracks})
        except Exception:
            return self.ok({"results": []})

    async def handle_recommended(self, params):
        """Random recommended / trending tracks."""
        try:
            import cytechlink, random
            if not cytechlink.NodePool._nodes:
                return self.ok({"results": []})
            node = list(cytechlink.NodePool._nodes.values())[0]
            results = await node.get_tracks("ytmsearch:trending music", requester=self.bot.user)
            res_list = results if isinstance(results, list) else getattr(results, 'tracks', [])
            random.shuffle(res_list)
            tracks = [{
                "title": t.title, "author": t.author, "uri": t.uri,
                "thumbnail": t.thumbnail or "logo-circle.png",
                "length": t.length, "encoded": t.track_id
            } for t in res_list[:20]]
            return self.ok({"results": tracks})
        except Exception:
            return self.ok({"results": []})

    async def handle_global_stats(self, params):
        """Global bot statistics (guilds, users, active players)."""
        return self.ok({
            "servers": len(self.bot.guilds),
            "users": len(self.bot.users),
            "playing": sum(
                1 for p in self.bot.voice_clients
                if hasattr(p, 'is_playing') and p.is_playing
            )
        })

    async def handle_lyrics(self, params):
        """Fetch lyrics for a song (used by dashboard)."""
        query = params.get('query') or ""
        title = query
        artist = ""
        if " - " in query:
            parts = query.split(" - ", 1)
            artist = parts[0]
            title = parts[1]

        try:
            lyrics_data = await self.lyrics_manager.get_lyrics(title, artist)
            if lyrics_data:
                lyrics_text = lyrics_data.get("default") or list(lyrics_data.values())[0]
                return self.ok({"lyrics": lyrics_text})
            return self.ok({"lyrics": None})
        except Exception as e:
            return self.error(str(e))

    async def handle_user_info(self, params):
        """User premium status, playlists, and favorites."""
        uid = params.get('user_id')
        if not uid:
            return self.error("Missing user_id")
        try:
            target_uid = int(uid)

            user_data = await self.bot.db_manager.get_user(uid)
            user_doc  = await self.bot.db_manager.get_user_doc(uid)

            is_prem   = await self.bot.is_premium(target_uid)
            is_owner  = target_uid in OWNER_IDS
            plan_name = user_data.get("premium_plan", "Free Member")
            expire    = user_data.get("premium_expire")

            if is_owner:
                plan_name = "Admin / Owner"
                is_prem   = True
                expire    = "Lifetime"
            elif is_prem and plan_name == "Free Member":
                plan_name = "Premium Member"

            return self.ok({
                "id":             uid,
                "premium":        is_prem,
                "is_owner":       is_owner,
                "expire":         expire,
                "plan":           plan_name,
                "playlist_limit": 100 if (is_prem or is_owner) else 20,
                "favorites":      user_doc.get("favorites", []),
                "playlists":      user_doc.get("playlists", [])
            })
        except Exception as e:
            print(f"[API Proxy] user_info error for {uid}: {e}")
            return self.ok({
                "id": uid, "premium": False, "plan": "Error",
                "favorites": [], "playlists": []
            })

    async def handle_guild_settings(self, params):
        """Fetch guild settings + role list from DB."""
        guild_id = params.get('guild_id')
        if not guild_id:
            return self.error("Missing guild_id")
        try:
            guild_data = await self.bot.db_manager.get_guild(guild_id)
            roles      = []
            guild      = self.bot.get_guild(int(guild_id))
            if guild:
                roles = [
                    {"id": str(r.id), "name": r.name}
                    for r in guild.roles if not r.is_default()
                ]
            return self.ok({**guild_data, "roles": roles})
        except Exception as e:
            return self.error(str(e))

    # ──────────────────────────────────────────────────────
    # MUSIC CONTROL HANDLERS  (Web → Bot → execute action)
    # ──────────────────────────────────────────────────────

    async def _control(self, params):
        """
        Generic delegate: forwards params directly to handle_ws_control.
        The 'action' key in params tells handle_ws_control what to do.
        """
        guild_id = params.get('guild_id')
        if not guild_id:
            return self.error("Missing guild_id")
        try:
            asyncio.create_task(
                self.bot.dashboard.handle_ws_control(params, int(guild_id))
            )
            return self.ok({"status": "ok"})
        except Exception as e:
            return self.error(str(e))

    # One-liner handlers — all delegate to _control()
    async def handle_play(self, params):     return await self._control(params)
    async def handle_pause(self, params):    return await self._control(params)
    async def handle_skip(self, params):     return await self._control(params)
    async def handle_stop(self, params):     return await self._control(params)
    async def handle_volume(self, params):   return await self._control(params)
    async def handle_seek(self, params):     return await self._control(params)
    async def handle_loop(self, params):     return await self._control(params)
    async def handle_skipto(self, params):   return await self._control(params)
    async def handle_remove(self, params):   return await self._control(params)
    async def handle_favorite(self, params): return await self._control(params)

    async def handle_random(self, params):
        """Pick a random trending track and queue it."""
        guild_id = params.get('guild_id')
        uid      = params.get('user_id')
        if not guild_id:
            return self.error("Missing guild_id")
        try:
            import cytechlink, random
            gid   = int(guild_id)
            g     = self.bot.get_guild(gid)
            m     = g.get_member(int(uid)) if g and uid else None
            if not m or not m.voice:
                return self.error("User not in voice channel")
            node     = list(cytechlink.NodePool._nodes.values())[0]
            results  = await node.get_tracks("ytmsearch:trending music", requester=self.bot.user)
            res_list = results if isinstance(results, list) else getattr(results, 'tracks', [])
            if not res_list:
                return self.error("No tracks found")
            track = random.choice(res_list)
            asyncio.create_task(self.bot.dashboard.handle_ws_control({
                'action': 'play', 'guild_id': guild_id, 'user_id': uid,
                'value':  {'encoded': track.track_id, 'uri': track.uri}
            }, gid))
            return self.ok({"status": "ok", "title": track.title})
        except Exception as e:
            return self.error(str(e))

    async def handle_proxy_control(self, params):
        """Special commands: guild_settings_save, etc."""
        cmd = params.get('cmd_action')
        if not cmd:
            return self.error("Missing cmd_action")

        if cmd == 'guild_settings_save':
            try:
                guild_id     = params.get('guild_id')
                settings_raw = params.get('settings', '{}')
                settings     = (
                    json.loads(settings_raw)
                    if isinstance(settings_raw, str)
                    else settings_raw
                )
                await self.bot.db_manager.update_guild(guild_id, settings)
                guild = self.bot.get_guild(int(guild_id)) if guild_id else None
                if guild:
                    asyncio.create_task(
                        self.bot.update_guild_embed(settings, guild_id=guild_id)
                    )
                return self.ok({"status": "saved"})
            except Exception as e:
                return self.error(str(e))

        return self.error(f"Unknown cmd_action: {cmd}")

    # ──────────────────────────────────────────────────────
    # UTILITIES
    # ──────────────────────────────────────────────────────

    def ok(self, data: dict):
        return web.json_response(data, headers=self.cors_headers)

    # Alias for backward compatibility
    def success_response(self, data: dict):
        return self.ok(data)

    def error(self, message: str, status: int = 400):
        return web.json_response({"error": message}, status=status, headers=self.cors_headers)

    # Alias for backward compatibility
    def error_response(self, message: str, status: int = 400):
        return self.error(message, status)

    async def _send_error_webhook(self, action: str, error_text: str, trace: str):
        try:
            from utils.config import ERROR_LOG_WEBHOOK
            if not ERROR_LOG_WEBHOOK:
                return
            embed = {
                "title": "🚨 API Proxy Error",
                "color": 15548997,
                "fields": [
                    {"name": "Action", "value": f"`{action}`", "inline": True},
                    {"name": "Error",  "value": f"```{error_text[:500]}```", "inline": False}
                ],
                "timestamp": datetime.datetime.utcnow().isoformat()
            }
            if len(trace) < 800:
                embed["description"] = f"```py\n{trace}```"
            async with aiohttp.ClientSession() as s:
                await s.post(ERROR_LOG_WEBHOOK, json={"embeds": [embed]})
        except Exception:
            pass
