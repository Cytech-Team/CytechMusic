"""
Filter Cog - Audio filters and effects for Cyori
Rebuilt with clean code, proper error handling, and i18n support
"""

import discord
import cytechlink
from typing import Union, Optional
from discord.ext import commands
from discord import app_commands
from bot import Cyori
from utils import config as ui_config


async def check_access(ctx: Union[commands.Context, discord.Interaction]) -> Optional[cytechlink.Player]:
    """Check if user has access to control the player."""
    player: cytechlink.Player = ctx.guild.voice_client
    if not player:
        return None

    user = getattr(ctx, "author", None) or ctx.user
    
    # Check if the user is in the voice channel
    if user not in player.channel.members:
        if not await player.is_privileged(user):
            return None

    return player


async def require_vote(bot: Cyori, ctx: commands.Context) -> bool:
    """
    Check if user has voted. Returns True if voted, False otherwise.
    If not voted, sends a vote prompt and returns False.
    """
    has_voted = await bot.check_vote(ctx.author.id, ctx.guild.id)
    if has_voted:
        return True
    
    lang = await bot.get_lang(ctx.guild.id)
    view = discord.ui.View()
    view.add_item(discord.ui.Button(
        style=discord.ButtonStyle.link, 
        label=bot.i18n.get("button_vote", lang), 
        url=ui_config.VOTE_URL
    ))
    embed = discord.Embed(
        title=bot.i18n.get("vote_required", lang),
        description=bot.i18n.get("vote_desc", lang, feature="Audio Filters"),
        color=ui_config.EMBED_COLOR
    )
    await ctx.reply(embed=embed, view=view, delete_after=15)
    return False

async def require_premium(bot: Cyori, ctx: commands.Context, feature_name: str) -> bool:
    """
    Check if user is premium. Returns True if premium, False otherwise.
    If not premium, sends a premium prompt and returns False.
    """
    if await bot.is_premium(ctx.author.id, ctx.guild.id):
        return True
    
    lang = await bot.get_lang(ctx.guild.id)
    embed = discord.Embed(
        title=bot.i18n.get("premium_required_title", lang),
        description=bot.i18n.get("premium_required_desc", lang, feature=feature_name),
        color=ui_config.EMBED_COLOR
    )
    view = discord.ui.View()
    view.add_item(discord.ui.Button(
        style=discord.ButtonStyle.link, 
        label=bot.i18n.get("button_premium", lang), 
        url=ui_config.DONATE_URL
    ))
    await ctx.reply(embed=embed, view=view, delete_after=15)
    return False

