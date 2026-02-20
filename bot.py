import os
import sys
import time
import asyncio
import aiohttp
from aiohttp import web, WSMsgType
import weakref
import collections
import discord
import pymongo
import pathlib
import traceback
import json
from discord.ext import commands, tasks
from motor.motor_asyncio import AsyncIOMotorClient

# Import from utils
from utils.config import (
    BOT_TOKEN, API_KEY, MONGO_URI, SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET,
    LAVALINK_HOST, LAVALINK_PORT, LAVALINK_PASS, LAVALINK_ID,
    DEFAULT_PREFIX, OWNER_IDS, VERSION, DBL_TOKEN,
    DEPRECATED_MODE, NEW_BOT_ID, WEB_PORT
)
from utils import config as ui_config
from utils.i18n import i18n
import logging

# Silence Logs for Deprecated Bot
if DEPRECATED_MODE:
    logging.getLogger("discord").setLevel(logging.ERROR)
    logging.getLogger("discord.http").setLevel(logging.ERROR)
    logging.getLogger("discord.app_commands").setLevel(logging.ERROR)

# --- GLOBAL CONSTANTS ---
SOURCE_GUILD_ID = 1413525842490953891 # ดิสต้นทาง
SYNC_ROLE_ID = 1413696208920117368   # ยศที่ต้องการแจก/ถอด

# Global DB Clients
myclient = pymongo.MongoClient(MONGO_URI)
myasync = AsyncIOMotorClient(MONGO_URI)

# Database selection logic
if getattr(ui_config, "DEV_MODE", False) and not getattr(ui_config, "IMPERSONATE_MAIN", False):
    # Isolated DB for Development to avoid messing up production data
    db_name = f"{getattr(ui_config, 'DB_NAME', 'Komo')}_Dev"
else:
    # Production DB (or Impersonation Mode)
    db_name = getattr(ui_config, "DB_NAME", "Komo")

db_c = myclient[db_name]
db_a = myasync[db_name]

collection_myclient = db_c["music_data"]
collection_myasync = db_a["music_data"]

from core.database import DatabaseManager
db_manager = DatabaseManager(collection_myasync)

