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


    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        # Find a suitable channel to send welcome message
        channel = discord.utils.get(guild.text_channels, name="general") or \
                  next((c for c in guild.text_channels if c.permissions_for(guild.me).send_messages), None)
        
        if channel:
            lang = "th" # Default to Thai for this project? Or check region.
            if guild.preferred_locale == "en-US": lang = "en"
            
            from utils.luxury import LuxuryEmbed, luxury_line
            embed = LuxuryEmbed(
                title=f"≡ƒæï α╕éα╕¡α╕Üα╕äα╕╕α╕ôα╕ùα╕╡α╣êα╣Çα╕èα╕┤α╕ì {self.user.name} α╣Çα╕éα╣ëα╕▓α╕¬α╕╣α╣êα╣Çα╕ïα╕┤α╕úα╣îα╕ƒα╣Çα╕ºα╕¡α╕úα╣î!",
                description=f"α╕éα╕¡α╕Üα╕äα╕╕α╕ôα╕ùα╕╡α╣êα╣äα╕ºα╣ëα╕ºα╕▓α╕çα╣âα╕êα╣âα╕½α╣ëα╣Çα╕úα╕▓α╕öα╕╣α╣üα╕Ñα╣Çα╕¬α╕╡α╕óα╕çα╣Çα╕₧α╕Ñα╕çα╣âα╕Öα╕½α╣ëα╕¡α╕çα╕éα╕¡α╕çα╕äα╕╕α╕ôα╕äα╕úα╕▒α╕Ü\n\n"
                            f"{luxury_line()}\n"
                            f"≡ƒôî **α╕ºα╕┤α╕ÿα╕úα╣Çα╕úα╕┤α╣êα╕íα╕òα╣ëα╕Ö:**\n"
                            f"1. α╣âα╕èα╣ëα╕äα╕│α╕¬α╕▒α╣êα╕ç `/setup` α╣Çα╕₧α╕╖α╣êα╕¡α╕¬α╕úα╣ëα╕▓α╕çα╕½α╣ëα╕¡α╕çα╕éα╕¡α╣Çα╕₧α╕Ñα╕çα╕¡α╕▒α╕òα╣éα╕Öα╕íα╕▒α╕òα╕┤ (α╣üα╕Öα╕░α╕Öα╕│α╕íα╕▓α╕ü!)\n"
                            f"2. α╕½α╕úα╕╖α╕¡α╕¬α╕┤α╕íα╕úα╕ôα╣îα╕äα╕│α╕¬α╕▒α╣êα╕ç `/play <α╕èα╕╖α╣êα╕¡α╣Çα╕₧α╕Ñα╕ç>` α╣Çα╕₧α╕╖α╣êα╕¡α╣Çα╕Ñα╣êα╕Öα╣Çα╣Çα╕₧α╕Ñα╕çα╕ùα╕▒α╕Öα╕ùα╕╡\n"
                            f"3. α╕₧α╕┤α╕íα╕₧α╣î `/help` α╣Çα╕₧α╕╖α╣êα╕¡α╕öα╕╣α╕äα╕│α╕¬α╕▒α╣êα╕çα╕ùα╕▒α╣ëα╕çα╕½α╕íα╕ö\n\n"
                            f"≡ƒÆÄ **Premium:** α╕¬α╕Öα╕▒α╕Üα╕¬α╕Öα╕╕α╕Öα╣Çα╕úα╕▓α╣Çα╕₧α╕╖α╣êα╕¡α╕¢α╕Ñα╕öα╕Ñα╣çα╕¡α╕äα╕ƒα╕╡α╣Çα╕êα╕¡α╕úα╣î 24/7 α╣üα╕Ñα╕░α╕äα╕╕α╕ôα╕áα╕▓α╕₧α╣Çα╕¬α╕╡α╕óα╕çα╕¬α╕╣α╕çα╕¬α╕╕α╕ö!\n"
                            f"{luxury_line()}",
                color=ui_config.EMBED_COLOR
            )
            embed.set_thumbnail(url=self.user.display_avatar.url)
            embed.set_image(url=ui_config.BANNER_URL)
            
            view = discord.ui.View()
            view.add_item(discord.ui.Button(label="Support Server", url=ui_config.SUPPORT_URL, style=discord.ButtonStyle.link))
            view.add_item(discord.ui.Button(label="Invite Me", url=ui_config.INVITE_URL, style=discord.ButtonStyle.link))
            
            try:
                await channel.send(embed=embed, view=view)
            except:
                pass

    async def update_guild_embed(self, guild_data, guild_id=None):
        if guild_data:
            channel_id = guild_data.get("channel_id")
            queue_embed_id = guild_data.get("queue_embed_id")
            play_embed_id = guild_data.get("play_embed_id")
            lang = guild_data.get("lang", "en") 
            
            # Sanitize Premium Features (Check Owner Premium)
            # We must check if the Server Owner is premium to allow showing the banner
            try:
                guild = self.get_guild(int(guild_id)) if guild_id else None
                if guild:
                    is_owner_prem = await self.is_premium(guild.owner_id, guild_id=guild.id)
                    if not is_owner_prem:
                        # Hide premium assets if owner not premium
                        guild_data = guild_data.copy()
                        if "premium_banner" in guild_data: del guild_data["premium_banner"]
                        if "premium_image" in guild_data: del guild_data["premium_image"]
            except:
                pass

            if not (channel_id and queue_embed_id and play_embed_id):
                return
            try:
                channel = self.get_channel(channel_id)
                if not channel:
                    return
                queue_message = await channel.fetch_message(queue_embed_id)
                play_message = await channel.fetch_message(play_embed_id)
                await queue_message.edit(embed=discord.Embed(title=self.i18n.get("no_queue", lang), color=ui_config.EMBED_COLOR))
                
                from cytechlink import JukeboxIdleView
                player = guild.voice_client if guild else None
                view = JukeboxIdleView(player, bot=self, lang=lang)
                await play_message.edit(embed=self.none_play_embed(lang, guild_data), view=view)
            except Exception:
                pass

    async def update_all_guild_embeds_on_startup(self):
        try:
            data = await asyncio.wait_for(collection_myasync.find_one({}), timeout=5)
        except asyncio.TimeoutError:
            if not DEPRECATED_MODE: print("MongoDB timeout!")
            data = {"guilds": {}}

        if not data or "guilds" not in data:
            return
        semaphore = asyncio.Semaphore(5)

        async def sem_task(gid, gdata):
            async with semaphore:
                await self.update_guild_embed(gdata, guild_id=gid)

        await asyncio.gather(*(sem_task(gid, gdata) for gid, gdata in data["guilds"].items()))

    async def start_nodes(self):
        if self._nodes_started:
            return
        from cytechlink import NodePool
        self.cytech = NodePool()
        await self.wait_until_ready()
        await self.cytech.create_node(
            bot=self,
            host=LAVALINK_HOST,
            port=LAVALINK_PORT,
            password=LAVALINK_PASS,
            identifier=LAVALINK_ID,
            spotify_client_id=self.spotify_client_id,
            spotify_client_secret=self.spotify_client_secret,
        )
        self._nodes_started = True

    async def start_web_server(self):
        """Starts the aiohttp web server."""
        if not self.web_app: return
        
        self.web_runner = web.AppRunner(self.web_app)
        await self.web_runner.setup()
        
        port = WEB_PORT
        site = web.TCPSite(self.web_runner, '0.0.0.0', port)
        await site.start()

        if not DEPRECATED_MODE: print(f"[Web] Server started on port {port}")

    @tasks.loop(minutes=5)
    async def update_stats_task(self):
        try:
            # Post stats for each instance using its own DBL_TOKEN
            await self.post_guild_count()
            
            mode = "OLD" if DEPRECATED_MODE else "MAIN"
            print(f"[Stats] {self.user.name} ({mode}) synced {len(self.guilds)} guilds to Top.gg.")
        except Exception as e:
            print(f"[Stats Error] {e}")

    @tasks.loop(seconds=10)
    async def status_loop(self):
        if not self.is_ready():
            return
            
        try:
            statuses = [
                discord.Activity(type=discord.ActivityType.watching, name="Cyori | /help"),
                discord.Activity(type=discord.ActivityType.competing, name=f"My name is {self.user.name if self.user else 'Cyori'} and I can play music"),
                discord.Activity(type=discord.ActivityType.listening, name=f"{len(self.guilds)} servers"),
                discord.Activity(type=discord.ActivityType.playing, name=f"with {len(self.users)} users"),
            ]
            await self.change_presence(activity=statuses[self._status_index % len(statuses)])
            self._status_index += 1
        except Exception as e:
            # Silence connection-related errors during status updates
            pass

    async def connect_db(self):
        try:
            myclient.server_info()
            await myasync.server_info()
            if not DEPRECATED_MODE: print("Successfully connected to MongoDB!")
        except Exception as e:
            raise Exception("Cannot connect MongoDB:", e)

    async def on_ready(self):
        if not DEPRECATED_MODE:
            os.system("cls" if os.name == "nt" else "clear")
            print(r"""
   ______ __  __ ____  ____  ____ 
  / ____/ \ \/ // __ \/ __ \/  _/ 
 / /       \  // / / / /_/ // /   
/ /___     / // /_/ / _, _// /    
\____/    /_/ \____/_/ |_/___/    
    ~ P R E M I U M   G O L D ~
            """)
            print(f"Logged in as {self.user}")
        else:
            print(f"[*] {self.user} ({self.user.id}) [OLD BOT] is now running silently (MIGRATION MODE).")
            print(f"    - Deprecated Mode: {DEPRECATED_MODE}")
            print(f"    - Main Bot ID: {NEW_BOT_ID}")

        if self.update_stats_task.is_running():
            self.update_stats_task.cancel()
        self.update_stats_task.start()

        if not DEPRECATED_MODE:
            if not self.sync_community_roles_task.is_running():
                self.sync_community_roles_task.start()

        await self.connect_db()
        
        # Load Cogs (Skip if dumb/deprecated mode)
        if DEPRECATED_MODE:
            pass # Silent
        else:
            await self.update_all_guild_embeds_on_startup()
            BASE_DIR = pathlib.Path(__file__).parent
            COGS_DIR = BASE_DIR / "cogs"
            loaded_exts = list(self.extensions.keys())
            
            for cog_file in COGS_DIR.glob("*.py"):
                cog_name = f"cogs.{cog_file.stem}"
                try:
                    if cog_name in loaded_exts:
                        await self.unload_extension(cog_name)
                    await self.load_extension(cog_name)
                    print(f"Loaded cog: {cog_file.stem}")
                except Exception as e:
                    print(f"Failed to load cog {cog_name}: {e}")

        # Sync command tree
        try:
            # Skip heavy syncing for Deprecated Bot to save rate limits
            if DEPRECATED_MODE:
                print(f"[*] Identity: {self.user.id} [MIGRATION MODE] - Skipping command sync.")
            else:
                # Smart Sync: If in DEV_MODE with a TEST_GUILD_ID, sync to that guild only (Instant)
                dev_mode = getattr(ui_config, "DEV_MODE", False)
                test_guild_id = getattr(ui_config, "TEST_GUILD_ID", 0)
                
                if dev_mode and test_guild_id:
                    guild = discord.Object(id=test_guild_id)
                    self.tree.copy_global_to(guild=guild)
                    sy = await self.tree.sync(guild=guild)
                    print(f"[*] DEV_MODE: Synced {len(sy)} commands to Test Guild ({test_guild_id})")
                else:
                    sy = await self.tree.sync()
                    print(f"[*] Synced {len(sy)} commands")
            print('------')
        except Exception as e:
            print(f"Failed to sync commands: {e}")

        if self.status_loop.is_running():
            self.status_loop.cancel()
        self.status_loop.start()

        # --- ROLE-BASED FEATURES ---
        if not DEPRECATED_MODE:
            # 1. MAIN BOT: Register to Proxy, Start Nodes, Start API
            print(f"[*] Identity: {self.user.id} [MAIN BOT] - Initializing Services...")
            await self.register_to_proxy()
            if not self.gas_poll_task.is_running():
                self.gas_poll_task.start()
            
            await self.start_nodes()
            await self.start_web_server()
        else:
            # 2. OLD BOT: Run Proactive Migration
            print(f"[*] Identity: {self.user.id} [MIGRATION MODE] - Scanning guilds for proactive migration...")
            for guild in self.guilds:
                async def check_and_migrate(g):
                    try:
                        # Check cache first, then fetch
                        has_new_bot = g.get_member(int(NEW_BOT_ID)) or await g.fetch_member(int(NEW_BOT_ID))
                        if has_new_bot:
                            await self.perform_migration_and_leave(g)
                    except: pass
                
                self.loop.create_task(check_and_migrate(guild))

    # --- Role Sync Logic ---
    @tasks.loop(hours=6)
    async def sync_community_roles_task(self):
        """Audit all guilds to sync roles for members who are in source guild AND have premium."""
        if DEPRECATED_MODE: return
        
        source_guild = self.get_guild(SOURCE_GUILD_ID)
        if not source_guild:
            try: source_guild = await self.fetch_guild(SOURCE_GUILD_ID)
            except: return

        print(f"[*] Starting Role Sync Audit for {len(self.guilds)} guilds...")
        
        # Get list of all member IDs in source guild
        try:
            source_member_ids = set()
            async for m in source_guild.fetch_members(limit=None):
                source_member_ids.add(m.id)
        except Exception as e:
            print(f"Failed to fetch source members: {e}")
            return

        for guild in self.guilds:
            if guild.id == SOURCE_GUILD_ID: continue
            role = guild.get_role(SYNC_ROLE_ID)
            if not role: continue
            
            try:
                # Audit members in this guild
                async for member in guild.fetch_members(limit=None):
                    # Logic: Must be in SOURCE and MUST have PREMIUM
                    is_in_source = member.id in source_member_ids
                    is_prem = await self.is_premium(member.id)
                    
                    should_have_role = is_in_source and is_prem
                    has_role = role in member.roles
                    
                    try:
                        if should_have_role and not has_role:
                            await member.add_roles(role, reason="Cyori Audit: Member + Premium Sync")
                        elif not should_have_role and has_role:
                            await member.remove_roles(role, reason="Cyori Audit: Not Premium/Source anymore")
                    except: pass
            except: pass
        print("[*] Role Sync Audit Completed.")




    # --- Deprecation Logic ---
    async def check_deprecation(self, interaction_or_msg):
        if not DEPRECATED_MODE:
            return False
            
        # 1. Handle Slash Commands / Buttons / Menus (ALWAYS Redirect)
        if isinstance(interaction_or_msg, discord.Interaction):
            pass # Proceed to show migration for any interaction type
        
        # 2. Handle Prefix Messages (Only if it's a command or mention)
        elif isinstance(interaction_or_msg, discord.Message):
            # Check if bot is mentioned
            if self.user in interaction_or_msg.mentions:
                 pass # Proceed to show migration
            else:
                 # Check if starts with prefix
                 guild_id = str(interaction_or_msg.guild.id) if interaction_or_msg.guild else None
                 prefix = DEFAULT_PREFIX
                 try:
                     # Attempt to get the real prefix from DB
                     data = await collection_myasync.find_one({}) or {}
                     if guild_id and str(guild_id) in data.get("guilds", {}):
                         prefix = data["guilds"][str(guild_id)].get("prefix", DEFAULT_PREFIX)
                 except: pass
                 
                 # Only trigger if it's an actual command call (starts with prefix)
                 if not interaction_or_msg.content.startswith(prefix):
                     return False
        
        new_bot_invite = f"https://discord.com/api/oauth2/authorize?client_id={NEW_BOT_ID}&permissions=3533896&scope=bot%20applications.commands"


        lang = "en"
        try:
            guild_id = str(interaction_or_msg.guild.id) if interaction_or_msg.guild else None
            data = await collection_myasync.find_one({}) or {}
            lang = data.get("guilds", {}).get(guild_id, {}).get("lang", "en") if guild_id else "en"
        except:
            pass

        # Text and translations
        title = "≡ƒÜ¿ Cyori has specialized to a NEW version!" if lang == "en" else "≡ƒÜ¿ Cyori α╕óα╣ëα╕▓α╕óα╣äα╕¢α╣Çα╕ºα╕¡α╕úα╣îα╕èα╕▒α╕Öα╣âα╕½α╕íα╣êα╣üα╕Ñα╣ëα╕º!"
        desc = (
            "This old bot instance is **no longer active**. Please move to our new, faster, and more stable version to continue playing music!\n\n"
            "**[≡ƒæë CLICK HERE TO INVITE THE NEW CYORI]({invite})**\n\n"
            "*Your premium and playlists will still work on the new bot.*"
            if lang == "en" else
            "α╕Üα╕¡α╕ùα╕òα╕▒α╕ºα╣Çα╕üα╣êα╕▓α╕Öα╕╡α╣ë **α╣Çα╕Ñα╕┤α╕üα╣âα╕èα╣ëα╕çα╕▓α╕Öα╣üα╕Ñα╣ëα╕º** α╣Çα╕₧α╕╖α╣êα╕¡α╕üα╕▓α╕úα╕ƒα╕▒α╕çα╣Çα╕₧α╕Ñα╕çα╕ùα╕╡α╣êα╕Ñα╕╖α╣êα╕Öα╕éα╕╢α╣ëα╕Öα╣üα╕Ñα╕░α╣Çα╕¬α╕ûα╕╡α╕óα╕úα╕üα╕ºα╣êα╕▓α╣Çα╕öα╕┤α╕í α╕úα╕Üα╕üα╕ºα╕Öα╕óα╣ëα╕▓α╕óα╣äα╕¢α╣âα╕èα╣ëα╕Üα╕¡α╕ùα╕òα╕▒α╕ºα╣âα╕½α╕íα╣êα╣üα╕ùα╕Öα╕Öα╕░α╕äα╕úα╕▒α╕Ü!\n\n"
            "**[≡ƒæë α╕äα╕Ñα╕┤α╕üα╕ùα╕╡α╣êα╕Öα╕╡α╣êα╣Çα╕₧α╕╖α╣êα╕¡α╣Çα╕èα╕┤α╕ì Cyori α╕òα╕▒α╕ºα╣âα╕½α╕íα╣ê]({invite})**\n\n"
            "*α╕₧α╕úα╕╡α╣Çα╕íα╕╡α╕óα╕íα╣üα╕Ñα╕░α╣Çα╕₧α╕Ñα╕óα╣îα╕Ñα╕┤α╕¬α╕òα╣îα╕éα╕¡α╕çα╕äα╕╕α╕ôα╕êα╕░α╕òα╕▓α╕íα╣äα╕¢α╕öα╣ëα╕ºα╕óα╕¡α╕▒α╕òα╣éα╕Öα╕íα╕▒α╕òα╕┤*"
        ).format(invite=new_bot_invite)

        embed = discord.Embed(
            title=title,
            description=desc,
            color=0xFF0000 # Red for alert
        )
        embed.set_image(url="https://i.postimg.cc/qBGwRzwN/wmremove-transformed-(1).jpg")
        embed.set_footer(text="Cyori Migration System ΓÇó 2026")
        
        try:
            if isinstance(interaction_or_msg, discord.Interaction):
                if not interaction_or_msg.response.is_done():
                    await interaction_or_msg.response.send_message(embed=embed, ephemeral=True)
                else:
                    await interaction_or_msg.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction_or_msg.reply(embed=embed, delete_after=30)
        except:
             pass
            
        return True


    # --- Event Handlers ---
    async def on_interaction(self, interaction: discord.Interaction):
        if await self.check_deprecation(interaction):
            return


    async def on_message(self, message: discord.Message):
        if await self.check_deprecation(message):
            return
        if message.author.bot:
            return
        if not message.guild:
            await message.reply(
                f"Hello! I'm {self.user.name}, a music bot. Invite me: https://discord.com/api/oauth2/authorize?client_id={self.user.id}&permissions=3533896&scope=bot%20applications.commands"
            )
            return

        try:
            data = await asyncio.wait_for(collection_myasync.find_one({}), timeout=5) or {}
        except asyncio.TimeoutError:
            data = {"guilds": {}}

        guild_id = str(message.guild.id)
        # Default defaults
        prefix = DEFAULT_PREFIX
        lang = "en"
        
        if "guilds" in data and guild_id in data["guilds"]:
            g_data = data["guilds"][guild_id]
            prefix = g_data.get("prefix", DEFAULT_PREFIX)
            lang = g_data.get("lang", "en")

        prefixes = commands.when_mentioned_or(prefix)(self, message)
        
        for p in prefixes:
            if message.content.startswith(p):
                 if any(command.name in message.content for command in self.commands):
                    await self.process_commands(message)
                    try:
                        await message.delete()
                    except:
                        pass
                    break
        
        if message.content in [f"<@{self.user.id}>", f"<@!{self.user.id}>"]:
            async with message.channel.typing():
                try:
                    await message.delete()
                except:
                    pass
                
                embed = discord.Embed(
                    title=self.i18n.get("hello_title", lang, author=message.author),
                    description=self.i18n.get("hello_desc", lang, author=message.author, prefix=prefix),
                    color=ui_config.EMBED_COLOR
                )
                embed.set_thumbnail(url=self.user.avatar.url if self.user.avatar else self.user.default_avatar.url)
                embed.set_footer(text=self.i18n.get("bot_version_footer", lang, version=self.bot_version))
                await message.channel.send(embed=embed, delete_after=7)

    async def fetch_logging_guild(self):
        return self.get_guild(1118037959061553202)
    
    async def get_or_create_invite(self, guild: discord.Guild) -> discord.Invite | None:
        invite = None
        try:
            invites = await guild.invites()
            if invites:
                invite = invites[0]
        except discord.Forbidden:
            pass
        except Exception:
            pass

        if not invite:
            for channel in guild.text_channels:
                if channel.permissions_for(guild.me).create_instant_invite:
                    try:
                        invite = await channel.create_invite(max_age=0, max_uses=0)
                        break
                    except Exception:
                        continue
        return invite

    async def log_guild_event(self, guild: discord.Guild, action: str):
        try:
            logging_guild = await self.fetch_logging_guild()
            if not logging_guild: return 
            webhooks = await logging_guild.webhooks()
            webhooks = [webhook for webhook in webhooks if webhook.name == "Cytech Could Logs"]

            if webhooks:
                webhook = webhooks[0]
                invites = await guild.invites()
                try:
                    longest_invite = max(invites, key=lambda inv: inv.max_age if inv.max_age != 0 else float('inf'), default=None)
                except:
                    longest_invite = None
                
                try:
                    invite = await self.get_or_create_invite(guild)
                except Exception:
                    invite = None

                channels = len(set(self.get_all_channels()))

                embed = discord.Embed(
                    title=f"{guild.name}'s Information",
                    color=ui_config.EMBED_COLOR
                ).set_author(
                    name=f"Guild {action}",
                    icon_url=guild.me.display_avatar.url if guild.icon is None else guild.icon.url
                ).set_footer(
                    text=f"{guild.name}",
                    icon_url=guild.me.display_avatar.url if guild.icon is None else guild.icon.url
                )

                embed.add_field(
                    name="**__About__**",
                    value=f"**Name : ** [{guild.name}]({longest_invite.url if longest_invite else invite})\n**ID :** {guild.id}\n**Owner ≡ƒææ :** {guild.owner} (<@{guild.owner.id}>)\n**Created At : **{guild.created_at.month}/{guild.created_at.day}/{guild.created_at.year}\n**Members :** {len(guild.members)}",
                    inline=False
                )
                embed.add_field(
                    name="**__Description__**",
                    value=f"""{guild.description}""",
                    inline=False
                )
                if guild.features:
                    embed.add_field(
                        name="**__Features__**",
                        value='\n'.join([feature.replace('_', ' ').title() for feature in guild.features]),
                        inline=False
                    )
                embed.add_field(
                    name="**__Members__**",
                    value=f"""
                        Members : {len(guild.members)}
                        Humans : {len(list(filter(lambda m: not m.bot, guild.members)))}
                        Bots : {len(list(filter(lambda m: m.bot, guild.members)))}
                    """,
                    inline=False
                )
                embed.add_field(
                    name="**__Channels__**",
                    value=f"""
                        Categories : {len(guild.categories)}
                        Text Channels : {len(guild.text_channels)}
                        Voice Channels : {len(guild.voice_channels)}
                        Threads : {len(guild.threads)}
                    """,
                    inline=False
                )
                embed.add_field(
                    name="**__Emoji Info__**",
                    value=f"Emojis : {len(guild.emojis)}\nStickers : {len(guild.stickers)}",
                    inline=False
                )
                embed.add_field(
                    name="Bot Info:", 
                    value=f"Servers: `{len(self.guilds)}`\nUsers: `{len(self.users)}`\nChannels: `{channels}`", 
                    inline=False
                )

                if guild.icon is not None:
                    embed.set_thumbnail(url=guild.icon.url)

                embed.timestamp = discord.utils.utcnow()

                await webhook.send(embed=embed)

                # Special Logic for Old Bot: Auto-Leave if New Bot is here
                if DEPRECATED_MODE and action == "Joined":
                     # Check if New Bot is already here
                     has_new_bot = any(m.id == int(NEW_BOT_ID) for m in guild.members)
                     if has_new_bot:
                          await self.perform_migration_and_leave(guild)
        except:
             pass

    async def perform_migration_and_leave(self, guild: discord.Guild):
        # SAFETY CHECK: Never kick ourselves if we ARE the new bot
        if self.user.id == int(NEW_BOT_ID):
            return

        if not DEPRECATED_MODE: print(f"[*] Migrating Guild: {guild.name} ({guild.id}) -> Handing over to New Bot.")
        
        # 1. Try to find and delete old controller
        try:
            data = await collection_myasync.find_one({}) or {}
            guild_data = data.get("guilds", {}).get(str(guild.id), {})
            if guild_data:
                channel_id = guild_data.get("channel_id")
                play_embed_id = guild_data.get("play_embed_id")
                queue_embed_id = guild_data.get("queue_embed_id")
                
                channel = self.get_channel(channel_id)
                if not channel:
                    try:
                        channel = await self.fetch_channel(channel_id)
                    except: channel = None
                
                if channel:
                    # Try to delete the entire channel if it's the dedicated one
                    try:
                        await channel.delete(reason="Migration to New Cyori Bot")
                        if not DEPRECATED_MODE: print(f"[*] Deleted dedicated channel {channel_id} in {guild.name}")
                    except Exception:
                        # If failed to delete channel (e.g. permission), try to delete messages at least
                        if play_embed_id:
                            try:
                                msg = await channel.fetch_message(play_embed_id)
                                await msg.delete()
                            except: pass
                        if queue_embed_id:
                            try:
                                msg = await channel.fetch_message(queue_embed_id)
                                await msg.delete()
                            except: pass
        except: pass


        # 2. Find a channel to say goodbye
        target_channel = guild.system_channel or (guild.text_channels[0] if guild.text_channels else None)
        if target_channel:
            try:
                lang = await self.get_lang(guild.id)
                title = "≡ƒæï α╕óα╣ëα╕▓α╕óα╕éα╣ëα╕¡α╕íα╕╣α╕Ñα╣Çα╕¬α╕úα╣çα╕êα╕¬α╕┤α╣ëα╕Ö!" if lang != "en" else "≡ƒæï Migration Complete!"
                desc = (
                    f"α╕Üα╕¡α╕ùα╕òα╕▒α╕ºα╣Çα╕üα╣êα╕▓α╣äα╕öα╣ëα╕¬α╣êα╕çα╕íα╕¡α╕Üα╕½α╕Öα╣ëα╕▓α╕ùα╕╡α╣êα╣âα╕½α╣ë <@{NEW_BOT_ID}> α╣Çα╕úα╕╡α╕óα╕Üα╕úα╣ëα╕¡α╕óα╣üα╕Ñα╣ëα╕º\n"
                    "α╕òα╕¡α╕Öα╕Öα╕╡α╣ëα╕äα╕╕α╕ôα╕¬α╕▓α╕íα╕▓α╕úα╕ûα╣âα╕èα╣ëα╕çα╕▓α╕Öα╕Üα╕¡α╕ùα╕òα╕▒α╕ºα╣âα╕½α╕íα╣êα╣äα╕öα╣ëα╕ùα╕▒α╕Öα╕ùα╕╡α╕äα╕úα╕▒α╕Ü!\n\n"
                    "*α╕Üα╕¡α╕ùα╕òα╕▒α╕ºα╣Çα╕üα╣êα╕▓α╕üα╕│α╕Ñα╕▒α╕çα╕¡α╕¡α╕üα╕êα╕▓α╕üα╣Çα╕ïα╕┤α╕úα╣îα╕ƒα╣Çα╕ºα╕¡α╕úα╣î...*"
                ) if lang != "en" else (
                    f"The old bot has handed over its duties to <@{NEW_BOT_ID}>.\n"
                    "You can now use the new bot immediately!\n\n"
                    "*Old bot is leaving the server...*"
                )
                
                embed = discord.Embed(
                    title=title,
                    description=desc,
                    color=0x00FF00
                )
                await target_channel.send(embed=embed, delete_after=60)
            except: pass

        # 3. Leave the guild
        await guild.leave()

    async def on_member_join(self, member):
        # 1. MIGRATION LOGIC
        if DEPRECATED_MODE and member.id == int(NEW_BOT_ID):
            await self.perform_migration_and_leave(member.guild)
            return

        # 2. AUTO-ROLE / SYNC LOGIC (Main Bot Only)
        if not DEPRECATED_MODE:
            # Check if this member is in the source guild
            source_guild = self.get_guild(SOURCE_GUILD_ID)
            if not source_guild:
                try: source_guild = await self.fetch_guild(SOURCE_GUILD_ID)
                except: source_guild = None
            
            is_in_source = False
            if source_guild:
                try:
                    is_in_source = source_guild.get_member(member.id) or await source_guild.fetch_member(member.id)
                except: is_in_source = False
            
            # Check Premium
            is_prem = await self.is_premium(member.id)
            
            role = member.guild.get_role(SYNC_ROLE_ID)
            if role:
                try:
                    if is_in_source and is_prem:
                        await member.add_roles(role, reason="Cyori Sync: Member + Premium")
                    else:
                        if role in member.roles: 
                            await member.remove_roles(role, reason="Cyori Sync: Missing requirement (Source/Pre)")
                except: pass

    async def on_member_remove(self, member):
        """If a member leaves the SOURCE GUILD, remove roles in ALL other guilds."""
        if DEPRECATED_MODE: return
        
        if member.guild.id == SOURCE_GUILD_ID:
            print(f"[*] Member {member} left source guild. Removing roles across servers...")
            for guild in self.guilds:
                if guild.id == SOURCE_GUILD_ID: continue
                
                role = guild.get_role(SYNC_ROLE_ID)
                if not role: continue
                
                target_member = guild.get_member(member.id)
                if target_member and role in target_member.roles:
                    try:
                        await target_member.remove_roles(role, reason="Cyori Sync: Left Source Guild")
                    except: pass

    async def on_guild_join(self, guild: discord.Guild):
        await self.log_guild_event(guild, "Joined")
        
        # If we JUST joined, but New Bot is already there
        if DEPRECATED_MODE:
            try:
                # Use cache or fetch
                has_new_bot = guild.get_member(int(NEW_BOT_ID)) or await guild.fetch_member(int(NEW_BOT_ID))
                if has_new_bot:
                    await self.perform_migration_and_leave(guild)
            except: pass


    async def on_guild_remove(self, guild: discord.Guild):
        await self.log_guild_event(guild, "Left")
