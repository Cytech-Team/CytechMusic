
import math
import time
import asyncio
import discord
from cogs import info
import cytechlink
from discord import app_commands
from typing import Union, Optional
from discord.ext import commands, tasks
from bot import Cyori, collection_myasync
from utils import config as ui_config

async def check_access(ctx: Union[commands.Context, discord.Interaction]):
    player: cytechlink.Player = ctx.guild.voice_client
    if not player:
        return None

    user = ctx.author or ctx.user
    
    # Check if the user is in the voice channel
    if user not in player.channel.members:
        if not await player.is_privileged(user):
            return None

    return player

def formatTime(number:str) -> Optional[int]:
    try:
        try:
            num = time.strptime(number, '%M:%S')
        except ValueError:
            try:
                num = time.strptime(number, '%S')
            except ValueError:
                num = time.strptime(number, '%H:%M:%S')
    except:
        return None
    
    return (int(num.tm_hour) * 3600 + int(num.tm_min) * 60 + int(num.tm_sec)) * 1000

class page(discord.ui.View):
    def __init__(self, bot: Cyori, source, author):
        super().__init__()
        self.bot = bot
        self.source = source
        self.author: discord.Member = author
        self.message: discord.Message = None
        self.index = 0

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.defer(thinking=True)
            lang = await self.bot.get_lang(interaction.guild.id)
            await interaction.followup.send(content=self.bot.i18n.get("perm_button", lang), ephemeral=True, delete_after=7)
            return False
        return True

    @discord.ui.button(label='≪', style=discord.ButtonStyle.grey)
    async def first_page_button(self, interaction:discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        self.index = 0
        await self.update_page()

    @discord.ui.button(label='<', style=discord.ButtonStyle.grey)
    async def previous_page_button(self, interaction:discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        if self.index == 0:
            return
        self.index -= 1
        await self.update_page()
        
    @discord.ui.button(label='■', style=discord.ButtonStyle.grey)
    async def middle_button(self, interaction:discord.Interaction, button: discord.ui.Button):
        await interaction.message.delete()

    @discord.ui.button(label='>', style=discord.ButtonStyle.grey)
    async def next_page_button(self, interaction:discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        if self.index >= len(self.source) - 1:
            return
        self.index += 1
        await self.update_page()

    @discord.ui.button(label='≫', style=discord.ButtonStyle.grey)
    async def last_page_button(self, interaction:discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        self.index = len(self.source) - 1
        await self.update_page()

    async def update_page(self):
        lang = await self.bot.get_lang(self.message.guild.id)
        embed: discord.Embed = self.source[self.index]
        embed.set_footer(text=self.bot.i18n.get("page_footer", lang, current=self.index + 1, total=len(self.source)), icon_url=str(self.bot.user.avatar.url))
        await self.update_buttons()
        await self.message.edit(embed=embed)
        

    @discord.ui.button(label='Lyrics', style=discord.ButtonStyle.secondary, custom_id="lyrics_btn")
    async def lyrics_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        # We can trigger lyrics command logic here or just tell them to use /lyrics
        # But this button is on the PAGE view (Queue). Maybe not relevant.
        # Let's stick to adding commands in the Cog.
        pass

        if self.index == 0:
            self.first_page_button.disabled = True
            self.previous_page_button.disabled = True
        else:
            self.first_page_button.disabled = False
            self.previous_page_button.disabled = False

        if self.index >= len(self.source) - 1:
            self.next_page_button.disabled = True
            self.last_page_button.disabled = True
        else:
            self.next_page_button.disabled = False
            self.last_page_button.disabled = False

        await self.message.edit(view=self)
        
    async def buttons_use(self):
        self.first_page_button.disabled = True
        self.previous_page_button.disabled = True
        self.next_page_button.disabled = False
        self.last_page_button.disabled = False
        try:
             await self.message.edit(view=self)
        except: pass

class Music(commands.Cog):
    def __init__(self, bot: Cyori) -> None:
        self.bot = bot
        self.regions = [
            "singapore", "japan", "hongkong", "sydney",
            "us-west", "us-east", "us-central", "us-south",
            "brazil", "europe", "india", "dubai", "southafrica"
        ]
        self.disconnect_timers = {}
        self.player_check.start()
        self.ctx_menu = app_commands.ContextMenu(
            name="play",
            callback=self._play
        )
        self.bot.tree.add_command(self.ctx_menu)

    async def _notify_web_dashboard(self, guild_id):
        try:
            # Zero-Delay Sync: Notify Dashboard API to push update
            dash_cog = self.bot.get_cog("DashboardAPI")
            if dash_cog:
                # Fire and forget task
                asyncio.create_task(dash_cog.broadcast_guild(int(guild_id)))
        except:
            pass

    def cog_unload(self):
        self.player_check.cancel()

    async def disconnect_with_warning(self, player: cytechlink.Player):
        try:
            # Play warning
            lang = await self.bot.get_lang(player.guild.id)
            if lang == "th":
                search = getattr(ui_config, "WARNING_SOUND_URL_TH", None)
            else:
                search = getattr(ui_config, "WARNING_SOUND_URL_EN", None)
            
            if not search:
                search = getattr(ui_config, "WARNING_SOUND_URL", None)

            if search:
                tracks = await player.get_tracks(search, requester=self.bot.user)
            else:
                tracks = None
            if tracks:
                track = tracks[0]
                await player.play(track)
                duration = (track.length / 1000)
                await asyncio.sleep(duration + 1)
            else:
                print(f"Warning track not found at: {search}")
        except Exception as e:
             import traceback
             traceback.print_exc()
             print(f"Error playing warning: {e}")
        
        # Final check
        if player.queue.is_empty:
             lang = await self.bot.get_lang(player.guild.id)
             try:
                embed = discord.Embed(
                     description=self.bot.i18n.get("inactive_left", lang),
                     color=ui_config.EMBED_COLOR
                )
                if player.controller:
                     await player.controller.channel.send(embed=embed, delete_after=30)
                elif player.context:
                    if isinstance(player.context, discord.Interaction):
                         await player.context.channel.send(embed=embed, delete_after=30)
                    else:
                         await player.context.send(embed=embed, delete_after=30)
             except: pass

             await player.teardown()
        else:
             player.is_closing = False

    @tasks.loop(seconds=20)
    async def player_check(self):
        # Optimization: Scan less frequently, rely on events for instant actions
        if not self.bot.voice_clients:
            return
        
        # Snapshot copy to allow iteration modification
        active_players = list(self.bot.voice_clients)
        
        for player in active_players:
            player: cytechlink.Player = player
            
            # Skip if already handling disconnect
            if getattr(player, "is_closing", False):
                continue

            # Check basic integrity
            if not player.channel or not player.guild:
                asyncio.create_task(player.teardown())
                continue
            
            # Using In-Memory State instead of DB Query (Crucial for 1M Servers)
            # Default to False if not set
            is_247 = getattr(player, "mode247", False)
            guild_id = str(player.guild.id)
            
            # Additional integrity check
            if not player.guild.me or not player.guild.me.voice:
                # If bot thinks it's connected but Discord says no -> Disconnect
                asyncio.create_task(player.teardown())
                continue

            # Logic: If empty channel (handled by event mostly, but as failsafe)
            members = player.channel.members
            if not any(not m.bot for m in members):
                 if not is_247:
                     asyncio.create_task(player.teardown())
                 else:
                     if not player.is_paused:
                         await player.set_pause(True, auto=True)
                 continue

            # Logic: Idle Timeout (Not playing for X seconds)
            playing = player.is_playing or not player.queue.is_empty
            
            if not playing:
                if not is_247:
                    if guild_id not in self.disconnect_timers:
                        self.disconnect_timers[guild_id] = time.time()
                    
                    # 2 Minutes Timeout
                    if time.time() - self.disconnect_timers[guild_id] >= 120:
                        player.is_closing = True
                        self.disconnect_timers.pop(guild_id, None)
                        asyncio.create_task(self.disconnect_with_warning(player))
                else:
                    # If 24/7 enabled but not playing -> Clear timer
                    self.disconnect_timers.pop(guild_id, None)
            else:
                 # Playing -> Clear timer
                 self.disconnect_timers.pop(guild_id, None)

            # Controller Update (Batched)
            if getattr(player, "update_pending", False):
                asyncio.create_task(player.update_controller())

    @commands.Cog.listener()
    async def on_cytechlink_track_end(self, player: cytechlink.Player, track: cytechlink.Track, _):
        await player.do_next()

    @commands.Cog.listener()
    async def on_cytechlink_track_stuck(self, player: cytechlink.Player, track: cytechlink.Track, _):
        await asyncio.sleep(10)
        player._track_is_stuck = False
        await player.do_next()

    @commands.Cog.listener() 
    async def on_cytechlink_track_exception(self, player: cytechlink.Player, track: cytechlink.Track, _): 
        try:
            player._track_is_stuck = True
            lang = await self.bot.get_lang(player.guild.id)
            await player.context.send(self.bot.i18n.get("error_next_song_10s", lang), delete_after=10)
        except:
            pass
        await player.do_next()

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot: return
        if before.channel == after.channel: return

        player: cytechlink.Player = member.guild.voice_client
        if not player or not player.channel: return

        # Check human members in the channel
        human_members = [m for m in player.channel.members if not m.bot]

        # Case: Bot is alone
        if len(human_members) == 0:
            # Check 24/7 mode from DB
            try:
                data = await collection_myasync.find_one({})
                is_247 = data.get("guilds", {}).get(str(member.guild.id), {}).get("24/7", False) if data else False
            except:
                is_247 = False
            
            if not is_247:
                # Leave immediately if not 24/7 and no one is left
                await player.teardown()
                return


        # Case: Human joined the channel
        if after.channel and after.channel.id == player.channel.id:
            # ONLY resume if it was auto-paused by the system
            if player.is_paused and getattr(player, "auto_paused", False):
                try:
                    # Auto resume if someone joins
                    await player.set_pause(False, requester=member, auto=False)
                    await self._notify_web_dashboard(member.guild.id)
                except:
                    pass
        
        # General Update
        await self._notify_web_dashboard(member.guild.id)

    async def _play(self, interaction: discord.Interaction, message: discord.Message):
        # Ensure we only defer if not already done
        if not interaction.response.is_done():
            await interaction.response.defer(thinking=True)
            
        lang = await self.bot.get_lang(interaction.guild.id)
        
        vc = getattr(interaction.user.voice, "channel", None)
        if not vc:
            msg = await interaction.followup.send(self.bot.i18n.get("error_voice_required", lang))
            await asyncio.sleep(7)
            await msg.delete()
            return

        player: cytechlink.Player
        if not (player := interaction.guild.voice_client):
            player = await cytechlink.connect_channel(interaction)

        search_query = message.content
        if not ("http" in search_query or "https" in search_query):
             # Try YouTube Music first (Better for music / less blocked)
             search_query_primary = f"ytmsearch:{search_query}"
             search_query_fallback = f"scsearch:{search_query}"
        else:
             search_query_primary = search_query
             search_query_fallback = None

        try:
            results = await player.get_tracks(search_query_primary, requester=interaction.user)
            # Fallback if primary yields no results AND it wasn't a direct URL
            if not results and search_query_fallback:
                 results = await player.get_tracks(search_query_fallback, requester=interaction.user)

        except Exception as e:
            # Try fallback on exception too
            if search_query_fallback:
                try:
                    results = await player.get_tracks(search_query_fallback, requester=interaction.user)
                except:
                    results = None
            else:
                results = None

        if not results:
            msg = await interaction.followup.send(self.bot.i18n.get("error_no_results", lang))
            await asyncio.sleep(7)
            await msg.delete()
            return

        try:
            if isinstance(results, cytechlink.Playlist):
                if results.tracks:
                    await player.add_track(results.tracks)
                    track = results.tracks[0] 
                else:
                    msg = await interaction.followup.send(self.bot.i18n.get("playlist_empty", lang))
                    await asyncio.sleep(7)
                    await msg.delete()
                    return
            else:
                track = results[0]
                await player.add_track(track)
        except Exception:
            msg = await interaction.followup.send(self.bot.i18n.get("queue_full", lang))
            await asyncio.sleep(7)
            await msg.delete()
            return

        try:
            desc = ""
            if isinstance(results, cytechlink.Playlist):
                desc = self.bot.i18n.get("added_playlist", lang, name=results.name, count=results.track_count)
                if results.uri:
                     desc = f"[{results.name}]({results.uri}) {self.bot.i18n.get('queue_title_added', lang)}"
            else:
                desc = self.bot.i18n.get("added_to_queue", lang, title=f"[{track.title}]({track.uri})")

            from utils.luxury import LuxuryEmbed, luxury_line
            embes = LuxuryEmbed(description=f"{luxury_line()}\n{desc}\n{luxury_line()}", color=ui_config.EMBED_COLOR)
            embes.set_author(name=self.bot.i18n.get("queue_title_added", lang), icon_url=self.bot.user.display_avatar.url)
            embes.set_thumbnail(url=self.bot.user.avatar.url)
            embes.add_luxury_footer(self.bot, lang, interaction.user)

            msg = await interaction.followup.send(embed=embes)
            await asyncio.sleep(7)
            await msg.delete()
        except Exception:
            msg = await interaction.followup.send(desc)
            await asyncio.sleep(7)
            await msg.delete()

        if not player.is_playing:
            try:
                player.controller = await interaction.followup.send(
                    embed=discord.Embed(
                        title=self.bot.i18n.get("searching", lang),
                        color=ui_config.EMBED_COLOR
                    )
                )
                await player.do_next()
            except Exception as e:
                print(f"Error starting playback: {e}")
                msg = await interaction.followup.send(self.bot.i18n.get("error_playback", lang))
                await asyncio.sleep(7)
                await msg.delete()
        else:
            await player.update_controller()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):  
        if message.author.bot: return
        if not message.guild: return
        
        try:
            data = await collection_myasync.find_one({})
            data = data if data else {"guilds": {}}
        except:
             data = {"guilds": {}}

        guild_id = str(message.guild.id)
        if "guilds" in data and guild_id in data["guilds"]:
            guild_data: dict = data["guilds"][guild_id]
            channel_id = guild_data.get("channel_id", None)
            play_embed_id = guild_data.get("play_embed_id", None)
            lang = guild_data.get("lang", "en")

            if channel_id and message.channel.id == channel_id:
                async with message.channel.typing():
                    try:
                        await message.delete()
                    except: pass
                    ctx = await self.bot.get_context(message)
                    search = message.content
                    vc = getattr(ctx.author.voice, "channel", None)
                    if not vc:
                        return await ctx.send(self.bot.i18n.get("error_voice_required", lang), delete_after=7)
                    if not (player := ctx.voice_client):
                        player = await cytechlink.connect_channel(ctx)
                    else:
                        player: cytechlink.Player = ctx.voice_client

                    try:
                        results = await player.get_tracks(search, requester=ctx.author)
                    except:
                        return await ctx.send(self.bot.i18n.get("error_no_results", lang), delete_after=7)
                    
                    if not results:
                        return await ctx.send(self.bot.i18n.get("error_no_results", lang), delete_after=7)

                    try:
                        if isinstance(results, cytechlink.Playlist):
                            await player.add_track(results.tracks)
                        else:
                            track = results[0]
                            await player.add_track(track)
                    except:
                        return await ctx.send(self.bot.i18n.get("queue_full", lang), delete_after=7)
                    
                    if isinstance(results, cytechlink.Playlist):
                         desc = self.bot.i18n.get("added_playlist", lang, name=results.name, count=results.track_count)
                         if results.uri: desc = f"[{results.name}]({results.uri}) {self.bot.i18n.get('queue_title_added', lang)}"
                    else:
                         desc = self.bot.i18n.get("added_to_queue", lang, title=f"[{track.title}]({track.uri})")

                    embes = discord.Embed(description=desc, color=ui_config.EMBED_COLOR)
                    embes.set_author(name=self.bot.i18n.get("queue_title_added", lang))
                    embes.set_thumbnail(url=self.bot.user.avatar.url)
                    embes.set_footer(text=self.bot.i18n.get("requested_by", lang, user=ctx.author.name), icon_url=ctx.author.avatar.url)
                    await ctx.send(embed=embes, delete_after=7)
                
                if not player.is_playing:
                    channel = self.bot.get_channel(channel_id)
                    try:
                        player.controller = await channel.fetch_message(play_embed_id)
                    except: 
                        pass
                    
                    # Call do_next cleanly outside the try/except
                    await player.do_next()
                else:
                    await player.update_controller()


    @commands.hybrid_command(aliases=["joi", "j", "summon", "su", "con", "connect"])
    @app_commands.describe(channel="Voice channel to join / ช่องเสียงที่ต้องการให้บอทเข้า")
    async def join(self, ctx: commands.Context, *, channel: discord.VoiceChannel = None):
        "Joins your voice channel / เข้าร่วมช่องเสียงของคุณ"
        async with ctx.typing():
            lang = await self.bot.get_lang(ctx.guild.id)
            if not ctx.voice_client:
                if not channel:
                    channel = getattr(ctx.author.voice, "channel", None)
                    if not channel:
                        return await ctx.reply(self.bot.i18n.get("error_voice_required", lang), delete_after=7)

                await cytechlink.connect_channel(ctx)
                await ctx.reply(self.bot.i18n.get("joined_voice", lang, channel=channel.mention), delete_after=7)
            else:
                await ctx.reply(self.bot.i18n.get("already_connected", lang, channel=ctx.voice_client.channel), delete_after=7)
            
    @commands.hybrid_command(aliases=["disconnect", "dc", "disc", "lv"])
    async def leave(self, ctx: commands.Context):
        "Disconnect the bot from voice channel / ตัดการเชื่อมต่อบอทจากช่องเสียง"
        async with ctx.typing():
            lang = await self.bot.get_lang(ctx.guild.id)
            player: cytechlink.Player = await check_access(ctx)
            if not player:
                 return await ctx.reply(self.bot.i18n.get("error_voice_required", lang), delete_after=7)
            
            if await player.is_privileged(ctx.author):
                await player.destroy()
                return await ctx.reply(self.bot.i18n.get("left_channel", lang), delete_after=7)
            return await ctx.reply(self.bot.i18n.get("dj_required", lang), delete_after=7)
    
    async def play_autocomplete(self, interaction: discord.Interaction, current: str):
        def shorten(text: str, max_len: int = 95) -> str:
            return text if len(text) <= max_len else text[:max_len - 3] + "..."

        choices = []
        user_id = str(interaction.user.id)
        data = await collection_myasync.find_one({}) or {"history": {}}
        user_history = data.get("history", {}).get(user_id, {}).get("recently_played", [])

        for song in user_history[:25]:
            val = f"https://www.youtube.com/watch?v={song['identifier']}"
            if len(val) > 100: val = val[:100]
            choices.append(app_commands.Choice(name="🕒 "+shorten(song["title"]), value=val))

        if current:
            try:
                tracks = await self.bot.cytech.get_node().get_tracks(f"ytsearch:{current}", requester=interaction.user)
                if not tracks:
                    tracks = []
            except Exception:
                tracks = []

            for song in tracks:
                if len(choices) >= 25: break
                
                val = song.uri or song.identifier
                if len(val) > 100:
                    val = song.identifier if len(song.identifier) <= 100 else val[:100]
                
                choices.append(app_commands.Choice(name=shorten(song.title), value=val))

        return choices
                
    @commands.hybrid_command(aliases=["pla", "p"])
    @app_commands.describe(search="Song name or link to play / ชื่อเพลงหรือลิงก์ youtube")
    @app_commands.autocomplete(search=play_autocomplete)
    async def play(self, ctx: commands.Context, *, search: str):
        """Play a song from any source / เล่นเพลงจากแหล่งต่างๆ"""
        # Safer deferral logic for hybrid commands:
        if not ctx.interaction or not ctx.interaction.response.is_done():
            try:
                await ctx.defer()
            except (discord.NotFound, discord.HTTPException):
                pass
            
        lang = await self.bot.get_lang(ctx.guild.id)
        vc = getattr(ctx.author.voice, "channel", None)
        if not vc:
            return await ctx.reply(self.bot.i18n.get("error_voice_required", lang), delete_after=7)

        player: cytechlink.Player
        if not (player := ctx.voice_client):
            player = await cytechlink.connect_channel(ctx)

        if not ("http" in search or "https" in search):
             # Force YouTube Music for better success rate
             search_primary = f"ytmsearch:{search}"
             search_fallback = f"scsearch:{search}"
        else:
             search_primary = search
             search_fallback = None

        try:
            results = await player.get_tracks(search_primary, requester=ctx.author)
            
            # Fallback Logic
            if not results and search_fallback:
                results = await player.get_tracks(search_fallback, requester=ctx.author)

        except Exception:
             if search_fallback:
                try:
                    results = await player.get_tracks(search_fallback, requester=ctx.author)
                except:
                    return await ctx.reply(self.bot.i18n.get("error_no_results", lang), delete_after=7)
             else:
                return await ctx.reply(self.bot.i18n.get("error_no_results", lang), delete_after=7)

        if not results:
            return await ctx.reply(self.bot.i18n.get("error_no_results", lang), delete_after=7)

        try:
            if isinstance(results, cytechlink.Playlist):
                if results.tracks:
                    await player.add_track(results.tracks)
                    asyncio.create_task(player.save_queue()) # Save Queue Persistently
                else:
                    return await ctx.reply(self.bot.i18n.get("playlist_empty", lang), delete_after=7)
            else:
                track = results[0]
                await player.add_track(track)
                asyncio.create_task(player.save_queue()) # Save Queue Persistently
        except Exception:
            return await ctx.reply(self.bot.i18n.get("queue_full", lang), delete_after=7)

        if isinstance(results, cytechlink.Playlist):
                desc = self.bot.i18n.get("added_playlist", lang, name=results.name, count=results.track_count)
                if results.uri: desc = f"[{results.name}]({results.uri}) {self.bot.i18n.get('queue_title_added', lang)}"
        else:
                desc = self.bot.i18n.get("added_to_queue", lang, title=f"[{track.title}]({track.uri})")

        embes = discord.Embed(description=desc, color=ui_config.EMBED_COLOR)
        embes.set_author(name=self.bot.i18n.get("queue_title_added", lang))
        embes.set_thumbnail(url=self.bot.user.avatar.url)
        embes.set_footer(text=self.bot.i18n.get("requested_by", lang, user=ctx.author.name), icon_url=getattr(ctx.author.avatar, 'url', None))
        await ctx.reply(embed=embes, delete_after=7)

        if player.is_playing:
            await player.update_controller()
            await self._notify_web_dashboard(ctx.guild.id)
            return

        try:
            player.controller = await ctx.send(
                embed=discord.Embed(title=self.bot.i18n.get("searching", lang), color=ui_config.EMBED_COLOR)
            )
            await player.do_next()
        except Exception as e:
            print(f"Error starting playback: {e}")
            await ctx.reply(self.bot.i18n.get("error_playback", lang), delete_after=7)

    @commands.hybrid_command(name="nowplaying", aliases=["np"])
    async def nowplaying(self, ctx: commands.Context):
        """Show the currently playing song / แสดงเพลงที่กำลังเล่นอยู่"""
        lang = await self.bot.get_lang(ctx.guild.id)
        player: cytechlink.Player = ctx.guild.voice_client
        
        if not player or not player.is_playing:
            return await ctx.send(self.bot.i18n.get("nothing_playing", lang), ephemeral=True)


        # Get persistent setup data
        data = await collection_myasync.find_one({}) or {"guilds": {}}
        guild_data = data.get("guilds", {}).get(str(ctx.guild.id), {})
        play_embed_id = guild_data.get("play_embed_id")

        # Logic: Always try to delete old one (if exists) and send new one in CURRENT channel
        if hasattr(player, "controller") and player.controller:
            # Don't delete if it's the persistent setup/music box
            if player.controller.id != play_embed_id:
                try:
                    await player.controller.delete()
                except:
                    pass
        
        # Send new controller in this channel
        view = cytechlink.MusicControls(player, ctx.author)
        embed = discord.Embed(description="Loading player...", color=ui_config.EMBED_COLOR)
        message = await ctx.send(embed=embed, view=view)
        player.controller = message
        
        await player.update_controller()
        
    class VolumeModal(discord.ui.Modal):
        def __init__(self, bot, ctx, lang="en"):   
            title = "Adjust Volume"
            if lang == "th":
                title = "ปรับระดับเสียง"
            super().__init__(title=title)
            self.bot = bot
            self.ctx = ctx
            self.lang = lang
            
            # Dynamic Label: recreate TextInput
            label = "Volume (1-100)"
            if lang == "th":
                label = "ระดับเสียง (1-100)"
                
            self.vol = discord.ui.TextInput(
                label=label, 
                min_length=1, 
                max_length=3, 
                required=True, 
                placeholder="50"
            )
            self.add_item(self.vol)

        async def on_submit(self, interaction: discord.Interaction):
            lang = await self.bot.get_lang(interaction.guild.id)
            player: cytechlink.Player = await check_access(self.ctx) 
            
            if not player or not interaction.guild.voice_client:
                return await interaction.response.send_message(self.bot.i18n.get("error_vol_not_playing", lang), ephemeral=True)
            
            if interaction.user not in player.channel.members:
                 return await interaction.response.send_message(self.bot.i18n.get("error_same_channel", lang), ephemeral=True)
            
            try:
                volume = int(self.vol.value)
            except ValueError:
                 return await interaction.response.send_message(self.bot.i18n.get("volume_invalid", lang), ephemeral=True)
            
            # Premium Check for Volume > 100
            max_vol = 100
            if await self.bot.is_premium(interaction.user.id, interaction.guild.id):
                max_vol = 200

            if not 0 < volume <= max_vol:
                if volume > 100 and max_vol == 100:
                    return await interaction.response.send_message(self.bot.i18n.get("premium_volume_limit", lang), ephemeral=True)
                return await interaction.response.send_message(self.bot.i18n.get("volume_invalid", lang), ephemeral=True)
            
            # Privilege check
            if not await player.is_privileged(interaction.user):
                 return await interaction.response.send_message(self.bot.i18n.get("dj_required", lang), ephemeral=True)
                 
            await player.set_volume(volume, requester=interaction.user)
            await interaction.response.send_message(self.bot.i18n.get("volume_set", lang, volume=volume), delete_after=7)


    @commands.hybrid_command(aliases=["vol", "v"])
    async def volume(self, ctx: commands.Context, volume: int = None):
        "Set music volume (1-100) / ปรับระดับเสียงเพลง (1-100)"
        
        # If no volume arg and it's an interaction (Slash Command), show Modal
        if volume is None:
            if ctx.interaction:
                # Modal ONLY works for interactions
                lang = await self.bot.get_lang(ctx.guild.id)
                modal = self.VolumeModal(self.bot, ctx, lang=lang)
                await ctx.interaction.response.send_modal(modal)
                return
            else:
                # If text command used without args
                lang = await self.bot.get_lang(ctx.guild.id)
                return await ctx.reply(self.bot.i18n.get("volume_invalid", lang), delete_after=7)

        # Standard Logic if volume is provided
        async with ctx.typing():
            lang = await self.bot.get_lang(ctx.guild.id)
            player: cytechlink.Player = await check_access(ctx)
            if not ctx.voice_client:
                return await ctx.reply(self.bot.i18n.get("error_vol_not_playing", lang), delete_after=7)
            
            if (ctx.author.voice is None or ctx.author.voice.channel != ctx.voice_client.channel):  
                return await ctx.reply(self.bot.i18n.get("error_same_channel", lang), delete_after=7)
            
            try:
                vol = int(volume)
            except ValueError:
                return await ctx.reply(self.bot.i18n.get("volume_invalid", lang), delete_after=7)
            
            # Premium Check for Volume > 100
            max_vol = 100
            if await self.bot.is_premium(ctx.author.id, ctx.guild.id):
                max_vol = 200

            if not 0 < vol <= max_vol:
                if vol > 100 and max_vol == 100:
                    return await ctx.reply(self.bot.i18n.get("premium_volume_limit", lang), delete_after=7)
                return await ctx.reply(self.bot.i18n.get("volume_invalid", lang), delete_after=7)
            
            if await player.is_privileged(ctx.author):
                await player.set_volume(vol, requester=ctx.author)
                await self._notify_web_dashboard(ctx.guild.id)
                return await ctx.reply(self.bot.i18n.get("volume_set", lang, volume=vol), delete_after=7)
            return await ctx.reply(self.bot.i18n.get("dj_required", lang), delete_after=7)

    @commands.hybrid_command(aliases=["pa", "pau", "res", "unpau"])
    async def pause(self, ctx: commands.Context):
        "Pause or Resume the music / หยุดชั่วคราว หรือ เล่นเพลงต่อ"
        async with ctx.typing():
            lang = await self.bot.get_lang(ctx.guild.id)
            player: cytechlink.Player = await check_access(ctx)
            if not ctx.voice_client:
                return await ctx.reply(self.bot.i18n.get("error_pause_not_playing", lang), delete_after=7)
            
            if (ctx.author.voice is None or ctx.author.voice.channel != ctx.voice_client.channel):      
                return await ctx.reply(self.bot.i18n.get("error_same_channel", lang), delete_after=7)
            
            if await player.is_privileged(ctx.author):
                await player.set_pause(not player.is_paused, requester=ctx.author.id)
                msg_key = "paused" if player.is_paused else "resumed"
                await self._notify_web_dashboard(ctx.guild.id)
                return await ctx.reply(self.bot.i18n.get(msg_key, lang), delete_after=7)
            return await ctx.reply(self.bot.i18n.get("dj_required", lang), delete_after=7)

    @commands.hybrid_command(aliases=["ski", "sk"])
    @app_commands.describe(index="Index of song to skip to (optional) / ลำดับเพลงที่ต้องการข้ามไป (ไม่จำเป็น)")
    async def skip(self, ctx: commands.Context, index: int = 0):
        "Skip to next song / ข้ามไปเพลงถัดไป"
        async with ctx.typing():
            lang = await self.bot.get_lang(ctx.guild.id)
            player: cytechlink.Player = await check_access(ctx)
            if not ctx.voice_client:
                return await ctx.reply(self.bot.i18n.get("error_skip_not_playing", lang), delete_after=7)
            
            if (ctx.author.voice is None or ctx.author.voice.channel != ctx.voice_client.channel):
                return await ctx.reply(self.bot.i18n.get("error_same_channel", lang), delete_after=7)
            
            if await player.is_privileged(ctx.author):
                if index:
                    try:
                        # User provides 1-based index, convert to 0-based
                        player.queue.skipto(index)
                    except cytechlink.exceptions.OutofList:
                        return await ctx.reply(self.bot.i18n.get("invalid_song_index", lang), delete_after=7)
                if player.queue._repeat.mode == cytechlink.LoopType.track:
                    await player.set_repeat(cytechlink.LoopType.off.name)
                await player.stop()
                await self._notify_web_dashboard(ctx.guild.id)
                return await ctx.reply(self.bot.i18n.get("skipped", lang, author=ctx.author), delete_after=7)
            return await ctx.reply(self.bot.i18n.get("dj_required", lang), delete_after=7)

    @commands.hybrid_command(name="skipto", aliases=["jump"])
    @app_commands.describe(index="Index of the song to skip to / ลำดับเพลงที่ต้องการข้ามไป")
    async def skipto(self, ctx: commands.Context, index: int):
        """Skip to a specific song in the queue / ข้ามไปเพลงที่ระบุลำดับ"""
        await self.skip(ctx, index=index)

    @commands.hybrid_command(name="clear", aliases=["cl"])
    async def clear(self, ctx: commands.Context):
        """Clear all songs in the queue / ล้างคิวเพลงทั้งหมด"""
        lang = await self.bot.get_lang(ctx.guild.id)
        player: cytechlink.Player = await check_access(ctx)
        
        if not player or player.queue.is_empty:
             return await ctx.reply(self.bot.i18n.get("queue_empty", lang), delete_after=7)

        if not await player.is_privileged(ctx.author):
             return await ctx.reply(self.bot.i18n.get("dj_required", lang), delete_after=7)
        
        player.queue.clear()
        player.queue.clear()
        await ctx.reply(self.bot.i18n.get("queue_cleared", lang), delete_after=7)
        await player.update_controller()
        await self._notify_web_dashboard(ctx.guild.id)

    @commands.hybrid_command(aliases=["sto", "st"])
    async def stop(self, ctx: commands.Context):
        "Stop music and disconnect / หยุดเพลงและออกจากช่องเสียง"
        async with ctx.typing():
            lang = await self.bot.get_lang(ctx.guild.id)
            player: cytechlink.Player = await check_access(ctx)
            if not ctx.voice_client:
                return await ctx.reply(self.bot.i18n.get("error_stop_not_playing", lang), delete_after=7)
            
            if (ctx.author.voice is None or ctx.author.voice.channel != ctx.voice_client.channel):
                return await ctx.reply(self.bot.i18n.get("error_same_channel", lang), delete_after=7)
            
            if await player.is_privileged(ctx.author):
                await player.teardown()
                await self._notify_web_dashboard(ctx.guild.id)
                return await ctx.reply(self.bot.i18n.get("stopped", lang), delete_after=10)
            return await ctx.reply(self.bot.i18n.get("dj_required", lang), delete_after=7)

    @commands.hybrid_command(name="seek")
    @app_commands.describe(position="Time position (e.g. 1:20) / ตำแหน่งเวลา (เช่น 1:20)")
    async def seek(self, ctx: commands.Context, position: str):
        "Seek to a specific time in the song / เลื่อนไปยังช่วงเวลาที่ต้องการ"
        lang = await self.bot.get_lang(ctx.guild.id)
        player: cytechlink.Player = await check_access(ctx)
        num = formatTime(position)
        if num is None:
            return await ctx.send(self.bot.i18n.get("invalid_time_format", lang), delete_after=7)

        await player.seek(num, ctx.author)
        await self._notify_web_dashboard(ctx.guild.id)
        await ctx.send(self.bot.i18n.get("seek_set", lang, position=position))

    @commands.hybrid_command(aliases=["qu", "que"])
    async def queue(self, ctx: commands.Context):
        "Show current music queue / แสดงคิวเพลงปัจจุบัน"
        async with ctx.typing():
            lang = await self.bot.get_lang(ctx.guild.id)
            player: cytechlink.Player = await check_access(ctx)
        
            if not player:
                return await ctx.reply(self.bot.i18n.get("no_player_found", lang), delete_after=7)
        
            queue: list[cytechlink.Track] = player.queue.tracks()
                
            if not queue:
                return await ctx.reply(self.bot.i18n.get("queue_empty", lang), delete_after=7)
        
            tracks = cytechlink.Track(
                track_id=player.current.track_id,
                info=cytechlink.decode(player.current.track_id),
                requester=player.current.requester
            )

            if len(queue) > 24:
                pages = []
                for i in range(0, len(queue), 24):
                    paginated_queue = queue[i:i+24]
                    embed = discord.Embed(
                        title=self.bot.i18n.get("queue_title", lang),
                        color=ui_config.EMBED_COLOR,
                    )
                    for i, track in enumerate(paginated_queue, start=i+1):
                        try:
                            embed.add_field(name="", value=f"**{i}.** [{track.title}]({track.uri})\n", inline=False)
                        except:
                            embed.add_field(name="", value=f"**{i}.** [{track.title}]({track.uri})\n", inline=False)
                    
                    try:
                        title_text = tracks.title.encode('utf-16', 'surrogatepass').decode('utf-16')
                    except:
                        title_text = tracks.title

                    now_text = f"[{title_text}]({tracks.uri})"
                    if tracks.is_stream:
                        now_text = self.bot.i18n.get("live_stream", lang, text=now_text)

                    embed.add_field(name=self.bot.i18n.get("now_playing_field", lang), value=now_text, inline=True)
                    embed.set_footer(text=self.bot.i18n.get("page_footer", lang, current=i//24 + 1, total=math.ceil(len(queue) / 24)), icon_url=str(self.bot.user.avatar.url))
                    pages.append(embed)
                
                page_view = page(self.bot, pages, ctx.author)
                message = await ctx.reply(embed=pages[0], view=page_view)
                page_view.message = message
                try: await page_view.buttons_use()
                except: pass
            else:
                embed = discord.Embed(title=self.bot.i18n.get("queue_title", lang), color=ui_config.EMBED_COLOR)
                for i, track in enumerate(queue, start=1):
                     embed.add_field(name="", value=f"**{i}.** [{track.title}]({track.uri})\n", inline=False)
                
                try:
                    title_text = tracks.title.encode('utf-16', 'surrogatepass').decode('utf-16')
                except:
                    title_text = tracks.title

                now_text = f"[{title_text}]({tracks.uri})"
                embed.add_field(name=self.bot.i18n.get("now_playing_field", lang), value=now_text, inline=True)
                embed.set_footer(text=self.bot.i18n.get("total_songs", lang, count=len(queue)), icon_url=str(self.bot.user.avatar.url))
                await ctx.reply(embed=embed)

    @commands.hybrid_command(name="fix")
    async def fix_region(self, ctx: commands.Context):
        "Fix voice issues by changing region / แก้ไขปัญหาเสียงด้วยการเปลี่ยน Region"
        async with ctx.typing():
            lang = await self.bot.get_lang(ctx.guild.id)
            if not ctx.author.voice or not ctx.author.voice.channel:
                 return await ctx.reply(self.bot.i18n.get("error_voice_required", lang), delete_after=7)

            channel = ctx.author.voice.channel
            # Permission check: Manage Channels
            if not channel.permissions_for(ctx.guild.me).manage_channels:
                 return await ctx.reply(self.bot.i18n.get("error_perm_manage_channels", lang), delete_after=7)

            current_region = str(channel.rtc_region) if channel.rtc_region else "automatic"
            
            try:
                # If specific region is set, find index
                idx = self.regions.index(current_region)
                new_region = self.regions[(idx + 1) % len(self.regions)]
            except ValueError:
                new_region = self.regions[0]

            try:
                await channel.edit(rtc_region=new_region)
                await ctx.reply(self.bot.i18n.get("region_fixed", lang, channel=channel.name, region=new_region), delete_after=10)
            except Exception as e:
                await ctx.reply(self.bot.i18n.get("region_fail", lang, e=e), delete_after=7)



    @commands.hybrid_command(name="remove", aliases=["rm"])
    @app_commands.describe(index="Index of the song to remove / ลำดับเพลงที่ต้องการลบ")
    async def remove(self, ctx: commands.Context, index: int):
        "Remove a song from the queue / ลบเพลงออกจากคิว"
        async with ctx.typing():
            lang = await self.bot.get_lang(ctx.guild.id)
            player: cytechlink.Player = await check_access(ctx)
            if not player:
                 return await ctx.reply(self.bot.i18n.get("no_player_found", lang), delete_after=7)
            
            # Require privilege to remove
            if not await player.is_privileged(ctx.author, strict=True):
                 return await ctx.reply(self.bot.i18n.get("dj_required", lang), delete_after=7)

            try:
                removed = player.queue.remove(index) 
                if removed:
                    track = removed[0]['track']
                    title = getattr(track, 'title', 'Unknown Track')
                    await ctx.reply(self.bot.i18n.get("removed_from_queue", lang, title=title), delete_after=7)
                    await player.update_controller()
                    await self._notify_web_dashboard(ctx.guild.id)
                else:
                     await ctx.reply(self.bot.i18n.get("invalid_song_index", lang), delete_after=7)
            except Exception:
                await ctx.reply("❌ Invalid song index.", delete_after=7)

    @commands.hybrid_command(name="shuffle", aliases=["sh"])
    async def shuffle(self, ctx: commands.Context):
        "Shuffle the queue / สุ่มลำดับเพลงในคิว"
        async with ctx.typing():
            lang = await self.bot.get_lang(ctx.guild.id)
            player: cytechlink.Player = await check_access(ctx)
            if not player:
                 return await ctx.reply(self.bot.i18n.get("no_player_found", lang), delete_after=7)

            if not await player.is_privileged(ctx.author): # Use standard check (supports vote if implemented in future, but shuffle usually strict or vote)
                 # Let's enforce strict for shuffle to avoid chaos, or standard check
                 # Standard check is fine if vote mode allows it? 
                 # Wait, player.shuffle doesn't have vote logic inside call, only buttons do.
                 # So command needs strict or vote logic. 
                 # For simplicity: Use Strict for commands to avoid complexity, or allow standard.
                if not await player.is_privileged(ctx.author, strict=True):
                    return await ctx.reply(self.bot.i18n.get("dj_required", lang), delete_after=7)

            player.queue.shuffle()
            await ctx.reply(self.bot.i18n.get("shuffled", lang), delete_after=7)
            await player.update_controller()
            await self._notify_web_dashboard(ctx.guild.id)

    # =========================================================================
    # NEW COMMANDS
    # =========================================================================

    @commands.hybrid_command(name="lyrics", aliases=["ly"])
    @app_commands.describe(query="Song to search lyrics for (optional) / ชื่อเพลงที่ต้องการค้นหาเนื้อร้อง")
    async def lyrics(self, ctx: commands.Context, *, query: str = None):
        """Get lyrics for the current or specified song / ดูเนื้อร้องเพลง"""
        await ctx.defer()
        lang = await self.bot.get_lang(ctx.guild.id)
        
        if not query:
            player: cytechlink.Player = ctx.guild.voice_client
            if player and player.is_playing:
                query = player.current.title
                import re
                query = re.sub(r"[\(\[].*?[\)\]]", "", query).strip()
            else:
                return await ctx.send(self.bot.i18n.get("nothing_playing", lang), ephemeral=True)
        
        search_url = f"https://www.google.com/search?q={query.replace(' ', '+')}+lyrics"
        embed = discord.Embed(
            title=f"Lyrics Search: {query}",
            description=f"Couldn't fetch full lyrics automatically (No API Key).\n[👉 Click here to search on Google]({search_url})",
            color=ui_config.EMBED_COLOR
        )
        await ctx.send(embed=embed)


    @commands.hybrid_command(name="grab", aliases=["save", "yoink"])
    async def grab(self, ctx: commands.Context):
        """Save current song to your DM / ส่งข้อมูลเพลงเข้า DM"""
        await ctx.defer(ephemeral=True)
        lang = await self.bot.get_lang(ctx.guild.id)
        player: cytechlink.Player = ctx.guild.voice_client

        if not player or not player.is_playing:
            return await ctx.send(self.bot.i18n.get("nothing_playing", lang), ephemeral=True)
            
        track = player.current
        
        embed = discord.Embed(title="Saved Track 💾", color=ui_config.EMBED_COLOR)
        embed.set_thumbnail(url=track.thumbnail)
        embed.add_field(name="Title", value=f"[{track.title}]({track.uri})", inline=False)
        embed.add_field(name="Author", value=track.author, inline=True)
        embed.add_field(name="Duration", value=track.formatted_length, inline=True)
        embed.add_field(name="Saved from", value=ctx.guild.name, inline=True)
        embed.set_footer(text=f"Saved by {ctx.author.name}")

        try:
            await ctx.author.send(embed=embed)
            await ctx.send("✅ Check your DMs!", ephemeral=True)
        except discord.Forbidden:
            await ctx.send("❌ I cannot DM you. Please check your privacy settings.", ephemeral=True)


    @commands.hybrid_command(name="removedupes", aliases=["rmd", "dedupe"])
    async def removedupes(self, ctx: commands.Context):
        """Remove duplicate songs from the queue / ลบเพลงซ้ำในคิว"""
        lang = await self.bot.get_lang(ctx.guild.id)
        player: cytechlink.Player = await check_access(ctx)
        
        if not player or player.queue.is_empty:
             return await ctx.send(self.bot.i18n.get("queue_empty", lang), ephemeral=True)

        if not await player.is_privileged(ctx.author):
             return await ctx.reply(self.bot.i18n.get("dj_required", lang), delete_after=7)

        unique_uris = set()
        new_queue = []
        removed_count = 0
        
        for track in player.queue:
            if track.uri not in unique_uris:
                unique_uris.add(track.uri)
                new_queue.append(track)
            else:
                removed_count += 1
        
        player.queue.clear()
        player.queue.extend(new_queue)
        
        await ctx.send(f"✅ Removed **{removed_count}** duplicate songs from the queue.")


    @commands.hybrid_command(name="move", aliases=["mv"])
    @app_commands.describe(from_index="Index of the song to move / ลำดับเพลงที่ต้องการย้าย", to_index="New position / ตำแหน่งใหม่")
    async def move(self, ctx: commands.Context, from_index: int, to_index: int):
        """Move a song to a different position in the queue / ย้ายตำแหน่งเพลง"""
        lang = await self.bot.get_lang(ctx.guild.id)
        player: cytechlink.Player = await check_access(ctx)
        
        if not player or player.queue.is_empty:
             return await ctx.send(self.bot.i18n.get("queue_empty", lang), ephemeral=True)

        if not await player.is_privileged(ctx.author, strict=True):
             return await ctx.reply(self.bot.i18n.get("dj_required", lang), delete_after=7)

        # Logic
        queue_len = len(player.queue)
        if not (1 <= from_index <= queue_len) or not (1 <= to_index <= queue_len):
             return await ctx.send("❌ Invalid index. / ลำดับเพลงไม่ถูกต้อง", ephemeral=True)
        
        if from_index == to_index:
             return await ctx.send("❌ Positions are the same. / ตำแหน่งเหมือนเดิม", ephemeral=True)

        # Adjust for 0-based index
        idx_from = from_index - 1
        idx_to = to_index - 1
        
        try:
            # We access the internal deque or list if needed, usually player.queue supports list ops
            track = player.queue[idx_from]
            del player.queue[idx_from]
            player.queue.insert(idx_to, track)
            
            track_title = getattr(track, 'title', 'Track')
            await ctx.send(self.bot.i18n.get("moved_track", lang, title=track_title, from_idx=from_index, to_idx=to_index))
            await player.update_controller()
        except Exception as e:
             await ctx.send(f"❌ Failed to move track: {e}", ephemeral=True)

    @commands.hybrid_command(name="history", aliases=["played"])
    async def history(self, ctx: commands.Context):
        """Show recently played songs / แสดงประวัติเพลงที่เล่นไปแล้ว"""
        lang = await self.bot.get_lang(ctx.guild.id)
        player: cytechlink.Player = await check_access(ctx)

        if not player:
            return await ctx.send(self.bot.i18n.get("no_player_active", lang), ephemeral=True)

        history_queue = player.queue.history()
        if not history_queue:
            return await ctx.send(self.bot.i18n.get("history_empty", lang), ephemeral=True)

        embed = discord.Embed(title=self.bot.i18n.get("history_title", lang), color=ui_config.EMBED_COLOR)
        
        # Show last 10 songs
        items = list(history_queue)[-10:]
        items.reverse() # Most recent first
        
        desc = ""
        for i, track in enumerate(items, 1):
            desc += f"**{i}.** [{track.title}]({track.uri}) - `{track.author}`\n"
            
        embed.description = desc
        embed.set_footer(text=f"Total History: {len(history_queue)}")
        
        await ctx.send(embed=embed)

async def setup(bot: Cyori):
    await bot.add_cog(Music(bot))