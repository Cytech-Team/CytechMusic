import discord
from aiohttp import web, WSMsgType
import json
import asyncio
import traceback
import time
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
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
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
        router.add_route('*', '/api/proxy', self.handle_proxy_route)
        
        # Keep existing specific routes for now, migrate gradually
        router.add_get('/api/status', self.get_status)
        router.add_post('/api/control', self.post_control)
        router.add_get('/api/gateway', self.websocket_handler)
        router.add_get('/api/search', self.get_search)
        router.add_get('/api/lyrics', self.get_lyrics)
        router.add_get('/api/user_info', self.get_user_info)
        router.add_get('/api/bot_guilds', self.get_bot_guilds) # Deprecated by proxy, keeping for compat if needed
        router.add_get('/api/stats', self.get_stats)
        router.add_get('/api/join_guild', self.join_guild_endpoint)
        router.add_get('/api/guild_settings', self.get_guild_settings)
        router.add_post('/api/guild_settings', self.post_guild_settings)
        router.add_post('/api/playlist', self.post_playlist)
        router.add_get('/api/find_voice', self.get_find_voice)
        router.add_get('/api/recommended', self.get_recommended)
        
        router.add_options('/api/playlist', self.handle_options)
        router.add_options('/api/status', self.handle_options)
        router.add_options('/api/control', self.handle_options)
        router.add_options('/api/guild_settings', self.handle_options)
        
        # Start Periodic Broadcaster (Heartbeat)
        self.bot.loop.create_task(self.realtime_broadcaster())
        print("[CytechX] Dashboard System Embedded & Ready (Refactored Proxy)")

    async def handle_proxy_route(self, request):
        """Delegates to the new APIProxyManager"""
        return await self.api_proxy.handle_proxy_request(request)

    async def realtime_broadcaster(self):
        """Ticker for smooth progress bars (300ms). Only broadcasts to guilds with active WS."""
        while not self.bot.is_closed():
            active_guilds = [gid for gid, clients in self.bot.sockets_by_guild.items() if clients]
            for gid in active_guilds:
                asyncio.create_task(self.bot.broadcast_guild(gid))
            await asyncio.sleep(0.3)

    async def handle_options(self, request):
        return web.Response(headers=self.cors_headers)

    async def get_bot_guilds(self, request):
        return web.json_response({"guilds": [str(g.id) for g in self.bot.guilds]}, headers=self.cors_headers)

    async def get_status(self, request):
        gid = request.query.get('guild_id')
        if not gid: return web.json_response({'error': 'no_guild'}, headers=self.cors_headers)
        state = await self.bot.build_dashboard_state(int(gid))
        return web.json_response(state, headers=self.cors_headers)

    async def get_stats(self, request):
        data = {
            "guilds": len(self.bot.guilds),
            "users": len(self.bot.users),
            "playing": sum(1 for p in self.bot.voice_clients if hasattr(p, 'is_playing') and p.is_playing)
        }
        return web.json_response(data, headers=self.cors_headers)

    async def post_control(self, request):
        try:
            payload = await request.json()
            gid = payload.get('guild_id')
            if gid:
                asyncio.create_task(self.handle_ws_control(payload, int(gid)))
                return web.json_response({'status': 'ok'}, headers=self.cors_headers)
            return web.json_response({'error': 'no_guild'}, headers=self.cors_headers)
        except Exception as e:
            return web.json_response({'error': str(e)}, headers=self.cors_headers)

    async def join_guild_endpoint(self, request):
        # Auto-join user to Support Server via OAuth token from dashboard
        guild_id = request.query.get('guild_id')
        user_id = request.query.get('user_id')
        token = request.query.get('token')
        if not (guild_id and user_id and token): return web.json_response({'error': 'missing_params'}, headers=self.cors_headers)
        
        url = f"https://discord.com/api/guilds/{guild_id}/members/{user_id}"
        headers = {"Authorization": f"Bot {self.bot.http.token}", "Content-Type": "application/json"}
        try:
            async with self.bot.session.put(url, headers=headers, json={"access_token": token}) as r:
                return web.json_response({'status': 'ok', 'discord': r.status}, headers=self.cors_headers)
        except:
            return web.json_response({'error': 'failed'}, headers=self.cors_headers)

    async def get_guild_settings(self, request):
        gid = request.query.get('guild_id')
        from bot import collection_myasync
        data = await collection_myasync.find_one({}) or {}
        guild_data = data.get("guilds", {}).get(str(gid), {})
        return web.json_response(guild_data, headers=self.cors_headers)

    async def post_guild_settings(self, request):
        payload = await request.json()
        gid = payload.get('guild_id')
        settings = payload.get('settings', {})
        
        from bot import collection_myasync
        await collection_myasync.update_one({}, {"$set": {f"guilds.{gid}": settings}}, upsert=True)
        # Update embed
        await self.bot.update_guild_embed(settings, guild_id=gid)
        return web.json_response({'status': 'ok'}, headers=self.cors_headers)

    async def get_user_info(self, request):
        uid = request.query.get('user_id')
        if not uid: 
            return web.json_response({'error': 'no_user'}, headers=self.cors_headers)
        
        try:
            target_uid = int(uid)
            from bot import collection_myasync
            
            # Fetch Data with Defaults
            data_all = await collection_myasync.find_one({"users": {"$exists": True}}) or {}
            user_data = data_all.get("users", {}).get(str(uid), {})
            
            user_doc = await collection_myasync.find_one({"user_id": str(uid)}) or {}
            
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
                "playlists": user_doc.get("playlists", []) if user_doc else []
            }
            return web.json_response(resp, headers=self.cors_headers)
        except Exception as e:
            print(f"[Dashboard] Get User Info Error for {uid}: {e}")
            # Return basic info even if error occurs, to prevent frontend crash
            return web.json_response({
                "id": uid,
                "premium": False, 
                "plan": "Error Loading",
                "favorites": [],
                "playlists": []
            }, headers=self.cors_headers)

    async def get_search(self, request):
        q = request.query.get('q') or request.query.get('query')
        if not q: return web.json_response([], headers=self.cors_headers)
        
        try:
            node = list(cytechlink.NodePool._nodes.values())[0]
            results = await node.get_tracks(f"ytmsearch:{q}", requester=self.bot.user)
            tracks = []
            res_list = results if isinstance(results, list) else getattr(results, 'tracks', [])
            for t in res_list[:20]:
                tracks.append({
                    "title": t.title, "author": t.author, "uri": t.uri, 
                    "thumbnail": t.thumbnail or "logo-circle.png", "length": t.length, "encoded": t.track_id
                })
            return web.json_response({"results": tracks}, headers=self.cors_headers)
        except:
            return web.json_response({"results": []}, headers=self.cors_headers)

    async def get_lyrics(self, request):
        query = request.query.get('query')
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
                    
                return web.json_response({"lyrics": text, "source": "Auto"}, headers=self.cors_headers)
            else:
                 return web.json_response({"error": "not_found"}, headers=self.cors_headers)
        except Exception as e:
            return web.json_response({"error": str(e)}, headers=self.cors_headers)

    async def get_find_voice(self, request):
        uid = request.query.get('user_id')
        if not uid: 
            return web.json_response({"found": False}, headers=self.cors_headers)
        
        try:
            target_uid = int(uid)
            # Iterate over guilds to find where the user has a voice state
            for guild in self.bot.guilds:
                member = guild.get_member(target_uid)
                if member and member.voice and member.voice.channel:
                    return web.json_response({
                        "found": True,
                        "guild_id": str(guild.id),
                        "guild_name": guild.name,
                        "channel_id": str(member.voice.channel.id)
                    }, headers=self.cors_headers)
        except Exception as e:
            print(f"[Dashboard] Find Voice Error: {e}")
            
        return web.json_response({"found": False}, headers=self.cors_headers)

    async def get_recommended(self, request):
        try:
            if not cytechlink.NodePool._nodes:
                return web.json_response({"results": []}, headers=self.cors_headers)
            node = list(cytechlink.NodePool._nodes.values())[0]
            results = await node.get_tracks("ytmsearch:trending music", requester=self.bot.user)
            tracks = []
            res_list = results if isinstance(results, list) else getattr(results, 'tracks', [])
            import random
            random.shuffle(res_list)
            for t in res_list[:20]:
                tracks.append({
                    "title": t.title, "author": t.author, "uri": t.uri, 
                    "thumbnail": t.thumbnail or "logo-circle.png", "length": t.length, "encoded": t.track_id
                })
            return web.json_response({"results": tracks}, headers=self.cors_headers)
        except:
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
                        op = data.get('op')
                        if op == 'connect':
                            gid = int(data.get('guild_id'))
                            if gid not in self.bot.sockets_by_guild: self.bot.sockets_by_guild[gid] = []
                            self.bot.sockets_by_guild[gid].append(ws)
                            # Push initial state
                            state = await self.bot.build_dashboard_state(gid)
                            await ws.send_json({'op': 'state', 'data': state})
                        elif op == 'control':
                             asyncio.create_task(self.handle_ws_control(data, gid))
                    except: pass
        finally:
            self.bot.all_sockets.discard(ws)
            if gid and gid in self.bot.sockets_by_guild:
                try: self.bot.sockets_by_guild[gid].remove(ws)
                except: pass
        return ws

    async def handle_ws_control(self, data, gid):
        if not gid: return
        act = data.get('action')
        val = data.get('value')
        uid = data.get('user_id')
        g = self.bot.get_guild(gid)
        p = g.voice_client if g else None
        
        try:
            if act == "play":
                 m = g.get_member(int(uid)) if uid else None
                 if not m or not m.voice: return
                 if not p:
                     p = await m.voice.channel.connect(cls=cytechlink.Player)
                 
                 encoded = val.get('encoded') if isinstance(val, dict) else val
                 uri = val.get('uri') if isinstance(val, dict) else None
                 
                 # Guard: reject bogus strings from frontend (JS undefined→'undefined')
                 if encoded in (None, '', 'undefined', 'null'):
                     encoded = None
                 
                 node = p.node
                 added_track = None
                 
                 if encoded:
                     added_track = await node.build_track(encoded, requester=m)
                     await p.add_track(added_track)
                 elif uri:
                     results = await node.get_tracks(uri, requester=m)
                     if results:
                         if hasattr(results, 'tracks'):
                             for t in results.tracks: await p.add_track(t)
                             added_track = results.tracks[0] if results.tracks else None
                         else:
                             added_track = results[0] if isinstance(results, list) else results
                             await p.add_track(added_track)
                 
                 # ── Anchor controller to jukebox embed (first connect only) ──
                 already_playing = p.is_playing
                 if not p.controller:
                     try:
                         from bot import collection_myasync
                         data = await collection_myasync.find_one({}) or {}
                         gd = data.get("guilds", {}).get(str(gid), {})
                         ch_id  = gd.get("channel_id")
                         emb_id = gd.get("play_embed_id")
                         if ch_id and emb_id:
                             setup_ch = self.bot.get_channel(int(ch_id))
                             if setup_ch:
                                 try:
                                     p.controller = await setup_ch.fetch_message(int(emb_id))
                                 except Exception:
                                     pass
                     except Exception:
                         pass

                 # ── Send Discord notification in setup channel ──
                 if added_track:
                     try:
                         from bot import collection_myasync
                         import discord as _d
                         _data = await collection_myasync.find_one({}) or {}
                         _gd = _data.get("guilds", {}).get(str(gid), {})
                         _ch_id = _gd.get("channel_id")
                         if _ch_id:
                             _ch = self.bot.get_channel(int(_ch_id))
                             if _ch:
                                 _title = getattr(added_track, 'title', 'Unknown Track')
                                 if already_playing:
                                     _desc = f"🎵 **{_title}**\nเพิ่มลงคิวจาก Dashboard โดย {m.mention}"
                                 else:
                                     _desc = f"▶️ **{_title}**\nเริ่มเล่นจาก Dashboard โดย {m.mention}"
                                 _notif = _d.Embed(description=_desc, color=0xFFD700)
                                 asyncio.create_task(_ch.send(embed=_notif, delete_after=12))
                     except Exception:
                         pass

                 if not already_playing: await p.do_next()


            elif not p: return
            
            elif act == 'pause': await p.set_pause(not p.is_paused)
            elif act == 'skip': await p.stop()
            elif act == 'stop': await p.teardown()
            elif act == 'volume': await p.set_volume(max(0, min(int(val), 100)))
            elif act == 'seek': await p.seek(int(val))
            elif act == 'loop':
                from cytechlink.enums import LoopType
                cm = p.queue._repeat.mode
                if cm == LoopType.off: p.queue._repeat.set_mode(LoopType.queue)
                elif cm == LoopType.queue: p.queue._repeat.set_mode(LoopType.track)
                else: p.queue._repeat.set_mode(LoopType.off)
            elif act == 'skipto':
                p.queue.skipto(int(val) + 1)
                await p.stop()
            elif act == 'remove':
                p.queue.remove(int(val) + 1)
            elif act == 'favorite':
                if uid:
                    from bot import collection_myasync
                    import time
                    
                    if isinstance(val, dict):
                         song_data = {
                            "title": val.get('title', 'Unknown'), 
                            "uri": val.get('uri'), 
                            "author": val.get('author', 'Unknown'),
                            "identifier": val.get('identifier'), 
                            "thumbnail": val.get('thumb') or val.get('thumbnail') or "logo-circle.png",
                            "length": val.get('len') or val.get('length') or 0, 
                            "added_at": int(time.time()), 
                            "encoded": val.get('encoded')
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
                            "encoded": track.track_id
                        }
                    else: 
                        return

                    if not song_data.get('uri'): return

                    # Fetch current favorites to check existence
                    user_doc = await collection_myasync.find_one({"user_id": str(uid)}) or {}
                    favorites = user_doc.get("favorites", [])
                    
                    # Check if already exists (by URI)
                    exists = False
                    for fav in favorites:
                        if fav.get('uri') == song_data['uri']:
                            exists = True
                            break
                    
                    if exists:
                        # Remove
                        await collection_myasync.update_one(
                            {"user_id": str(uid)}, 
                            {"$pull": {"favorites": {"uri": song_data['uri']}}}
                        )
                    else:
                        # Add
                        await collection_myasync.update_one(
                            {"user_id": str(uid)}, 
                            {"$addToSet": {"favorites": song_data}}, 
                            upsert=True
                        )
            
            # Broadcast update
            await asyncio.sleep(0.05)
            await self.bot.broadcast_guild(gid)
        except: pass


    async def post_playlist(self, request):
        payload = await request.json()
        uid = payload.get('user_id')
        action = payload.get('action')
        if not uid: return web.json_response({'error': 'no_user'}, headers=self.cors_headers)
        
        from bot import collection_myasync
        user_doc = await collection_myasync.find_one({"user_id": str(uid)}) or {"user_id": str(uid), "playlists": [], "favorites": []}
        playlists = user_doc.get("playlists", [])
        
        if action == "create":
            name = payload.get('name', 'My Playlist')
            description = payload.get('description', '')
            playlists.append({"name": name, "description": description, "tracks": [], "created_at": int(time.time())})
            await collection_myasync.update_one({"user_id": str(uid)}, {"$set": {"playlists": playlists}}, upsert=True)
            return web.json_response({'status': 'ok'}, headers=self.cors_headers)
            
        elif action == "delete":
            idx = int(payload.get('index', -1))
            if 0 <= idx < len(playlists):
                playlists.pop(idx)
                await collection_myasync.update_one({"user_id": str(uid)}, {"$set": {"playlists": playlists}}, upsert=True)
            return web.json_response({'status': 'ok'}, headers=self.cors_headers)
            
        elif action == "add_track":
            idx = int(payload.get('playlist_index', -1))
            track = payload.get('track')
            if 0 <= idx < len(playlists) and track:
                playlists[idx]['tracks'].append(track)
                await collection_myasync.update_one({"user_id": str(uid)}, {"$set": {"playlists": playlists}}, upsert=True)
            return web.json_response({'status': 'ok'}, headers=self.cors_headers)
            
        elif action == "save_queue":
            gid = payload.get('guild_id')
            g = self.bot.get_guild(int(gid)) if gid else None
            p = g.voice_client if g else None
            if not p: return web.json_response({'error': 'no_player'}, headers=self.cors_headers)
            
            tracks = []
            if p.current:
                tracks.append({"title": p.current.title, "author": p.current.author, "uri": p.current.uri, "thumbnail": p.current.thumbnail, "length": p.current.length, "encoded": p.current.track_id})
            for t in p.queue.tracks():
                tracks.append({"title": t.title, "author": t.author, "uri": t.uri, "thumbnail": t.thumbnail, "length": t.length, "encoded": t.track_id})
            
            name = payload.get('name', f"Queue {time.strftime('%Y-%m-%d')}")
            playlists.append({"name": name, "description": "Saved from queue", "tracks": tracks, "created_at": int(time.time())})
            await collection_myasync.update_one({"user_id": str(uid)}, {"$set": {"playlists": playlists}}, upsert=True)
            return web.json_response({'status': 'ok'}, headers=self.cors_headers)
            
        elif action == "play_playlist":
             gid = payload.get('guild_id')
             idx = int(payload.get('playlist_index', -1))
             m = self.bot.get_guild(int(gid)).get_member(int(uid)) if gid else None
             if not m or not m.voice: return web.json_response({'error': 'no_vc'}, headers=self.cors_headers)
             
             if 0 <= idx < len(playlists):
                 pl_tracks = playlists[idx]['tracks']
                 g = self.bot.get_guild(int(gid))
                 p = g.voice_client
                 if not p:
                     ctx = FakeContext(self.bot, g, m.voice.channel, m)
                     p = await m.voice.channel.connect(cls=cytechlink.Player)
                 
                 for t in pl_tracks:
                     track = await p.node.build_track(t['encoded'], requester=m)
                     await p.add_track(track)
                 if not p.is_playing: await p.do_next()
             return web.json_response({'status': 'ok'}, headers=self.cors_headers)
             
        elif action == "remove_favorite":
            uri = payload.get('uri')
            favs = user_doc.get("favorites", [])
            new_favs = [f for f in favs if f.get('uri') != uri]
            await collection_myasync.update_one({"user_id": str(uid)}, {"$set": {"favorites": new_favs}}, upsert=True)
            return web.json_response({'status': 'ok'}, headers=self.cors_headers)

        return web.json_response({'error': 'unknown_action'}, headers=self.cors_headers)
