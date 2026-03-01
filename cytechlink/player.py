import time
from math import ceil
from asyncio import sleep
import asyncio
import traceback
from typing import Any, Dict, Optional, Union, List
import discord
from discord import Guild, VoiceChannel, VoiceProtocol, Member, ui, Message, Interaction
from bot import Cyori
from discord.ext import commands
from . import events
from .enums import SearchType, LoopType
from .events import CytechlinkEvent, TrackEndEvent, TrackStartEvent
from .exceptions import (
    CytechlinkException,
    FilterInvalidArgument,
    TrackInvalidPosition,
    TrackLoadError,
    FilterTagAlreadyInUse,
    DuplicateTrack,
)
from .filters import Filter, Filters
from .objects import Track, Playlist, ctime
from .pool import Node, NodePool
from .queue import Queue, FairQueue
from .formatter import encode, decode
from random import shuffle, choice
from utils.config import WARNING_SOUND_URL_TH, WARNING_SOUND_URL_EN, OWNER_IDS
from utils.music_ui import (
    safe_get_guild_data,
    safe_delete,
    safe_fetch_message,
    safe_text,
    loop_mode_to_str,
    loop_emoji_safe,
    MusicControls,
    JukeboxIdleView,
)


async def connect_channel(
    ctx: Union[commands.Context, Interaction], channel: VoiceChannel = None
):
    try:
        channel = (
            channel or ctx.author.voice.channel
            if isinstance(ctx, commands.Context)
            else ctx.user.voice.channel
        )
    except Exception:
        raise CytechlinkException("")

    check = channel.permissions_for(ctx.guild.me)
    if check.connect == False or check.speak == False:
        raise CytechlinkException("")

    player: Player = await channel.connect(
        cls=Player(
            ctx.bot if isinstance(ctx, commands.Context) else ctx.client, channel, ctx
        )
    )

    return player


