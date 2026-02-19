
import discord
from discord.ext import commands
from discord import app_commands
from bot import Cyori
import io
import contextlib
import traceback
import textwrap
import asyncio


class Owner(commands.Cog):
    def __init__(self, bot: Cyori):
        self.bot = bot

    async def cog_check(self, ctx: commands.Context):
        if not await self.bot.is_owner(ctx.author):
            raise commands.NotOwner("You do not own this bot.")
        return True

    @commands.hybrid_group(name="own", description="Owner-only management commands / คำสั่งจัดการสำหรับเจ้าของบอท")
    @commands.is_owner()
    async def own_group(self, ctx: commands.Context):
        """Main group for owner commands."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    # ===================================================================
    # SHUTDOWN
    # ===================================================================
    @own_group.command(name="shutdown", description="Shut down the bot / ปิดการทำงานของบอท")
    @commands.is_owner()
    async def shutdown(self, ctx: commands.Context):
        await ctx.defer(ephemeral=True)
        await ctx.send("Shutting down... Goodbye!", ephemeral=True)
        await self.bot.close()

    # ===================================================================
    # EXTENSION MANAGEMENT
    # ===================================================================
    @own_group.command(name="reload", description="Reload a cog / รีโหลดส่วนเสริม (Cog)")
    @commands.is_owner()
    async def reload(self, ctx: commands.Context, cog: str):
        await ctx.defer(ephemeral=True)
        try:
            await self.bot.reload_extension(f"cogs.{cog}")
            await ctx.send(f"Reloaded `cogs.{cog}`", ephemeral=True)
        except Exception as e:
            await ctx.send(f"Failed to reload `{cog}`:\n```py\n{e}\n```", ephemeral=True)

    @own_group.command(name="load", description="Load a cog / โหลดส่วนเสริม (Cog)")
    @commands.is_owner()
    async def load(self, ctx: commands.Context, cog: str):
        await ctx.defer(ephemeral=True)
        try:
            await self.bot.load_extension(f"cogs.{cog}")
            await ctx.send(f"Loaded `cogs.{cog}`", ephemeral=True)
        except Exception as e:
            await ctx.send(f"Failed to load `{cog}`:\n```py\n{e}\n```", ephemeral=True)

    @own_group.command(name="unload", description="Unload a cog / ยกเลิกโหลดส่วนเสริม (Cog)")
    @commands.is_owner()
    async def unload(self, ctx: commands.Context, cog: str):
        await ctx.defer(ephemeral=True)
        try:
            await self.bot.unload_extension(f"cogs.{cog}")
            await ctx.send(f"Unloaded `cogs.{cog}`", ephemeral=True)
        except Exception as e:
            await ctx.send(f"Failed to unload `{cog}`:\n```py\n{e}\n```", ephemeral=True)

    # ===================================================================
    # SYNC COMMANDS
    # ===================================================================
    @own_group.command(name="sync", description="Sync slash commands / ซิงค์คำสั่ง Slash Command")
    @commands.is_owner()
    async def sync(self, ctx: commands.Context):
        await ctx.defer(ephemeral=True)
        try:
            synced = await self.bot.tree.sync()
            await ctx.send(f"Synced {len(synced)} commands globally.", ephemeral=True)
        except Exception as e:
            await ctx.send(f"Sync failed: {e}", ephemeral=True)

    # ===================================================================
    # SERVER MANAGEMENT
    # ===================================================================
    @own_group.command(name="servers", description="List top guilds by member count / แสดงรายการเซิร์ฟเวอร์เรียงตามจำนวนสมาชิก")
    @commands.is_owner()
    async def servers(self, ctx: commands.Context):
        await ctx.defer(ephemeral=True)
        guilds = sorted(self.bot.guilds, key=lambda g: g.member_count, reverse=True)
        
        msg = "**Top Guilds by Members:**\n"
        for i, guild in enumerate(guilds[:15], 1):
            msg += f"{i}. **{guild.name}** (`{guild.id}`) - {guild.member_count} members\n"
        
        msg += f"\nTotal Servers: {len(self.bot.guilds)}\nTotal Users: {len(self.bot.users)}"
        
        if len(msg) > 2000:
            msg = msg[:1990] + "..."
            
        await ctx.send(msg, ephemeral=True)

    @own_group.command(name="leave", description="Force bot to leave a guild / บังคับบอทออกจากเซิร์ฟเวอร์")
    @commands.is_owner()
    async def leave_guild(self, ctx: commands.Context, guild_id: str):
        await ctx.defer(ephemeral=True)
        try:
            guild = self.bot.get_guild(int(guild_id))
            if not guild:
                return await ctx.send("Guild not found.", ephemeral=True)
            
            await guild.leave()
            await ctx.send(f"Left guild: **{guild.name}** ({guild.id})", ephemeral=True)
        except Exception as e:
            await ctx.send(f"Failed to leave guild: {e}", ephemeral=True)

    # ===================================================================
    # EVAL (ปลอดภัยและสวยขึ้น)
    # ===================================================================
    @own_group.command(name="eval", description="Execute Python code / รันโค้ด Python")
    @commands.is_owner()
    async def eval(self, ctx: commands.Context, *, code: str):
        await ctx.defer(ephemeral=True)

        if code.startswith("```") and code.endswith("```"):
            code = "\n".join(code.split("\n")[1:-1])

        env = {
            "bot": self.bot,
            "ctx": ctx,
            "discord": discord,
            "commands": commands,
        }
        env.update(globals())

        stdout = io.StringIO()
        result = None

        try:
            with contextlib.redirect_stdout(stdout):
                exec(f"async def func():\n{textwrap.indent(code, '    ')}", env)
                func = env["func"]
                result = await func()
        except Exception:
            output = stdout.getvalue()
            error = traceback.format_exc()
            await ctx.send(f"```py\n{output}{error}\n```", ephemeral=True)
            return

        output = stdout.getvalue()
        if result is None:
            if output:
                await ctx.send(f"```py\n{output}\n```", ephemeral=True)
            else:
                await ctx.send("No output.", ephemeral=True)
        else:
            await ctx.send(f"```py\n{output}Result: {result}\n```", ephemeral=True)

    # ===================================================================
    # SAY
    # ===================================================================
    @own_group.command(name="say", description="Make the bot send a message to a channel / ให้บอทส่งข้อความไปยังห้องที่กำหนด")
    @commands.is_owner()
    async def say(self, ctx: commands.Context, channel: discord.TextChannel, *, message: str):
        await ctx.defer(ephemeral=True)
        try:
            await channel.send(message)
            await ctx.send(f"Message sent to {channel.mention}", ephemeral=True)
        except discord.Forbidden:
            await ctx.send("I don't have permission to send messages there.", ephemeral=True)

    # ===================================================================
    # DM OWNER
    # ===================================================================
    @own_group.command(name="dm", description="DM the server owner / ส่งข้อความหาเจ้าของเซิร์ฟเวอร์")
    @commands.is_owner()
    async def dmowner(self, ctx: commands.Context, *, message: str):
        if not ctx.guild:
            return await ctx.send("This command can only be used in a server.", ephemeral=True)

        await ctx.defer(ephemeral=True)
        owner = ctx.guild.owner
        if not owner:
            return await ctx.send("This server has no owner?", ephemeral=True)

        try:
            await owner.send(f"Message from bot owner ({ctx.author}):\n\n{message}")
            await ctx.send(f"DM sent to {owner} ({owner.id})", ephemeral=True)
        except discord.Forbidden:
            await ctx.send(f"Cannot DM {owner} — they have DMs disabled or blocked the bot.", ephemeral=True)

    # ===================================================================
    # ANNOUNCE TO ALL OWNERS
    # ===================================================================
    @own_group.command(name="announce", description="Send a DM to all server owners / ประกาศถึงเจ้าของเซิร์ฟเวอร์ทุกคน")
    @commands.is_owner()
    async def announce(self, ctx: commands.Context, *, message: str):
        await ctx.defer(ephemeral=True)

        if len(message) > 1800:
            return await ctx.send("Message too long! Max 1800 characters.", ephemeral=True)

        sent = 0
        failed = 0
        owners_sent = set()

        for guild in self.bot.guilds:
            if not guild.owner or guild.owner.id in owners_sent:
                continue

            try:
                await guild.owner.send(f"Bot Announcement:\n\n{message}")
                owners_sent.add(guild.owner.id)
                sent += 1
                # Rate Limit Protection
                await asyncio.sleep(1.5) 
            except:
                failed += 1

        await ctx.send(
            f"Announcement sent!\n"
            f"Success: `{sent}` owners\n"
            f"Failed: `{failed}` owners",
            ephemeral=True
        )

    # ===================================================================
    # BOT PRESENCE & IDENTITY (NEW)
    # ===================================================================
    @own_group.command(name="status", description="Change bot status / เปลี่ยนสถานะของบอท")
    @commands.is_owner()
    @app_commands.describe(status_type="Type: playing, listening... / ประเภทสถานะ", text="Status text / ข้อความสถานะ")
    @app_commands.choices(status_type=[
        app_commands.Choice(name="Playing", value="playing"),
        app_commands.Choice(name="Listening", value="listening"),
        app_commands.Choice(name="Watching", value="watching"),
        app_commands.Choice(name="Competing", value="competing")
    ])
    async def setstatus(self, ctx: commands.Context, status_type: str, *, text: str):
        await ctx.defer(ephemeral=True)
        try:
            activity_type = getattr(discord.ActivityType, status_type, discord.ActivityType.playing)
            activity = discord.Activity(type=activity_type, name=text)
            await self.bot.change_presence(activity=activity)
            
            # Stop auto-loop if running to prevent overwrite
            if hasattr(self.bot, "status_loop") and self.bot.status_loop.is_running():
                self.bot.status_loop.cancel()
                
            await ctx.send(f"Status changed to: `{status_type.capitalize()} {text}`", ephemeral=True)
        except Exception as e:
            await ctx.send(f"Failed to set status: {e}", ephemeral=True)

    @own_group.command(name="rename", description="Change bot username / เปลี่ยนชื่อผู้ใช้ของบอท")
    @commands.is_owner()
    async def rename(self, ctx: commands.Context, *, name: str):
        await ctx.defer(ephemeral=True)
        try:
            await self.bot.user.edit(username=name)
            await ctx.send(f"Username changed to: **{name}**", ephemeral=True)
        except discord.HTTPException as e:
            await ctx.send(f"Failed (Rate Limit?): {e}", ephemeral=True)

    @own_group.command(name="avatar", description="Change bot avatar / เปลี่ยนรูปโปรไฟล์ของบอท")
    @commands.is_owner()
    async def setavatar(self, ctx: commands.Context, url: str = None):
        await ctx.defer(ephemeral=True)
        
        if not url and ctx.message.attachments:
            url = ctx.message.attachments[0].url
            
        if not url:
            return await ctx.send("Please provide a URL or attach an image.", ephemeral=True)

        try:
            if not self.bot.session:
                return await ctx.send("Bot session not ready.", ephemeral=True)
                
            async with self.bot.session.get(url) as resp:
                if resp.status != 200:
                    return await ctx.send("Failed to download image.", ephemeral=True)
                data = await resp.read()
                
            await self.bot.user.edit(avatar=data)
            await ctx.send("Avatar updated successfully!", ephemeral=True)
        except Exception as e:
            await ctx.send(f"Failed to change avatar: {e}", ephemeral=True)


async def setup(bot: Cyori):
    await bot.add_cog(Owner(bot))