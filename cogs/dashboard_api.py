import discord
from discord.ext import commands
from aiohttp import web, WSMsgType
import weakref
import asyncio

from bot import Cyori
import json
import asyncio
import logging
import traceback
import cytechlink
from cytechlink.enums import LoopType

class FakeContext:
    def __init__(self, bot, guild, channel, author):
        self.bot = bot
        self.guild = guild
        self.channel = channel
        self.author = author
        self.user = author # Alias for player.py compatibility
        self.message = None # For complete compatibility
    
    async def send(self, *args, **kwargs):
        if self.channel:
            return await self.channel.send(*args, **kwargs)
        return None

    def typing(self):
        return MagicContext()

class MagicContext:
    async def __aenter__(self):
        return self
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return None

class DashboardAPI(commands.Cog):
    def __init__(self, bot: Cyori):
        self.bot = bot
        self.cors_headers = {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type, Authorization',
        }
        # ZERO-DELAY REALTIME ENGINE
        self.sockets_by_guild = {}
        self.all_sockets = weakref.WeakSet()
        self.bot.loop.create_task(self.realtime_broadcaster())

    async def cog_load(self):
        # Register Routes
        if self.bot.web_app:
            self.bot.web_app.router.add_options('/api/status', self.handle_options)
            self.bot.web_app.router.add_options('/api/control', self.handle_options)
            self.bot.web_app.router.add_get('/api/status', self.get_status)
            self.bot.web_app.router.add_post('/api/control', self.post_control)
            self.bot.web_app.router.add_get('/api/control', self.control_get_handler) # Handle GET gracefully
            self.bot.web_app.router.add_get('/api/search', self.get_search)
            self.bot.web_app.router.add_get('/api/find_voice', self.find_voice_channel)
            self.bot.web_app.router.add_get('/api/stats', self.get_global_stats) # NEW: Public Stats
            self.bot.web_app.router.add_get('/api/join_guild', self.join_guild_endpoint) # NEW: Auto-Join
            self.bot.web_app.router.add_get('/api/user_info', self.get_user_info) # NEW: Profile Info
            self.bot.web_app.router.add_get('/api/bot_guilds', self.get_bot_guilds)
            self.bot.web_app.router.add_get('/api/guild_settings', self.get_guild_settings)
            self.bot.web_app.router.add_post('/api/guild_settings', self.post_guild_settings)
            self.bot.web_app.router.add_options('/api/guild_settings', self.handle_options)
            self.bot.web_app.router.add_options('/api/playlist', self.handle_options)
            self.bot.web_app.router.add_post('/api/playlist', self.post_playlist)
            self.bot.web_app.router.add_get('/api/proxy', self.api_proxy_handler) # Unified Proxy
            self.bot.web_app.router.add_get('/api/gateway', self.websocket_handler) # Zero Delay Gateway
            self.bot.web_app.router.add_get('/api/recommended', self.get_recommended)
            print("[Dashboard] API Routes Registered + Realtime System")

    async def handle_options(self, request):
        resp = web.Response(headers=self.cors_headers)
        return resp

    async def control_get_handler(self, request):
        """Handle GET to /api/control to avoid log spam (Return 200 to silence logs)."""
        return web.json_response({
            'error': 'Method Not Allowed',
            'message': 'Please use POST method for control actions.'
        }, status=200, headers=self.cors_headers)

    async def get_bot_guilds(self, request):
        guilds = [str(g.id) for g in self.bot.guilds]
        return web.json_response({'guilds': guilds}, headers=self.cors_headers)


    async def get_status(self, request):
        guild_id_raw = request.query.get('guild_id')
        if not guild_id_raw:
            return web.json_response({'error': 'Missing guild_id'}, headers=self.cors_headers)

        guild_id = int(guild_id_raw)
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return web.json_response({'error': 'Guild not found'}, headers=self.cors_headers)

        player = guild.voice_client
        
        # Default data
        data = {
            "is_playing": False,
            "title": "Nothing Playing",
            "author": "-",
            "thumbnail": "logo-circle.png", 
            "position": 0,
            "duration": 0,
            "paused": False,
            "volume": 100,
            "queue": [],
            "loop_mode": "Off"
        }

        # OPTIMIZED: Branding Fetch (Cached in Bot Object or Simple DB Check)
        # We assume bot has a simple cache dict, if not we create one locally or just optimize the ID check
        if not hasattr(self.bot, 'branding_cache'):
            self.bot.branding_cache = {}

        # Cache valid for 5 minutes or until config update
        cache_entry = self.bot.branding_cache.get(guild_id)
        if cache_entry and (asyncio.get_running_loop().time() - cache_entry['time'] < 300):
            if cache_entry['img']: data["thumbnail"] = cache_entry['img']
        else:
            # Background update or Quick fetch
            asyncio.create_task(self._update_branding_cache(guild_id))
            # Use specific branding if recently cached was present even if expired (stale-while-revalidate)
            if cache_entry and cache_entry['img']: data["thumbnail"] = cache_entry['img']

        if player and player.is_playing and player.current:
            data["is_playing"] = True
            data["title"] = player.current.title
            data["author"] = player.current.author
            thumb = player.current.thumbnail
            if thumb and "null" not in thumb:
                data["thumbnail"] = thumb
            
            data["position"] = player.position
            data["duration"] = player.current.length
            data["paused"] = player.is_paused
            data["volume"] = player.volume
            
            try:
                loop = player.queue._repeat.mode.name
                data["loop_mode"] = loop.capitalize()
            except: 
                pass

            # Optimized Queue Slicing (Limit to 20 to reduce payload size)
            # Full queue fetching is slow for large playlists
            tracks = list(player.queue.tracks())[:50] 
            for track in tracks:
                data["queue"].append({
                    "title": track.title,
                    "author": track.author,
                    "uri": track.uri
                })

        return web.json_response(data, headers=self.cors_headers)

    async def _update_branding_cache(self, guild_id):
        try:
            from bot import collection_myasync
            # Projection to fetch ONLY necessary fields (Faster)
            db_data = await collection_myasync.find_one(
                {f"guilds.{guild_id}": {"$exists": True}}, 
                {f"guilds.{guild_id}.premium_image": 1, f"guilds.{guild_id}.premium_banner": 1}
            )
            
            img = None
            if db_data and "guilds" in db_data:
                g_data = db_data["guilds"].get(str(guild_id), {})
                img = g_data.get("premium_image") or g_data.get("premium_banner")
            
            if not hasattr(self.bot, 'branding_cache'): self.bot.branding_cache = {}
            self.bot.branding_cache[guild_id] = {
                'img': img,
                'time': asyncio.get_running_loop().time()
            }
        except: pass

    async def post_control(self, request):
        try:
            payload = await request.json()
        except:
            return web.json_response({'error': 'Invalid JSON'}, status=400, headers=self.cors_headers)

        guild_id_raw = payload.get('guild_id')
        user_id_raw = payload.get('user_id')
        action = payload.get('action')
        value = payload.get('value')

        if not guild_id_raw:
            return web.json_response({'error': 'Missing guild_id'}, status=400, headers=self.cors_headers)
        
        try:
            guild_id = int(guild_id_raw)
        except (ValueError, TypeError):
            return web.json_response({'error': 'Invalid guild_id'}, status=400, headers=self.cors_headers)
        
        guild = self.bot.get_guild(guild_id)
        if not guild: 
            return web.json_response({'error': f'Guild {guild_id} not found or bot not in guild'}, status=404, headers=self.cors_headers)
        
        player = guild.voice_client
        user_id = user_id_raw
        
        try:
            skip_update = False 
            member = guild.get_member(int(user_id)) if user_id and str(user_id).isdigit() else None
            
            # 1. Voice Channel Logic (Security + UX)
            if action in ["pause", "skip", "stop", "volume", "shuffle", "loop", "random", "play"]:
                if not member or not member.voice or not member.voice.channel:
                    return web.json_response({'error': 'You must be in a voice channel to use this command! / คุณต้องอยู่ในห้องเสียงเพื่อใช้คำสั่งนี้'}, status=403, headers=self.cors_headers)
                
                if player and member.voice.channel.id != player.channel.id:
                    return web.json_response({'error': 'You must be in the same voice channel as the bot! / คุณต้องอยู่ในห้องเสียงเดียวกับบอท'}, status=403, headers=self.cors_headers)

            if action == "random":
                import random
                from bot import collection_myasync
                try:
                    db_data = await collection_myasync.find_one({})
                    lang = db_data.get("guilds", {}).get(str(guild.id), {}).get("lang", "th")
                except: lang = "th"
                
                search_query = "ytmsearch:Trending Music Thailand" if lang == "th" else "ytmsearch:Trending Global Hits"
                node = player.node if player else None
                if not node and hasattr(self.bot, 'cytech') and self.bot.cytech.nodes:
                    node = list(self.bot.cytech.nodes.values())[0]
                
                if node:
                    load_res = await node.get_tracks(search_query, requester=guild.me)
                    tracks = load_res if isinstance(load_res, list) else getattr(load_res, 'tracks', [])
                    if tracks:
                        track = random.choice(tracks[:15]) # Pick from top 15
                        action = "play"
                        value = {"encoded": track.track_id, "uri": track.uri}
                        print(f"[Dashboard] Random Selected: {track.title}")

            if action == "pause":
                if player: await player.set_pause(not player.is_paused)
            elif action == "skip":
                if player: await player.stop(); skip_update = True
            elif action == "stop":
                if player: await player.teardown(); skip_update = True
            elif action == "volume":
                if player:
                    vol = int(payload.get('value', 100))
                    await player.set_volume(max(0, min(vol, 100)))
            elif action == "shuffle":
                if player: player.queue.shuffle()
            elif action == "loop":
                if player:
                    from cytechlink.enums import LoopType
                    current_mode = player.queue._repeat.mode
                    if current_mode == LoopType.off: player.queue._repeat.set_mode(LoopType.queue)
                    elif current_mode == LoopType.queue: player.queue._repeat.set_mode(LoopType.track)
                    else: player.queue._repeat.set_mode(LoopType.off)
            
            elif action == "play":
                query = value
                print(f"[Dashboard] Play Request: {query} (User: {user_id})")
                
                target_channel = None

                # 1. Resolve Text Channel for feedback
                if member and member.voice and member.voice.channel:
                     if member.voice.channel.permissions_for(guild.me).send_messages:
                         target_channel = member.voice.channel
                if not target_channel and player and hasattr(player, 'controller') and player.controller:
                    try: target_channel = player.controller.channel
                    except: pass
                if not target_channel:
                    for c in guild.text_channels:
                         if c.permissions_for(guild.me).send_messages: target_channel = c; break

                # 2. Auto-join
                if not player and member:
                    try:
                        if member.voice and member.voice.channel:
                            fake_ctx = FakeContext(self.bot, guild, target_channel, member)
                            player = await member.voice.channel.connect(cls=cytechlink.Player(self.bot, member.voice.channel, fake_ctx))
                            await asyncio.sleep(0.5)
                    except: pass

                if player and member:
                     player.context = FakeContext(self.bot, guild, target_channel, member)
                     if not player.dj: player.dj = member

                if query:
                    results = None
                    # Robust Payload Handling
                    import json
                    payload_data = None
                    try:
                        if isinstance(query, dict): payload_data = query
                        elif isinstance(query, str) and query.strip().startswith('{'):
                             payload_data = json.loads(query)
                    except: pass

                    if payload_data:
                        uri = payload_data.get('uri')
                        encoded = payload_data.get('encoded')
                        if encoded:
                            try:
                                # Get any available node for building track
                                node = player.node if player else None
                                if not node and hasattr(self.bot, 'cytech') and self.bot.cytech.nodes:
                                    node = list(self.bot.cytech.nodes.values())[0]
                                
                                if node:
                                    results = [await node.build_track(encoded, requester=member or guild.me)]
                            except: 
                                if uri: query = uri
                        elif uri: query = uri

                    if not results:
                        if isinstance(query, str) and query.startswith("load:"):
                            enc = query[5:]
                            node = player.node if player else None
                            if not node and hasattr(self.bot, 'cytech') and self.bot.cytech.nodes:
                                node = list(self.bot.cytech.nodes.values())[0]
                            if node:
                                results = [await node.build_track(enc, requester=member or guild.me)]
                        else:
                            if not ("http" in query or "https" in query): query = f"ytmsearch:{query}"
                            if player:
                                results = await player.get_tracks(query, requester=member or guild.me)
                            else:
                                # Fallback search using node directly if skip_update/join failed
                                node = None
                                if hasattr(self.bot, 'cytech') and self.bot.cytech.nodes:
                                    node = list(self.bot.cytech.nodes.values())[0]
                                if node:
                                    load_res = await node.get_tracks(query, requester=member or guild.me)
                                    if load_res:
                                        results = load_res if isinstance(load_res, list) else getattr(load_res, 'tracks', [])

                    if results:
                        if not player:
                            return web.json_response({'error': 'Bot is not in a voice channel. Please join a channel first. / บอทไม่ได้อยู่ในห้องเสียง กรุณาเข้าห้องเสียงก่อนสั่งเล่นครับ'}, status=400, headers=self.cors_headers)

                        if isinstance(results, list): await player.add_track(results[0])
                        else: await player.add_track(results.tracks)

                        if not player.is_playing:
                            if target_channel:
                                try:
                                    embed = discord.Embed(title="Searching...", color=0xFFD700)
                                    player.controller = await target_channel.send(embed=embed)
                                except: pass
                            await player.do_next()
                            skip_update = True
                return web.json_response({'status': 'ok'}, headers=self.cors_headers)

            if hasattr(player, "update_controller") and not skip_update:
                await player.update_controller(force=True)

            return web.json_response({'status': 'ok', 'action': action}, headers=self.cors_headers)

        except Exception as e:
            traceback.print_exc()
            return web.json_response({'error': str(e)}, status=500, headers=self.cors_headers)

    # ==========================================
    # REALTIME ZERO-DELAY ENGINE
    # ==========================================
    async def websocket_handler(self, request):
        h = dict(request.headers)
        print(f"DEBUG: WS Attempt from {request.remote}")
        print(f"DEBUG: Headers: {h}")
        ws = web.WebSocketResponse()
        try:
            await ws.prepare(request)
        except Exception as e:
            print(f"DEBUG: WS Prepare Error: {e}")
            # Manual Check: If Cloudflare stripped 'Upgrade' but we know it's a gateway attempt
            # We can't easily bypass aiohttp's prepare, but we can see WHAT is missing.
            return web.Response(status=400, text=f"Handshake Failed: {e}")
        
        self.all_sockets.add(ws)
        gid = None
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = msg.json()
                        op = data.get('op')
                        print(f"[Dashboard WS] Received Op: {op} for Guild: {data.get('guild_id')}")
                        if op == 'connect':
                             gid = int(data.get('guild_id'))
                             if gid not in self.sockets_by_guild: self.sockets_by_guild[gid] = []
                             self.sockets_by_guild[gid].append(ws)
                             asyncio.create_task(self.push_state(ws, gid))
                        elif op == 'control':
                             asyncio.create_task(self.handle_ws_control(data, gid))
                    except: pass
        finally:
            self.all_sockets.discard(ws)
            if gid and gid in self.sockets_by_guild:
                try: self.sockets_by_guild[gid].remove(ws)
                except: pass
        return ws

    async def realtime_broadcaster(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            await asyncio.sleep(0.3) # 300ms Tick
            active = [k for k,v in self.sockets_by_guild.items() if v]
            for gid in active: asyncio.create_task(self.broadcast_guild(gid))

    async def broadcast_guild(self, gid):
        clients = self.sockets_by_guild.get(gid, [])
        if not clients: return
        state = await self.build_state(gid)
        payload = {'op': 'state', 'data': state}
        for ws in clients:
            try: await ws.send_json(payload)
            except: pass

    async def build_state(self, gid):
        g = self.bot.get_guild(gid)
        p = g.voice_client if g else None
        d = {"playing": False, "paused": False, "pos": 0, "len": 0}
        if p and p.is_playing and p.current:
            d.update({
                "playing": True, "paused": p.is_paused, 
                "pos": p.position, "len": p.current.length,
                "title": p.current.title, "author": p.current.author,
                "thumb": p.current.thumbnail if p.current and p.current.thumbnail and "null" not in p.current.thumbnail else "logo-circle.png",
                "vol": p.volume
            })
        return d

    async def handle_ws_control(self, data, gid):
        if not gid: return
        act = data.get('action'); val = data.get('value')
        g = self.bot.get_guild(gid)
        p = g.voice_client if g else None
        if not p: return
        try:
            if act == 'pause': await p.set_pause(not p.is_paused)
            elif act == 'skip': await p.stop()
            elif act == 'stop': await p.teardown()
            elif act == 'volume': await p.set_volume(max(0, min(int(val), 100)))
            elif act == 'seek': await p.seek(int(val))
            # Force Instant Broadcast
            await asyncio.sleep(0.05)
            await self.broadcast_guild(gid)
        except: pass
    
    async def push_state(self, ws, gid):
        state = await self.build_state(gid)
        try: await ws.send_json({'op': 'state', 'data': state})
        except: pass

    async def get_search(self, request):
        query = request.query.get('query')
        guild_id = request.query.get('guild_id')
        
        if not query:
            return web.json_response({'error': 'Missing query'}, headers=self.cors_headers)

        node = None
        if guild_id:
            guild = self.bot.get_guild(int(guild_id))
            if guild and guild.voice_client:
                node = guild.voice_client.node
        
        if not node:
            try:
                if self.bot.cytech.nodes:
                    node = list(self.bot.cytech.nodes.values())[0]
                else:
                    node = self.bot.cytech.get_node()
            except: pass

        if not node:
            return web.json_response({'error': 'No music node available'}, status=503, headers=self.cors_headers)

        try:
            if not ("http" in query or "https" in query):
                search_query = f"ytmsearch:{query}"
            else:
                search_query = query
            
            results = await node.get_tracks(search_query, requester=None)
            search_data = []
            if results:
                tracks = results if isinstance(results, list) else getattr(results, 'tracks', [])
                for track in tracks[:20]:
                    search_data.append({
                        "title": track.title,
                        "author": track.author,
                        "length": track.length,
                        "uri": track.uri,
                        "identifier": track.identifier,
                        "encoded": track.track_id
                    })
            
            return web.json_response({'status': 'ok', 'results': search_data}, headers=self.cors_headers)
        except cytechlink.TrackLoadError:
            return web.json_response({'error': 'Source not supported / ไม่รองรับแหล่งที่มานี้'}, status=400, headers=self.cors_headers)
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500, headers=self.cors_headers)

    async def get_recommended(self, request):
        guild_id_raw = request.query.get('guild_id')
        user_id_raw = request.query.get('user_id')
        
        node = None
        player = None
        current_track = None
        
        # 1. Try to get node from active player first
        if guild_id_raw and str(guild_id_raw).isdigit():
            guild = self.bot.get_guild(int(guild_id_raw))
            if guild and guild.voice_client:
                player = guild.voice_client
                node = getattr(player, 'node', None)
                if player.is_playing and player.current:
                    current_track = player.current

        # 2. Fallback to any node
        if not node:
            try:
                if hasattr(self.bot, 'cytech') and self.bot.cytech.nodes:
                    node = list(self.bot.cytech.nodes.values())[0]
                else:
                    node = self.bot.cytech.get_node()
            except: pass

        if not node:
            return web.json_response({'error': 'No music node available', 'results': []}, status=503, headers=self.cors_headers)

        try:
            from bot import collection_myasync
            
            # STRATEGY 1: User History
            seeds = []
            if user_id_raw:
                try:
                    db_data = await collection_myasync.find_one({}) or {"history": {}}
                    user_history = db_data.get("history", {}).get(str(user_id_raw), {}).get("recently_played", [])
                    if user_history:
                        # Use last 2 songs as seeds
                        seeds = [s.get("identifier") for s in user_history[-2:] if s.get("identifier")]
                except Exception as e:
                    print(f"[Recommended] History DB Error: {e}")

            # STRATEGY 2: Current Track
            if not seeds and current_track and hasattr(current_track, 'identifier'):
                seeds = [current_track.identifier]

            # FETCH RECOMMENDATIONS
            results = None
            if seeds:
                # Use YouTube Music Mix for the first seed
                seed = seeds[-1]
                query = f"https://www.youtube.com/watch?v={seed}&list=RD{seed}"
                print(f"[Recommended] Fetching RD for seed: {seed}")
                results = await node.get_tracks(query, requester=None)

            # STRATEGY 3: Language-based Trending (If no history/RD failed)
            if not results or (not isinstance(results, list) and not getattr(results, 'tracks', [])):
                lang = "th" # Default
                if guild_id_raw:
                    try:
                        guild_doc = await collection_myasync.find_one({})
                        lang = guild_doc.get("guilds", {}).get(str(guild_id_raw), {}).get("lang", "th")
                    except: pass
                
                trending_query = "ytmsearch:Trending Music Thailand" if lang == "th" else "ytmsearch:Trending Global Hits"
                print(f"[Recommended] Fetching language fallback ({lang}): {trending_query}")
                results = await node.get_tracks(trending_query, requester=None)

            # PROCESS RESULTS
            rec_data = []
            if results:
                tracks = results if isinstance(results, list) else getattr(results, 'tracks', [])
                
                # Filter out current track if it's the first in RD list
                start_idx = 0
                if current_track and tracks and getattr(tracks[0], 'identifier', None) == current_track.identifier:
                    start_idx = 1
                
                for track in tracks[start_idx:start_idx+12]:
                    rec_data.append({
                        "title": getattr(track, 'title', 'Unknown Track'),
                        "author": getattr(track, 'author', 'Unknown Author'),
                        "length": getattr(track, 'length', 0),
                        "uri": getattr(track, 'uri', '#'),
                        "thumbnail": getattr(track, 'thumbnail', 'logo-circle.png') or "logo-circle.png",
                        "encoded": getattr(track, 'track_id', None)
                    })

            return web.json_response({'status': 'ok', 'results': rec_data}, headers=self.cors_headers)

        except Exception as e:
            print(f"[Recommended] Global ERROR: {e}")
            traceback.print_exc()
            return web.json_response({'status': 'ok', 'results': [], 'debug_error': str(e)}, headers=self.cors_headers)


    async def find_voice_channel(self, request):
        user_id = request.query.get('user_id')
        if not user_id:
            return web.json_response({'error': 'Missing user_id'}, headers=self.cors_headers)

        try:
            target_id = int(request.query['user_id'])
            # print(f"DEBUG: Searching for user {target_id} in {len(self.bot.guilds)} guilds")

            # 1. Fast Cache Search
            for guild in self.bot.guilds:
                member = guild.get_member(target_id)
                if member and member.voice and member.voice.channel:
                    # print(f"DEBUG: Found in {guild.name}")
                    return web.json_response({
                        'found': True,
                        'guild_id': str(guild.id),
                        'channel_id': str(member.voice.channel.id),
                        'guild_name': guild.name,
                        'voice_channel': member.voice.channel.name
                    }, headers=self.cors_headers)

            # print("DEBUG: User not found in voice")
            return web.json_response({'found': False}, headers=self.cors_headers)
        except Exception as e:
            return web.json_response({'error': str(e)}, headers=self.cors_headers)


    async def post_playlist(self, request):
        """Manage custom playlists (Create/Delete/Add)"""
        try:
            payload = await request.json()
            user_id = str(payload.get('user_id'))
            action = payload.get('action') # 'create', 'delete', 'add_track'
            
            if not user_id or not action:
                return web.json_response({'error': 'Missing params'}, status=400, headers=self.cors_headers)

            from bot import collection_myasync
            user_doc = await collection_myasync.find_one({"user_id": user_id}) or {"playlists": []}
            playlists = user_doc.get("playlists", [])
            
            # Check Limits
            is_premium = await self.bot.is_premium(int(user_id))
            limit = 10 if is_premium else 7
            
            if action == "create":
                name = payload.get('name', 'New Playlist')
                if len(playlists) >= limit:
                    return web.json_response({'error': f'Limit reached ({limit} playlists)'}, status=403, headers=self.cors_headers)
                
                new_pl = {"name": name, "tracks": []}
                await collection_myasync.update_one(
                    {"user_id": user_id},
                    {"$push": {"playlists": new_pl}},
                    upsert=True
                )
                return web.json_response({'status': 'ok', 'message': 'Playlist created'}, headers=self.cors_headers)

            elif action == "delete":
                index = payload.get('index')
                if index is not None and 0 <= int(index) < len(playlists):
                    playlists.pop(int(index))
                    await collection_myasync.update_one(
                        {"user_id": user_id},
                        {"$set": {"playlists": playlists}}
                    )
                    return web.json_response({'status': 'ok'}, headers=self.cors_headers)

            elif action == "add_track":
                pl_index = payload.get('playlist_index')
                track = payload.get('track')
                if pl_index is not None and track:
                    # Logic to push track into nested array
                    field = f"playlists.{pl_index}.tracks"
                    await collection_myasync.update_one(
                        {"user_id": user_id},
                        {"$push": {field: track}}
                    )
                    return web.json_response({'status': 'ok'}, headers=self.cors_headers)

            return web.json_response({'error': 'Invalid action'}, status=400, headers=self.cors_headers)
            
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500, headers=self.cors_headers)

    async def get_global_stats(self, request):
        import time
        uptime_seconds = int(time.time() - self.bot.start_time)
        data = {
            "servers": len(self.bot.guilds),
            "users": len(self.bot.users),
            "uptime": uptime_seconds
        }
        return web.json_response(data, headers=self.cors_headers)

    async def join_guild_endpoint(self, request):
        guild_id = request.query.get('guild_id')
        user_id = request.query.get('user_id')
        access_token = request.query.get('token')
        
        if not (guild_id and user_id and access_token):
             return web.json_response({'error': 'Missing params'}, headers=self.cors_headers)
             
        url = f"https://discord.com/api/guilds/{guild_id}/members/{user_id}"
        headers = {
            "Authorization": f"Bot {self.bot.http.token}",
            "Content-Type": "application/json"
        }
        payload = {
            "access_token": access_token
        }
        
        try:
            print(f"DEBUG: Attempting to add user {user_id} to guild {guild_id}")
            async with self.bot.session.put(url, headers=headers, json=payload) as resp:
                status = resp.status
                text = await resp.text()
                print(f"DEBUG: Discord Response Status: {status} | Body: {text}")
                
                if status in [201, 204]:
                    return web.json_response({'status': 'success'}, headers=self.cors_headers)
                else:
                    return web.json_response({'error': f'Discord API Error: {status}', 'details': text}, headers=self.cors_headers)
        except Exception as e:
            print(f"DEBUG: Exception in join_guild: {e}")
            return web.json_response({'error': str(e)}, headers=self.cors_headers)

    async def get_user_info(self, request):
        user_id = request.query.get('user_id')
        if not user_id:
            return web.json_response({'error': 'Missing user_id'}, headers=self.cors_headers)

        try:
            # Import locally to avoid circular dependencies
            from bot import collection_myasync
            
            # Use filter to find the document that actually contains users
            data = await collection_myasync.find_one({"users": {"$exists": True}})
            if not data:
                # Fallback to general find_one if specific one not found
                data = await collection_myasync.find_one({}) or {}
            
            all_users = data.get("users", {})
            user_data = all_users.get(str(user_id), {})
            
            # Source of truth: check both formats
            is_prem = False
            expire_at = None
            
            # Get plan name, default to "Free" but we will override if premium detected without a plan name
            plan_name = user_data.get("premium_plan") 

            # DEBUG: Print user data for inspection
            print(f"[API] User Info Request: {user_id} | Data Found: {user_data}")

            # 1. Lifetime
            # Check for truthiness rather than strict "is True" (handles 1, True, "true" etc.)
            raw_prem = user_data.get("premium")
            if raw_prem and str(raw_prem).lower() != "false": 
                is_prem = True
                expire_at = "Lifetime"
                if not plan_name: plan_name = "Lifetime"
            
            # 2. Expiration based
            expire = user_data.get("premium_expire")
            if expire:
                try: 
                    expire_val = float(expire)
                    import time
                    if time.time() < expire_val:
                        is_prem = True
                        if not plan_name: plan_name = "Premium"
                    
                    if not expire_at: # Don't override Lifetime
                        expire_at = expire_val
                except:
                    pass

            # Final fallback for plan name
            if not plan_name:
                plan_name = "Free"

            # PLAYLISTS & FAVORITES FETCH (Dedicated per-user document)
            user_doc = await collection_myasync.find_one({"user_id": str(user_id)}) or {}
            playlists = user_doc.get("playlists", [])
            favorites = user_doc.get("favorites", [])

            response_data = {
                "user_id": user_id,
                "premium": is_prem,
                "expire": expire_at,
                "plan": plan_name,
                "joined_at": user_data.get("joined_at"),
                "favorites": favorites,
                "playlists": playlists,
                "limits": {
                    "total": 10 if is_prem else 7,
                    "used": len(playlists) + (1 if favorites else 0)
                }
            }
            
            return web.json_response(response_data, headers=self.cors_headers)
        except Exception as e:
            traceback.print_exc()
            return web.json_response({'error': str(e)}, status=500, headers=self.cors_headers)


    async def get_guild_settings(self, request):
        guild_id = request.query.get('guild_id')
        user_id = request.query.get('user_id')
        if not guild_id or not user_id:
            return web.json_response({'error': 'Missing guild_id or user_id'}, headers=self.cors_headers)

        try:
            guild = self.bot.get_guild(int(guild_id))
            if not guild:
                return web.json_response({'error': 'Guild not found'}, headers=self.cors_headers)

            # Basic permission check: User must be in guild and have manage_guild or be owner
            member = guild.get_member(int(user_id))
            if not member or not (member.guild_permissions.manage_guild or member.id == guild.owner_id):
                return web.json_response({'error': 'Unauthorized'}, status=403, headers=self.cors_headers)

            from bot import collection_myasync
            data = await collection_myasync.find_one({}) or {}
            guild_data = data.get("guilds", {}).get(str(guild_id), {})
            
            # Check if user/owner is premium for branding features
            is_prem = await self.bot.is_premium(int(user_id), guild_id=guild.id) or await self.bot.is_premium(guild.owner_id, guild_id=guild.id)

            settings = {
                "prefix": guild_data.get("prefix", "cm!"),
                "lang": guild_data.get("lang", "en"),
                "mode247": guild_data.get("24/7", False),
                "autoplay": guild_data.get("autoplay", False),
                "dj_mode": guild_data.get("dj_mode", False),
                "vote_mode": guild_data.get("vote_mode", False),
                "dj_role": str(guild_data.get("dj_role", "")),
                "branding": {
                    "image": guild_data.get("premium_image", ""),
                    "banner": guild_data.get("premium_banner", ""),
                    "color": hex(guild_data.get("color", 16766720)).replace("0x", "#") if "color" in guild_data else "#FFD700",
                    "is_premium": is_prem
                },
                "roles": [{"id": str(r.id), "name": r.name} for r in guild.roles if not r.is_default()]
            }

            return web.json_response(settings, headers=self.cors_headers)
        except Exception as e:
            traceback.print_exc()
            return web.json_response({'error': str(e)}, status=500, headers=self.cors_headers)

    async def post_guild_settings(self, request):
        try:
            payload = await request.json()
            guild_id = payload.get('guild_id')
            user_id = payload.get('user_id')
            settings = payload.get('settings', {})
            if isinstance(settings, str):
                try:
                    settings = json.loads(settings)
                except:
                    pass
            
            if not guild_id or not user_id:
                return web.json_response({'error': 'Missing parameters'}, headers=self.cors_headers)

            guild = self.bot.get_guild(int(guild_id))
            if not guild:
                return web.json_response({'error': 'Guild not found'}, headers=self.cors_headers)

            member = guild.get_member(int(user_id))
            if not member or not (member.guild_permissions.manage_guild or member.id == guild.owner_id):
                return web.json_response({'error': 'Unauthorized'}, status=403, headers=self.cors_headers)

            from bot import collection_myasync
            update_data = {}

            # Handle basic settings
            if 'prefix' in settings:
                update_data[f"guilds.{guild_id}.prefix"] = settings['prefix'][:5]
            if 'lang' in settings:
                update_data[f"guilds.{guild_id}.lang"] = settings['lang']
            if 'mode247' in settings:
                update_data[f"guilds.{guild_id}.24/7"] = bool(settings['mode247'])
            if 'autoplay' in settings:
                update_data[f"guilds.{guild_id}.autoplay"] = bool(settings['autoplay'])
            if 'dj_mode' in settings:
                update_data[f"guilds.{guild_id}.dj_mode"] = bool(settings['dj_mode'])
            if 'vote_mode' in settings:
                update_data[f"guilds.{guild_id}.vote_mode"] = bool(settings['vote_mode'])
            if 'dj_role' in settings:
                role_id = settings['dj_role']
                if role_id:
                    update_data[f"guilds.{guild_id}.dj_role"] = int(role_id)
                else:
                    await collection_myasync.update_one({}, {"$unset": {f"guilds.{guild_id}.dj_role": ""}})

            # Handle Branding (Premium Only)
            is_prem = await self.bot.is_premium(int(user_id), guild_id=guild.id) or await self.bot.is_premium(guild.owner_id, guild_id=guild.id)
            if is_prem and 'branding' in settings:
                b = settings['branding']
                if 'image' in b: update_data[f"guilds.{guild_id}.premium_image"] = b['image']
                if 'banner' in b: update_data[f"guilds.{guild_id}.premium_banner"] = b['banner']
                if 'color' in b:
                    color_str = b['color'].lstrip('#')
                    try: update_data[f"guilds.{guild_id}.color"] = int(color_str, 16)
                    except: pass

            if update_data:
                await collection_myasync.update_one({}, {"$set": update_data}, upsert=True)

            # Trigger update if playing
            player = guild.voice_client
            if player:
                if 'autoplay' in settings: player.autoplay = bool(settings['autoplay'])
                if 'mode247' in settings: player.mode247 = bool(settings['mode247'])
                
                if hasattr(player, "update_controller"):
                    await player.update_controller()

            return web.json_response({'status': 'ok'}, headers=self.cors_headers)
        except Exception as e:
            traceback.print_exc()
            return web.json_response({'error': str(e)}, status=500, headers=self.cors_headers)

    async def post_github_webhook(self, request):
        """Receives Git Push updates from GAS Proxy"""
        try:
            data = await request.json()
            repo = data.get("repo", "Unknown Repo")
            author = data.get("author", "Someone")
            msg = data.get("message", "No message")
            
            print(f"\n[🚀 GitHub Sync] {repo} updated by {author}")
            print(f"   - Message: {msg}")
            print(f"   - Context: Receiving via GAS Proxy Broadcaster\n")

            return web.json_response({'status': 'acknowledged'}, headers=self.cors_headers)
        except Exception as e:
            print(f"GitHub Webhook Error: {e}")
            return web.json_response({'status': 'error', 'details': str(e)}, status=400, headers=self.cors_headers)

    async def api_proxy_handler(self, request):
        """Unified Proxy Handler for legacy ?action= calls"""
        action = request.query.get('action')
        if not action:
            return web.json_response({'error': 'Missing action'}, status=400, headers=self.cors_headers)
        
        # Dispatch to specific methods
        handlers = {
            'status': self.get_status,
            'search': self.get_search,
            'recommended': self.get_recommended,
            'user_info': self.get_user_info,
            'stats': self.get_global_stats,
            'find_voice': self.find_voice_channel,
            'bot_guilds': self.get_bot_guilds,
            'guild_settings': self.get_guild_settings
        }
        
        handler = handlers.get(action)
        if handler:
            return await handler(request)
            
        return web.json_response({'error': f'Unknown action: {action}'}, status=400, headers=self.cors_headers)

async def setup(bot: Cyori):
    await bot.add_cog(DashboardAPI(bot))
