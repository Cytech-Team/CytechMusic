
import discord
from discord.ext import commands
from discord import app_commands
from typing import Union
from bot import Cyori, collection_myasync
from utils import config as ui_config
import cytechlink


async def check_access(ctx: Union[commands.Context, discord.Interaction]) -> cytechlink.Player | None:
    player: cytechlink.Player | None = ctx.guild.voice_client
    if not player:
        return None
    user = getattr(ctx, "author", None) or ctx.user
    if user not in player.channel.members and not await player.is_privileged(user):
        return None
    return player


class Settings(commands.Cog):
    def __init__(self, bot: Cyori):
        self.bot = bot

    async def _update_controller_if_playing(self, guild_id: int):
        """เรียกอัปเดต embed + controller ทันที ถ้ากำลังเล่นเพลงอยู่"""
        player = None
        for p in self.bot.voice_clients:
            if p.guild.id == guild_id:
                player = p
                break
        
        if player and player.is_playing and hasattr(player, "update_controller"):
            try:
                await player.update_controller()
            except:
                pass

    # ===================================================================
    # RESET SETTINGS
    # ===================================================================
    @commands.hybrid_command(name="reset", description="Reset settings to default / รีเซ็ตการตั้งค่าเป็นค่าเริ่มต้น")
    @commands.has_permissions(manage_guild=True)
    async def reset(self, ctx: commands.Context):
        await ctx.defer()
        lang = await self.bot.get_lang(ctx.guild.id)
        
        try:
            # Preserve Premium Status
            data = await collection_myasync.find_one({}) or {}
            is_prem = data.get("guilds", {}).get(str(ctx.guild.id), {}).get("premium", False)

            # Unset the guild's data in the single document
            await collection_myasync.update_one(
                {},
                {"$unset": {f"guilds.{ctx.guild.id}": ""}}
            )
            
            # Restore Premium
            if is_prem:
                 await collection_myasync.update_one(
                    {},
                    {"$set": {f"guilds.{ctx.guild.id}.premium": True}}
                )

            # Use i18n or fallback
            msg = self.bot.i18n.get("reset_success", lang)
            if not msg or msg == "reset_success":
                 msg = self.bot.i18n.get("reset_success", lang)
            await ctx.send(msg, ephemeral=False)
        except Exception as e:
            await ctx.send(f"Failed to reset settings: {e}", ephemeral=True)

    # ===================================================================
    # SETUP
    # ===================================================================
    @commands.hybrid_command(name="setup", description="Create music request channel / สร้างห้องขอเพลง")
    @commands.has_permissions(manage_channels=True)
    @commands.guild_only()
    async def setup(self, ctx: commands.Context):
        await ctx.defer()
        lang = await self.bot.get_lang(ctx.guild.id)

        try:
            guild_id = ctx.guild.id
            data = await collection_myasync.find_one({}) or {}
            old_channel_id = data.get("guilds", {}).get(str(guild_id), {}).get("channel_id")
            
            channel = ctx.guild.get_channel(old_channel_id) if old_channel_id else None

            if channel:
                # Reuse existing channel: Clear it
                if hasattr(channel, 'purge'):
                    await channel.purge(limit=100)
            else:
                # Create new channel if not found
                channel = await ctx.guild.create_text_channel(
                    name="〔🎶〕〢Cyori",
                    category=ctx.channel.category,
                    slowmode_delay=3,
                    topic=self.bot.i18n.get("join_voice_chat_title", lang)
                )

            g_data = data.get("guilds", {}).get(str(guild_id), {})

            queue_embed = discord.Embed(title=self.bot.i18n.get("no_queue", lang), color=ui_config.EMBED_COLOR)
            play_embed = self.bot.none_play_embed(lang, g_data)

            q_msg = await channel.send(embed=queue_embed)
            p_msg = await channel.send(embed=play_embed)

            await save_data_setup(guild_id, q_msg.id, p_msg.id, channel.id)
            await ctx.send(self.bot.i18n.get("setup_complete", lang, channel=channel.mention), ephemeral=False)

            await self._update_controller_if_playing(guild_id)

        except Exception as e:
            await ctx.send(f"Setup failed: {e}", ephemeral=True)

    # ===================================================================
    # PREFIX
    # ===================================================================
    @commands.hybrid_command(name="prefix", description="Change bot prefix / เปลี่ยนคำนำหน้าบอท")
    @commands.has_permissions(manage_guild=True)
    @app_commands.describe(prefix="New prefix (max 5 chars) / คำนำหน้าใหม่ (สูงสุด 5 ตัวอักษร)")
    async def prefix(self, ctx: commands.Context, prefix: str):
        lang = await self.bot.get_lang(ctx.guild.id)
        if len(prefix) > 5:
            return await ctx.send(self.bot.i18n.get("prefix_too_long", lang), ephemeral=True)

        await ctx.defer()
        await save_data_prefix(ctx.guild.id, prefix)
        await ctx.send(self.bot.i18n.get("prefix_changed", lang, prefix=prefix), ephemeral=False)

    # ===================================================================
    # LANGUAGE
    # ===================================================================
    @commands.hybrid_command(name="language", description="Change bot language / เปลี่ยนภาษาของบอท")
    @commands.has_permissions(manage_guild=True)
    @app_commands.describe(lang="Select language / เลือกภาษา")
    @app_commands.choices(lang=[
        app_commands.Choice(name="English", value="en"),
        app_commands.Choice(name="Thai", value="th")
    ])
    async def language(self, ctx: commands.Context, lang: str):
        if not ctx.interaction or not ctx.interaction.response.is_done():
            try:
                await ctx.defer()
            except (discord.NotFound, discord.HTTPException):
                pass
        # Hybrid command passes 'choice' value as str, not object
        
        await save_data_language(ctx.guild.id, lang)
        
        # Helper map for display
        names = {"en": "English", "th": "Thai"}
        display = names.get(lang, lang)
        
        # Use lang_name to avoid format conflict
        resp = self.bot.i18n.get("lang_set", lang, lang_name=display)
        
        # 1. Update the setup channel UI immediately if it exists
        try:
             data = await collection_myasync.find_one({}) or {}
             if "guilds" in data and str(ctx.guild.id) in data["guilds"]:
                 g_data = data["guilds"][str(ctx.guild.id)]
                 # Force reload lang in g_data since we just saved it but didn't refetch
                 g_data["lang"] = lang 
                 await self.bot.update_guild_embed(g_data, guild_id=ctx.guild.id)
        except Exception as e:
            print(f"Update UI error: {e}")

        # 2. Update player controller if playing
        await self._update_controller_if_playing(ctx.guild.id)

        # 3. Send response
        if ctx.interaction:
             await ctx.send(resp)
        else:
             await ctx.reply(resp)


    # ===================================================================
    # 24/7
    # ===================================================================
    @commands.hybrid_command(name="247", description="Toggle 24/7 mode / เปิด-ปิดโหมด 24/7 (บอทไม่หลุด)")
    @commands.has_permissions(manage_guild=True)
    async def playforever(self, ctx: commands.Context):
        await ctx.defer()
        lang = await self.bot.get_lang(ctx.guild.id)

        # Premium Only Check
        if not await self.bot.is_premium(ctx.author.id, ctx.guild.id):
            embed = discord.Embed(
                title=self.bot.i18n.get("premium_required_title", lang),
                description=self.bot.i18n.get("premium_required_desc", lang, feature="24/7 Mode"),
                color=ui_config.EMBED_COLOR
            )
            embed.set_footer(text="Premium Feature", icon_url=self.bot.user.avatar.url)
            
            view = discord.ui.View()
            view.add_item(discord.ui.Button(label="Get Premium", url=ui_config.DONATE_URL, style=discord.ButtonStyle.link))
            
            return await ctx.send(embed=embed, view=view, ephemeral=True)

        current = (await collection_myasync.find_one({}) or {}).get("guilds", {}).get(str(ctx.guild.id), {}).get("24/7", False)
        new_state = not current
        await save_data_247(ctx.guild.id, new_state)

        player = ctx.guild.voice_client
        if player and hasattr(player, "mode247"):
            player.mode247 = new_state


        state_key = "enabled" if new_state else "disabled"
        state_text = self.bot.i18n.get(state_key, lang)
        await ctx.send(self.bot.i18n.get("247_mode", lang, state=state_text), ephemeral=False)
        await self._update_controller_if_playing(ctx.guild.id)

    # ===================================================================
    # AUTOPLAY
    # ===================================================================
    @commands.hybrid_command(name="autoplay", description="Toggle Autoplay / เปิด-ปิดเล่นเพลงอัตโนมัติ")
    @commands.guild_only()
    async def autoplay(self, ctx: commands.Context):
        await ctx.defer()
        lang = await self.bot.get_lang(ctx.guild.id)

        if not await self.bot.check_vote(ctx.author.id, ctx.guild.id):
            view = discord.ui.View()
            view.add_item(discord.ui.Button(label="Vote on Top.gg", url=ui_config.VOTE_URL, style=discord.ButtonStyle.link))
            return await ctx.send(embed=discord.Embed(title=self.bot.i18n.get("vote_required", lang), 
                                                      description=self.bot.i18n.get("vote_desc", lang, feature="Autoplay"), 
                                                      color=ui_config.EMBED_COLOR), view=view, ephemeral=True)

        player = await check_access(ctx)
        if not player:
            return await ctx.send(self.bot.i18n.get("no_player_active", lang), ephemeral=True)

        if not await player.is_privileged(ctx.author, strict=True):
            return await ctx.send(self.bot.i18n.get("dj_required", lang), ephemeral=True)

        new_state = not getattr(player, "autoplay", False)
        await save_data_autoplay(ctx.guild.id, new_state)
        player.autoplay = new_state

        state_key = "enabled" if new_state else "disabled"
        state_text = self.bot.i18n.get(state_key, lang)
        await ctx.send(self.bot.i18n.get("autoplay_mode", lang, state=state_text), ephemeral=False)
        await self._update_controller_if_playing(ctx.guild.id)

        if new_state and not player.is_playing:
            await player.do_next()


    # ===================================================================
    # DJ SETTINGS
    # ===================================================================

    @commands.hybrid_command(name="djrole", description="Set DJ Role / ตั้งค่า role ที่เป็น DJ")
    @app_commands.describe(role="The role to set as DJ / role ที่จะให้เป็น DJ")
    async def dj_role(self, ctx: commands.Context, role: discord.Role):
        await ctx.defer()
        lang = await self.bot.get_lang(ctx.guild.id)
        await save_data_dj_role(ctx.guild.id, role.id)
        # Assuming simple response for now or add to i18n later if requested
        await ctx.send(f"✅ Set DJ role to {role.mention}")

    @commands.hybrid_command(name="djmode", description="Toggle DJ Mode (Strict Mode) / เปิด-ปิดโหมด DJ")
    async def dj_mode(self, ctx: commands.Context):
        await ctx.defer()
        lang = await self.bot.get_lang(ctx.guild.id)
        data = await collection_myasync.find_one({}) or {}
        current = data.get("guilds", {}).get(str(ctx.guild.id), {}).get("dj_mode", False)
        new_state = not current
        await save_data_dj_mode(ctx.guild.id, new_state)
        state_text = "Enabled (Only DJ/Admin can control)" if new_state else "Disabled (Everyone in VC can control)"
        await ctx.send(f"✅ DJ Mode is now **{state_text}**")

    @commands.hybrid_command(name="vote_mode", description="Toggle Vote Mode / เปิด-ปิดโหมดโหวต")
    async def vote_mode(self, ctx: commands.Context):
        await ctx.defer()
        lang = await self.bot.get_lang(ctx.guild.id)
        data = await collection_myasync.find_one({}) or {}
        current = data.get("guilds", {}).get(str(ctx.guild.id), {}).get("vote_mode", False)
        new_state = not current
        await save_data_vote_mode(ctx.guild.id, new_state)
        state_text = "Enabled" if new_state else "Disabled"
        await ctx.send(f"✅ Vote Mode is now **{state_text}**") 

    # ===================================================================
    # VIEW SETTINGS
    # ===================================================================
    @commands.hybrid_command(name="viewsettings", aliases=["settings", "config"], description="View current server settings / ดูการตั้งค่าปัจจุบัน")
    @commands.has_permissions(manage_guild=True)
    async def view_settings(self, ctx: commands.Context):
        await ctx.defer()
        lang = await self.bot.get_lang(ctx.guild.id)
        
        try:
            data = await collection_myasync.find_one({}) or {}
            guild_data = data.get("guilds", {}).get(str(ctx.guild.id), {})
            
            prefix = guild_data.get("prefix", ui_config.DEFAULT_PREFIX)
            language = guild_data.get("lang", "en")
            mode_247 = guild_data.get("24/7", False)
            autoplay = guild_data.get("autoplay", False)
            channel_id = guild_data.get("channel_id")
            dj_role_id = guild_data.get("dj_role")
            dj_mode = guild_data.get("dj_mode", False)
            vote_mode = guild_data.get("vote_mode", False)

            # Language display mapping
            lang_display = {
                "en": "English 🇺🇸",
                "th": "ไทย 🇹🇭"
            }
            language_text = lang_display.get(language, language.upper())

            # Section headers by language
            # Section headers by language
            section_general = self.bot.i18n.get("settings_sect_general", lang)
            section_player = self.bot.i18n.get("settings_sect_player", lang)
            section_perms = self.bot.i18n.get("settings_sect_perms", lang)

            # Helper to get Enabled/Disabled with emoji
            def get_state(bool_val):
                if bool_val:
                    return f"✅ **{self.bot.i18n.get('enabled', lang)}**"
                return f"❌ **{self.bot.i18n.get('disabled', lang)}**"
            
            not_set = f"⚠️ *{self.bot.i18n.get('not_set', lang)}*"

            # Build embed
            embed = discord.Embed(color=ui_config.EMBED_COLOR)
            embed.set_author(
                name=self.bot.i18n.get("settings_title", lang, guild=ctx.guild.name),
                icon_url=ctx.guild.icon.url if ctx.guild.icon else self.bot.user.avatar.url
            )

            # General Settings
            general_value = (
                f"📝 **{self.bot.i18n.get('prefix_label', lang)}:** `{prefix}`\n"
                f"🌐 **{self.bot.i18n.get('lang_label', lang)}:** {language_text}\n"
                f"📻 **{self.bot.i18n.get('setup_channel_label', lang)}:** {f'<#{channel_id}>' if channel_id else not_set}"
            )
            embed.add_field(name=section_general, value=general_value, inline=False)

            # Player Settings
            player_value = (
                f"⏰ **{self.bot.i18n.get('247_label', lang)}:** {get_state(mode_247)}\n"
                f"🔄 **{self.bot.i18n.get('autoplay_label', lang)}:** {get_state(autoplay)}"
            )
            embed.add_field(name=section_player, value=player_value, inline=False)

            # Permission Settings
            dj_role_str = f"<@&{dj_role_id}>" if dj_role_id else not_set
            dj_mode_label = self.bot.i18n.get("settings_dj_mode", lang)
            vote_mode_label = self.bot.i18n.get("settings_vote_mode", lang)
            
            perms_value = (
                f"👑 **DJ Role:** {dj_role_str}\n"
                f"{dj_mode_label} {get_state(dj_mode)}\n"
                f"{vote_mode_label} {get_state(vote_mode)}"
            )
            embed.add_field(name=section_perms, value=perms_value, inline=False)
            
            # Footer with requester info
            embed.set_footer(
                text=self.bot.i18n.get("requested_by", lang, user=ctx.author.display_name),
                icon_url=ctx.author.avatar.url if ctx.author.avatar else None
            )
            embed.timestamp = discord.utils.utcnow()
            
            await ctx.send(embed=embed)

        except Exception as e:
            await ctx.send(f"Failed to fetch settings: {e}", ephemeral=True)
