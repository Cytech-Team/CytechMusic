import os
import pathlib
from dotenv import load_dotenv

# --- WINDOWS UNICODE FIX ---
import sys

if sys.platform == "win32":
    # Force UTF-8 encoding for standard output and error
    # This is critical for Thai characters and emojis in the console.
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Load .env file
BASE_DIR = pathlib.Path(__file__).parent.parent
env_file = os.getenv("ENV_FILE", ".env")
load_dotenv(dotenv_path=BASE_DIR / env_file)

# Credentials
BOT_TOKEN = os.getenv("BOT_TOKEN")
DBL_TOKEN = os.getenv("DBL_TOKEN")
API_KEY = os.getenv("API_KEY")
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
STRIPE_API_KEY = os.getenv("STRIPE_API_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
# Optional: Proxy URL for Stripe Webhooks (HTTPS)
STRIPE_PROXY_URL = os.getenv("STRIPE_PROXY_URL")
DOMAIN_URL = os.getenv("DOMAIN_URL", "http://localhost:3000")
# Optional: Discord Webhook for error logging
ERROR_LOG_WEBHOOK = os.getenv("ERROR_LOG_WEBHOOK", None)

WEB_PORT = int(os.getenv("WEB_PORT", 3000))

# Migration Settings
NEW_BOT_ID = os.getenv("NEW_BOT_ID", "1469606905948405833")

# --- AUTOMATIC ROLE DETECTION ---
# Only the bot with NEW_BOT_ID should be ACTIVE.
# All other bots must run in DEPRECATED_MODE.
try:
    if BOT_TOKEN:
        # Extract ID from token
        _token_id_part = BOT_TOKEN.split(".")[0]
        _token_id_part += "=" * (-len(_token_id_part) % 4)
        import base64

        _client_id = str(int(base64.b64decode(_token_id_part).decode("utf-8")))

        # We trust .env if it explicitly sets DEPRECATED_MODE
        env_dep = os.getenv("DEPRECATED_MODE")
        if env_dep is not None:
            DEPRECATED_MODE = env_dep.lower() == "true"
        else:
            DEPRECATED_MODE = _client_id != NEW_BOT_ID

        _bot_role = "MIGRATOR/OLD" if DEPRECATED_MODE else "MAIN/NEW"
        print(
            f"[*] Identity: {_client_id} ({_bot_role}) "
            f"| DEPRECATED_MODE = {DEPRECATED_MODE}",
            flush=True,
        )
    else:
        DEPRECATED_MODE = False
        print(
            "[!] Warning: No BOT_TOKEN found. " "Defaulting to Active Mode.", flush=True
        )
except Exception as e:
    DEPRECATED_MODE = False
    print(
        f"[!] Warning: Identity detection failed ({e}). " "Defaulting to Active Mode.",
        flush=True,
    )

# Smart Dev Mode
DEV_MODE = os.getenv("DEV_MODE", "false").lower() == "true"
IMPERSONATE_MAIN = os.getenv("IMPERSONATE_MAIN", "false").lower() == "true"
TEST_GUILD_ID = int(os.getenv("TEST_GUILD_ID", 0))


# Database
MONGO_URI = os.getenv("MONGO_URI")

# Auto DB Name Logic
import base64  # noqa: E402
import json  # noqa: E402
import urllib.request  # noqa: E402

_auto_db_name = "Komo"  # Final fallback

# 1. Try to fetch Username from Discord API (User Request: "bot.name")
try:
    _url = "https://discord.com/api/v10/users/@me"
    _req = urllib.request.Request(
        _url, headers={"Authorization": f"Bot {BOT_TOKEN}", "User-Agent": "Cyori/1"}
    )
    with urllib.request.urlopen(_req, timeout=5) as _res:
        _data = json.load(_res)
        _bot_username = _data.get("username", "")
        if _bot_username:
            # Sanitize (Alphanumeric only to be safe for DB name)
            _clean_name = "".join(c for c in _bot_username if c.isalnum())
            if _clean_name:
                _auto_db_name = _clean_name
except Exception:
    # 2. Fallback to Client ID from Token
    try:
        _token_id_part = BOT_TOKEN.split(".")[0]
        _token_id_part += "=" * (-len(_token_id_part) % 4)
        _client_id = str(int(base64.b64decode(_token_id_part).decode("utf-8")))
        _auto_db_name = f"Komo_{_client_id}"
    except Exception:
        # 3. Fallback to Folder Name
        _folder_name = os.path.basename(pathlib.Path(__file__).parent.parent)
        _auto_db_name = "".join(c for c in _folder_name if c.isalnum())
        if not _auto_db_name:
            _auto_db_name = "Komo"

DB_NAME = os.getenv("DB_NAME", _auto_db_name)

# LAVALINK
LAVALINK_HOST = os.getenv("LAVALINK_HOST")
LAVALINK_PORT = int(os.getenv("LAVALINK_PORT", 2333))
LAVALINK_PASS = os.getenv("LAVALINK_PASS")
LAVALINK_ID = os.getenv("LAVALINK_ID")

# Other
DEFAULT_PREFIX = os.getenv("DEFAULT_PREFIX", "cm!")
_owner_ids_str = os.getenv("OWNER_IDS", "")
OWNER_IDS = [int(x.strip()) for x in _owner_ids_str.split(",") if x.strip()]
VERSION = os.getenv("VERSION")
# ID for error logs
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", 0))
# Webhook for error logs
LOG_WEBHOOK_URL = os.getenv("LOG_WEBHOOK_URL")


# UI Configuration
# Colors
EMBED_COLOR = int(os.getenv("EMBED_COLOR", "0xFFD700"), 16)
ERROR_COLOR = int(os.getenv("ERROR_COLOR", "0xFF0000"), 16)
SUCCESS_COLOR = int(os.getenv("SUCCESS_COLOR", "0x00FF00"), 16)

# Warning Sounds (Direct Link to .mp3)
WARNING_SOUND_URL_TH = os.getenv(
    "WARNING_SOUND_URL_TH",
    "https://raw.githubusercontent.com/CytechNaRak/Cytech-Cloud/main/warning_TH_sound.mp3",
)
WARNING_SOUND_URL_EN = os.getenv(
    "WARNING_SOUND_URL_EN",
    "https://raw.githubusercontent.com/CytechNaRak/Cytech-Cloud/main/warning_EN_sound.mp3",
)

# Images
BANNER_URL = os.getenv("BANNER_URL", "https://i.postimg.cc/5y5pk1bL/Cyori-Banner.png")

# Links
SUPPORT_URL = os.getenv("SUPPORT_URL", "https://discord.gg/jcJ2P6Bh2p")
DASHBOARD_URL = os.getenv("DASHBOARD_URL", f"{DOMAIN_URL}/dashboard")
INVITE_URL = os.getenv("INVITE_URL", f"{DOMAIN_URL}/invite")
DONATE_URL = os.getenv("DONATE_URL", "https://easydonate.app/NamoPlayZone")
VOTE_URL = os.getenv("VOTE_URL", f"https://top.gg/bot/{NEW_BOT_ID}")

# Stripe URLs
STRIPE_SUCCESS_URL = os.getenv("STRIPE_SUCCESS_URL", "https://cyori.pages.dev/success.html")
STRIPE_CANCEL_URL = os.getenv("STRIPE_CANCEL_URL", "https://cyori.pages.dev/premium.html")
