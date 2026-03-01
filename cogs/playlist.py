import discord
from discord import app_commands
from discord.ext import commands
import time
import datetime
import cytechlink
from bot import Cyori
from utils import config as ui_config


class Playlist(commands.Cog):
    def __init__(self, bot: Cyori) -> None:
        self.bot = bot

    def _track_to_dict(self, track):
        return {
            "title": track.title,
            "uri": track.uri,
            "author": track.author,
            "identifier": track.identifier,
            "thumbnail": (
                track.thumbnail if hasattr(track, "thumbnail") else "logo-circle.png"
            ),
            "length": track.length,
            "encoded": track.track_id,
        }

    @commands.hybrid_group(name="playlist", invoke_without_command=True)
    async def playlist(self, ctx: commands.Context):
        """จัดการเพลย์ลิสต์ของคุณ (Manage your playlists)"""
        if ctx.invoked_subcommand is None:
            await self.list(ctx)

    @playlist.command(name="create")
    @app_commands.describe(name="ชื่อเพลย์ลิสต์", description="คำอธิบายสั้นๆ")
    async def create(self, ctx: commands.Context, name: str, description: str = None):
        """สร้างเพลย์ลิสต์ใหม่ (Create a new playlist)"""
        user_id = str(ctx.author.id)
        is_premium = await self.bot.is_premium(ctx.author.id)
        limit = 100 if is_premium else 20

        user_doc = await self.bot.db_manager.get_user_doc(user_id)
        playlists = user_doc.get("playlists", [])

        if len(playlists) >= limit:
            return await ctx.send(
                f"❌ คุณมีเพลย์ลิสต์ถึงขีดจำกัดแล้ว ({limit})", ephemeral=True
            )

        if any(pl["name"].lower() == name.lower() for pl in playlists):
            return await ctx.send(
                f"❌ คุณมีเพลย์ลิสต์ชื่อ **{name}** อยู่แล้ว!", ephemeral=True
            )

        new_pl = {
            "name": name,
            "description": description or f"คอลเลกชันเพลงของ {ctx.author.name}",
            "tracks": [],
            "created_at": int(time.time()),
            "count": 0,
        }
        await self.bot.db_manager.update_user_doc(
            user_id, {"$push": {"playlists": new_pl}}
        )
        await ctx.send(f"✅ สร้างเพลย์ลิสต์ **{name}** เรียบร้อยแล้ว!", ephemeral=True)

    @playlist.command(name="save")
    @app_commands.describe(name="ชื่อเพลย์ลิสต์ที่จะบันทึก", description="คำอธิบาย")
    async def save(
        self, ctx: commands.Context, name: str = None, description: str = None
    ):
        """บันทึกคิวปัจจุบันลงเพลย์ลิสต์ (Save current queue to playlist)"""
        user_id = str(ctx.author.id)
        is_premium = await self.bot.is_premium(ctx.author.id)
        limit = 100 if is_premium else 20

        user_doc = await self.bot.db_manager.get_user_doc(user_id)
        playlists = user_doc.get("playlists", [])

        if len(playlists) >= limit:
            return await ctx.send(
                f"❌ โควตาเพลย์ลิสต์เต็มแล้ว ({limit})", ephemeral=True
            )

        # Check music player
        p = ctx.guild.voice_client
        if not p or not p.current:
            return await ctx.send("❌ บอทไม่ได้เล่นเพลงอยู่!", ephemeral=True)

        if isinstance(ctx, discord.Interaction):
            await ctx.response.defer(ephemeral=True)

        tracks = [self._track_to_dict(p.current)]
        for item in p.queue:
            tracks.append(self._track_to_dict(item["track"]))

        pl_name = name or f"Saved_{datetime.datetime.now().strftime('%m%d_%H%M')}"
        new_pl = {
            "name": pl_name,
            "description": description
            or f"บันทึกเมื่อ {datetime.datetime.now().strftime('%d/%m/%Y')}",
            "tracks": tracks,
            "created_at": int(time.time()),
            "count": len(tracks),
        }

        await self.bot.db_manager.update_user_doc(
            user_id, {"$push": {"playlists": new_pl}}
        )
        msg = (
            f"✅ บันทึกคิวปัจจุบันลงเพลย์ลิสต์ **{pl_name}** แล้ว! ({len(tracks)} เพลง)"
        )
        if isinstance(ctx, discord.Interaction):
            await ctx.followup.send(msg)
        else:
            await ctx.send(msg)

    @playlist.command(name="add")
    @app_commands.describe(name="ชื่อเพลย์ลิสต์", query="ลิงก์เพลง หรือ ชื่อเพลง")
    async def add(self, ctx: commands.Context, name: str, query: str):
        """เพิ่มเพลงเข้าเพลย์ลิสต์ (Add track(s) to playlist)"""
        user_id = str(ctx.author.id)
        user_doc = await self.bot.db_manager.get_user_doc(user_id)
        playlists = user_doc.get("playlists", [])

        idx = next(
            (i for i, pl in enumerate(playlists) if pl["name"].lower() == name.lower()),
            -1,
        )
        if idx == -1:
            return await ctx.send(f"❌ ไม่พบเพลย์ลิสต์ชื่อ **{name}**", ephemeral=True)

        if isinstance(ctx, discord.Interaction):
            await ctx.response.defer(ephemeral=True)

        results = await self.bot.cytechlink.get_tracks(query)
        if not results:
            msg = "❌ ไม่พบเพลง!"
            return (
                await ctx.followup.send(msg)
                if isinstance(ctx, discord.Interaction)
                else await ctx.send(msg)
            )

        added_tracks = []
        if isinstance(results, list):
            added_tracks.append(self._track_to_dict(results[0]))
        else:
            for t in results.tracks:
                added_tracks.append(self._track_to_dict(t))

        playlists[idx]["tracks"].extend(added_tracks)
        playlists[idx]["count"] = len(playlists[idx]["tracks"])

        await self.bot.db_manager.update_user_doc(
            user_id, {"$set": {"playlists": playlists}}
        )
        msg = f"✅ เพิ่ม {len(added_tracks)} เพลงลงใน **{name}** เรียบร้อย!"
        if isinstance(ctx, discord.Interaction):
            await ctx.followup.send(msg)
        else:
            await ctx.send(msg)

    @playlist.command(name="list")
    async def list(self, ctx: commands.Context):
        """ดูรายการเพลย์ลิสต์ทั้งหมด (List all your playlists)"""
        user_id = str(ctx.author.id)
        is_premium = await self.bot.is_premium(ctx.author.id)
        limit = 100 if is_premium else 20

        user_doc = await self.bot.db_manager.get_user_doc(user_id)
        playlists = user_doc.get("playlists", [])

        if not playlists:
            return await ctx.send("⚠️ คุณยังไม่มีเพลย์ลิสต์", ephemeral=True)

        embed = discord.Embed(title="📂 เพลย์ลิสต์ของคุณ", color=ui_config.EMBED_COLOR)
        for i, pl in enumerate(playlists):
            desc = pl.get("description", "ไม่มีคำอธิบาย")
            embed.add_field(
                name=f"{i+1}. {pl['name']} ({pl['count']} เพลง)",
                value=f"> *{desc}*\n📅 <t:{pl['created_at']}:R>",
                inline=False,
            )
        embed.set_footer(text=f"Quota: {len(playlists)}/{limit}")
        await ctx.send(embed=embed, ephemeral=True)

    @playlist.command(name="delete")
    @app_commands.describe(name="ชื่อเพลย์ลิสต์ที่ต้องการลบ")
    async def delete(self, ctx: commands.Context, name: str):
        """ลบเพลย์ลิสต์ (Delete a playlist)"""
        user_id = str(ctx.author.id)
        user_doc = await self.bot.db_manager.get_user_doc(user_id)
        playlists = user_doc.get("playlists", [])

        new_playlists = [pl for pl in playlists if pl["name"].lower() != name.lower()]
        if len(new_playlists) == len(playlists):
            return await ctx.send(f"❌ ไม่พบเพลย์ลิสต์ชื่อ **{name}**", ephemeral=True)

        await self.bot.db_manager.update_user_doc(
            user_id, {"$set": {"playlists": new_playlists}}
        )
        await ctx.send(f"🗑️ ลบเพลย์ลิสต์ **{name}** เรียบร้อยแล้ว", ephemeral=True)

    @playlist.command(name="load")
    @app_commands.describe(name="ชื่อเพลย์ลิสต์")
    async def load(self, ctx: commands.Context, name: str):
        """โหลดเพลย์ลิสต์มาเล่น (Load and play a playlist)"""
        user_id = str(ctx.author.id)
        user_doc = await self.bot.db_manager.get_user_doc(user_id)
        playlists = user_doc.get("playlists", [])

        pl = next((p for p in playlists if p["name"].lower() == name.lower()), None)
        if not pl:
            return await ctx.send(f"❌ ไม่พบเพลย์ลิสต์ชื่อ **{name}**", ephemeral=True)

        player = ctx.guild.voice_client
        if not player:
            if not ctx.author.voice:
                return await ctx.send("❌ คุณต้องอยู่ในห้องเสียงก่อน!", ephemeral=True)
            player = await ctx.author.voice.channel.connect(cls=cytechlink.Player)

        if isinstance(ctx, discord.Interaction):
            await ctx.response.defer()

        tracks_data = pl.get("tracks", [])
        added_count = 0

        for t_data in tracks_data:
            try:
                track = await player.node.decode_track(t_data["encoded"])
                player.queue.add(track, requester=ctx.author.id)
                added_count += 1
            except Exception:
                continue

        if not player.is_playing and player.queue:
            await player.do_next()

        msg = f"✅ โหลดเพลย์ลิสต์ **{pl['name']}** เรียบร้อย! เพิ่มเพลง {added_count} เพลง"
        if isinstance(ctx, discord.Interaction):
            await ctx.followup.send(msg)
        else:
            await ctx.send(msg)


async def setup(bot: Cyori) -> None:
    await bot.add_cog(Playlist(bot))
