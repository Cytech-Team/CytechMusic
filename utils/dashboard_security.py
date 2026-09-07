"""Fail-closed security perimeter for the self-hosted CytechMusic dashboard."""
from __future__ import annotations

import json
import time
from pathlib import Path

import aiohttp
import discord
from aiohttp import web

from utils import config

_TOKEN_CACHE: dict[str, tuple[float, dict]] = {}
_GUILD_CACHE: dict[str, tuple[float, list[dict]]] = {}
_TOKEN_TTL = 300
_GUILD_TTL = 180
_WEB_DIR = Path(__file__).parent.parent / "web"


async def _discord_get(token: str, path: str):
    if not token or len(token) < 20:
        return None
    try:
        timeout = aiohttp.ClientTimeout(total=5)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(
                f"https://discord.com/api{path}",
                headers={"Authorization": f"Bearer {token}"},
            ) as response:
                if response.status == 200:
                    return await response.json()
    except Exception:
        return None
    return None


async def _user(token: str) -> dict | None:
    now = time.time()
    cached = _TOKEN_CACHE.get(token)
    if cached and cached[0] > now:
        return cached[1]
    user = await _discord_get(token, "/users/@me")
    if isinstance(user, dict) and user.get("id"):
        _TOKEN_CACHE[token] = (now + _TOKEN_TTL, user)
        return user
    return None


async def _guilds(token: str) -> list[dict] | None:
    now = time.time()
    cached = _GUILD_CACHE.get(token)
    if cached and cached[0] > now:
        return cached[1]
    guilds = await _discord_get(token, "/users/@me/guilds?limit=200")
    if isinstance(guilds, list):
        _GUILD_CACHE[token] = (now + _GUILD_TTL, guilds)
        return guilds
    return None


async def _guild_access(token: str, guild_id: int) -> dict | None:
    target = str(int(guild_id))
    guilds = await _guilds(token) or []
    return next((guild for guild in guilds if str(guild.get("id")) == target), None)


def _can_manage_guild(guild: dict | None) -> bool:
    if not guild:
        return False
    if guild.get("owner") is True:
        return True
    try:
        permissions = discord.Permissions(int(guild.get("permissions", 0)))
    except (TypeError, ValueError):
        return False
    return permissions.administrator or permissions.manage_guild


def _bearer(request: web.Request, data: dict | None = None) -> str | None:
    if data:
        token = data.get("access_token")
        if token:
            return str(token)
    token = request.query.get("access_token")
    if token:
        return token
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return None


def _same_voice(bot, guild_id: int, user_id: int) -> bool:
    guild = bot.get_guild(int(guild_id))
    if not guild:
        return False
    member = guild.get_member(int(user_id))
    if not member or not member.voice or not member.voice.channel:
        return False
    player = guild.voice_client
    if not player:
        return True
    player_channel = getattr(player, "channel", None)
    return bool(player_channel and player_channel.id == member.voice.channel.id)


def _html_path(path: str) -> Path | None:
    if path == "/":
        candidate = _WEB_DIR / "index.html"
    elif path == "/dashboard":
        candidate = _WEB_DIR / "dashboard.html"
    elif path.endswith(".html"):
        candidate = (_WEB_DIR / path.lstrip("/")).resolve()
        try:
            candidate.relative_to(_WEB_DIR.resolve())
        except ValueError:
            return None
    else:
        return None
    return candidate if candidate.is_file() else None


