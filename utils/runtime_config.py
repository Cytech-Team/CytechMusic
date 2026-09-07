"""Public, non-secret runtime configuration for Community web pages."""
from aiohttp import web

from utils import config


def make_runtime_config_middleware(bot):
    @web.middleware
    async def runtime_config(request: web.Request, handler):
        if (
            request.method == "GET"
            and request.path == "/api/proxy"
            and request.query.get("action") == "runtime_config"
        ):
            client_id = ""
            if getattr(bot, "user", None):
                client_id = str(bot.user.id)
            elif getattr(config, "NEW_BOT_ID", None):
                client_id = str(config.NEW_BOT_ID)
            return web.json_response({"client_id": client_id})
        return await handler(request)

    return runtime_config
