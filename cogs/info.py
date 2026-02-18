import math
import time
import psutil
import cpuinfo
import discord
import datetime
import platform
import cytechlink
from discord import app_commands
from discord.ext import commands
from bot import Cyori, collection_myasync
from utils import config as ui_config

def sec_to_min(time: float):
    time = round(time) 
    hours, remainder = divmod(time, 60 * 60) 
    minutes, seconds = divmod(remainder, 60)
    days, remainder = divmod(hours, 24)
    months, days = divmod(days, 30)
    years, months = divmod(months, 12)

    if years >= 1:
        return "%d:%d:%d:%02d:%02d:%02d" % (years, months, days, hours, minutes, seconds)
    elif months >= 1:
        return "%d:%d:%02d:%02d:%02d" % (months, days, hours, minutes, seconds)
    elif days >= 1:
        return "%d:%02d:%02d:%02d" % (days, hours, minutes, seconds)
    elif hours >= 1:
        return "%02d:%02d:%02d" % (hours, minutes, seconds)
    else:
        return "%02d:%02d" % (minutes, seconds)

def formatBytes(bytes: int, unit: bool = False):
    """Format bytes to human readable format (MB or GB)."""
    if bytes <= 1_000_000_000:
        return f"{bytes / (1024 ** 2):.1f}" + ("MB" if unit else "")
    return f"{bytes / (1024 ** 3):.1f}" + ("GB" if unit else "")

def get_cmd_desc(bot, command, lang):
    key = f"cmd_{command.name}_desc"
    desc = bot.i18n.get(key, lang)
    if desc == key:
        return command.help or bot.i18n.get("no_desc", lang)
    return desc

