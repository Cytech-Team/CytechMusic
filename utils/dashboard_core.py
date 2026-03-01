import discord
from aiohttp import web, WSMsgType
import json
import asyncio
import traceback
import time
import pathlib
import cytechlink
from cytechlink.enums import LoopType
from utils.lyrics import LyricsManager


class FakeContext:
    def __init__(self, bot, guild, channel, author):
        self.bot = bot
        self.guild = guild
        self.channel = channel
        self.author = author
        self.user = author
        self.message = None

    async def send(self, *args, **kwargs):
        if self.channel:
            return await self.channel.send(*args, **kwargs)
        return None

    def typing(self):
        class Magic:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

        return Magic()


from utils.api_proxy import APIProxyManager


class DashboardSystem:
    def __init__(self, bot):
        self.bot = bot
        self.cors_headers = bot.cors_headers
        self.lyrics_manager = LyricsManager()
        self.api_proxy = APIProxyManager(bot)


    async def setup_routes(self, app):
        router = app.router

        # New Centralized Proxy Route
        router.add_route("*", "/api/proxy", self.handle_proxy_route)

        # Keep existing specific routes for now, migrate gradually
        # Static Files & Pages
        web_path = pathlib.Path(__file__).parent.parent / "web"
        

        async def serve_index(request):
            return web.FileResponse(str(web_path / "index.html"))
        
        async def serve_dashboard(request):
            return web.FileResponse(str(web_path / "dashboard.html"))

        router.add_get("/", serve_index)
        router.add_get("/index.html", serve_index)
        router.add_get("/dashboard", serve_dashboard)
        router.add_get("/dashboard.html", serve_dashboard)
        
        async def redirect_invite(request):
            from utils.config import NEW_BOT_ID
            return web.HTTPFound(f"https://discord.com/oauth2/authorize?client_id={NEW_BOT_ID}&permissions=8&scope=bot%20applications.commands")

        router.add_get("/invite", redirect_invite)
        
        router.add_get("/api/status", self.get_status)
        router.add_post("/api/control", self.post_control)
        router.add_get("/api/gateway", self.websocket_handler)
        router.add_get("/api/search", self.get_search)
        router.add_get("/api/lyrics", self.get_lyrics)
        router.add_get("/api/user_info", self.get_user_info)
        router.add_get(
            "/api/bot_guilds", self.get_bot_guilds
        )  # Deprecated by proxy, keeping for compat if needed
        router.add_get("/api/stats", self.get_stats)
        router.add_get("/api/join_guild", self.join_guild_endpoint)
        router.add_get("/api/guild_settings", self.get_guild_settings)
        router.add_post("/api/guild_settings", self.post_guild_settings)
        router.add_post("/api/playlist", self.post_playlist)
        router.add_get("/api/find_voice", self.get_find_voice)
        router.add_get("/api/recommended", self.get_recommended)

        router.add_options("/api/playlist", self.handle_options)
        router.add_options("/api/status", self.handle_options)
        router.add_options("/api/control", self.handle_options)
        router.add_options("/api/guild_settings", self.handle_options)

        # Start Periodic Broadcaster (Heartbeat)
        self.bot.loop.create_task(self.realtime_broadcaster())
        
        # Add static file serving last, so specific routes take precedence
        router.add_static("/", str(web_path), name="static")

        print(f"[CytechX] Dashboard System Embedded & Ready")
        print(f"[CytechX] Routes loaded: /, /dashboard, /api/proxy, and static files")
        print(f"[!] SECURITY WARNING: The built-in dashboard uses a simple web server.")
        print(f"[!] For public use, hide it behind a reverse proxy (e.g. Nginx).")

    async def handle_proxy_route(self, request):
        """Delegates to the new APIProxyManager"""
        return await self.api_proxy.handle_proxy_request(request)

    async def realtime_broadcaster(self):
        """Ticker for smooth progress bars (300ms). Only broadcasts to guilds with active WS."""
        while not self.bot.is_closed():
            active_guilds = [
                gid for gid, clients in self.bot.sockets_by_guild.items() if clients
            ]
            for gid in active_guilds:
                asyncio.create_task(self.bot.broadcast_guild(gid))
            await asyncio.sleep(0.3)

    async def handle_options(self, request):
        return web.Response(headers=self.cors_headers)

    async def get_bot_guilds(self, request):
        return web.json_response(
            {"guilds": [str(g.id) for g in self.bot.guilds]}, headers=self.cors_headers
        )

    async def get_status(self, request):
        gid = request.query.get("guild_id")
        if not gid:
            return web.json_response({"error": "no_guild"}, headers=self.cors_headers)
        state = await self.bot.build_dashboard_state(int(gid))
        return web.json_response(state, headers=self.cors_headers)

    async def get_stats(self, request):
        data = {
            "guilds": len(self.bot.guilds),
            "users": len(self.bot.users),
            "playing": sum(
                1
                for p in self.bot.voice_clients
                if hasattr(p, "is_playing") and p.is_playing
            ),
        }
        return web.json_response(data, headers=self.cors_headers)

    async def post_control(self, request):
        try:
            payload = await request.json()
            gid = payload.get("guild_id")
            if gid:
                asyncio.create_task(self.handle_ws_control(payload, int(gid)))
                return web.json_response({"status": "ok"}, headers=self.cors_headers)
            return web.json_response({"error": "no_guild"}, headers=self.cors_headers)
        except Exception as e:
            return web.json_response({"error": str(e)}, headers=self.cors_headers)

    async def join_guild_endpoint(self, request):
        # Auto-join user to Support Server via OAuth token from dashboard
        guild_id = request.query.get("guild_id")
        user_id = request.query.get("user_id")
        token = request.query.get("token")
        if not (guild_id and user_id and token):
            return web.json_response(
                {"error": "missing_params"}, headers=self.cors_headers
            )

        url = f"https://discord.com/api/guilds/{guild_id}/members/{user_id}"
        headers = {
            "Authorization": f"Bot {self.bot.http.token}",
            "Content-Type": "application/json",
        }
        try:
            async with self.bot.session.put(
                url, headers=headers, json={"access_token": token}
            ) as r:
                return web.json_response(
                    {"status": "ok", "discord": r.status}, headers=self.cors_headers
                )
        except Exception:
            return web.json_response({"error": "failed"}, headers=self.cors_headers)

    async def get_guild_settings(self, request):
        gid = request.query.get("guild_id")
        if not gid:
            return web.json_response({"error": "no_guild"}, headers=self.cors_headers)
            
        guild_data = await self.bot.db_manager.get_guild(gid)
        
        # Add Discord Cache Info
        discord_guild = self.bot.get_guild(int(gid))
        if discord_guild:
            guild_data["name"] = discord_guild.name
            guild_data["icon"] = str(discord_guild.icon.url) if discord_guild.icon else None
            guild_data["member_count"] = discord_guild.member_count
            
        return web.json_response(guild_data, headers=self.cors_headers)

    async def post_guild_settings(self, request):
        payload = await request.json()
        gid = payload.get("guild_id")
        settings = payload.get("settings", {})

        await self.bot.db_manager.update_guild(gid, settings)
        # Update embed
        await self.bot.update_guild_embed(settings, guild_id=gid)
        return web.json_response({"status": "ok"}, headers=self.cors_headers)

    async def get_user_info(self, request):
        uid = request.query.get("user_id")
        if not uid:
            return web.json_response({"error": "no_user"}, headers=self.cors_headers)

        try:
            target_uid = int(uid)

            # Fetch Data with Defaults
            user_data = await self.bot.db_manager.get_user(uid)
            user_doc = await self.bot.db_manager.get_user_doc(uid)

            # Premium Logic
            is_prem = await self.bot.is_premium(target_uid)
            from utils.config import OWNER_IDS

            is_owner = target_uid in OWNER_IDS

            plan_name = user_data.get("premium_plan", "Free Member")
            expire_date = user_data.get("premium_expire")

            if is_owner:
                plan_name = "Admin / Owner"
                is_prem = True
                expire_date = "Lifetime"
            elif is_prem and plan_name == "Free Member":
                plan_name = "Premium Member"

            playlist_limit = 100 if (is_prem or is_owner) else 20

            resp = {
                "id": uid,
                "premium": is_prem,
                "is_owner": is_owner,
                "expire": expire_date,
                "plan": plan_name,
                "playlist_limit": playlist_limit,
                "favorites": user_doc.get("favorites", []) if user_doc else [],
                "playlists": user_doc.get("playlists", []) if user_doc else [],
            }
            return web.json_response(resp, headers=self.cors_headers)
        except Exception as e:
            print(f"[Dashboard] Get User Info Error for {uid}: {e}")
            # Return basic info even if error occurs, to prevent frontend crash
            return web.json_response(
                {
                    "id": uid,
                    "premium": False,
                    "plan": "Error Loading",
                    "favorites": [],
                    "playlists": [],
                },
                headers=self.cors_headers,
            )

    async def get_search(self, request):
        q = request.query.get("q") or request.query.get("query")
        if not q:
            return web.json_response([], headers=self.cors_headers)

        try:
            node = list(cytechlink.NodePool._nodes.values())[0]
            results = await node.get_tracks(f"ytmsearch:{q}", requester=self.bot.user)
            tracks = []
            res_list = (
                results if isinstance(results, list) else getattr(results, "tracks", [])
            )
            for t in res_list[:20]:
                tracks.append(
                    {
                        "title": t.title,
                        "author": t.author,
                        "uri": t.uri,
                        "thumbnail": t.thumbnail or "logo-circle.png",
                        "length": t.length,
                        "encoded": t.track_id,
                    }
                )
            return web.json_response({"results": tracks}, headers=self.cors_headers)
        except Exception:
            return web.json_response({"results": []}, headers=self.cors_headers)

    async def get_lyrics(self, request):
        query = request.query.get("query")
        if not query:
            return web.json_response({"error": "no_query"}, headers=self.cors_headers)

        try:
            # Check if it's "Artist - Title" format
            if " - " in query:
                parts = query.split(" - ", 1)
                title = parts[1]
                artist = parts[0]
            else:
                title = query
                artist = ""

            lyrics_data = await self.lyrics_manager.get_lyrics(title, artist)

            if lyrics_data:
                # Format for frontend
                # If multiple parts, join them or just take default
                text = lyrics_data.get("default", "")
                if not text and len(lyrics_data) > 0:
                    text = list(lyrics_data.values())[0]

                return web.json_response(
                    {"lyrics": text, "source": "Auto"}, headers=self.cors_headers
                )
            else:
                return web.json_response(
                    {"error": "not_found"}, headers=self.cors_headers
                )
        except Exception as e:
            return web.json_response({"error": str(e)}, headers=self.cors_headers)

    async def get_find_voice(self, request):
        uid = request.query.get("user_id")
        if not uid:
            return web.json_response({"found": False}, headers=self.cors_headers)

        try:
            target_uid = int(uid)
            # Iterate over guilds to find where the user has a voice state
            for guild in self.bot.guilds:
                member = guild.get_member(target_uid)
                if member and member.voice and member.voice.channel:
                    return web.json_response(
                        {
                            "found": True,
                            "guild_id": str(guild.id),
                            "guild_name": guild.name,
                            "channel_id": str(member.voice.channel.id),
                        },
                        headers=self.cors_headers,
                    )
        except Exception as e:
            print(f"[Dashboard] Find Voice Error: {e}")

        return web.json_response({"found": False}, headers=self.cors_headers)

    async def get_recommended(self, request):
        try:
            if not cytechlink.NodePool._nodes:
                return web.json_response({"results": []}, headers=self.cors_headers)
            node = list(cytechlink.NodePool._nodes.values())[0]
            results = await node.get_tracks(
                "ytmsearch:trending music", requester=self.bot.user
            )
            tracks = []
            res_list = (
                results if isinstance(results, list) else getattr(results, "tracks", [])
            )
            import random

            random.shuffle(res_list)
            for t in res_list[:20]:
                tracks.append(
                    {
                        "title": t.title,
                        "author": t.author,
                        "uri": t.uri,
                        "thumbnail": t.thumbnail or "logo-circle.png",
                        "length": t.length,
                        "encoded": t.track_id,
                    }
                )
            return web.json_response({"results": tracks}, headers=self.cors_headers)
        except Exception:
            return web.json_response({"results": []}, headers=self.cors_headers)

    async def websocket_handler(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.bot.all_sockets.add(ws)
        gid = None
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = msg.json()
                        op = data.get("op")
                        if op == "connect":
                            r_gid = data.get("guild_id")
                            if not r_gid or r_gid == "null":
                                continue
                            gid = int(r_gid)
                            if gid not in self.bot.sockets_by_guild:
                                self.bot.sockets_by_guild[gid] = []
                            self.bot.sockets_by_guild[gid].append(ws)
                            # Push initial state
                            state = await self.bot.build_dashboard_state(gid)
                            await ws.send_json({"op": "state", "data": state})
                        elif op == "control":
                            asyncio.create_task(self.handle_ws_control(data, gid, ws=ws))
                    except Exception as e:
                        print(f"[WebSocket Error] {e}")
        finally:
            self.bot.all_sockets.discard(ws)
            if gid and gid in self.bot.sockets_by_guild:
                try:
                    self.bot.sockets_by_guild[gid].remove(ws)
                except Exception:
                    pass
        return ws

    async def handle_ws_control(self, data, gid, ws=None):
        if not gid:
            return
        act = data.get("action")
        val = data.get("value")
        uid = data.get("user_id")
        g = self.bot.get_guild(gid)
        p = g.voice_client if g else None

        try:
            if act == "play":
                try:
                    target_uid = int(uid) if uid else 0
                except (ValueError, TypeError):
                    target_uid = 0
                
                m = g.get_member(target_uid) if target_uid else None
                if not m or not m.voice:
                    if ws and not ws.closed:
                        await ws.send_json({"op": "error", "message": "กรุณาเข้าห้องเสียงก่อนใช้งานบอทบนหน้าเว็บ!"})
                    return
                if not p:
                    p = await m.voice.channel.connect(cls=cytechlink.Player)

                encoded = val.get("encoded") if isinstance(val, dict) else val
                uri = val.get("uri") if isinstance(val, dict) else None

                # Guard: reject bogus strings from frontend (JS undefined→'undefined')
                if encoded in (None, "", "undefined", "null"):
                    encoded = None

                node = p.node
                added_track = None

                if encoded:
                    added_track = await node.build_track(encoded, requester=m)
                    await p.add_track(added_track)
                elif uri:
                    results = await node.get_tracks(uri, requester=m)
                    if results:
                        if hasattr(results, "tracks"):
                            for t in results.tracks:
                                await p.add_track(t)
                            added_track = results.tracks[0] if results.tracks else None
                        else:
                            added_track = (
                                results[0] if isinstance(results, list) else results
                            )
                            await p.add_track(added_track)

                # ── Anchor controller to jukebox embed (first connect only) ──
                already_playing = p.is_playing
                if not p.controller:
                    try:
                        _gd = await self.bot.db_manager.get_guild(gid)
                        ch_id = _gd.get("channel_id")
                        emb_id = _gd.get("play_embed_id")
                        if ch_id and emb_id:
                            setup_ch = self.bot.get_channel(int(ch_id))
                            if setup_ch:
                                try:
                                    p.controller = await setup_ch.fetch_message(
                                        int(emb_id)
                                    )
                                except Exception:
                                    pass
                    except Exception:
                        pass

                # ── Send Now Playing embed into the voice channel text section ──
                # Setup channel jukebox (play_embed_id) ยัง update อิสระผ่าน Section 2 ของ update_controller()
                # Controller ที่ set ที่นี่จะถูก Section 4 จัดการ (ลบ-ส่งใหม่เมื่อ track เปลี่ยน)
                if added_track:

                    async def _send_vc_embed():
                        try:
                            import discord as _d

                            _title = getattr(added_track, "title", "Unknown Track")
                            _author = getattr(added_track, "author", "")
                            _uri = getattr(added_track, "uri", None)
                            _thumb = getattr(added_track, "thumbnail", None)

                            vc_channel = m.voice.channel if m.voice else None

                            if already_playing:
                                # กำลังเล่นอยู่ → แค่ notify "Added to Queue" ใน VC (auto-delete ได้)
                                emb = _d.Embed(
                                    description=f"🎵 **{_title}**\nเพิ่มลงคิวโดย {m.mention}",
                                    color=0xFFD700,
                                )
                                emb.set_author(name="Added to Queue")
                                if vc_channel:
                                    try:
                                        await vc_channel.send(
                                            embed=emb, delete_after=15
                                        )
                                        return
                                    except Exception:
                                        pass
                                # fallback → setup channel
                                _g2 = await self.bot.db_manager.get_guild(gid)
                                _c = (
                                    self.bot.get_channel(int(_g2["channel_id"]))
                                    if _g2.get("channel_id")
                                    else None
                                )
                                if _c:
                                    await _c.send(embed=emb, delete_after=12)

                            else:
                                # เพลงใหม่ (fresh start) → ส่ง Now Playing embed และ set เป็น controller
                                # ⚠️ ไม่ใส่ delete_after เพราะ cytechlink จะ manage lifecycle เอง
                                emb = _d.Embed(title=_title, url=_uri, color=0xFFD700)
                                emb.set_author(
                                    name="▶️ Now Playing · Dashboard",
                                    icon_url=self.bot.user.display_avatar.url,
                                )
                                emb.add_field(
                                    name="Artist", value=f"`{_author}`", inline=True
                                )
                                emb.set_footer(
                                    text=f"Requested by {m.display_name}",
                                    icon_url=m.display_avatar.url,
                                )
                                if _thumb:
                                    emb.set_thumbnail(url=_thumb)

                                target_ch = None
                                # 1️⃣ ลอง VC text section ก่อน
                                if vc_channel:
                                    try:
                                        sent = await vc_channel.send(embed=emb)
                                        p.controller = sent
                                        # ให้ context ชี้ไปที่ VC channel เพื่อให้ NotFound handler resend ถูกที่
                                        if not hasattr(p, "context") or not p.context:
                                            p.context = type(
                                                "_CtxPlaceholder",
                                                (),
                                                {"channel": vc_channel},
                                            )()
                                        return
                                    except Exception:
                                        target_ch = None

                                # 2️⃣ Fallback → setup channel (ส่งเป็น controller ที่นั่นแทน)
                                _g2 = await self.bot.db_manager.get_guild(gid)
                                _ch_id2 = _g2.get("channel_id")
                                _emb_id2 = _g2.get("play_embed_id")
                                if _ch_id2:
                                    _setup = self.bot.get_channel(int(_ch_id2))
                                    if _setup:
                                        # ถ้ามี jukebox embed → ใช้เป็น controller
                                        if _emb_id2 and not p.controller:
                                            try:
                                                p.controller = (
                                                    await _setup.fetch_message(
                                                        int(_emb_id2)
                                                    )
                                                )
                                            except Exception:
                                                pass
                        except Exception:
                            pass

                    asyncio.create_task(_send_vc_embed())

                if not already_playing:
                    await p.do_next()

            elif not p:
                return

            elif act == "pause":
                await p.set_pause(not p.is_paused)
                await p.update_controller(force=True)
            elif act == "skip":
                # Handle Loop Track mode: must turn off loop to skip
                from cytechlink.enums import LoopType

                if (
                    hasattr(p.queue, "_repeat")
                    and p.queue._repeat.mode == LoopType.track
                ):
                    p.queue._repeat.set_mode(LoopType.off)
                elif hasattr(p.queue, "mode") and str(p.queue.mode).endswith("track"):
                    p.queue.mode = "off"

                await p.stop()
                await self.bot.broadcast_guild(gid)
            elif act == "stop":
                await p.teardown()
                await self.bot.broadcast_guild(gid)
            elif act == "volume":
                await p.set_volume(max(0, min(int(val), 100)))
                await p.update_controller(force=True)
            elif act == "seek":
                await p.seek(int(val))
                await p.update_controller(force=True)
            elif act == "loop":
                from cytechlink.enums import LoopType

                cm = p.queue._repeat.mode
                if cm == LoopType.off:
                    p.queue._repeat.set_mode(LoopType.queue)
                elif cm == LoopType.queue:
                    p.queue._repeat.set_mode(LoopType.track)
                else:
                    p.queue._repeat.set_mode(LoopType.off)
                await p.update_controller(force=True)
            elif act == "skipto":
                # Handle Loop Track mode: must turn off loop to jump
                from cytechlink.enums import LoopType

                if (
                    hasattr(p.queue, "_repeat")
                    and p.queue._repeat.mode == LoopType.track
                ):
                    p.queue._repeat.set_mode(LoopType.off)
                elif hasattr(p.queue, "mode") and str(p.queue.mode).endswith("track"):
                    p.queue.mode = "off"

                p.queue.skipto(int(val) + 1)
                await p.stop()
                await self.bot.broadcast_guild(gid)
            elif act == "remove":
                p.queue.remove(int(val) + 1)
                await p.update_controller(force=True)
                await self.bot.broadcast_guild(gid)
            elif act == "shuffle":
                p.queue.shuffle()
                await self.bot.broadcast_guild(gid)
            elif act == "clear":
                p.queue.clear()
                await self.bot.broadcast_guild(gid)
            elif act == "favorite":
                if uid:
                    import time

                    if isinstance(val, dict):
                        song_data = {
                            "title": val.get("title", "Unknown"),
                            "uri": val.get("uri"),
                            "author": val.get("author", "Unknown"),
                            "identifier": val.get("identifier"),
                            "thumbnail": val.get("thumb")
                            or val.get("thumbnail")
                            or "logo-circle.png",
                            "length": val.get("len") or val.get("length") or 0,
                            "added_at": int(time.time()),
                            "encoded": val.get("encoded"),
                        }
                    elif p and p.current:
                        track = p.current
                        song_data = {
                            "title": track.title,
                            "uri": track.uri,
                            "author": track.author,
                            "identifier": track.identifier,
                            "thumbnail": track.thumbnail,
                            "length": track.length,
                            "added_at": int(time.time()),
                            "encoded": track.track_id,
                        }
                    else:
                        return

                    if (
                        not song_data.get("uri")
                        and not song_data.get("encoded")
                        and not song_data.get("identifier")
                    ):
                        return

                    # Fetch current favorites to check existence
                    user_doc = await self.bot.db_manager.get_user_doc(uid)
                    favorites = user_doc.get("favorites", [])

                    # Robust check: Match by URI or Track ID (encoded) or Identifier or Title+Author
                    exists_index = -1
                    target_uri = song_data.get("uri")
                    target_encoded = song_data.get("encoded")
                    target_id = song_data.get("identifier")
                    target_title = song_data.get("title")
                    target_author = song_data.get("author")

                    for i, fav in enumerate(favorites):
                        # Match URI
                        if target_uri and fav.get("uri") == target_uri:
                            exists_index = i
                            break
                        # Match Encoded
                        if target_encoded and fav.get("encoded") == target_encoded:
                            exists_index = i
                            break
                        # Match Identifier
                        if target_id and fav.get("identifier") == target_id:
                            exists_index = i
                            break
                        # Match Title + Author (Fallback for different providers)
                        if target_title == fav.get(
                            "title"
                        ) and target_author == fav.get("author"):
                            exists_index = i
                            break

                    if exists_index > -1:
                        # Toggle Remove: Pull based on any available unique field
                        target_fav = favorites[exists_index]
                        pull_target = {}
                        if target_fav.get("uri"):
                            pull_target["uri"] = target_fav["uri"]
                        elif target_fav.get("encoded"):
                            pull_target["encoded"] = target_fav["encoded"]
                        elif target_fav.get("identifier"):
                            pull_target["identifier"] = target_fav["identifier"]

                        if pull_target:
                            await self.bot.db_manager.update_user_doc(
                                uid, {"$pull": {"favorites": pull_target}}
                            )
                        else:
                            # Edge case: If no unique field, pull exactly (less reliable but fallback)
                            await self.bot.db_manager.update_user_doc(
                                uid, {"$pull": {"favorites": target_fav}}
                            )
                    else:
                        # Add
                        await self.bot.db_manager.update_user_doc(
                            uid, {"$addToSet": {"favorites": song_data}}
                        )

            # Broadcast update immediately
            await self.bot.broadcast_guild(gid)
            # Second broadcast after a small delay to ensure DB sync for all clients
            await asyncio.sleep(0.5)
            await self.bot.broadcast_guild(gid)
        except Exception:
            pass

    async def post_playlist(self, request):
        payload = await request.json()
        uid = payload.get("user_id")
        action = payload.get("action")
        if not uid:
            return web.json_response({"error": "no_user"}, headers=self.cors_headers)

        user_doc = await self.bot.db_manager.get_user_doc(uid)
        playlists = user_doc.get("playlists", [])

        if action == "create":
            name = payload.get("name", "My Playlist")
            description = payload.get("description", "")
            playlists.append(
                {
                    "name": name,
                    "description": description,
                    "tracks": [],
                    "created_at": int(time.time()),
                }
            )
            await self.bot.db_manager.update_user_doc(
                uid, {"$set": {"playlists": playlists}}
            )
            return web.json_response({"status": "ok"}, headers=self.cors_headers)

        elif action == "delete":
            idx = int(payload.get("index", -1))
            if 0 <= idx < len(playlists):
                playlists.pop(idx)
                await self.bot.db_manager.update_user_doc(
                    uid, {"$set": {"playlists": playlists}}
                )
            return web.json_response({"status": "ok"}, headers=self.cors_headers)

        elif action == "add_track":
            idx = int(payload.get("playlist_index", -1))
            track = payload.get("track")
            if 0 <= idx < len(playlists) and track:
                playlists[idx]["tracks"].append(track)
                await self.bot.db_manager.update_user_doc(
                    uid, {"$set": {"playlists": playlists}}
                )
            return web.json_response({"status": "ok"}, headers=self.cors_headers)

        elif action == "save_queue":
            gid = payload.get("guild_id")
            g = self.bot.get_guild(int(gid)) if gid else None
            p = g.voice_client if g else None
            if not p:
                return web.json_response(
                    {"error": "no_player"}, headers=self.cors_headers
                )

            tracks = []
            if p.current:
                tracks.append(
                    {
                        "title": getattr(p.current, "title", "Unknown"),
                        "author": getattr(p.current, "author", "Unknown Artist"),
                        "uri": getattr(p.current, "uri", ""),
                        "thumbnail": getattr(p.current, "thumbnail", "logo-circle.png"),
                        "length": getattr(p.current, "length", getattr(p.current, "duration", 0)),
                        "encoded": getattr(p.current, "track_id", getattr(p.current, "id", "")),
                    }
                )
            raw_queue = []
            try:
                if hasattr(p.queue, "tracks"):
                    t_prop = p.queue.tracks
                    raw_queue = list(t_prop() if callable(t_prop) else t_prop)
                elif isinstance(p.queue, list):
                    raw_queue = p.queue
                else:
                    raw_queue = list(p.queue)
            except Exception:
                pass

            for t in raw_queue:
                tracks.append(
                    {
                        "title": getattr(t, "title", "Unknown"),
                        "author": getattr(t, "author", "Unknown Artist"),
                        "uri": getattr(t, "uri", ""),
                        "thumbnail": getattr(t, "thumbnail", "logo-circle.png"),
                        "length": getattr(t, "length", getattr(t, "duration", 0)),
                        "encoded": getattr(t, "track_id", getattr(t, "id", "")),
                    }
                )

            name = payload.get("name", f"Queue {time.strftime('%Y-%m-%d')}")
            playlists.append(
                {
                    "name": name,
                    "description": "Saved from queue",
                    "tracks": tracks,
                    "created_at": int(time.time()),
                }
            )
            await self.bot.db_manager.update_user_doc(
                uid, {"$set": {"playlists": playlists}}
            )
            return web.json_response({"status": "ok"}, headers=self.cors_headers)

        elif action == "play_playlist":
            gid = payload.get("guild_id")
            idx = int(payload.get("playlist_index", -1))
            m = self.bot.get_guild(int(gid)).get_member(int(uid)) if gid else None
            if not m or not m.voice:
                return web.json_response({"error": "no_vc"}, headers=self.cors_headers)

            if 0 <= idx < len(playlists):
                pl_tracks = playlists[idx]["tracks"]
                g = self.bot.get_guild(int(gid))
                p = g.voice_client
                if not p:
                    ctx = FakeContext(self.bot, g, m.voice.channel, m)
                    p = await m.voice.channel.connect(cls=cytechlink.Player)

                for t in pl_tracks:
                    track = await p.node.build_track(t["encoded"], requester=m)
                    await p.add_track(track)
                if not p.is_playing:
                    await p.do_next()
            return web.json_response({"status": "ok"}, headers=self.cors_headers)

        elif action == "remove_favorite":
            uri = payload.get("uri")
            favs = user_doc.get("favorites", [])
            new_favs = [f for f in favs if f.get("uri") != uri]
            await self.bot.db_manager.update_user_doc(
                uid, {"$set": {"favorites": new_favs}}
            )
            return web.json_response({"status": "ok"}, headers=self.cors_headers)

        return web.json_response({"error": "unknown_action"}, headers=self.cors_headers)