# ===================================================================
# CLEAN & FAST DB HELPERS
# ===================================================================
async def save_data_setup(guild_id: int, queue_embed_id: int, play_embed_id: int, channel_id: int):
    await collection_myasync.update_one(
        {},
        {"$set": {
            f"guilds.{guild_id}.queue_embed_id": queue_embed_id,
            f"guilds.{guild_id}.play_embed_id": play_embed_id,
            f"guilds.{guild_id}.channel_id": channel_id
        }},
        upsert=True
    )

async def save_data_247(guild_id: int, state: bool):
    await collection_myasync.update_one({}, {"$set": {f"guilds.{guild_id}.24/7": state}}, upsert=True)

async def save_data_autoplay(guild_id: int, state: bool):
    await collection_myasync.update_one({}, {"$set": {f"guilds.{guild_id}.autoplay": state}}, upsert=True)

async def save_data_prefix(guild_id: int, prefix: str):
    await collection_myasync.update_one({}, {"$set": {f"guilds.{guild_id}.prefix": prefix}}, upsert=True)

async def save_data_language(guild_id: int, lang: str):
    await collection_myasync.update_one({}, {"$set": {f"guilds.{guild_id}.lang": lang}}, upsert=True)

async def save_data_dj_role(guild_id: int, role_id: int):
    await collection_myasync.update_one({}, {"$set": {f"guilds.{guild_id}.dj_role": role_id}}, upsert=True)