class HelpControl(discord.ui.View):
    def __init__(self, bot: Cyori, source, author, lang="en"):
        super().__init__()
        self.source = source
        self.index = 0
        self.bot = bot
        self.lang = lang
        self.author: discord.Member = author
        self.message: discord.Message = None
        cogs = [cog for cog in self.bot.cogs]
        cogs.sort()  # Sort alphabetically
        self.select = discord.ui.Select(
            placeholder=self.bot.i18n.get("help_choose_cog", self.lang), 
            options=[
                discord.SelectOption(label=self.bot.i18n.get("help_home", self.lang), value="Home"),
                *[discord.SelectOption(label=cog, value=cog) for index, cog in enumerate(cogs)]
            ]
        )
        self.add_item(self.select)
        self.add_item(discord.ui.Button(style=discord.ButtonStyle.link, label=self.bot.i18n.get("button_invite", self.lang), url=ui_config.INVITE_URL))
        self.add_item(discord.ui.Button(style=discord.ButtonStyle.link, label=self.bot.i18n.get("button_support", self.lang), url=ui_config.SUPPORT_URL))
        self.add_item(discord.ui.Button(style=discord.ButtonStyle.link, label=self.bot.i18n.get("button_donate", self.lang), url=ui_config.DONATE_URL))
        self.add_item(discord.ui.Button(style=discord.ButtonStyle.link, label=self.bot.i18n.get("button_vote", self.lang), url=ui_config.VOTE_URL))
        self.select.callback = self.on_select    

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.defer(thinking=True)
            await interaction.followup.send(content=self.bot.i18n.get("perm_button", self.lang), ephemeral=True)
            return False
        return True

    @discord.ui.button(label='≪', style=discord.ButtonStyle.grey)
    async def first_page_button(self, interaction:discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        self.index = 0
        await self.update_page()

    @discord.ui.button(label='<', style=discord.ButtonStyle.grey)
    async def previous_page_button(self, interaction:discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        if self.index == 0:
            return
        self.index -= 1
        await self.update_page()
        
    @discord.ui.button(label='■', style=discord.ButtonStyle.grey)
    async def middle_button(self, interaction:discord.Interaction, button: discord.ui.Button):
        await interaction.message.delete()

    @discord.ui.button(label='>', style=discord.ButtonStyle.grey)
    async def next_page_button(self, interaction:discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        if self.index >= len(self.source) - 1:
            return
        self.index += 1
        await self.update_page()

    @discord.ui.button(label='≫', style=discord.ButtonStyle.grey)
    async def last_page_button(self, interaction:discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        self.index = len(self.source) - 1
        await self.update_page()

    async def update_page(self):
        embed: discord.Embed = self.source[self.index]
        embed.set_footer(text=self.bot.i18n.get("page_footer", self.lang, current=self.index + 1, total=len(self.source)), icon_url=str(self.author.avatar.url))
        await self.update_buttons()
        await self.message.edit(embed=embed)
        
    async def update_buttons(self):
        if self.index == 0:
            self.first_page_button.disabled = True
            self.previous_page_button.disabled = True
        else:
            self.first_page_button.disabled = False
            self.previous_page_button.disabled = False

        if self.index >= len(self.source) - 1:
            self.next_page_button.disabled = True
            self.last_page_button.disabled = True
        else:
            self.next_page_button.disabled = False
            self.last_page_button.disabled = False

        await self.message.edit(view=self)
        
    async def buttons_not_use(self):
        self.first_page_button.disabled = True
        self.previous_page_button.disabled = True
        self.next_page_button.disabled = True
        self.last_page_button.disabled = True
        await self.message.edit(view=self)
        
    async def buttons_use(self):
        self.first_page_button.disabled = True
        self.previous_page_button.disabled = True
        self.next_page_button.disabled = False
        self.last_page_button.disabled = False
        await self.message.edit(view=self)
        
    async def on_select(self, interaction: discord.Interaction):
        data = await collection_myasync.find_one({})
        if data:
            data = data
        else:
            data = {"guilds": {}}          
        guild_id = str(interaction.guild.id)
        if "guilds" in data and guild_id in data["guilds"]:
            guild_data: dict = data["guilds"][guild_id]
            prefix = guild_data.get("prefix", "cm!")
        else:
            prefix = "cm!"
        if interaction.data['values'][0] == "Home":
            await interaction.response.defer()
            from utils.luxury import LuxuryEmbed, luxury_line
            embed = LuxuryEmbed(
                title=self.bot.i18n.get("help_title", self.lang),
                description=f"{luxury_line()}\n"
                            f"📌 **Prefix:** `{prefix}`\n"
                            f"✨ **Slash:** `/help` or `/play`\n"
                            f"{luxury_line()}",
                colour=discord.Colour(value=ui_config.EMBED_COLOR)
            )
            # Add a banner if available
            embed.set_image(url=ui_config.BANNER_URL)
            cog_arguments = {}
            for cog_name, cog in self.bot.cogs.items():
                cog_command_names = []
                for command in cog.get_commands():
                    cog_command_names.append(f"`{commands.when_mentioned_or(prefix)(self.bot, interaction)[2]}{command.name}`")
                cog_arguments[cog_name] = cog_command_names

            other_arguments = []
            for arg in self.bot.commands:
                if not arg.cog:
                    other_arguments.append(f"`{commands.when_mentioned_or(prefix)(self.bot, interaction)[2]}{arg.name}`")

            embed.add_field(name=f"> **`{commands.when_mentioned_or(prefix)(self.bot, interaction)[2]}play` or `/play`**", value=self.bot.i18n.get('help_play_desc', self.lang))
            if cog_arguments:
                for cog_name, cog_command_names in cog_arguments.items():
                    embed.add_field(
                        name=f"📂 **{cog_name}**",
                        value=", ".join(cog_command_names),
                        inline=False
                    )
            if other_arguments:
                embed.add_field(name=f"> **{self.bot.i18n.get('help_other_desc', self.lang)}**", value=", ".join(other_arguments), inline=False)
            embed.add_field(
                name=f"💡 {self.bot.i18n.get('help_note', self.lang, prefix=prefix).replace('**', '')}",
                value=f"{luxury_line()}\n{self.bot.i18n.get('help_footer', self.lang)}",
                inline=False
            )
            embed.set_footer(text=self.bot.i18n.get("requested_by", self.lang, user=interaction.user.name), icon_url=interaction.user.avatar.url)
            embed.set_thumbnail(url=self.bot.user.avatar.url)
            helpcontrol = HelpControl(self.bot, embed, interaction.user, self.lang)
            await interaction.edit_original_response(embed=embed, view=helpcontrol)
            message = await interaction.original_response()
            helpcontrol.message = message
            await helpcontrol.buttons_not_use()
        else:
            await interaction.response.defer()
            cog_name = interaction.data['values'][0]
            cog = self.bot.get_cog(cog_name)
            if cog:
                cog_commands = cog.get_commands()
                if len(cog_commands) > 25:
                    cogs = [cog for cog in self.bot.cogs]
                    cogs.sort()
                    # Simulating having less than 25 fields
                    fields = []
                    for command in cog.get_commands():
                        fields.append({
                            "name": f"> `{commands.when_mentioned_or(prefix)(self.bot, interaction)[2]}{command.name}` or `/{command.name}`",
                            "value": get_cmd_desc(self.bot, command, self.lang),
                            "inline": False
                        })
                    # Automatically split fields into pages of 25 fields each
                    embeds = []
                    for i in range(0, len(fields), 24):
                        embed = discord.Embed(title=f"{cog_name} Cog", colour=discord.Colour(value=ui_config.EMBED_COLOR))
                        embed.set_thumbnail(url=self.bot.user.avatar.url)
                        embed.set_footer(text=self.bot.i18n.get("page_footer", self.lang, current=i//24 + 1, total=math.ceil(len(fields) / 24)), icon_url=str(interaction.user.avatar.url))
                        for field in fields[i:i+25]:
                            embed.add_field(name=field["name"], value=field["value"], inline=field["inline"])
                        embeds.append(embed)
                        
                    helpcontrol = HelpControl(self.bot, embeds, interaction.user, self.lang)
                    await interaction.followup.edit_message(embed=embeds[0], view=helpcontrol)
                    message = await interaction.original_response()
                    helpcontrol.message = message
                    await helpcontrol.buttons_use()
                else:
                    help_message = discord.Embed(title=f"{cog_name} Cog", colour=discord.Colour(value=ui_config.EMBED_COLOR))
                    for command in cog.get_commands():
                        help_message.add_field(
                            name=f"> `{commands.when_mentioned_or(prefix)(self.bot, interaction)[2]}{command.name}` or `/{command.name}`",
                            value=get_cmd_desc(self.bot, command, self.lang),
                            inline=False
                        )
                    help_message.set_thumbnail(url=self.bot.user.avatar.url)
                    help_message.set_footer(text=self.bot.i18n.get("requested_by", self.lang, user=interaction.user.name), icon_url=interaction.user.avatar.url)
                    helpcontrol = HelpControl(self.bot, help_message, interaction.user, self.lang)
                    await interaction.edit_original_response(embed=help_message, view=helpcontrol)
                    message = await interaction.original_response()
                    helpcontrol.message = message
                    await helpcontrol.buttons_not_use()
            else:
                await interaction.followup.send(f"No cog found with the name {cog_name}.", delete_after=7)

class Info(commands.Cog):
    def __init__(self, bot: Cyori) -> None:
        self.bot = bot

    @commands.hybrid_command(name='help', aliases=['h'])
    @app_commands.describe(arguments="Command, group or cog name / ชื่อคำสั่ง กลุ่ม หรือหมวดหมู่")
    async def help(self, ctx: commands.Context, *, arguments: str = None):
        "Show help info / แสดงวิธีใช้งานและรายชื่อคำสั่ง"
        async with ctx.typing():
            lang = await self.bot.get_lang(ctx.guild.id)
            data = await collection_myasync.find_one({})
            if data:
                data = data
            else:
                data = {"guilds": {}}          
            guild_id = str(ctx.guild.id)
            if "guilds" in data and guild_id in data["guilds"]:
                guild_data: dict = data["guilds"][guild_id]
                prefix = guild_data.get("prefix", "cm!")
            else:
                prefix = "cm!"
            embed = discord.Embed(
                title=self.bot.i18n.get("help_title", lang),
                description=f"`{commands.when_mentioned_or(prefix)(self.bot, ctx)[2]}help` or `/help`",
                colour=discord.Colour(value=ui_config.EMBED_COLOR)
            )

            if not arguments:
                cog_arguments = {}
                for cog_name, cog in self.bot.cogs.items():
                    cog_command_names = []
                    for command in cog.get_commands():
                        cog_command_names.append(f"`{commands.when_mentioned_or(prefix)(self.bot, ctx)[2]}{command.name}`")
                    cog_arguments[cog_name] = cog_command_names

                other_arguments = []
                for command in self.bot.commands:
                    if not command.cog:
                        other_arguments.append(f"`{commands.when_mentioned_or(prefix)(self.bot, ctx)[2]}{command.name}`")

                embed.add_field(name=f"> **`{commands.when_mentioned_or(prefix)(self.bot, ctx)[2]}play` or `/play`**", value=self.bot.i18n.get('help_play_desc', lang))
                if cog_arguments:
                    for cog_name, cog_command_names in cog_arguments.items():
                        embed.add_field(
                            name=f"📂 **{cog_name}**",
                            value=", ".join(cog_command_names),
                            inline=False
                        )
                if other_arguments:
                    embed.add_field(name=f"> **{self.bot.i18n.get('help_other_desc', lang)}**", value=", ".join(other_arguments), inline=False)
                embed.add_field(
                    name=self.bot.i18n.get("help_note", lang, prefix=prefix),
                    value=self.bot.i18n.get("help_footer", lang),
                    inline=False
                )
                embed.set_footer(text=self.bot.i18n.get("requested_by", lang, user=ctx.author.name), icon_url=ctx.author.avatar.url)
                embed.set_thumbnail(url=self.bot.user.avatar.url)
                helpcontrol = HelpControl(self.bot, embed, ctx.author, lang)
                message = await ctx.reply(embed=embed, view=helpcontrol)
                helpcontrol.message = message
                await helpcontrol.buttons_not_use()
            else:
                cog = self.bot.get_cog(arguments)
                if cog:
                    cog_commands = cog.get_commands()
                    if len(cog_commands) > 25:
                        cogs = [cog for cog in self.bot.cogs]
                        cogs.sort()
                        
                        fields = []
                        for command in cog.get_commands():
                            fields.append({
                                "name": f"> `{commands.when_mentioned_or(prefix)(self.bot, ctx)[2]}{command.name}` or `/{command.name}`",
                                "value": get_cmd_desc(self.bot, command, lang),
                                "inline": False
                            })
                            
                        # Automatically split fields into pages of 25 fields each
                        embeds = []
                        for i in range(0, len(fields), 25):
                            embed = discord.Embed(title=f"{arguments} Cog", colour=discord.Colour(value=ui_config.EMBED_COLOR))
                            embed.set_thumbnail(url=self.bot.user.avatar.url)
                            embed.set_footer(text=self.bot.i18n.get("page_footer", lang, current=i//25 + 1, total=math.ceil(len(fields) / 25)), icon_url=str(ctx.author.avatar.url))
                            for field in fields[i:i+25]:
                                embed.add_field(name=field["name"], value=field["value"], inline=field["inline"])
                            embeds.append(embed)
                            
                        helpcontrol = HelpControl(self.bot, embeds, ctx.author, lang)
                        message = await ctx.reply(embed=embeds[0], view=helpcontrol)
                        helpcontrol.message = message
                        await helpcontrol.buttons_use()
                    else:
                        help_message = discord.Embed(title=f"{arguments} Cog", colour=discord.Colour(value=ui_config.EMBED_COLOR))
                        for command in cog.get_commands():
                            help_message.add_field(name=f'> `{commands.when_mentioned_or(prefix)(self.bot, ctx)[2]}{command.name}` or `/{command.name}`', value=get_cmd_desc(self.bot, command, lang), inline=False)
                        help_message.set_thumbnail(url=self.bot.user.avatar.url)
                        help_message.set_footer(text=self.bot.i18n.get("requested_by", lang, user=ctx.author.name), icon_url=ctx.author.avatar.url)
                        helpcontrol = HelpControl(self.bot, embed, ctx.author, lang)
                        message = await ctx.reply(embed=help_message, view=helpcontrol)
                        helpcontrol.message = message
                        await helpcontrol.buttons_not_use()
                else:
                    arg = self.bot.get_command(arguments)
                    matches = arguments.split()
                    if len(matches) >= 2:
                        group_name = matches[0]
                        subcommand_name = matches[1]
                        group = self.bot.get_command(group_name)
                        if group and isinstance(group, commands.Group):
                            for cmd in group.commands:
                                if cmd.name == subcommand_name:
                                    embed = discord.Embed(
                                        title=f"Help with {cmd.name}",
                                        color=discord.Color(value=ui_config.EMBED_COLOR)
                                    )
                                    embed.add_field(
                                        name=f'> `{commands.when_mentioned_or(prefix)(self.bot, ctx)[2]}{arguments} {cmd.name}` or `/{arguments} {cmd.name}`',
                                        value=get_cmd_desc(self.bot, cmd, lang),
                                        inline=False
                                    )   
                                    embed.set_thumbnail(url=self.bot.user.avatar.url)
                                    embed.set_footer(text=self.bot.i18n.get("requested_by", lang, user=ctx.author.name), icon_url=ctx.author.avatar.url)
                                    helpcontrol = HelpControl(self.bot, embed, ctx.author, lang)
                                    message = await ctx.reply(embed=embed, view=helpcontrol)
                                    helpcontrol.message = message
                                    await helpcontrol.buttons_not_use()
                                    return
                        else:  # Help for a specific subcommand
                            embed = discord.Embed(
                                title=f"Help with {arguments}",
                                color=discord.Color(value=ui_config.EMBED_COLOR)
                            )
                            embed.add_field(
                                name=f'> `{commands.when_mentioned_or(prefix)(self.bot, ctx)[2]}{arguments}` or `/{arguments}`',
                                value=get_cmd_desc(self.bot, arg, lang),
                                inline=False
                            )
                            embed.set_thumbnail(url=self.bot.user.avatar.url)
                            embed.set_footer(text=self.bot.i18n.get("requested_by", lang, user=ctx.author.name), icon_url=ctx.author.avatar.url)
                            helpcontrol = HelpControl(self.bot, embed, ctx.author, lang)
                            message = await ctx.reply(embed=embed, view=helpcontrol)
                            helpcontrol.message = message
                            await helpcontrol.buttons_not_use()
                    elif arguments in self.bot.all_commands:
                        command = self.bot.get_command(arguments)
                        if isinstance(command, commands.Group):
                            group_embed = discord.Embed(
                                title=f"{arguments} " + "Group",
                                colour=discord.Colour(value=ui_config.EMBED_COLOR)
                            )
                            for cmd in command.commands:
                                group_embed.add_field(
                                    name=f'> `{commands.when_mentioned_or(prefix)(self.bot, ctx)[2]}{arguments} {cmd.name}` or `/{arguments} {cmd.name}`',
                                    value=get_cmd_desc(self.bot, cmd, lang),
                                    inline=False
                                )
                                group_embed.set_thumbnail(url=self.bot.user.avatar.url)
                                group_embed.set_footer(text=self.bot.i18n.get("requested_by", lang, user=ctx.author.name), icon_url=ctx.author.avatar.url)
                                helpcontrol = HelpControl(self.bot, group_embed, ctx.author, lang)
                                message = await ctx.reply(embed=group_embed, view=helpcontrol)
                                helpcontrol.message = message
                                await helpcontrol.buttons_not_use()
                        else:
                            embed = discord.Embed(
                                title=f"Help with {command}",
                                color=discord.Color(value=ui_config.EMBED_COLOR)
                            )
                            embed.add_field(
                                name=f'> `{commands.when_mentioned_or(prefix)(self.bot, ctx)[2]}{command}` or `/{command}`',
                                value=get_cmd_desc(self.bot, command, lang),
                                inline=False
                            )
                            embed.set_thumbnail(url=self.bot.user.avatar.url)
                            embed.set_footer(text=self.bot.i18n.get("requested_by", lang, user=ctx.author.name), icon_url=ctx.author.avatar.url)
                            helpcontrol = HelpControl(self.bot, embed, ctx.author, lang)
                            message = await ctx.reply(embed=embed, view=helpcontrol)
                            helpcontrol.message = message
                            await helpcontrol.buttons_not_use()
                    else:
                        await ctx.reply(embed=discord.Embed(description="Command not found.", colour=discord.Colour(value=ui_config.EMBED_COLOR)), delete_after=7)

    @commands.hybrid_command()
    async def ping(self, ctx: commands.Context):
        """Check bot latency / เช็คค่าความหน่วง (Ping) ของบอท"""
        async with ctx.typing():
            lang = await self.bot.get_lang(ctx.guild.id)
            ping = round(self.bot.latency * 1000)

            # Mapping color + status
            if ping <= 50:
                color, status = 0x44ff44, self.bot.i18n.get("status_excellent", lang)
            elif ping <= 100:
                color, status = 0xffd000, self.bot.i18n.get("status_good", lang)
            elif ping <= 200:
                color, status = 0xff6600, self.bot.i18n.get("status_moderate", lang)
            else:
                color, status = 0x990000, self.bot.i18n.get("status_poor", lang)

            from utils.luxury import LuxuryEmbed, luxury_line
            embed = LuxuryEmbed(
                title=self.bot.i18n.get("pong", lang),
                description=f"{luxury_line()}\n"
                            f"📡 **{self.bot.i18n.get('latency', lang, ping=ping, status=status).split(':')[0]}:** `{ping} ms`\n"
                            f"📊 **Status:** {status}\n"
                            f"{luxury_line()}",
                color=color
            )
            embed.add_luxury_footer(self.bot, lang, ctx.author)

            await ctx.reply(embed=embed, delete_after=7)

            await ctx.reply(embed=embed, delete_after=7)

    @commands.hybrid_command()
    async def uptime(self, ctx: commands.Context):
        "Check bot uptime / เช็คเวลาทำงานของบอท"
        async with ctx.typing():
            lang = await self.bot.get_lang(ctx.guild.id)
            # Use the bot's start_time that was set when the bot initialized
            start_time = getattr(self.bot, 'start_time', time.time())
            current_time = time.time()
            difference = int(round(current_time - start_time))
            uptime_text = str(datetime.timedelta(seconds=difference))

            from utils.luxury import LuxuryEmbed
            embed = LuxuryEmbed(color=0xFFD700)
            embed.set_author(name=self.bot.i18n.get("uptime_label", lang), icon_url=self.bot.user.display_avatar.url)
            embed.description = f"⏲️ **Online for:** `{uptime_text}`"
            embed.add_luxury_footer(self.bot, lang)

            try:
                await ctx.reply(embed=embed, delete_after=7)
            except discord.HTTPException:   
                await ctx.reply("Current uptime: " + uptime_text, delete_after=7)

    @commands.hybrid_command() 
    async def stats(self, ctx: commands.Context): 
        "Show system & node stats / แสดงสถานะระบบและ Music Node"
        async with ctx.typing():
            lang = await self.bot.get_lang(ctx.guild.id)
            from utils.luxury import LuxuryEmbed, luxury_line
            em = LuxuryEmbed( 
                title=f"📊 {self.bot.i18n.get('stats_title', lang)}",
                color=ui_config.EMBED_COLOR
            )
            for name, node in cytechlink.NodePool._nodes.items():
                total_memory = node.stats.used + node.stats.free
                status_emoji = "🟢" if node._available else "🔴"
                
                info = (
                    f"> 🔗 **{self.bot.i18n.get('stats_address', lang)}:** `{node._host}:{node._port}`\n"
                    f"> 👥 **{self.bot.i18n.get('stats_players', lang)}:** `{len(node._players)}`\n"
                    f"> 🧠 **RAM:** `{formatBytes(node.stats.free)} / {formatBytes(total_memory, True)}`\n"
                    f"> 💻 **CPU:** `{node.stats.cpu_process_load:.1f}%`\n"
                    f"> ⏱️ **{self.bot.i18n.get('stats_uptime', lang)}:** `{sec_to_min(node.stats.uptime)}`"
                )
                
                em.add_field(
                    name=f"{status_emoji} Node {name}",
                    value=info, 
                    inline=False
                )
            
            total_players = sum(len(node._players) for node in cytechlink.NodePool._nodes.values())
            em.add_luxury_footer(self.bot, lang, ctx.author)
            await ctx.reply(embed=em, delete_after=30)

    @commands.hybrid_command(aliases=["info"])
    async def botinfo(self, ctx: commands.Context):
        "Show bot information / แสดงข้อมูลเกี่ยวกับบอท"
        async with ctx.typing():
            lang = await self.bot.get_lang(ctx.guild.id)
            
            # System Info
            cpu = cpuinfo.get_cpu_info()["brand_raw"]
            cpu_cores = psutil.cpu_count(logical=False)
            memory = psutil.virtual_memory()
            ram_used = round(memory.used / (1024 ** 3), 2)
            ram_total = round(memory.total / (1024 ** 3), 2)
            ram_percent = memory.percent
            
            from utils.luxury import LuxuryEmbed, luxury_line
            embed = LuxuryEmbed(title=self.bot.i18n.get("botinfo_title", lang), color=ui_config.EMBED_COLOR)
            embed.set_thumbnail(url=self.bot.user.avatar.url)
            embed.set_image(url=ui_config.BANNER_URL)
            
            # Bot Details
            embed.add_field(
                name=f"📦 {self.bot.i18n.get('botinfo_version', lang)}",
                value=f"```\nCyori: {self.bot.bot_version}\nPython: {platform.python_version()}\nDiscord.py: {discord.__version__}\n```",
                inline=False
            )
            embed.add_field(
                 name=f"📊 {self.bot.i18n.get('botinfo_stats', lang)}",
                 value=f"```\n🏰 {self.bot.i18n.get('stats_guilds', lang, count=len(self.bot.guilds))}\n👥 {self.bot.i18n.get('stats_users', lang, count=len(self.bot.users))}\n💬 {self.bot.i18n.get('stats_channels', lang, count=sum(1 for _ in self.bot.get_all_channels()))}\n```",
                 inline=False
            )
            
            # System Details
            sys_info = (
                f"🖥️ {self.bot.i18n.get('sys_os', lang, value=f'{platform.system()} {platform.release()}')}\n"
                f"⚙️ {self.bot.i18n.get('sys_cpu', lang, value=cpu)}\n"
                f"🧠 {self.bot.i18n.get('sys_ram', lang, used=ram_used, total=ram_total, percent=ram_percent)}"
            )

            embed.add_field(
                name=f"💻 {self.bot.i18n.get('botinfo_system', lang)}",
                value=f"```\n{sys_info}\n```",
                inline=False
            )
            
            embed.set_footer(text=self.bot.i18n.get("footer_quote", lang))
            
            # Buttons
            view = discord.ui.View()
            view.add_item(discord.ui.Button(style=discord.ButtonStyle.link, label=self.bot.i18n.get("button_invite", lang), url=ui_config.INVITE_URL))
            view.add_item(discord.ui.Button(style=discord.ButtonStyle.link, label=self.bot.i18n.get("button_support", lang), url=ui_config.SUPPORT_URL))
            view.add_item(discord.ui.Button(style=discord.ButtonStyle.link, label=self.bot.i18n.get("button_donate", lang), url=ui_config.DONATE_URL))
            view.add_item(discord.ui.Button(style=discord.ButtonStyle.link, label=self.bot.i18n.get("button_vote", lang), url=ui_config.VOTE_URL))
            
            await ctx.reply(embed=embed, view=view)

    @commands.hybrid_command()
    async def avatar(self, ctx: commands.Context, member: discord.Member = None):
        """Show member's avatar / ดูรูปโปรไฟล์ของสมาชิก"""
        member = member or ctx.author
        lang = await self.bot.get_lang(ctx.guild.id)
        
        from utils.luxury import LuxuryEmbed
        embed = LuxuryEmbed(title=f"🖼️ Avatar - {member.name}", color=ui_config.EMBED_COLOR)
        embed.set_image(url=member.display_avatar.url)
        embed.add_luxury_footer(self.bot, lang, ctx.author)
        
        await ctx.reply(embed=embed)

    @commands.hybrid_command()
    async def serverinfo(self, ctx: commands.Context):
        """Show server information / ดูข้อมูลของเซิร์ฟเวอร์นี้"""
        guild = ctx.guild
        lang = await self.bot.get_lang(ctx.guild.id)
        
        roles = [role.mention for role in sorted(guild.roles, key=lambda r: r.position, reverse=True) if not role.is_default()]
        roles_text = ", ".join(roles[:10]) + (f" ... and {len(roles)-10} more" if len(roles) > 10 else "") if roles else "None"
        
        from utils.luxury import LuxuryEmbed, luxury_line
        embed = LuxuryEmbed(title=f"🏰 Server Info: {guild.name}", color=ui_config.EMBED_COLOR)
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
            
        embed.description = (
            f"{luxury_line()}\n"
            f"🆔 **ID:** `{guild.id}`\n"
            f"👑 **Owner:** {guild.owner.mention}\n"
            f"📅 **Created:** {discord.utils.format_dt(guild.created_at, style='D')}\n"
            f"👥 **Members:** `{guild.member_count}`\n"
            f"💬 **Channels:** `Text: {len(guild.text_channels)} | Voice: {len(guild.voice_channels)}`\n"
            f"{luxury_line()}\n"
            f"🎭 **Roles:** {roles_text}\n"
            f"{luxury_line()}"
        )
        
        if guild.banner:
            embed.set_image(url=guild.banner.url)
            
        embed.add_luxury_footer(self.bot, lang, ctx.author)
        await ctx.reply(embed=embed)

    @commands.hybrid_command()
    async def userinfo(self, ctx: commands.Context, member: discord.Member = None):
        """Show user information / ดูข้อมูลส่วนตัวของคุณหรือของผู้อื่น"""
        member = member or ctx.author
        lang = await self.bot.get_lang(ctx.guild.id)
        
        roles = [role.mention for role in sorted(member.roles, key=lambda r: r.position, reverse=True) if not role.is_default()]
        roles_text = ", ".join(roles[:10]) + (f" ... and {len(roles)-10} more" if len(roles) > 10 else "") if roles else "None"
        
        from utils.luxury import LuxuryEmbed, luxury_line
        embed = LuxuryEmbed(title=f"👤 User Info: {member.name}", color=ui_config.EMBED_COLOR)
        embed.set_thumbnail(url=member.display_avatar.url)
        
        embed.description = (
            f"{luxury_line()}\n"
            f"🆔 **ID:** `{member.id}`\n"
            f"🏷️ **Nickname:** `{member.nick or 'None'}`\n"
            f"📅 **Joined Discord:** {discord.utils.format_dt(member.created_at, style='D')}\n"
            f"📥 **Joined Server:** {discord.utils.format_dt(member.joined_at, style='D')}\n"
            f"{luxury_line()}\n"
            f"🎭 **Roles:** {roles_text}\n"
            f"{luxury_line()}"
        )
        
        embed.add_luxury_footer(self.bot, lang, ctx.author)
        await ctx.reply(embed=embed)

    @commands.hybrid_command()
    async def invite(self, ctx: commands.Context):
        """Invite the bot to your server / เชิญบอทเข้าเซิร์ฟเวอร์ของคุณ"""
        lang = await self.bot.get_lang(ctx.guild.id)
        
        from utils.luxury import LuxuryEmbed, luxury_line
        embed = LuxuryEmbed(
            title="💌 Invite Cyori",
            description=f"{luxury_line()}\n"
                        f"Click the button below to invite me to your server!\nหรือคลิกที่ปุ่มด้านล่างเพื่อเชิญบอท\n\n"
                        f"👉 **[Click here to Invite]({ui_config.INVITE_URL})**\n"
                        f"{luxury_line()}",
            color=ui_config.EMBED_COLOR
        )
        embed.set_thumbnail(url=self.bot.user.avatar.url)
        
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label=self.bot.i18n.get("button_invite", lang), url=ui_config.INVITE_URL, style=discord.ButtonStyle.link))
        
        await ctx.reply(embed=embed, view=view)

    @commands.hybrid_command(name="dashboard", description="Web Dashboard link / ลิงก์แดชบอร์ดควบคุมผ่านเว็บ")
    async def dashboard(self, ctx: commands.Context):
        lang = await self.bot.get_lang(ctx.guild.id)
        
        from utils.luxury import LuxuryEmbed, luxury_line
        embed = LuxuryEmbed(
            title=f"🌐 {self.bot.i18n.get('dashboard_title', lang)}",
            description=f"{luxury_line()}\n"
                        f"{self.bot.i18n.get('dashboard_desc', lang)}\n\n"
                        f"👉 **[Link to Dashboard]({ui_config.DASHBOARD_URL})**\n"
                        f"{luxury_line()}",
            color=ui_config.EMBED_COLOR
        )
        embed.set_thumbnail(url=self.bot.user.avatar.url)
        embed.set_image(url=ui_config.BANNER_URL)
        embed.add_luxury_footer(self.bot, lang, ctx.author)
        
        view = discord.ui.View()
        view.add_item(discord.ui.Button(
            label=self.bot.i18n.get("button_dashboard", lang), 
            url=ui_config.DASHBOARD_URL, 
            style=discord.ButtonStyle.link,
            emoji="🌐"
        ))
        
        await ctx.reply(embed=embed, view=view)

    @commands.command(name="export_commands", hidden=True)
    @commands.is_owner()
    async def export_commands(self, ctx: commands.Context):
        """Export all bot commands in Top.gg format (Owner Only)"""
        cog = self.bot.get_cog("DashboardAPI")
        if not cog:
            return await ctx.send("DashboardAPI cog not found.")
        
        # We need a fake request object or just call the logic
        class FakeRequest:
            def __init__(self): self.query = {"show_all": "true"}
        
        # Actually it's easier to just re-implement the logic or move it to a helper
        # Let's just use the cog's method but we need to handle the response
        try:
            # Re-using the parse logic
            all_cmds = []
            for c_name, c_obj in self.bot.cogs.items():
                for cmd in c_obj.get_commands():
                    all_cmds.extend(cog._parse_command_recursive(cmd, category=c_name))
            
            topgg_text = ""
            for cmd in all_cmds:
                if cmd.get("is_group"): continue
                topgg_text += f"{cmd['usage']} - {cmd['description']}\n"
            
            # Send as file if too long
            if len(topgg_text) > 1900:
                import io
                file = discord.File(io.BytesIO(topgg_text.encode()), filename="topgg_commands.txt")
                await ctx.send("✅ Exported commands to file:", file=file)
            else:
                await ctx.send(f"✅ **Top.gg Command Export:**\n```\n{topgg_text}\n```")
        except Exception as e:
            await ctx.send(f"❌ Error: {e}")


async def setup(bot: Cyori) -> None:
    await bot.add_cog(Info(bot))