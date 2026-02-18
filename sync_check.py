
import asyncio
import discord
from discord.ext import commands
from bot import Cyori
from utils.config import BOT_TOKEN

async def run_sync():
    intents = discord.Intents.all()
    bot = Cyori(command_prefix="!", intents=intents)
    
    @bot.event
    async def on_ready():
        print(f"Logged in as {bot.user} (ID: {bot.user.id})")
        # Load Cogs
        import pathlib
        BASE_DIR = pathlib.Path(__file__).parent
        COGS_DIR = BASE_DIR / "cogs"
        for cog_file in COGS_DIR.glob("*.py"):
            cog_name = f"cogs.{cog_file.stem}"
            try:
                await bot.load_extension(cog_name)
                print(f"Loaded: {cog_name}")
            except Exception as e:
                print(f"Failed {cog_name}: {e}")
        
        print("Syncing...")
        synced = await bot.tree.sync()
        print(f"\n✅ Total Synced Commands: {len(synced)}")
        for cmd in synced:
            print(f"- /{cmd.name}")
        
        await bot.close()

    print("Logging in...")
    await bot.start(BOT_TOKEN)

if __name__ == "__main__":
    asyncio.run(run_sync())
