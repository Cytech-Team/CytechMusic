import asyncio
import discord
import json
import pathlib
from discord.ext import commands
from bot import Cyori
from utils.config import BOT_TOKEN

async def run_sync():
    intents = discord.Intents.all()
    bot = Cyori(command_prefix="!", intents=intents)
    
async def run_sync():
    intents = discord.Intents.all()
    bot = Cyori(command_prefix="!", intents=intents)
    
    bot.remove_command('help')
    
    # Very aggressive loop and task mocking
    loop = asyncio.get_event_loop()
    bot.loop = loop
    bot._connection.loop = loop
    
    # Prevent cogs from starting background tasks during load
    original_create_task = loop.create_task
    def mocked_create_task(coro, *args, **kwargs):
        name = getattr(coro, '__name__', str(coro))
        if any(x in name for x in ['realtime_broadcaster', 'check_premium_expiry', 'before_check']):
            # Close the coroutine to prevent "was never awaited" warning
            try: coro.close()
            except: pass
            # Return a dummy task/future
            fut = loop.create_future()
            fut.set_result(None)
            return fut
        return original_create_task(coro, *args, **kwargs)
    
    bot.loop.create_task = mocked_create_task
    
    # Mock bot methods that tasks/cogs call during load
    async def mock_ready_true(): return True
    bot.wait_until_ready = mock_ready_true
    bot.is_ready = lambda: True
    bot.get_lang = lambda *args: "en" # Prevent DB calls in get_lang
    if not hasattr(bot, 'db'): bot.db = None

    print("Loading Cogs...")
    BASE_DIR = pathlib.Path(__file__).parent
    COGS_DIR = BASE_DIR / "cogs"

    for cog_file in COGS_DIR.glob("*.py"):
        cog_name = f"cogs.{cog_file.stem}"
        try:
            await bot.load_extension(cog_name)
            print(f"✅ Loaded: {cog_name}")
        except Exception as e:
            print(f"❌ Failed {cog_name}: {e}")
    
    print("\nPreparing payload...")
    payload = []
    
    def get_opt_type(param):
        t = param.type
        if hasattr(t, 'value'): return int(t.value)
        mapping = {
            str: 3, int: 4, float: 10, bool: 5,
            discord.Member: 6, discord.User: 6, discord.TextChannel: 7, 
            discord.VoiceChannel: 7, discord.CategoryChannel: 7, 
            discord.Role: 8, discord.Attachment: 11
        }
        if t in mapping: return mapping[t]
        try: return int(t)
        except: return 3

    def parse_command(cmd, is_subcommand=False):
        if isinstance(cmd, discord.app_commands.ContextMenu):
            return {
                "name": cmd.name,
                "description": "",
                "type": 2 if cmd.type == discord.AppCommandType.user else 3
            }

        # Discord API Constants:
        # Root level: CHAT_INPUT = 1
        # Inside options: SUB_COMMAND = 1, SUB_COMMAND_GROUP = 2
        
        desc = (getattr(cmd, 'description', "…") or "…")[:100]
        
        data = {
            "name": cmd.name.lower(),
            "description": desc,
            "type": 1, # Default for Root and Subcommands
        }
        
        # If it's a group, the type *inside* options is 2 (SUB_COMMAND_GROUP)
        # But root level groups are just CHAT_INPUT (Type 1) with options
        if is_subcommand and isinstance(cmd, discord.app_commands.Group):
            data["type"] = 2
        elif is_subcommand:
            data["type"] = 1 # SUB_COMMAND
        else:
            data["type"] = 1 # Root CHAT_INPUT

        if hasattr(cmd, 'parameters') and cmd.parameters:
            data["options"] = []
            for param in cmd.parameters:
                p_type = get_opt_type(param)
                opt_data = {
                    "name": param.name.lower(),
                    "description": (param.description or "…")[:100],
                    "type": p_type,
                    "required": param.required
                }
                if hasattr(param, 'min_value') and param.min_value is not None: opt_data["min_value"] = param.min_value
                if hasattr(param, 'max_value') and param.max_value is not None: opt_data["max_value"] = param.max_value
                if hasattr(param, 'choices') and param.choices:
                    opt_data["choices"] = [{"name": c.name, "value": c.value} for c in param.choices]
                data["options"].append(opt_data)
        
        if isinstance(cmd, discord.app_commands.Group):
            if "options" not in data: data["options"] = []
            for sub_cmd in cmd.commands:
                data["options"].append(parse_command(sub_cmd, is_subcommand=True))
        
        return data

    all_tree_cmds = bot.tree.get_commands()
    for cmd in all_tree_cmds:
        try:
            payload.append(parse_command(cmd))
            print(f" - Processed: /{cmd.name}")
        except Exception as e:
            print(f" ⚠️  Skipped /{cmd.name}: {e}")

    output_path = BASE_DIR / "slash_commands_payload.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=4, ensure_ascii=False)
        
    print(f"\n✅ Successfully exported {len(payload)} commands with strict Top.gg types")
    
    # Cancel all running tasks to prevent cleaner exit
    current_tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    for t in current_tasks: t.cancel()
    
if __name__ == "__main__":
    asyncio.run(run_sync())
