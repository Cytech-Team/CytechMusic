import base64
import os
import pathlib
import sys

from dotenv import load_dotenv

# --- WINDOWS UNICODE FIX ---
if sys.platform == "win32":
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

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
STRIPE_PROXY_URL = os.getenv("STRIPE_PROXY_URL")
DOMAIN_URL = os.getenv("DOMAIN_URL", "http://localhost:3000").rstrip("/")
ERROR_LOG_WEBHOOK = os.getenv("ERROR_LOG_WEBHOOK")
WEB_PORT = int(os.getenv("WEB_PORT", 3000))


def _client_id_from_token(token: str | None) -> str | None:
    """Derive the public Discord application/user ID without exposing token contents."""
    if not token:
        return None
    try:
        part = token.split(".", 1)[0]
        part += "=" * (-len(part) % 4)
        decoded = base64.b64decode(part).decode("utf-8")
        return str(int(decoded))
    except Exception:
        return None


# Community builds must never default to Cyori's production application ID.
TOKEN_CLIENT_ID = _client_id_from_token(BOT_TOKEN)
NEW_BOT_ID = os.getenv("NEW_BOT_ID") or TOKEN_CLIENT_ID or ""

# Migration mode is opt-in for Community deployments. If NEW_BOT_ID is explicitly
# set to a different bot, automatic detection can still be used for migrations.
env_dep = os.getenv("DEPRECATED_MODE")
if env_dep is not None:
    DEPRECATED_MODE = env_dep.lower() == "true"
elif TOKEN_CLIENT_ID and NEW_BOT_ID:
    DEPRECATED_MODE = TOKEN_CLIENT_ID != NEW_BOT_ID
else:
    DEPRECATED_MODE = False

if TOKEN_CLIENT_ID:
    role = "MIGRATOR/OLD" if DEPRECATED_MODE else "MAIN/ACTIVE"
    print(
        f"[*] Identity: {TOKEN_CLIENT_ID} ({role}) | DEPRECATED_MODE = {DEPRECATED_MODE}",
        flush=True,
    )
else:
    print("[!] Warning: No BOT_TOKEN found.", flush=True)

# Development
DEV_MODE = os.getenv("DEV_MODE", "false").lower() == "true"
IMPERSONATE_MAIN = os.getenv("IMPERSONATE_MAIN", "false").lower() == "true"
TEST_GUILD_ID = int(os.getenv("TEST_GUILD_ID", 0))

# Database
MONGO_URI = os.getenv("MONGO_URI")
if os.getenv("DB_NAME"):
    DB_NAME = os.getenv("DB_NAME")
elif TOKEN_CLIENT_ID:
    DB_NAME = f"CytechMusic_{TOKEN_CLIENT_ID}"
else:
    folder_name = "".join(c for c in BASE_DIR.name if c.isalnum())
    DB_NAME = folder_name or "CytechMusic"

# Lavalink
LAVALINK_HOST = os.getenv("LAVALINK_HOST")
LAVALINK_PORT = int(os.getenv("LAVALINK_PORT", 2333))
LAVALINK_PASS = os.getenv("LAVALINK_PASS")
LAVALINK_ID = os.getenv("LAVALINK_ID", "main")

# Other
DEFAULT_PREFIX = os.getenv("DEFAULT_PREFIX", "cm!")
_owner_ids_str = os.getenv("OWNER_IDS", "")
OWNER_IDS = [int(x.strip()) for x in _owner_ids_str.split(",") if x.strip()]
VERSION = os.getenv("VERSION", "community")
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", 0))
LOG_WEBHOOK_URL = os.getenv("LOG_WEBHOOK_URL")

# UI Configuration
EMBED_COLOR = int(os.getenv("EMBED_COLOR", "0xFFD700"), 16)
ERROR_COLOR = int(os.getenv("ERROR_COLOR", "0xFF0000"), 16)
SUCCESS_COLOR = int(os.getenv("SUCCESS_COLOR", "0x00FF00"), 16)

WARNING_SOUND_URL_TH = os.getenv(
    "WARNING_SOUND_URL_TH",
    "https://raw.githubusercontent.com/CytechNaRak/Cytech-Cloud/main/warning_TH_sound.mp3",
)
WARNING_SOUND_URL_EN = os.getenv(
    "WARNING_SOUND_URL_EN",
    "https://raw.githubusercontent.com/CytechNaRak/Cytech-Cloud/main/warning_EN_sound.mp3",
)
BANNER_URL = os.getenv(
    "BANNER_URL",
    "https://raw.githubusercontent.com/Cytech-Team/CytechMusic/main/web/logo-circle.png",
)

# Community-safe links. Deployers can override every value through environment variables.
SUPPORT_URL = os.getenv("SUPPORT_URL", "https://github.com/Cytech-Team/CytechMusic")
DASHBOARD_URL = os.getenv("DASHBOARD_URL", f"{DOMAIN_URL}/dashboard")
INVITE_URL = os.getenv("INVITE_URL", f"{DOMAIN_URL}/invite")
DONATE_URL = os.getenv("DONATE_URL", "https://github.com/Cytech-Team/CytechMusic")
VOTE_URL = os.getenv(
    "VOTE_URL",
    f"https://top.gg/bot/{NEW_BOT_ID}" if NEW_BOT_ID else "https://top.gg/",
)

# Stripe URLs
STRIPE_SUCCESS_URL = os.getenv("STRIPE_SUCCESS_URL", f"{DOMAIN_URL}/success.html")
STRIPE_CANCEL_URL = os.getenv("STRIPE_CANCEL_URL", f"{DOMAIN_URL}/premium.html")
