
import discord
import time
from utils import config as ui_config

class LuxuryEmbed(discord.Embed):
    def __init__(self, title=None, description=None, color=None, **kwargs):
        if color is None:
            color = ui_config.EMBED_COLOR
        super().__init__(title=title, description=description, color=color, **kwargs)
        
    @classmethod
    def success(cls, description: str, title: str = "✅ Success"):
        return cls(title=title, description=description, color=ui_config.SUCCESS_COLOR)

    @classmethod
    def error(cls, description: str, title: str = "❌ Error"):
        return cls(title=title, description=description, color=ui_config.ERROR_COLOR)

    @classmethod
    def info(cls, description: str, title: str = "ℹ️ Information"):
        return cls(title=title, description=description, color=ui_config.EMBED_COLOR)

    def add_luxury_footer(self, bot, lang="en", user=None):
        if user:
            self.set_footer(
                text=bot.i18n.get("requested_by", lang, user=user.name),
                icon_url=user.display_avatar.url
            )
        else:
            self.set_footer(text=bot.i18n.get("footer_quote", lang))
        return self

def premium_badge(lang="en"):
    if lang == "th":
        return " 💎 [พรีเมียม]"
    return " 💎 [PREMIUM]"

def luxury_line():
    return "───────────────────────────"
