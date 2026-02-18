import asyncio
import discord
import json
import pathlib
from discord.ext import commands
from bot import Cyori
from utils.config import BOT_TOKEN

async def run_topgg_export():
    print("🚀 Starting Top.gg Export Sync (v3)...")
    
    intents = discord.Intents.all()
    bot = Cyori(command_prefix="!", intents=intents)
    bot.remove_command('help')
    
    # Mock loop and tasks
    loop = asyncio.get_event_loop()
    bot.loop = loop
    bot._connection.loop = loop
    
    original_create_task = loop.create_task
    def mocked_create_task(coro, *args, **kwargs):
        name = getattr(coro, '__name__', str(coro))
        if any(x in name for x in ['realtime_broadcaster', 'check_premium_expiry', 'status_loop']):
            try: coro.close() 
            except: pass
            fut = loop.create_future()
            fut.set_result(None)
            return fut
        return original_create_task(coro, *args, **kwargs)
    
    bot.loop.create_task = mocked_create_task
    
    # Mock bot state
    async def mock_ready_true(): return True
    bot.wait_until_ready = mock_ready_true
    bot.is_ready = lambda: True
    bot.get_lang = lambda *args: "en"
    if not hasattr(bot, 'db'): bot.db = None

    print("[*] Loading Cogs...")
    BASE_DIR = pathlib.Path(__file__).parent
    COGS_DIR = BASE_DIR / "cogs"

    for cog_file in COGS_DIR.glob("*.py"):
        if cog_file.stem in ["owner", "dashboard_api"]:
            print(f"⏩ Skipping Infrastructure/Owner: {cog_file.stem}")
            continue
            
        cog_path = f"cogs.{cog_file.stem}"
        try:
            await bot.load_extension(cog_path)
            print(f"✅ Loaded: {cog_path}")
        except Exception as e:
            print(f"❌ Failed {cog_path}: {e}")
    
    print(f"\n[*] Processing Commands...")
    
    processed_names = set()
    json_payload = []
    text_format = ""

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

    def clean_desc(desc, name):
        if not desc or desc.strip() in ["…", ""]:
            return f"Command {name}" # Top.gg requires valid description
        return desc[:100]

    def parse_command(cmd, parent_name="", is_subcommand=False):
        full_name = f"{parent_name} {cmd.name}".strip().lower()
        desc = clean_desc(getattr(cmd, 'description', ""), cmd.name)
        
        data = {
            "name": cmd.name.lower(),
            "description": desc,
            "type": 1 # Default Root
        }

        # Sub-level type mapping
        if is_subcommand:
            # 1: SUB_COMMAND, 2: SUB_COMMAND_GROUP
            data["type"] = 2 if isinstance(cmd, discord.app_commands.Group) else 1

        # Options processing
        options_list = []
        
        # 1. Handle regular parameters
        if hasattr(cmd, 'parameters') and cmd.parameters:
            for param in cmd.parameters:
                p_type = get_opt_type(param)
                opt = {
                    "name": param.name.lower(),
                    "description": clean_desc(param.description, param.name),
                    "type": p_type,
                    "required": param.required
                }
                
                # Extract choices
                choices_raw = getattr(param, 'choices', [])
                if choices_raw:
                    opt["choices"] = [{"name": c.name, "value": c.value} for c in choices_raw]
                
                # Min/Max values
                if hasattr(param, 'min_value') and param.min_value is not None: opt["min_value"] = param.min_value
                if hasattr(param, 'max_value') and param.max_value is not None: opt["max_value"] = param.max_value
                
                options_list.append(opt)

        # 2. Handle subcommands (recursive)
        if isinstance(cmd, discord.app_commands.Group):
            for sub_cmd in cmd.commands:
                options_list.append(parse_command(sub_cmd, parent_name=full_name, is_subcommand=True))

        if options_list:
            data["options"] = options_list

        # Bulk add text format (leaf commands only)
        nonlocal text_format
        if not isinstance(cmd, discord.app_commands.Group):
            # Format: /cmd [req] <opt> - description
            usage = f"/{full_name}"
            # Only show parameters for usage string
            if hasattr(cmd, 'parameters') and cmd.parameters:
                for p in cmd.parameters:
                    if p.required: usage += f" [{p.name}]"
                    else: usage += f" <{p.name}>"
            text_format += f"{usage} - {desc}\n"

        return data

    # Traverse all registered app commands
    all_tree_cmds = bot.tree.get_commands()
    for cmd in all_tree_cmds:
        if cmd.name.lower() in processed_names: continue
            
        try:
            cmd_data = parse_command(cmd)
            json_payload.append(cmd_data)
            processed_names.add(cmd.name.lower())
            print(f" - [AppTree] Processed: /{cmd.name}")
        except Exception as e:
            print(f" ⚠️  Skipped /{cmd.name}: {e}")

    # Final Save
    json_path = BASE_DIR / "topgg_commands.json"
    text_path = BASE_DIR / "topgg_bulk_add.txt"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_payload, f, indent=4, ensure_ascii=False)
        
    with open(text_path, "w", encoding="utf-8") as f:
        f.write(text_format)

    print(f"\n✨ Export Completed ✨")
    print(f"📁 JSON: {json_path}")
    print(f"📁 Text: {text_path}")
    print(f"✅ Total Root Commands: {len(json_payload)}")
    
    # Cleanup
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    for t in tasks: t.cancel()

if __name__ == "__main__":
    asyncio.run(run_topgg_export())