def make_dashboard_security_middleware(bot):
    @web.middleware
    async def dashboard_security(request: web.Request, handler):
        # Inject the auth bootstrap into embedded HTML without duplicating it in every page.
        if request.method == "GET":
            html_path = _html_path(request.path)
            if html_path:
                html = html_path.read_text(encoding="utf-8-sig")
                marker = '<script src="script.js"></script>'
                bootstrap = '<script src="security-bootstrap.js"></script>'
                if bootstrap not in html:
                    if marker in html:
                        html = html.replace(marker, f"{bootstrap}\n    {marker}", 1)
                    else:
                        html = html.replace("</head>", f"    {bootstrap}\n</head>", 1)
                return web.Response(text=html, content_type="text/html", charset="utf-8")

        # The legacy gateway accepted arbitrary user_id values in control frames. Disable it
        # until the gateway itself binds a verified Discord identity to the socket.
        if request.path == "/api/gateway":
            return web.json_response(
                {"error": "realtime_temporarily_disabled", "fallback": "polling"},
                status=503,
            )

        # Stripe events must never reach the legacy handler unsigned or unconfigured.
        if request.path == "/stripe/webhook":
            if not config.STRIPE_WEBHOOK_SECRET:
                return web.json_response({"error": "stripe_webhook_not_configured"}, status=503)
            if not request.headers.get("Stripe-Signature"):
                return web.json_response({"error": "missing_stripe_signature"}, status=400)
            return await handler(request)

        # Old direct state-changing endpoints are no longer browser-facing. The local poller
        # still uses /api/control from loopback, so retain that single internal path.
        if request.method == "POST" and request.path in {
            "/api/control",
            "/api/guild_settings",
            "/api/playlist",
        }:
            if request.path == "/api/control" and request.remote in {"127.0.0.1", "::1"}:
                return await handler(request)
            return web.json_response({"error": "use_authenticated_proxy"}, status=410)

        # Old direct privacy-sensitive reads are retired in favour of /api/proxy.
        if request.method == "GET" and request.path in {
            "/api/status",
            "/api/user_info",
            "/api/find_voice",
            "/api/guild_settings",
            "/api/bot_guilds",
        }:
            return web.json_response({"error": "use_authenticated_proxy"}, status=410)

        if request.path != "/api/proxy" or request.method == "OPTIONS":
            return await handler(request)

        if request.method == "GET":
            action = request.query.get("action")
            secure_actions = {
                "status",
                "user_info",
                "find_voice",
                "guild_settings",
                "bot_guilds",
            }
            if action not in secure_actions:
                return await handler(request)

            token = _bearer(request)
            user = await _user(token or "")
            if not user:
                return web.json_response({"error": "unauthorized"}, status=401)

            requested_uid = request.query.get("user_id")
            if requested_uid and str(requested_uid) != str(user["id"]):
                return web.json_response({"error": "forbidden"}, status=403)

            if action == "bot_guilds":
                user_guilds = await _guilds(token) or []
                visible_ids = {str(guild.get("id")) for guild in user_guilds if guild.get("id")}
                mutual = [str(guild.id) for guild in bot.guilds if str(guild.id) in visible_ids]
                return web.json_response({"guilds": mutual})

            guild_id = request.query.get("guild_id")
            if action in {"status", "guild_settings"}:
                if not guild_id or not str(guild_id).isdigit():
                    return web.json_response({"error": "no_guild"}, status=400)
                if not await _guild_access(token, int(guild_id)):
                    return web.json_response({"error": "forbidden"}, status=403)

            return await handler(request)

        if request.method != "POST":
            return await handler(request)

        try:
            data = await request.json()
        except Exception:
            return web.json_response({"error": "invalid_json"}, status=400)

        token = _bearer(request, data)
        user = await _user(token or "")
        if not user:
            return web.json_response({"error": "unauthorized"}, status=401)

        # Never trust the user_id supplied by browser JavaScript.
        uid = int(user["id"])
        data["user_id"] = str(uid)
        action = data.get("action")
        guild_raw = data.get("guild_id")
        guild_id = int(guild_raw) if str(guild_raw or "").isdigit() else None

        if action == "proxy_control" and data.get("cmd_action") == "guild_settings_save":
            if not guild_id or not _can_manage_guild(await _guild_access(token, guild_id)):
                return web.json_response({"error": "manage_guild_required"}, status=403)

        if action == "playlist" and data.get("playlist_action") in {"save_queue", "play_playlist"}:
            if not guild_id or not _same_voice(bot, guild_id, uid):
                return web.json_response({"error": "same_voice_required"}, status=403)
        elif guild_id and action not in {"playlist", "proxy_control"}:
            if not _same_voice(bot, guild_id, uid):
                return web.json_response({"error": "same_voice_required"}, status=403)

        # aiohttp caches the request body; replace it so downstream code sees verified identity.
        request._read_bytes = json.dumps(data, separators=(",", ":")).encode("utf-8")
        return await handler(request)

    return dashboard_security