async def save_data_vote_mode(guild_id: int, mode: bool):
    await collection_myasync.update_one({}, {"$set": {f"guilds.{guild_id}.vote_mode": mode}}, upsert=True)

async def save_data_dj_mode(guild_id: int, mode: bool):
    await collection_myasync.update_one({}, {"$set": {f"guilds.{guild_id}.dj_mode": mode}}, upsert=True)


    # ===================================================================
    # UTILITY: FIX & CLEANUP
    # ===================================================================
    @commands.hybrid_command(name="fix", description="Fix voice connection issues / แก้ไขปัญหาเสียงหาย")
    @commands.has_permissions(manage_guild=True)
    async def fix(self, ctx: commands.Context):
        """Fix voice issues by changing region or reconnecting"""
        await ctx.defer()
        lang = await self.bot.get_lang(ctx.guild.id)
        
        if not ctx.guild.voice_client:
            return await ctx.send(self.bot.i18n.get("no_player_found", lang), ephemeral=True)

        try:
            # Method 1: Change Region (Effective for "No Sound")
            # We toggle between typical regions or let Discord handle 'automatic'
            current_region = ctx.guild.region
            # discord.py 2.0+ handles regions differently (RTC Region in Voice Channels)
            vc = ctx.guild.voice_client.channel
            
            if hasattr(vc, "rtc_region"):
                # Toggle
                new_region = "singapore" if vc.rtc_region is None else None 
                await vc.edit(rtc_region=new_region)
                display_region = new_region if new_region else "Automatic"
                await ctx.send(self.bot.i18n.get("fix_voice", lang, region=display_region))
            else:
                 await ctx.send("❌ Cannot change voice region (Not supported).")
                 
        except Exception as e:
            await ctx.send(self.bot.i18n.get("fix_voice_error", lang, e=e))

    @commands.hybrid_command(name="voicefix", description="Force Reconnect Voice / บังคับเชื่อมต่อเสียงใหม่")
    @commands.has_permissions(manage_guild=True)
    async def voicefix(self, ctx: commands.Context):
        """Force bot to disconnect and reconnect to voice channel"""
        await ctx.defer()
        lang = await self.bot.get_lang(ctx.guild.id)
        
        player = ctx.guild.voice_client
        if not player or not player.channel:
             return await ctx.send(self.bot.i18n.get("no_player_found", lang), ephemeral=True)

        channel = player.channel
        try:
            # 1. Disconnect
            await player.disconnect(force=True)
            # 2. Reconnect
            await channel.connect(cls=cytechlink.Player)
            await ctx.send("✅ **Voice Connection Reset!** / รีเซ็ตการเชื่อมต่อเสียงเรียบร้อย")
            
            # 3. Restore controller if possible
            # Note: Queue might be cleared depending on player implementation, 
            # Wavelink usually clears queue on disconnect unless specifically handled.
            # CytechLink likely behaves similarly.
        except Exception as e:
            await ctx.send(f"❌ Voice Fix failed: {e}", ephemeral=True)

    @commands.hybrid_command(name="cleanup", description="Clean up bot messages / ลบข้อความของบอท")
    @commands.has_permissions(manage_messages=True)
    async def cleanup(self, ctx: commands.Context, limit: int = 50):
        """Delete recent bot messages to clean up channel"""
        await ctx.defer(ephemeral=True)
        lang = await self.bot.get_lang(ctx.guild.id)
        
        if limit > 100: limit = 100
        
        try:
            def is_bot(m):
                return m.author == self.bot.user or m.content.startswith(tuple(self.bot.command_prefix))

            deleted = await ctx.channel.purge(limit=limit, check=is_bot)
            await ctx.send(self.bot.i18n.get("cleanup_message", lang, count=len(deleted)), ephemeral=True)
        except Exception as e:
            await ctx.send(f"❌ Clean up failed: {e}", ephemeral=True)

async def setup(bot: Cyori):
    await bot.add_cog(Settings(bot))