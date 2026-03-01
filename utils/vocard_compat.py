import asyncio
import json
import logging
import traceback
import typing

from aiohttp import web, WSMsgType
from cytechlink.enums import LoopType

class VocardCompatLayer:
    """
    Compatibility layer to handle WebSocket communication from the 
    Vocard-Dashboard frontend using CytechMusic's backend data structures.
    """
    
    def __init__(self, bot):
        self.bot = bot
        self.log = logging.getLogger("VocardCompat")
        
    async def handle_ws_user(self, request):
        """
        Handler for /ws_user route. This simulates Vocard's user connection.
        """
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        
        # Keep track of the socket in our pool for broadcasting
        self.bot.all_sockets.add(ws)
        
        user_id = None
        guild_id = None
        
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = msg.json()
                        op = data.get("op")
                        
                        # Handshake from Vocard's websocket.js connect method
                        if op == "initUser" or op == "initPlayer":
                            user_id = data.get("userId")
                            # Send mock response back to satisfy Vocard's frontend
                            await ws.send_json({"op": op})
                            
                        # When user clicks a server from 'header.html/menu.html'
                        elif op == "getMutualGuilds":
                            await self._send_mutual_guilds(ws, user_id, request)
                            
                        elif op == "updateGuild":
                            guild_id = data.get("guildId")
                            user_data = data.get("user", {})
                            if not user_id: 
                                user_id = user_data.get("userId")
                                
                            is_joined = data.get("isJoined", False)
                            
                            if is_joined and guild_id:
                                # Vocard frontend is now viewing this guild
                                await self._send_guild_state(ws, guild_id, user_id)
                                
                        elif op == "playerClose":
                           # Do nothing, frontend asks bot to stop sending data for this guild
                           pass

                        # Playback control operations
                        elif op in ["play", "pause", "resume", "skip", "stop", "volume", "seek", "loop", "shuffle"]:
                            await self._handle_control(op, data, ws, guild_id, user_id)
                            
                    except Exception as e:
                        self.log.error(f"Error parsing Vocard WS message: {e}\n{traceback.format_exc()}")
        finally:
            self.bot.all_sockets.discard(ws)
            
        return ws

    async def _send_mutual_guilds(self, ws, user_id, request):
        """Send a list of mutual guilds so they appear in the Vocard header dropdown"""
        if not user_id:
            await ws.send_json({"op": "getMutualGuilds", "guilds": {}})
            return
            
        target_uid = int(user_id)
        guilds = {}
        for g in self.bot.guilds:
            if g.get_member(target_uid):
                guilds[str(g.id)] = {
                    "name": g.name,
                    "avatar": str(g.icon.url) if g.icon else None
                }
                
        await ws.send_json({"op": "getMutualGuilds", "guilds": guilds})
        
    async def _send_guild_state(self, ws, guild_id, user_id):
        """Build and send a state payload that Vocard-Dashboard JS expects"""
        guild = self.bot.get_guild(int(guild_id))
        if not guild:
            return
            
        settings = await self.bot.db_manager.get_guild(guild_id)
        state_data = {
            "op": "updateGuild",
            "guildId": str(guild_id),
            "settings": settings,  # E.g. queueType, voteDisable, 24/7 etc.
        }
        
        # Audio Player State
        p = guild.voice_client 
        if p:
            is_playing = p.is_playing() if hasattr(p, 'is_playing') else getattr(p, 'is_playing', False)
            is_paused = p.is_paused() if hasattr(p, 'is_paused') else getattr(p, 'is_paused', False)
            
            # Vocard expects track objects in its own format
            current_track = self._format_track(p.current) if getattr(p, 'current', None) else None
            
            queue = []
            if hasattr(p, 'queue'):
                q = p.queue if isinstance(p.queue, list) else list(p.queue)
                queue = [self._format_track(t) for t in q[:50]] # Limit to 50 for payload size
                
            repeat_mode = "Off"
            if hasattr(p.queue, '_repeat'):
                rm = p.queue._repeat.mode
                if rm == LoopType.track: repeat_mode = "Track"
                elif rm == LoopType.queue: repeat_mode = "Queue"
                
            player_state = {
                "channelId": str(p.channel.id) if getattr(p, 'channel', None) else None,
                "isPaused": is_paused,
                "isPlaying": is_playing,
                "current": current_track,
                "queue": queue,
                "position": int(p.position) if hasattr(p, 'position') else 0,
                "volume": int(p.volume) if hasattr(p, 'volume') else 100,
                "repeatMode": repeat_mode,
                "dj": settings.get("dj_role"),
            }
            state_data["player"] = player_state
            
        await ws.send_json(state_data)
        
    def _format_track(self, t) -> dict:
        """Convert a cytechlink Track to Vocard frontend format"""
        if getattr(t, 'is_stream', False):
            length = 0
            is_stream = True
        else:
            length = t.length if hasattr(t, 'length') else 0
            is_stream = False
            
        # Optional: Grab requester info if it exists
        requester_id = None
        requester_avatar = None
        if hasattr(t, 'requester') and t.requester:
            requester_id = str(getattr(t.requester, 'id', ''))
            req_av = getattr(t.requester, 'display_avatar', None)
            requester_avatar = req_av.url if req_av else None
            
        return {
            "title": getattr(t, 'title', 'Unknown'),
            "author": getattr(t, 'author', 'Unknown'),
            "length": length,
            "identifier": getattr(t, 'identifier', ''),
            "uri": getattr(t, 'uri', ''),
            "isStream": is_stream,
            "isSeekable": not getattr(t, 'is_stream', False),
            "sourceName": "youtube", # fallback
            "thumbnail": getattr(t, 'thumbnail', '/static/img/default-banner.svg'),
            "requester": {
                "id": requester_id,
                "avatar": requester_avatar
            }
        }
        
    async def _handle_control(self, op, data, ws, guild_id, user_id):
        """Map Vocard control actions to CytechMusic's player"""
        if not guild_id: return
        guild = self.bot.get_guild(int(guild_id))
        p = guild.voice_client if guild else None
        
        # Play operation is complex if we have to connect & search
        if op == "play":
            query = data.get("query")
            if not query: return
            
            # Use original handler to perform join & play 
            # Note: handle_ws_control from standard dashboard_core will do all the setup channel embeds too!
            dummy_payload = {
                "action": "play",
                "value": {"uri": query}, # Vocard usually sends a URI or search term
                "user_id": user_id
            }
            # Instantiate original core
            core = getattr(self.bot, 'dashboard_system', None)
            if core:
                await core.handle_ws_control(dummy_payload, guild_id)
            
            # Send state back immediately
            await self._send_guild_state(ws, guild_id, user_id)
            return

        # Player must exist for the rest
        if not p: return

        if op == "pause":
            await p.set_pause(True)
        elif op == "resume":
            await p.set_pause(False)
        elif op == "skip":
            await p.stop()
        elif op == "stop":
            await p.teardown()
        elif op == "volume":
            vol = data.get("volume", 100)
            await p.set_volume(max(0, min(int(vol), 100)))
        elif op == "seek":
            pos = data.get("position", 0)
            await p.seek(pos)
        elif op == "loop":
            mode = data.get("mode", "Off")
            if hasattr(p.queue, '_repeat'):
                if mode == "Track":
                    p.queue._repeat.set_mode(LoopType.track)
                elif mode == "Queue":
                    p.queue._repeat.set_mode(LoopType.queue)
                else:
                    p.queue._repeat.set_mode(LoopType.off)
        elif op == "shuffle":
            if hasattr(p.queue, 'shuffle'):
                p.queue.shuffle()

        # Reply with the updated state
        await self._send_guild_state(ws, guild_id, user_id)
