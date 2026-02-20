import sys
import traceback
import aiohttp
import discord
from discord.ext import commands

class Events(commands.Cog):
    """
    Centralized Event Handlers and Error Logging.
    """
    def __init__(self, bot):
        self.bot = bot

    async def log_error(self, error, ctx=None, event_name=None):
        """Sends error logs to a designated Discord channel or Webhook."""
        if not self.bot.error_log_channel_id and not self.bot.error_webhook_url:
            return

        embed = discord.Embed(title="🚨 Bug/Error Detected", color=discord.Color.red())
        
        if ctx:
            embed.add_field(name="Command", value=f"`{ctx.command}`", inline=True)
            embed.add_field(name="Guild", value=f"{ctx.guild.name} ({ctx.guild.id})", inline=True)
            embed.add_field(name="User", value=f"{ctx.author} ({ctx.author.id})", inline=True)
        elif event_name:
            embed.add_field(name="Event", value=f"`{event_name}`", inline=True)

        # Get traceback
        tb = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        if len(tb) > 1000:
            tb = tb[:1000] + "\n... (truncated)"
        
        embed.description = f"```py\n{tb}\n```"
        embed.timestamp = discord.utils.utcnow()

        # 1. Try Webhook (Priority)
        if self.bot.error_webhook_url:
            try:
                from discord import Webhook
                async with aiohttp.ClientSession() as session:
                    webhook = Webhook.from_url(self.bot.error_webhook_url, session=session)
                    await webhook.send(embed=embed, username="Cyori Bug Hunter", avatar_url=self.bot.user.display_avatar.url if self.bot.user else None)
                    return # Success
            except Exception as e:
                print(f"Failed to log error via Webhook: {e}")

        # 2. Try Channel ID (Fallback)
        if self.bot.error_log_channel_id:
            try:
                channel = self.bot.get_channel(self.bot.error_log_channel_id)
                if channel:
                    await channel.send(embed=embed)
            except Exception as e:
                print(f"Failed to log error to Discord Channel: {e}")

    @commands.Cog.listener()
    async def on_error(self, event_method, *args, **kwargs):
        """Global error handler for events."""
        error = sys.exc_info()[1]
        if error:
            await self.log_error(error, event_name=event_method)

    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        # Ignore CommandNotFound
        if isinstance(error, commands.CommandNotFound):
            return

        # Handle MissingPermissions
        if isinstance(error, commands.MissingPermissions):
            lang = await self.bot.get_lang(ctx.guild.id)
            perms = ", ".join(error.missing_permissions)
            embed = discord.Embed(
                title=self.bot.i18n.get("error_title", lang) or "Error",
                description=f"You need the following permissions to use this command: **{perms}**",
                color=discord.Color.red()
            )
            return await ctx.reply(embed=embed, delete_after=10)

        # Handle BotMissingPermissions
        if isinstance(error, commands.BotMissingPermissions):
            lang = await self.bot.get_lang(ctx.guild.id)
            perms = ", ".join(error.missing_permissions)
            from utils.luxury import LuxuryEmbed
            embed = LuxuryEmbed.error(
                description=f"I need the following permissions to execute this command: **{perms}**",
                title=self.bot.i18n.get("error_title", lang) or "Error"
            )
            return await ctx.reply(embed=embed, delete_after=10)

        # Handle other errors
        if isinstance(error, commands.CommandOnCooldown):
             return await ctx.reply(f"This command is on cooldown. Try again in {error.retry_after:.2f}s.", delete_after=5)

        # Log to Discord and print for other errors
        await self.log_error(error, ctx=ctx)
        print(f"Ignoring exception in command {ctx.command}:", file=sys.stderr)
        traceback.print_exception(type(error), error, error.__traceback__, file=sys.stderr)

async def setup(bot):
    await bot.add_cog(Events(bot))