class Cyori(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bot_version = VERSION
        self._nodes_started = False
        self.api_key = API_KEY
        self.dbl_token = DBL_TOKEN 
        self.spotify_client_id = SPOTIFY_CLIENT_ID
        self.spotify_client_secret = SPOTIFY_CLIENT_SECRET
        self.session: aiohttp.ClientSession | None = None
        self._status_index = 0
        self.i18n = i18n
        self.start_time = time.time()  # Track bot start time for payment usage
        self.web_app = None
        self.web_runner = None
        self._processed_events = set() # Cache for de-duplication
        self.error_log_channel_id = getattr(ui_config, "LOG_CHANNEL_ID", 0)
        self.error_webhook_url = getattr(ui_config, "LOG_WEBHOOK_URL", None)
        
        # Dashboard Core
        self.sockets_by_guild = {}
        self.all_sockets = weakref.WeakSet()
        self.branding_cache = {}
        self.cors_headers = {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type, Authorization',
        }

    async def broadcast_guild(self, guild_id: int):
        """Broadcasts the current player state to all connected dashboard websockets for a guild."""
        clients = self.sockets_by_guild.get(guild_id, [])
        if not clients: 
            return
            
        state = await self.build_dashboard_state(guild_id)
        payload = {'op': 'state', 'data': state}
        
        for ws in clients[:]:
            try:
                if not ws.closed:
                    await ws.send_json(payload)
                else:
                    clients.remove(ws)
            except:
                try: clients.remove(ws)
                except: pass

    async def build_dashboard_state(self, guild_id: int):
        """Constructs a JSON-serializable state object for the dashboard."""
        try:
            g = self.get_guild(guild_id)
            if not g: return {"playing": False, "paused": False, "pos": 0, "len": 0}

            p = g.voice_client
            d = {"playing": False, "paused": False, "pos": 0, "len": 0}
            
            # Check if player exists and has a current track
            if p and hasattr(p, 'current') and p.current:
                # Loop Mode Logic (Safe Access)
                loop_mode = "Off"
                try:
                    if hasattr(p.queue, 'mode'): # Standard Wavelink 2/3
                         loop_mode = str(p.queue.mode).split('.')[-1].capitalize()
                    elif hasattr(p.queue, '_repeat'): # Data structure specific
                         loop_mode = p.queue._repeat.mode.name.capitalize()
                except: pass

                # Queue Logic (Safe Iterator)
                queue_tracks = []
                try:
                    # Handle different queue implementations logic
                    raw_queue = []
                    if hasattr(p.queue, 'tracks'):
                        # Wavelink 3.x property or method
                        t = p.queue.tracks
                        raw_queue = list(t() if callable(t) else t)
                    elif isinstance(p.queue, list):
                        raw_queue = p.queue
                    else:
                        # Fallback for iterable queues
                        raw_queue = list(p.queue)

                    for t in raw_queue[:20]: # Limit to 20 for payload size
                         queue_tracks.append({
                             "title": getattr(t, 'title', 'Unknown'),
                             "author": getattr(t, 'author', 'Unknown'),
                             "uri": getattr(t, 'uri', ''),
                             "encoded": getattr(t, 'track_id', '') or getattr(t, 'id', ''),
                             "duration": getattr(t, 'length', getattr(t, 'duration', 0)),
                             "thumbnail": t.thumbnail if getattr(t, 'thumbnail', None) and "null" not in t.thumbnail else "logo-circle.png"
                         })
                except: pass

                d.update({
                    "playing": True, # Activity Flag
                    "paused": p.is_paused if hasattr(p, 'is_paused') else False,
                    "pos": p.position if hasattr(p, 'position') else 0,
                    "duration": p.current.length if hasattr(p.current, 'length') else 0,
                    "is_stream": getattr(p.current, 'is_stream', False),
                    "title": getattr(p.current, 'title', 'Unknown Track'),
                    "author": getattr(p.current, 'author', 'Unknown Artist'),
                    "uri": getattr(p.current, 'uri', ''),
                    "encoded": getattr(p.current, 'track_id', ''),
                    "thumbnail": p.current.thumbnail if getattr(p.current, 'thumbnail', None) and "null" not in p.current.thumbnail else "logo-circle.png",
                    "vol": p.volume if hasattr(p, 'volume') else 100,
                    "loop_mode": loop_mode,
                    "queue": queue_tracks
                })
            
            return d
        except Exception as e:
            print(f"[Dashboard State Error] {e}")
            return {"playing": False, "paused": False, "error": str(e)}

    async def on_cytechlink_track_start(self, player, track):
        """Broadcast state when a track starts."""
        await self.broadcast_guild(player.guild.id)

    async def on_cytechlink_track_end(self, player, track, reason):
        """Broadcast state when a track ends."""
        await self.broadcast_guild(player.guild.id)

    async def on_cytechlink_track_exception(self, player, track, exception):
        """Dispatched when a track error occurs."""
        error_msg = f"Track Exception: {track.title} ({track.uri})\nException: {exception.get('message', 'No message')}"
        
        # Broadcast Error to Dashboard if possible (Optional future enhancement)
        await self.broadcast_guild(player.guild.id)
        
        embed = discord.Embed(title="🎵 Music Player Error", color=discord.Color.orange())
        embed.add_field(name="Track", value=f"[{track.title}]({track.uri})", inline=False)
        embed.add_field(name="Guild", value=f"{player.guild.name} ({player.guild.id})", inline=True)
        embed.description = f"```py\n{exception}\n```"
        embed.timestamp = discord.utils.utcnow()

        # Try Webhook
        if self.error_webhook_url:
            try:
                from discord import Webhook
                async with aiohttp.ClientSession() as session:
                    webhook = Webhook.from_url(self.error_webhook_url, session=session)
                    await webhook.send(embed=embed, username="Cyori DJ Watchdog", avatar_url=self.user.display_avatar.url if self.user else None)
                    return
            except: pass

        # Try Channel Fallback
        if self.error_log_channel_id:
            try:
                channel = self.get_channel(self.error_log_channel_id)
                if channel: await channel.send(embed=embed)
            except: pass

        print(f"[Music Error] {error_msg}")

    async def setup_hook(self):
        await self.load_extension("cogs.events")
        self.session = aiohttp.ClientSession()
        self.web_app = web.Application()

        # Final wall for Slash Commands
        # Final wall for Slash Commands
        async def global_interaction_check(interaction: discord.Interaction):
            # Whitelist commands that CAN be used in DM
            dm_whitelist = ["help", "ping", "stats", "botinfo", "premium check", "redeem"]
            
            if not interaction.guild:
                if interaction.command and interaction.command.qualified_name not in dm_whitelist:
                    await interaction.response.send_message("❌ This command can only be used in a server! / คำสั่งนี้ใช้ได้เฉพาะในเซิร์ฟเวอร์เท่านั้น!", ephemeral=True)
                    return False
            
            if await self.check_deprecation(interaction):
                return False # Stop command execution
            return True

        self.tree.interaction_check = global_interaction_check
        
        # Initialize Dashboard
        await self.setup_dashboard()

        # Global check for Prefix Commands
        @self.check
        async def global_prefix_check(ctx):
            # Whitelist commands that CAN be used in DM
            dm_whitelist = ["help", "ping", "stats", "botinfo", "premium", "redeem"]
            
            if not ctx.guild:
                if ctx.command and ctx.command.qualified_name not in dm_whitelist:
                    await ctx.send("❌ This command can only be used in a server! / คำสั่งนี้ใช้ได้เฉพาะในเซิร์ฟเวอร์เท่านั้น!")
                    return False
            return True


    async def setup_dashboard(self):
        """Initializes the embedded Dashboard System."""
        if self.web_app:
            from utils.dashboard_core import DashboardSystem
            self.dashboard = DashboardSystem(self)
            await self.dashboard.setup_routes(self.web_app)

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()
        if self.web_runner:
            await self.web_runner.cleanup()
        await super().close()

    async def get_lang(self, guild_id: int) -> str:
        try:
            guild_data = await db_manager.get_guild(guild_id)
            return guild_data.get("lang", "en")
        except Exception:
            pass
        return "en"

    async def get_user_vote(self, user_id: int) -> bool:
        url = f"https://top.gg/api/bots/{self.user.id}/check?userId={user_id}"
        headers = {"Authorization": self.dbl_token}
        if not self.session: return False
        async with self.session.get(url, headers=headers) as resp:
            try:
                data: dict = await resp.json()
                return data.get("voted", 0) == 1
            except Exception as e:
                print(f"Failed to fetch vote: {e}")
                return False

    async def register_to_proxy(self, target_url=None):
        """Registers this bot's local endpoint to the GAS Proxy for dynamic routing."""
        proxy_url = getattr(ui_config, "STRIPE_PROXY_URL", None)
        if not proxy_url or DEPRECATED_MODE: return
        
        # Use provided URL or fallback to DOMAIN_URL from .env
        my_url = target_url or getattr(ui_config, "DOMAIN_URL", None)
        if not my_url: return

        payload = {
            "action": "register_bot",
            "url": my_url
        }
        
        try:
            async with self.session.post(proxy_url, json=payload, timeout=5) as resp:
                if resp.status == 200:
                    try:
                        data = await resp.json()
                        print(f"[Proxy] Registered: {my_url}")
                    except:
                        print(f"[Proxy] Registered (Raw Response)")
                else:
                    print(f"[Proxy] Registration Failed with status: {resp.status}")
        except Exception as e:
            print(f"[Proxy] Error registering to {proxy_url}: {e} (Type: {type(e).__name__})")

    @tasks.loop(seconds=3)
    async def gas_poll_task(self):
        """Polls the GAS Proxy for queued events (Dashboard/Git) to support No-Address mode."""
        proxy_url = getattr(ui_config, "STRIPE_PROXY_URL", None)
        if not proxy_url or DEPRECATED_MODE: return

        try:
            url = f"{proxy_url}?action=poll"
            async with self.session.get(url, timeout=5) as resp:
                if resp.status == 200:
                    events = await resp.json()
                    if not events: return
                    
                    for event_wrap in events:
                        e_id = event_wrap.get("id")
                        if e_id in self._processed_events: continue
                        
                        event = event_wrap.get("data", {})
                        e_type = event.get("type")
                        
                        if e_type == "github_push":
                            print(f"\n[🚀 GitHub Sync (via Poll)] {event.get('repo')} updated by {event.get('author')}")
                            print(f"   - Message: {event.get('message')}\n")
                            self._processed_events.add(e_id)
                        
                        elif e_type == "control":
                            payload = event.get("payload", {})
                            inner_id = payload.get("event_id")
                            if inner_id and inner_id in self._processed_events:
                                self._processed_events.add(e_id)
                                continue
                                
                            print(f"[📬 Polling] Received Remote Control: {payload.get('action')}")
                            
                            # Forward to local API for execution
                            local_url = f"http://127.0.0.1:{WEB_PORT}/api/control"
                            async with self.session.post(local_url, json=payload) as local_resp:
                                res = await local_resp.json()
                                print(f"   - Execution Result: {res.get('status')}")
                                self._processed_events.add(e_id)
                        
                        # Cleanup cache if it gets too large
                        if len(self._processed_events) > 1000:
                            self._processed_events.clear()

        except Exception as e:
             # Silently fail polling to avoid console spam
             pass

    async def post_guild_count(self):
        url = f"https://top.gg/api/bots/{self.user.id}/stats"
        headers = {
            "Authorization": self.dbl_token,
            "Content-Type": "application/json"
        }
        payload = {"server_count": len(self.guilds)}
        if not self.session: return
        try:
            async with self.session.post(url, json=payload, headers=headers) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    if not DEPRECATED_MODE:
                        print(f"[TopGG Error] Failed to post stats for {self.user.id}: {resp.status} - {text}")
                else:
                    if not DEPRECATED_MODE:
                        print(f"[TopGG] Successfully posted {len(self.guilds)} servers for {self.user.id}")
        except Exception as e:
            if not DEPRECATED_MODE:
                print(f"[TopGG Error] Exception during stats post: {e}")

    async def is_premium(self, user_id: int, guild_id: int = None) -> bool:
        if not user_id: return False
        try:
            # Check User Premium
            u_data = await db_manager.get_user(str(user_id))
            
            # 1. Lifetime
            if u_data.get("premium") is True:
                return True
            
            # 2. Expiration
            expire = u_data.get("premium_expire")
            if expire and isinstance(expire, (int, float)):
                import time
                return time.time() < expire
                
            return False
        except:
            return False

    async def check_vote(self, user_id: int, guild_id: int = None):
        # 1. Check Owner (Bot Owner)
        bot_info = await self.application_info()
        owner = bot_info.owner
        if user_id == owner.id or user_id in OWNER_IDS:
             return True

        # 2. Check Premium (User or Guild Owner)
        # 2a. Check User
        if await self.is_premium(user_id, guild_id=guild_id):
            return True
            
        # 2b. Check Guild Owner (if configured to allow server-wide perk)
        if guild_id:
            guild = self.get_guild(guild_id)
            if guild and await self.is_premium(guild.owner_id, guild_id=guild.id):
                return True

        # 3. Check Vote
        return await self.get_user_vote(user_id)

    def none_play_embed(self, lang="en", guild_data: dict = None):
        from utils.luxury import LuxuryEmbed, luxury_line
        
        # UI Components Links
        support = f"[Support]({ui_config.SUPPORT_URL})"
        invite = f"[Invite]({ui_config.INVITE_URL})"
        donate = f"[Donate]({ui_config.DONATE_URL})"
        vote = f"[Vote](https://top.gg/bot/{self.user.id}/vote)" if self.user else "[Vote](https://top.gg)"

        play_embed = LuxuryEmbed(
            description=f"> {support} • {invite} • {donate} • {vote}\n\n"
                        f"{luxury_line()}\n"
                        f"🎵 **{self.i18n.get('join_voice_chat_channel', lang).replace('{channel}', 'Voice Channel')}**\n"
                        f"✨ **Commands:** `/help` or `/play`",
            color=ui_config.EMBED_COLOR
        )
        if self.user:
            play_embed.set_author(
                name=self.i18n.get("join_voice_chat_title", lang),
                icon_url=self.user.avatar.url if self.user.avatar else self.user.default_avatar.url
            )
        
        # Custom Banner Logic (Server Owner Premium)
        banner_url = ui_config.BANNER_URL
        if guild_data:
             # Check if we should use premium banner using stored config
             # We assume if the config exists, the owner IS premium (or was).
             # To be strict, we really should check owner premium status again?
             # But fetching owner ID here might be expensive if not in guild_data.
             # Use the field if it exists. (User said: "If expired, save config. Restore if pay again").
             # So we must Check Premium Status before showing it.
             # Wait, `is_premium` is async. `none_play_embed` is sync.
             # We can't await `is_premium` here.
             # Solution: `update_guild_embed` should pass a logic flag?
             # Or assumption: If `premium_banner` is in DB, show it?
             # User said: "If expire, reset default".
             # So `check_premium_expiry` handles logic? No, we agreed to store data and check at runtime.
             # BUT `none_play_embed` is synchronous.
             # We passed `guild_data`. We can perhaps store a cache flag in `update_guild_embed` which is async.
             pass

        # Since we can't await here, we rely on the caller to sanitize guild_data?
        # OR we just show it if it exists, and rely on `check_premium_expiry` to unset it?
        # NO, user said "Keep data". So `premium_banner` stays in DB.
        # But `none_play_embed` will use it if present.
        # So inactive premium will still show banner? This violates "reset default".
        # We need a way to check premium sync or move embed creation async.
        # Let's change `none_play_embed` to just check `premium_banner` presence, 
        # BUT we MUST filter `guild_data` before passing it in `update_guild_embed`.
        
        if guild_data and guild_data.get("premium_banner"):
             banner_url = guild_data.get("premium_banner")

        play_embed.set_image(url=banner_url)
        play_embed.add_luxury_footer(self, lang)
        return play_embed