class Player(VoiceProtocol):
    """The base player class for Cytechlink.
    In order to initiate a player, you must pass it in as a cls when you connect to a channel.
    i.e: ```py
    await ctx.author.voice.channel.connect(cls=Cytechlink.Player)
    ```
    """

    def __call__(self, client: Cyori, channel: VoiceChannel):
        self.client: Cyori = client
        self.channel: VoiceChannel = channel

        return self

    def __init__(
        self,
        client: Optional[Cyori] = None,
        channel: Optional[VoiceChannel] = None,
        ctx: Union[commands.Context, Interaction] = None,
    ):
        self.client: Cyori = client
        self._bot: Cyori = client
        self.context = ctx
        self.dj: Optional[Member] = None
        if ctx:
            # Use getattr for maximum resilience
            self.dj = getattr(ctx, "user", getattr(ctx, "author", None))
        self.channel: VoiceChannel = channel
        self._guild = channel.guild if channel else None
        self.joinTime: float = round(time.time())
        self._volume: int = 100
        self.queue = Queue()

        self._node = NodePool.get_node()
        self._current: Track = None
        self._filters: Filters = Filters()
        self._paused: bool = False
        self._is_connected: bool = False
        self._ping: float = 0.0
        self._track_is_stuck = False

        self._position: int = 0
        self._last_position: int = 0
        self._last_update: int = 0
        self._ending_track: Optional[Track] = None

        self._voice_state: dict = {}

        self.controller: Message = None
        self.updating: bool = False

        self.pause_votes = set()
        self.resume_votes = set()
        self.skip_votes = set()
        self.previous_votes = set()
        self.shuffle_votes = set()
        self.stop_votes = set()
        self.is_closing: bool = False
        self.last_message_update = 0  # Rate limit handling
        self.update_pending: bool = False

        # Auto-Load Queue (Persistent)
        if self._guild:
            asyncio.create_task(self.load_queue())

    async def save_queue(self):
        """Save current queue to MongoDB for persistence."""
        if not self.guild:
            return

        # Serialize Queue
        queue_data = []
        for track in self.queue:
            encoded = track.track_id
            if not encoded:
                continue

            queue_data.append(
                {
                    "encoded": encoded,
                    "info": {
                        "title": track.title,
                        "author": track.author,
                        "uri": track.uri,
                        "identifier": track.identifier,
                        "length": track.length,
                        "is_stream": track.is_stream,
                    },
                }
            )
            if len(queue_data) > 30:
                break  # Cap at 30

        try:
            guild_id_str = str(self.guild.id)
            await self.bot.db_manager.update_guild(
                guild_id_str, {"saved_queue": queue_data, "updated_at": time.time()}
            )
        except Exception as e:
            print(f"[Player] Save Queue Error: {e}")

    async def load_queue(self):
        """Load saved queue from MongoDB."""
        try:
            await asyncio.sleep(2)  # Wait for connection stabilization
            if not self.guild:
                return

            data = await self.bot.db_manager.get_guild(self.guild.id)
            if data and "saved_queue" in data:
                saved = data["saved_queue"]
                if not saved:
                    return

                tracks = []
                for item in saved:
                    try:
                        encoded = item.get("encoded")
                        info = item.get("info", {})
                        if encoded:
                            t_info = info
                            if not t_info:
                                t_info = decode(encoded)

                            track = Track(encoded, t_info, requester=self.bot.user)
                            tracks.append(track)
                    except Exception as e:
                        pass

                if tracks:
                    if self.queue.is_empty:
                        self.queue.extend(tracks)
                        print(
                            f"[Player] Loaded {len(tracks)} tracks from saved queue for {self.guild.name}"
                        )
        except Exception as e:
            print(f"[Player] Load Queue Error: {e}")

    def __repr__(self):
        return (
            f"<Cytechlink.player bot={self.bot} guildId={self.guild.id} "
            f"is_connected={self.is_connected} is_playing={self.is_playing}>"
        )

    @property
    def position(self) -> float:
        """Property which returns the player's position in a track in milliseconds"""
        current = self._current.original

        if not self.is_playing or not self._current:
            return 0

        if self.is_paused:
            return min(self._last_position, current.length)

        difference = (time.time() * 1000) - self._last_update
        position = self._last_position + difference

        if current.length is None:
            # If length is None (e.g. some streams), we can't cap it.
            return self._last_position + difference

        if position > current.length:
            return 0

        return min(position, current.length)

    @property
    def is_playing(self) -> bool:
        """Property which returns whether or not the player is actively playing a track."""
        return self._is_connected and self._current is not None

    @property
    def is_connected(self) -> bool:
        """Property which returns whether or not the player is connected"""
        return self._is_connected

    @property
    def is_paused(self) -> bool:
        """Property which returns whether or not the player has a track which is paused or not."""
        return self._is_connected and self._paused

    @property
    def current(self) -> Track:
        """Property which returns the currently playing track"""
        return self._current

    @property
    def node(self) -> Node:
        """Property which returns the node the player is connected to"""
        return self._node

    @property
    def guild(self) -> Guild:
        """Property which returns the guild associated with the player"""
        return self._guild

    @property
    def volume(self) -> int:
        """Property which returns the players current volume"""
        return self._volume

    @property
    def filters(self) -> Filters:
        """Property which returns the helper class for interacting with filters"""
        return self._filters

    @property
    def bot(self) -> Cyori:
        """Property which returns the bot associated with this player instance"""
        return self._bot

    @property
    def is_dead(self) -> bool:
        """Returns a bool representing whether the player is dead or not.
        A player is considered dead if it has been destroyed and removed from stored players.
        """
        return self.guild.id not in self._node._players

    @property
    def ping(self) -> float:
        return round(self._ping / 1000, 2)

    def required(self, leave=False):
        human_members = [m for m in self.channel.members if not m.bot]
        # Calculate roughly 40-50% of listeners
        required = (
            ceil((len(human_members) - 1) / 2.5)
            if leave
            else ceil(len(human_members) / 2.5)
        )

        if leave:
            if len(human_members) == 3:
                required = 2

        return max(required, 1)

    async def is_privileged(self, user: Member, strict: bool = False) -> bool:
        """
        Check if user has permission to control the bot.
        strict=True: Requires Admin/DJ Role/ManageGuild regardless of other conditions. (For dangerous commands like 24/7)
        strict=False:
            - If user NOT in VC: Requires strict perms.
            - If user IN VC:
                - If DJ Mode is OFF: Allowed.
                - If DJ Mode is ON: Requires strict perms OR Alone in VC.
        """
        if user.id in OWNER_IDS:
            return True

        # Check Bot Owner (Application Owner)
        if not hasattr(self.bot, "app_info"):
            self.bot.app_info = await self.bot.application_info()
        if user.id == self.bot.app_info.owner.id:
            return True

        # 1. Strict Permissions (Admin / Manage Guild / DJ Role)
        is_strict = False
        if user.guild_permissions.administrator or user.guild_permissions.manage_guild:
            is_strict = True

        # Check DJ Role
        if not is_strict:
            try:
                guild_data = await safe_get_guild_data(str(self.guild.id))
                dj_role_id = guild_data.get("dj_role")
                if dj_role_id:
                    role = self.guild.get_role(dj_role_id)
                    if role and role in user.roles:
                        is_strict = True
            except Exception:
                pass

        if is_strict:
            return True

        # If strict check is required, return False here
        if strict:
            return False

        # 2. Relaxed Permissions (VC based)
        # MUST be in same voice channel
        if user not in self.channel.members:
            return False

        # Check DJ Mode
        try:
            guild_data = await safe_get_guild_data(str(self.guild.id))
            dj_mode = guild_data.get("dj_mode", False)
            if not dj_mode:
                return True  # DJ Mode OFF -> Everyone in VC is allowed
        except Exception:
            return True  # Default to allowed if error

        # If DJ Mode is ON, check if user is ALONE in VC (excluding bots)
        human_members = [m for m in self.channel.members if not m.bot]
        if len(human_members) == 1 and human_members[0].id == user.id:
            return True

        return False

    async def _update_state(self, data: dict) -> None:
        state: dict = data.get("state")
        self._last_update = time.time() * 1000
        self._is_connected = state.get("connected")
        self._last_position = state.get("position")
        self._ping = state.get("ping")

    async def _dispatch_voice_update(self, voice_data: Dict[str, Any]):
        if {"sessionId", "event"} != self._voice_state.keys():
            return

        await self._node.send(
            method=0,
            guild_id=self._guild.id,
            data={
                "voice": {
                    "token": voice_data["event"]["token"],
                    "endpoint": voice_data["event"]["endpoint"],
                    "sessionId": voice_data["sessionId"],
                }
            },
        )

    async def on_voice_server_update(self, data: dict):
        self._voice_state.update({"event": data})
        await self._dispatch_voice_update(self._voice_state)

    async def on_voice_state_update(self, data: dict):
        self._voice_state.update({"sessionId": data.get("session_id")})

        if not (channel_id := data.get("channel_id")):
            await self.teardown()
            self._voice_state.clear()
            return

        self.channel = self.guild.get_channel(int(channel_id))

        if not data.get("token"):
            return

        await self._dispatch_voice_update({**self._voice_state, "event": data})

    async def _dispatch_event(self, data: dict):
        event_type = data.get("type")
        event: CytechlinkEvent = getattr(events, event_type)(data, self)

        if isinstance(event, TrackEndEvent) and event.reason != "replaced":
            self._current = None

        event.dispatch(self._bot)

        if isinstance(event, TrackStartEvent):
            self._ending_track = self._current

    async def update_controller(
        self, track: Optional[Track] = None, force: bool = False
    ):
        # Rate Limit Check (5 seconds) except for forced updates (Interaction/Dashboard)
        if not force and time.time() - self.last_message_update < 5:
            self.update_pending = True
            return
        self.update_pending = False
        self.last_message_update = time.time()

        try:
            # ดึง config ครั้งเดียว
            guild_data = await safe_get_guild_data(str(self.guild.id))

            # Sanitize Premium (Owner Check)
            if guild_data:
                is_owner_prem = await self.bot.is_premium(
                    self.guild.owner_id, guild_id=self.guild.id
                )
                if not is_owner_prem:
                    gd_copy = guild_data.copy()
                    if "premium_image" in gd_copy:
                        del gd_copy["premium_image"]
                    guild_data = gd_copy

            # Check Requester Premium (Async)
            requester = getattr(self.current, "requester", None)
            is_req_prem = (
                await self.bot.is_premium(requester.id, guild_id=self.guild.id)
                if requester
                else False
            )

            channel_id = guild_data.get("channel_id")
            queue_embed_id = guild_data.get("queue_embed_id")
            play_embed_id = guild_data.get("play_embed_id")

            # Fetch lang
            lang = await self.bot.get_lang(self.guild.id)

            # ใช้ track ที่ส่งมา หรือ current ถ้าไม่มี
            current_track = track or getattr(self, "current", None)

            # ───────────────────────────────
            # 1. สร้าง Embed + View (ใช้ร่วมกันทุกที่)
            # ───────────────────────────────
            embed = None
            view = None

            if current_track:
                # สร้าง Now Playing Embed
                loop_mode_str = loop_mode_to_str(
                    getattr(self.queue._repeat, "mode", None)
                    if hasattr(self.queue, "_repeat")
                    else None
                )
                loop_emoji_part = loop_emoji_safe(loop_mode_str)

                # Check status
                is_247 = guild_data.get("24/7", False)
                is_autoplay = guild_data.get("autoplay", False)

                status_247 = (
                    f"{self.bot.i18n.get('enabled', lang)}"
                    if is_247
                    else f"{self.bot.i18n.get('disabled', lang)}"
                )
                status_autoplay = (
                    f"{self.bot.i18n.get('enabled', lang)}"
                    if is_autoplay
                    else f"{self.bot.i18n.get('disabled', lang)}"
                )
                is_dj_mode = guild_data.get("dj_mode", False)
                status_dj_mode = (
                    f"{self.bot.i18n.get('enabled', lang)}"
                    if is_dj_mode
                    else f"{self.bot.i18n.get('disabled', lang)}"
                )

                # Check if it's warning sound
                is_warning = (
                    getattr(current_track, "uri", "") == WARNING_SOUND_URL_TH
                    or getattr(current_track, "uri", "") == WARNING_SOUND_URL_EN
                )

                if is_warning:
                    # Hide warning track, show "Waiting..." state
                    embed = discord.Embed(
                        description=self.bot.i18n.get("no_track_playing", lang),
                        color=0xFFD700,
                    )
                    embed.set_author(
                        name=self.bot.i18n.get("now_playing_title", lang),
                        icon_url=self.bot.user.display_avatar.url,
                    )
                    embed.set_footer(text=self.bot.i18n.get("waiting_for_music", lang))
                    view = None
                else:
                    # Normal Now Playing logic
                    title_text = self.bot.i18n.get("now_playing_title", lang)
                    if is_req_prem:
                        from utils.luxury import premium_badge

                        title_text += premium_badge(lang)

                    if getattr(current_track, "is_stream", False):
                        embed = discord.Embed(
                            title=f"🔴 **LIVE STREAM** {safe_text(current_track.title)}",
                            url=safe_text(current_track.uri),
                            color=0xFFD700,
                        )
                    else:
                        embed = discord.Embed(
                            title=f"{safe_text(current_track.title)}",
                            url=safe_text(current_track.uri),
                            color=0xFFD700,
                        )

                    # Set Author (Now Playing + Premium Badge)
                    embed.set_author(
                        name=title_text, icon_url=self.bot.user.display_avatar.url
                    )

                    # Better Layout with Spacing
                    from utils.luxury import luxury_line

                    # Define Loop Values
                    loop_map = {
                        "Track": self.bot.i18n.get("loop_mode_track", lang),
                        "Queue": self.bot.i18n.get("loop_mode_queue", lang),
                        "Off": self.bot.i18n.get("loop_mode_off", lang),
                    }

                    dur_ms = getattr(current_track, "length", 0)
                    pos_ms = self.position
                    is_live = getattr(current_track, "is_stream", False)
                    dur_str = ctime(dur_ms) if not is_live else "🔴 LIVE"

                    # Calculate End Time for Discord Dynamic Timestamp
                    end_timestamp = int(time.time() + ((dur_ms - pos_ms) / 1000))

                    # Format: 01:23 / 04:30 (Ends in 2 minutes)
                    if is_live:
                        time_info = f"`LIVE STREAM` — (เริ่มเล่นเมื่อ <t:{int(time.time() - (pos_ms / 1000))}:R>)"
                    else:
                        time_info = f"`{ctime(pos_ms)} / {dur_str}`"
                        if not self.is_paused:
                            time_info += f" — (จบประมาณ <t:{end_timestamp}:R>)"

                    if is_live:
                        embed.description = (
                            f"👤 **{self.bot.i18n.get('song_by', lang)}**: `{safe_text(getattr(current_track, 'author', 'Unknown'))}`\n\n"
                            f"🔴 **LIVE STREAM**\n"
                            f"{time_info}\n\n"
                            f"🔊 **{self.bot.i18n.get('song_volume', lang)}**: `{getattr(self, 'volume', 100)}%`  •  🔁 `{loop_map.get(loop_mode_str, loop_mode_str)}` {loop_emoji_part}\n"
                            f"⌛ **{self.bot.i18n.get('247_label', lang)}**: `{status_247}`  •  📻 **Auto**: `{status_autoplay}`\n"
                            f"🎧 **DJ Mode**: `{status_dj_mode}`\n"
                            f"{luxury_line()}"
                        )
                    else:
                        embed.description = (
                            f"👤 **{self.bot.i18n.get('song_by', lang)}**: `{safe_text(getattr(current_track, 'author', 'Unknown'))}`\n\n"
                            f"✨ **Status:** `{self.bot.i18n.get('playing', lang)}`\n"
                            f"{time_info}\n\n"
                            f"🔊 **{self.bot.i18n.get('song_volume', lang)}**: `{getattr(self, 'volume', 100)}%`  •  🔁 `{loop_map.get(loop_mode_str, loop_mode_str)}` {loop_emoji_part}\n"
                            f"⌛ **{self.bot.i18n.get('247_label', lang)}**: `{status_247}`  •  📻 **Auto**: `{status_autoplay}`\n"
                            f"🎧 **DJ Mode**: `{status_dj_mode}`\n"
                            f"{luxury_line()}"
                        )

                    if getattr(current_track, "requester", None):
                        req = current_track.requester
                        embed.set_footer(
                            text=self.bot.i18n.get(
                                "requested_by",
                                lang,
                                user=safe_text(req.display_name or str(req)),
                            ),
                            icon_url=getattr(req.display_avatar, "url", None),
                        )
                    if getattr(current_track, "thumbnail", None):
                        embed.set_image(url=safe_text(current_track.thumbnail))

                    # Premium Image (Thumbnail) -> Only if Owner Premium
                    if guild_data and guild_data.get("premium_image"):
                        embed.set_thumbnail(url=guild_data.get("premium_image"))

                    # ปุ่ม
                    view = MusicControls(self, current_track.requester)
            else:
                # กรณีไม่มีเพลงเล่นอยู่
                embed = self.bot.none_play_embed(lang, guild_data)
                view = JukeboxIdleView(self, bot=self.bot, lang=lang)

            # ───────────────────────────────
            # 2. Resolve Setup Channel ONCE (Performance Update)
            # ───────────────────────────────
            channel = None
            if channel_id:
                channel = self.bot.get_channel(channel_id)
                if not channel:
                    try:
                        channel = await self.bot.fetch_channel(channel_id)
                    except discord.NotFound:
                        # 🛡️ Auto-cleanup dirty db state if channel was manually deleted
                        await self.bot.db_manager.unset_guild(
                            self.guild.id,
                            ["channel_id", "play_embed_id", "queue_embed_id"],
                        )
                        channel_id = None
                        play_embed_id = None
                        queue_embed_id = None

            # ───────────────────────────────
            # 3. อัปเดต play_embed (ถาวร)
            # ───────────────────────────────
            if channel and play_embed_id:
                try:
                    # Try to fetch full message first (USER REQUEST)
                    try:
                        play_msg = await channel.fetch_message(play_embed_id)
                        await play_msg.edit(embed=embed, view=view)
                    except discord.NotFound:
                        # Message deleted manually, send new one
                        new_msg = await channel.send(embed=embed, view=view)
                        await self.bot.db_manager.update_guild(
                            self.guild.id, {"play_embed_id": new_msg.id}
                        )
                    except (discord.HTTPException, discord.Forbidden):
                        pass
                except Exception as e:
                    pass

            # ───────────────────────────────
            # 4. อัปเดต queue_embed (ถาวร)
            # ───────────────────────────────
            if channel and queue_embed_id:
                try:
                    tracks = (
                        list(self.queue.tracks())
                        if hasattr(self.queue, "tracks")
                        else []
                    )

                    if tracks:
                        queue_embed = discord.Embed(
                            title=f"{self.bot.i18n.get('queue_title', lang)} • {len(tracks)} track{'s' if len(tracks) != 1 else ''}",
                            color=0xFFD700,
                        )
                        for i, t in enumerate(tracks[:10], 1):
                            title = safe_text(getattr(t, "title", "Unknown Track"))
                            uri = safe_text(getattr(t, "uri", "")) or "#"
                            queue_embed.add_field(
                                name=f"{i}.", value=f"[{title}]({uri})", inline=False
                            )
                        if len(tracks) > 10:
                            queue_embed.set_footer(
                                text=f"And {len(tracks) - 10} more track{'s' if len(tracks) - 10 != 1 else ''}..."
                            )
                    else:
                        queue_embed = discord.Embed(
                            title=self.bot.i18n.get("queue_title", lang),
                            description=self.bot.i18n.get("no_queue", lang),
                            color=0xFFD700,
                        )
                    try:
                        queue_msg = await channel.fetch_message(queue_embed_id)
                        await queue_msg.edit(embed=queue_embed, view=None)
                    except discord.NotFound:
                        # Message deleted manually, send new one
                        new_q_msg = await channel.send(embed=queue_embed)
                        await self.bot.db_manager.update_guild(
                            self.guild.id, {"queue_embed_id": new_q_msg.id}
                        )
                    except Exception:
                        pass
                except Exception:
                    pass
            # ───────────────────────────────
            # 4. ลบ + ส่ง controller ใหม่
            # ───────────────────────────────
            # ───────────────────────────────
            # 4. อัปเดต Controller (สำคัญ: แก้ไขที่มีอยู่ ไม่ใช่ลบสร้างใหม่)
            # ───────────────────────────────
            if self.controller:
                # Don't touch if it IS the setup message (play_embed_id)
                if self.controller.id == play_embed_id:
                    pass
                else:
                    try:
                        # ลบเมสเสจเก่าแล้วส่งใหม่ตามคำขอ (USER REQUEST)
                        # เพิ่อให้ข้อความเพลงล่าสุดอยู่ล่างสุดเสมอ ในช่องแชทปกติ
                        channel = self.controller.channel
                        try:
                            await self.controller.delete()
                        except Exception:
                            pass

                        if embed and current_track:
                            self.controller = await channel.send(embed=embed, view=view)
                        else:
                            self.controller = None

                    except discord.NotFound:
                        # If message deleted, try to send a new one if we have an embed/track
                        try:
                            if embed and current_track:
                                target = None
                                if hasattr(self, "context") and self.context:
                                    target = self.context.channel

                                if target:
                                    self.controller = await target.send(
                                        embed=embed, view=view
                                    )
                            else:
                                self.controller = None
                        except Exception:
                            self.controller = None
                    except discord.Forbidden:
                        self.controller = None
                    except Exception as e:
                        print(
                            f"Error resending controller in {self.guild.name} ({self.guild.id}): {e}"
                        )
                        self.controller = None

            # ───────────────────────────────
            # 5. Broadcast to Dashboard
            # ───────────────────────────────
            try:
                # Embedded Dashboard Broadcast (CytechX Core)
                if hasattr(self.bot, "broadcast_guild"):
                    self.bot.loop.create_task(self.bot.broadcast_guild(self.guild.id))
            except Exception:
                pass

        except Exception as e:
            print(
                f"Error in update controller for {self.guild.name} ({self.guild.id}):",
                e,
            )
            traceback.print_exc()

    async def do_next(self) -> None:
        try:
            # if already playing or no voice channel set, return
            if getattr(self, "is_playing", False) or not getattr(self, "channel", None):
                return

            # un-pause flags
            if getattr(self, "_track_is_stuck", False):
                await asyncio.sleep(10)
                self._track_is_stuck = False

            if not getattr(self.guild.me, "voice", None):
                # reconnect attempt
                try:
                    await self.connect(timeout=0.0, reconnect=True)
                except Exception as e:
                    print(f"Failed to connect voice: {e}")

            # reset votes
            for v in (
                "pause_votes",
                "resume_votes",
                "skip_votes",
                "previous_votes",
                "shuffle_votes",
                "stop_votes",
            ):
                if hasattr(self, v):
                    getattr(self, v).clear()

            # Save Queue State
            asyncio.create_task(self.save_queue())

            guild_data = await self.bot.db_manager.get_guild(self.guild.id)
            autoplay = bool(guild_data.get("autoplay", False))
            mode_24_7 = bool(guild_data.get("24/7", False))

            # get next track
            try:
                track = self.queue.get()
            except Exception as e:
                print(f"Error getting next track from queue: {e}")
                track = None

            if not track:
                # attempt autoplay or 24/7 behavior
                if autoplay:
                    try:
                        if await self.get_recommendations():
                            return await self.do_next()
                    except Exception:
                        pass
                if mode_24_7:
                    # loop waiting for new items or attempt to re-enter do_next
                    return

                # ---------------- WARNING SOUND & GRACE PERIOD (Moved to do_next) ----------------
                try:
                    # Check flag from previous run
                    warning_just_played = getattr(self, "warning_playing", False)
                    # Reset flag
                    self.warning_playing = False

                    # If warning NOT just played, and queue is empty, attempt to play warning
                    if (
                        not warning_just_played
                        and self.queue.is_empty
                        and not self.is_playing
                    ):
                        # Interrupt Check 1
                        if not self.queue.is_empty:
                            return

                        # CACHING LOGIC
                        warning_track = getattr(self, "warning_track_cache", None)
                        if not warning_track:
                            # Determine Warning URL based on Lang
                            lang = await self.bot.get_lang(self.guild.id)
                            warn_url = (
                                WARNING_SOUND_URL_TH
                                if lang == "th"
                                else WARNING_SOUND_URL_EN
                            )

                            if warn_url:
                                results = await self.get_tracks(
                                    warn_url, requester=self.bot.user
                                )
                                if results:
                                    warning_track = results[0]
                                    self.warning_track_cache = warning_track

                        # Interrupt Check 2 (After fetch)
                        if not self.queue.is_empty:
                            return

                        if warning_track:
                            # Update embed to show "Waiting..."
                            await self.update_controller(warning_track)

                            # Set flag BEFORE play so next do_next knows
                            self.warning_playing = True
                            await self.play(warning_track)

                            # Wait for track duration (Interruptible)
                            duration = warning_track.length / 1000
                            for _ in range(int(duration + 1)):
                                if not self.queue.is_empty:
                                    self.warning_playing = (
                                        False  # Cancel flag if interrupted
                                    )
                                    await self.stop()
                                    return
                                await asyncio.sleep(1)

                            # Stop triggers do_next -> which will see warning_playing=True and enter Grace Period
                            await self.stop()
                            return

                except Exception as e:
                    print(f"Failed to play warning sound: {e}")
                    self.warning_playing = False  # Safety reset

                # Grace Period (60s) with Interrupt Check
                # Reachable ONLY if:
                # 1. We just finished playing warning (warning_just_played=True)
                # 2. OR Warning failed/skipped (queue empty but no warning track)
                if self.queue.is_empty and not self.is_playing:
                    for _ in range(30):
                        if not self.queue.is_empty:
                            await self.do_next()
                            await self.update_controller()
                            return
                        await asyncio.sleep(1)

                    # Time's up -> Call teardown
                    return await self.teardown()

                return

            # sync properties
            self.autoplay = autoplay
            self.mode247 = mode_24_7

            # update user history safely
            try:
                uid = (
                    str(track.requester.id)
                    if getattr(track, "requester", None)
                    else None
                )
                if uid:
                    user_doc = await self.bot.db_manager.get_user(uid)
                    user_history = user_doc.get("recently_played", [])

                    identifiers = {
                        song.get("identifier")
                        for song in user_history
                        if isinstance(song, dict)
                    }
                    if getattr(track, "identifier", None) not in identifiers:
                        if len(user_history) >= 25:  # Keep up to 25
                            user_history.pop(0)
                        user_history.append(
                            {
                                "identifier": getattr(track, "identifier", None),
                                "title": getattr(track, "title", None),
                            }
                        )

                    # Store back to db
                    await self.bot.db_manager.update_user(
                        uid, {"recently_played": user_history}
                    )
            except Exception as e:
                print(f"Error updating user history: {e}")

            # finally, play the track
            try:
                await self.play(track, start=getattr(track, "position", 0))
                self.dj = (
                    track.requester if getattr(track, "requester", None) else self.dj
                )
                try:
                    # Always update controller (handles persistent jukebox as well)
                    await self.update_controller(track, force=True)
                except Exception as e:
                    print("Unhandled error in update embed:", e)
                    traceback.print_exc()
            except Exception as e:
                print(f"Failed to play track: {e}")
                # Retry do_next to skip bad track
                await self.do_next()

        except Exception as e:
            print("Unhandled error in do_next:", e)
            traceback.print_exc()

    async def teardown(self):
        guild_id = str(self.guild.id)
        guild_data = await self.bot.db_manager.get_guild(guild_id)

        # Fetch lang
        lang = await self.bot.get_lang(self.guild.id)

        if guild_data:
            channel_id = guild_data.get("channel_id", None)
            queue_id = guild_data.get("queue_embed_id", None)
            play_id = guild_data.get("play_embed_id", None)

            # Resolve channel once (ลด latency)
            if channel_id:
                channel = self.bot.get_channel(channel_id)
                # ----- UPDATE QUEUE + PLAY -----
                if channel:
                    # Update queue embed
                    if queue_id:
                        try:
                            _, msg = await safe_fetch_message(
                                self.bot, channel.id, queue_id
                            )
                            if msg:
                                await msg.edit(
                                    embed=discord.Embed(
                                        title=self.bot.i18n.get("no_queue", lang),
                                        color=0xFFD700,
                                    )
                                )
                        except (discord.HTTPException, discord.NotFound):
                            pass

                    if play_id:
                        try:
                            _, msg = await safe_fetch_message(
                                self.bot, channel.id, play_id
                            )
                            if msg:
                                await msg.edit(
                                    embed=self.bot.none_play_embed(lang),
                                    view=JukeboxIdleView(None, bot=self.bot, lang=lang),
                                )
                        except (discord.HTTPException, discord.NotFound):
                            pass

        # ----- CONTROLLER -----
        if self.controller and self.controller.id != play_id:
            try:
                channel = self.bot.get_channel(channel_id)
                if guild_data and channel:
                    play_embed = discord.Embed(
                        title=self.bot.i18n.get(
                            "join_voice_chat_channel", lang, channel=f"<#{channel_id}>"
                        ),
                        color=0xFFD700,
                    )
                    await self.controller.edit(
                        embed=play_embed, view=None, delete_after=10
                    )

                # Create background task for deletion so we don't block
                async def _delayed_delete(msg):
                    await asyncio.sleep(10)
                    await safe_delete(msg)

                self.bot.loop.create_task(_delayed_delete(self.controller))

            except (discord.HTTPException, discord.NotFound):
                pass

        # ----- DASHBOARD DISCONNECT -----
        if hasattr(self.bot, "broadcast_guild"):
            self.bot.loop.create_task(self.bot.broadcast_guild(self.guild.id))

        # ----- FINAL DESTROY -----
        try:
            await self.destroy()
        except Exception:
            pass
        self.bot.loop.create_task(
            self.bot.broadcast_guild(self.guild.id)
        )  # Final broadcast to clear UI

    async def get_tracks(
        self,
        query: str,
        *,
        requester: Member,
        search_type: SearchType = SearchType.ytsearch,
    ) -> Union[List[Track], Playlist]:
        """Fetches tracks from the node's REST api to parse into Lavalink.

        If you passed in Spotify API credentials when you created the node,
        you can also pass in a Spotify URL of a playlist, album or track and it will be parsed
        accordingly.

        You can also pass in a discord.py Context object to get a
        Context object on any track you search.
        """
        return await self._node.get_tracks(
            query, requester=requester, search_type=search_type
        )

    async def connect(
        self,
        *,
        timeout: float,
        reconnect: bool,
        self_deaf: bool = True,
        self_mute: bool = False,
    ):
        await self.guild.change_voice_state(
            channel=self.channel, self_deaf=True, self_mute=self_mute
        )
        self._node._players[self.guild.id] = self
        self._is_connected = True

    async def stop(self):
        """Stops the currently playing track."""
        self._current = None
        await self._node.send(
            method=0, guild_id=self._guild.id, data={"encodedTrack": None}
        )

    async def disconnect(self, *, force: bool = False):
        """Disconnects the player from voice."""
        try:
            await self.guild.change_voice_state(channel=None)
        finally:
            self.cleanup()
            self._is_connected = False
            self.channel = None

    async def destroy(self):
        """Disconnects and destroys the player, and runs internal cleanup."""
        try:
            await self.disconnect()
        except Exception:
            # 'NoneType' has no attribute '_get_voice_client_key' raised by self.cleanup() ->
            # assume we're already disconnected and cleaned up
            assert self.channel is None and not self.is_connected

        self._node._players.pop(self.guild.id)
        await self._node.send(method=1, guild_id=self._guild.id)

    async def play(
        self,
        track: Track,
        *,
        start: int = 0,
        end: int = 0,
        ignore_if_playing: bool = False,
    ) -> Track:
        """Plays a track. If a Spotify track is passed in, it will be handled accordingly."""
        if not self._node:
            return track

        if track.spotify:
            if not track.original:
                search = None
                queries = []

                if track.author and track.title:
                    queries.append(f"ytsearch:{track.author} - {track.title}")
                if track.title:
                    queries.append(f"ytsearch:{track.title}")

                for q in queries:
                    try:
                        search = await self._node.get_tracks(
                            q, requester=track.requester
                        )
                        if search:
                            break
                    except Exception:
                        continue

                if not search:
                    raise TrackLoadError("Can't not found a playable source!")

                track.original = search[0]

        data = {
            "encodedTrack": (
                track.original.track_id if track.original else track.track_id
            ),
            "position": str(start),
        }

        if end > 0:
            data["endTime"] = str(end)

        await self._node.send(
            method=0,
            guild_id=self._guild.id,
            data=data,
            query=f"noReplace={ignore_if_playing}",
        )

        self._current = track

        if self.volume != 100:
            await self.set_volume(self.volume)

        return self._current

    async def add_track(
        self,
        raw_tracks: Union[Track, List[Track]],
        *,
        at_font: bool = False,
        duplicate: bool = True,
    ) -> int:
        tracks = []
        position = 0

        # Change: Only check UPCOMING tracks for duplicates, not history.
        _duplicate_tracks = (
            () if duplicate else (track.uri for track in self.queue.tracks())
        )

        try:
            if isList := isinstance(raw_tracks, List):
                for track in raw_tracks:
                    if track.uri in _duplicate_tracks:
                        continue
                    self.queue.put_at_front(track) if at_font else self.queue.put(track)
                    tracks.append(track)
            else:
                if raw_tracks.uri in _duplicate_tracks:
                    raise DuplicateTrack("")

                position = (
                    self.queue.put_at_front(raw_tracks)
                    if at_font
                    else self.queue.put(raw_tracks)
                )
                tracks.append(raw_tracks)
        except DuplicateTrack:
            pass

        if tracks:
            return len(tracks) if isList else position
        return 0

    async def seek(self, position: float, requester: Member = None) -> float:
        """Seeks to a position in the currently playing track milliseconds"""
        if position < 0 or position > self._current.original.length:
            raise TrackInvalidPosition(
                "Seek position must be between 0 and the track length"
            )

        await self._node.send(
            method=0, guild_id=self._guild.id, data={"position": position}
        )
        return self._position

    async def set_pause(
        self, pause: bool, requester: Member = None, auto: bool = False
    ) -> bool:
        """Sets the pause state of the currently playing track."""
        await self._node.send(method=0, guild_id=self._guild.id, data={"paused": pause})
        self._paused = pause
        # If user manually handles pause/resume, clear auto_paused flag
        self.auto_paused = pause if auto else False
        if hasattr(self.bot, "broadcast_guild"):
            self.bot.loop.create_task(self.bot.broadcast_guild(self.guild.id))
        return self._paused

    async def set_volume(self, volume: int, requester: Member = None) -> int:
        """Sets the volume of the player as an integer. Lavalink accepts values from 0 to 500."""
        await self._node.send(
            method=0, guild_id=self._guild.id, data={"volume": volume}
        )
        self._volume = volume
        if hasattr(self.bot, "broadcast_guild"):
            self.bot.loop.create_task(self.bot.broadcast_guild(self.guild.id))
        return self._volume

    async def shuffle(self, queue_type: str, requester: Member = None) -> None:
        replacement = (
            self.queue.tracks() if queue_type == "queue" else self.queue.history()
        )
        if len(replacement) < 3:
            return

        shuffle(replacement)
        self.queue.replace(queue_type, replacement)
        self.shuffle_votes.clear()
        if hasattr(self.bot, "broadcast_guild"):
            self.bot.loop.create_task(self.bot.broadcast_guild(self.guild.id))

    async def set_repeat(self, mode: str = None) -> str:
        if not mode:
            mode = self.queue._repeat.next().name

        is_found = False
        for type in LoopType:
            if type.name.lower() == mode.lower():
                self.queue._repeat.set_mode(type)
                is_found = True
                break

        if not is_found:
            raise CytechlinkException("Invalid repeat mode.")

        if hasattr(self.bot, "broadcast_guild"):
            self.bot.loop.create_task(self.bot.broadcast_guild(self.guild.id))

        return mode

    async def add_filter(self, filter: Filter, fast_apply=False) -> Filters:
        try:
            self._filters.add_filter(filter=filter)
        except FilterTagAlreadyInUse:
            raise FilterTagAlreadyInUse("")
        payload = self._filters.get_all_payloads()
        await self._node.send(
            method=0, guild_id=self._guild.id, data={"filters": payload}
        )
        if fast_apply:
            await self.seek(self.position)
        return self._filters

    async def remove_filter(self, filter_tag: str, fast_apply=False) -> Filters:
        self._filters.remove_filter(filter_tag=filter_tag)
        payload = self._filters.get_all_payloads()
        await self._node.send(
            method=0, guild_id=self._guild.id, data={"filters": payload}
        )
        if fast_apply:
            await self.seek(self.position)

        return self._filters

    async def reset_filter(self, *, fast_apply=False) -> None:
        if not self._filters:
            raise FilterInvalidArgument(
                "You must have filters applied first in order to use this method."
            )
        self._filters.reset_filters()
        await self._node.send(method=0, guild_id=self._guild.id, data={"filters": {}})
        if fast_apply:
            await self.seek(self.position)

    async def change_node(self, identifier: str = None) -> None:
        """Change node."""
        try:
            node = NodePool.get_node(identifier=identifier)
        except Exception:
            return await self.teardown()

        self._node._players.pop(self.guild.id)
        self._node = node
        self._node._players[self.guild.id] = self

        await self._dispatch_voice_update(self._voice_state)

        if self.current:
            await self.play(self.current, start=self.position)
            self._last_update = time.time() * 1000

            if self.is_paused:
                await self.set_pause(True)

        if self.volume != 100:
            await self.set_volume(self.volume)

    async def get_recommendations(self, *, track: Track = None) -> bool:
        """Get recommendations from Youtube or Spotify."""
        try:
            if not track:
                hist = self.queue.history(incTrack=True)
                if not hist:  # History empty
                    return False
                # User Request: Pull from the very last song only
                track = hist[-1]

            tracks = None
            if track.spotify:
                spotify_tracks = await self._node._spotify_client.similar_track(
                    seed_tracks=track.identifier or track
                )
                if spotify_tracks:
                    tracks = [
                        Track(
                            track_id=None,
                            search_type=SearchType.ytsearch,
                            spotify_track=track,
                            info=track.to_dict(),
                            requester=self.client.user,
                        )
                        for track in spotify_tracks
                    ]

            else:
                # If valid youtube ID, try RD list
                query = None
                if track.source == "youtube" and track.identifier:
                    query = f"https://www.youtube.com/watch?v={track.identifier}&list=RD{track.identifier}"

                if query:
                    try:
                        tracks = await self.get_tracks(
                            query, requester=self.client.user
                        )
                    except Exception:
                        tracks = None

                # Fallback: If Mix doesn't exist or Not Youtube source, search by title
                if not tracks and track.title:
                    try:
                        # 0. Try YouTube Music Search first (Better for songs)
                        search_query = (
                            f"ytmsearch:{track.author} - {track.title}"
                            if track.author
                            else f"ytmsearch:{track.title}"
                        )
                        try:
                            tracks = await self.get_tracks(
                                search_query, requester=self.client.user
                            )
                            # Verify result is somewhat similar if possible, or just trust YTM
                        except Exception:
                            tracks = None

                        # 1. Try Normal YouTube Search Author + Title
                        if not tracks:
                            search_query = (
                                f"ytsearch:{track.author} - {track.title}"
                                if track.author
                                else f"ytsearch:{track.title}"
                            )
                            tracks = await self.get_tracks(
                                search_query, requester=self.client.user
                            )

                        # 2. If nothing, try Title only (broader match)
                        if not tracks and track.author:
                            tracks = await self.get_tracks(
                                f"ytsearch:{track.title}", requester=self.client.user
                            )

                    except Exception:
                        pass

            if tracks:
                candidates = tracks.tracks if isinstance(tracks, Playlist) else tracks
                if candidates:
                    # Filter out the seed track and recently played tracks to find "Next"
                    recent_ids = {
                        t.identifier
                        for t in self.queue.history(incTrack=True)[-30:]
                        if t.identifier
                    }  # Increased history check

                    # Shuffle candidates to avoid always picking the top 1 result which might be the song itself
                    # But if it's a Mix (Playlist), top results are usually good.
                    if not isinstance(tracks, Playlist):
                        candidates_to_check = candidates[
                            :5
                        ]  # Check top 5 search results
                        shuffle(candidates_to_check)  # Shuffle them for variety
                        candidates = candidates_to_check + candidates[5:]

                    # Try to find a valid track that isn't a strict duplicate
                    for candidate in candidates:
                        # Skip if it's the exact same identifier as seed (don't repeat immediately)
                        if candidate.identifier == track.identifier:
                            continue

                        # Soft check against recent history
                        if candidate.identifier in recent_ids:
                            continue

                        # Try adding. add_track now only checks UPCOMING queue for strict duplicates.
                        # So if it's in history but not recent_ids (checked above), it will be added.
                        added = await self.add_track(candidate, duplicate=False)
                        if added > 0:
                            return True

                    # Fallback: If all candidates were in recent history
                    # Try to find one that is NOT the seed track and hasn't been played VERY recently (last 5)
                    very_recent = {
                        t.identifier
                        for t in self.queue.history(incTrack=True)[-5:]
                        if t.identifier
                    }
                    for candidate in candidates:
                        if (
                            candidate.identifier != track.identifier
                            and candidate.identifier not in very_recent
                        ):
                            added = await self.add_track(candidate, duplicate=False)
                            if added > 0:
                                return True

        except Exception as e:
            print(f"Autoplay Error: {e}")
            traceback.print_exc()

        return False
