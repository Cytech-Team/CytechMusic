import logging
import discord
from discord.ext import commands
from bot import Cyori
from utils.config import BOT_TOKEN

logging.basicConfig(level=logging.INFO)
logging.getLogger("discord.http").setLevel(logging.CRITICAL)

async def get_prefix(bot, message: discord.Message):
    if not message.guild:
        return commands.when_mentioned_or("cm!")(bot, message)
    
    try:
        guild_data = await bot.db_manager.get_guild(message.guild.id)
        prefix = guild_data.get("prefix", "cm!")
    except Exception:
        prefix = "cm!"
        
    return commands.when_mentioned_or(prefix)(bot, message)

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = Cyori(
    command_prefix=get_prefix,
    activity=discord.Activity(type=discord.ActivityType.listening, name="Starting..."),
    help_command=None,
    case_insensitive=True,
    intents=intents
)

if __name__ == "__main__":
    bot.run(BOT_TOKEN)