class Filter(commands.Cog):
    """Audio filter commands for music playback."""
    
    def __init__(self, bot: Cyori) -> None:
        self.bot = bot

    async def _get_player_or_error(self, ctx: commands.Context) -> Optional[cytechlink.Player]:
        """Get player with proper error handling."""
        player = await check_access(ctx)
        if not player:
            lang = await self.bot.get_lang(ctx.guild.id)
            await ctx.reply(self.bot.i18n.get("no_player_found", lang), delete_after=7)
            return None
        return player

    async def effect_autocomplete(self, interaction: discord.Interaction, current: str) -> list:
        """Autocomplete for effect names."""
        player: cytechlink.Player = interaction.guild.voice_client
        if not player:
            return []
        
        filters = player.filters.get_filters()
        if current:
            return [
                app_commands.Choice(name=effect.tag, value=effect.tag) 
                for effect in filters if current.lower() in effect.tag.lower()
            ]
        return [app_commands.Choice(name=effect.tag, value=effect.tag) for effect in filters]

    # =========================================================================
    # SPEED
    # =========================================================================
    @commands.hybrid_command(name="speed")
    @app_commands.describe(value="Speed multiplier (e.g. 1.25) / ตัวคูณความเร็ว (เช่น 1.25)")
    async def speed(self, ctx: commands.Context, value: commands.Range[float, 0.1, 2.0]):
        """Set playback speed / ปรับความเร็วเพลง"""
        async with ctx.typing():
            if not await require_premium(self.bot, ctx, "Speed Control"):
                return
            
            player = await self._get_player_or_error(ctx)
            if not player:
                return

            if player.filters.has_filter(filter_tag="speed"):
                player.filters.remove_filter(filter_tag="speed")
            
            await player.add_filter(cytechlink.Timescale(tag="speed", speed=value))
            
            lang = await self.bot.get_lang(ctx.guild.id)
            await ctx.reply(self.bot.i18n.get("filter_speed", lang, value=value), delete_after=7)

    # =========================================================================
    # KARAOKE
    # =========================================================================
    @commands.hybrid_command(name="karaoke")
    @app_commands.describe(
        level="Vocals level (default 1.0) / ระดับเสียงร้อง (ปกติ 1.0)",
        monolevel="Mono level (default 1.0) / ระดับ Mono (ปกติ 1.0)",
        filterband="Filter band (default 220.0) / แบนด์ความถี่ (ปกติ 220.0)",
        filterwidth="Filter width (default 100.0) / ความกว้างความถี่ (ปกติ 100.0)"
    )
    async def karaoke(
        self, ctx: commands.Context, 
        level: commands.Range[float, 0.0, 2.0] = 1.0, 
        monolevel: commands.Range[float, 0.0, 2.0] = 1.0, 
        filterband: commands.Range[float, 100.0, 300.0] = 220.0, 
        filterwidth: commands.Range[float, 50.0, 150.0] = 100.0
    ) -> None:
        """Apply karaoke effect (remove vocals) / เปิดโหมดคาราโอเกะ (ตัดเสียงร้อง)"""
        async with ctx.typing():
            if not await require_premium(self.bot, ctx, "Karaoke Mode"):
                return
            
            player = await self._get_player_or_error(ctx)
            if not player:
                return

            if player.filters.has_filter(filter_tag="karaoke"):
                player.filters.remove_filter(filter_tag="karaoke")
            
            await player.add_filter(cytechlink.Karaoke(
                tag="karaoke", 
                level=level, 
                mono_level=monolevel, 
                filter_band=filterband, 
                filter_width=filterwidth
            ))
            lang = await self.bot.get_lang(ctx.guild.id)
            await ctx.reply(self.bot.i18n.get("filter_karaoke", lang, level=level, monolevel=monolevel), delete_after=7)

    # =========================================================================
    # TREMOLO
    # =========================================================================
    @commands.hybrid_command(name="tremolo")
    @app_commands.describe(
        frequency="Frequency (default 2.0) / ความถี่ (ปกติ 2.0)",
        depth="Depth (default 0.5) / ความลึก (ปกติ 0.5)"
    )
    async def tremolo(
        self, ctx: commands.Context, 
        frequency: commands.Range[float, 0.1, 10.0] = 2.0, 
        depth: commands.Range[float, 0.0, 1.0] = 0.5
    ) -> None:
        """Apply tremolo effect / เปิดเอฟเฟกต์ Tremolo (สั่น)"""
        async with ctx.typing():
            if not await require_premium(self.bot, ctx, "Tremolo Effect"):
                return
            
            player = await self._get_player_or_error(ctx)
            if not player:
                return

            if player.filters.has_filter(filter_tag="tremolo"):
                player.filters.remove_filter(filter_tag="tremolo")
            
            await player.add_filter(cytechlink.Tremolo(tag="tremolo", frequency=frequency, depth=depth))
            lang = await self.bot.get_lang(ctx.guild.id)
            await ctx.reply(self.bot.i18n.get("filter_tremolo", lang, frequency=frequency, depth=depth), delete_after=7)

    # =========================================================================
    # VIBRATO
    # =========================================================================
    @commands.hybrid_command(name="vibrato")
    @app_commands.describe(
        frequency="Frequency (default 2.0) / ความถี่ (ปกติ 2.0)",
        depth="Depth (default 0.5) / ความลึก (ปกติ 0.5)"
    )
    async def vibrato(
        self, ctx: commands.Context, 
        frequency: commands.Range[float, 0.1, 14.0] = 2.0, 
        depth: commands.Range[float, 0.0, 1.0] = 0.5
    ) -> None:
        """Apply vibrato effect / เปิดเอฟเฟกต์ Vibrato (ลูกคอ)"""
        async with ctx.typing():
            if not await require_premium(self.bot, ctx, "Vibrato Effect"):
                return
            
            player = await self._get_player_or_error(ctx)
            if not player:
                return

            if player.filters.has_filter(filter_tag="vibrato"):
                player.filters.remove_filter(filter_tag="vibrato")
            
            await player.add_filter(cytechlink.Vibrato(tag="vibrato", frequency=frequency, depth=depth))
            lang = await self.bot.get_lang(ctx.guild.id)
            await ctx.reply(self.bot.i18n.get("filter_vibrato", lang, frequency=frequency, depth=depth), delete_after=7)

    # =========================================================================
    # ROTATION (8D)
    # =========================================================================
    @commands.hybrid_command(name="rotation")
    @app_commands.describe(hertz="Rotation speed (hertz) / ความเร็วการหมุน")
    async def rotation(self, ctx: commands.Context, hertz: commands.Range[float, 0.01, 2.0] = 0.2) -> None:
        """Apply rotation effect (8D audio) / เปิดเอฟเฟกต์หมุนเสียง (8D)"""
        async with ctx.typing():
            if not await require_premium(self.bot, ctx, "Rotation (8D) Control"):
                return
            
            player = await self._get_player_or_error(ctx)
            if not player:
                return

            if player.filters.has_filter(filter_tag="rotation"):
                player.filters.remove_filter(filter_tag="rotation")
            
            await player.add_filter(cytechlink.Rotation(tag="rotation", rotation_hertz=hertz))
            lang = await self.bot.get_lang(ctx.guild.id)
            await ctx.reply(self.bot.i18n.get("filter_rotation", lang, hertz=hertz), delete_after=7)

    # =========================================================================
    # DISTORTION
    # =========================================================================
    @commands.hybrid_command(name="distortion")
    async def distortion(self, ctx: commands.Context) -> None:
        """Apply distortion effect / เปิดเอฟเฟกต์ Distortion (เสียงแตก)"""
        async with ctx.typing():
            if not await require_premium(self.bot, ctx, "Distortion Effect"):
                return
            
            player = await self._get_player_or_error(ctx)
            if not player:
                return

            if player.filters.has_filter(filter_tag="distortion"):
                player.filters.remove_filter(filter_tag="distortion")
            
            await player.add_filter(cytechlink.Distortion(
                tag="distortion",
                sin_offset=0.0, sin_scale=1.0,
                cos_offset=0.0, cos_scale=1.0,
                tan_offset=0.0, tan_scale=1.0,
                offset=0.0, scale=1.0
            ))
            lang = await self.bot.get_lang(ctx.guild.id)
            await ctx.reply(self.bot.i18n.get("filter_distortion", lang), delete_after=7)

    # =========================================================================
    # LOWPASS
    # =========================================================================
    @commands.hybrid_command(name="lowpass")
    @app_commands.describe(smoothing="Smoothing level (default 20.0) / ระดับความนุ่มนวล (ปกติ 20.0)")
    async def lowpass(self, ctx: commands.Context, smoothing: commands.Range[float, 10.0, 30.0] = 20.0) -> None:
        """Apply lowpass filter (muffled sound) / เปิด Lowpass Filter (ตัดเสียงแหลม)"""
        async with ctx.typing():
            if not await require_premium(self.bot, ctx, "Lowpass Filter"):
                return
            
            player = await self._get_player_or_error(ctx)
            if not player:
                return

            if player.filters.has_filter(filter_tag="lowpass"):
                player.filters.remove_filter(filter_tag="lowpass")
            
            await player.add_filter(cytechlink.LowPass(tag="lowpass", smoothing=smoothing))
            lang = await self.bot.get_lang(ctx.guild.id)
            await ctx.reply(self.bot.i18n.get("filter_lowpass", lang, smoothing=smoothing), delete_after=7)

    # =========================================================================
    # CHANNELMIX
    # =========================================================================
    @commands.hybrid_command(name="channelmix")
    @app_commands.describe(
        left_to_left="Left to Left (default 1.0) / ซ้ายออกซ้าย",
        right_to_right="Right to Right (default 1.0) / ขวาออกขวา",
        left_to_right="Left to Right (default 0.0) / ซ้ายออกขวา",
        right_to_left="Right to Left (default 0.0) / ขวาออกซ้าย"
    )
    async def channelmix(
        self, ctx: commands.Context, 
        left_to_left: commands.Range[float, 0.0, 1.0] = 1.0, 
        right_to_right: commands.Range[float, 0.0, 1.0] = 1.0, 
        left_to_right: commands.Range[float, 0.0, 1.0] = 0.0, 
        right_to_left: commands.Range[float, 0.0, 1.0] = 0.0
    ) -> None:
        """Mix audio channels manually / ปรับแต่ง Channel เสียงเอง"""
        async with ctx.typing():
            if not await require_premium(self.bot, ctx, "Channel Mixer"):
                return
            
            player = await self._get_player_or_error(ctx)
            if not player:
                return

            if player.filters.has_filter(filter_tag="channelmix"):
                player.filters.remove_filter(filter_tag="channelmix")
            
            await player.add_filter(cytechlink.ChannelMix(
                tag="channelmix",
                left_to_left=left_to_left,
                right_to_right=right_to_right,
                left_to_right=left_to_right,
                right_to_left=right_to_left
            ))
            lang = await self.bot.get_lang(ctx.guild.id)
            await ctx.reply(
                self.bot.i18n.get("filter_channelmix", lang, l2l=left_to_left, r2r=right_to_right, l2r=left_to_right, r2l=right_to_left),
                delete_after=10
            )

    # =========================================================================
    # NIGHTCORE
    # =========================================================================
    @commands.hybrid_command(name="nightcore")
    async def nightcore(self, ctx: commands.Context) -> None:
        """Apply Nightcore effect / เปิดโหมด Nightcore"""
        async with ctx.typing():
            if not await require_vote(self.bot, ctx):
                return
            
            player = await self._get_player_or_error(ctx)
            if not player:
                return

            await player.add_filter(cytechlink.Timescale.nightcore())
            lang = await self.bot.get_lang(ctx.guild.id)
            await ctx.reply(self.bot.i18n.get("filter_nightcore", lang), delete_after=7)

    # =========================================================================
    # 8D AUDIO
    # =========================================================================
    @commands.hybrid_command(name="8d")
    async def eightD(self, ctx: commands.Context) -> None:
        """Apply 8D Audio effect / เปิดโหมด 8D Audio"""
        async with ctx.typing():
            if not await require_vote(self.bot, ctx):
                return
            
            player = await self._get_player_or_error(ctx)
            if not player:
                return

            await player.add_filter(cytechlink.Rotation.eightD())
            lang = await self.bot.get_lang(ctx.guild.id)
            await ctx.reply(self.bot.i18n.get("filter_8d", lang), delete_after=7)

    # =========================================================================
    # VAPORWAVE
    # =========================================================================
    @commands.hybrid_command(name="vaporwave")
    async def vaporwave(self, ctx: commands.Context) -> None:
        """Apply Vaporwave effect / เปิดโหมด Vaporwave"""
        async with ctx.typing():
            if not await require_vote(self.bot, ctx):
                return
            
            player = await self._get_player_or_error(ctx)
            if not player:
                return

            await player.add_filter(cytechlink.Timescale.vaporwave())
            lang = await self.bot.get_lang(ctx.guild.id)
            await ctx.reply(self.bot.i18n.get("filter_vaporwave", lang), delete_after=7)

    # =========================================================================
    # CLEAR EFFECTS
    # =========================================================================
    @commands.hybrid_command(name="cleareffect")
    @app_commands.describe(effect="Specific effect name to remove / ชื่อเอฟเฟกต์ที่ต้องการลบ")
    @app_commands.autocomplete(effect=effect_autocomplete)
    async def cleareffect(self, ctx: commands.Context, effect: str = None) -> None:
        """Clear sound effects / ล้างเอฟเฟกต์เสียงทั้งหมด"""
        async with ctx.typing():
            if not await require_vote(self.bot, ctx):
                return
            
            player = await self._get_player_or_error(ctx)
            if not player:
                return

            lang = await self.bot.get_lang(ctx.guild.id)
            if effect:
                await player.remove_filter(effect)
                await ctx.reply(self.bot.i18n.get("filter_removed", lang, effect=effect), delete_after=7)
            else:
                await player.reset_filter()
                await ctx.reply(self.bot.i18n.get("filter_cleared", lang), delete_after=7)


async def setup(bot: Cyori) -> None:
    await bot.add_cog(Filter(bot))