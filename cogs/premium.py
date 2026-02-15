
import discord
import secrets
import time
import datetime
from discord.ext import commands, tasks
from discord import app_commands
from bot import Cyori, collection_myasync
from utils import config as ui_config

class RenewalView(discord.ui.View):
    def __init__(self, bot, user_id):
        super().__init__(timeout=None)
        self.bot = bot
        self.user_id = user_id

    @discord.ui.button(label="Renew Premium / ต่ออายุ", style=discord.ButtonStyle.green, emoji="💎")
    async def renew_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        payment_cog = self.bot.get_cog("Payment")
        if not payment_cog:
            return await interaction.response.send_message("❌ Payment system unavailable.", ephemeral=True)
        
        await interaction.response.defer(ephemeral=True)
        
        # Determine plan to renew
        data = await collection_myasync.find_one({}) or {}
        user_data = data.get("users", {}).get(str(self.user_id), {})
        plan_id = user_data.get("premium_plan_id", "1_month") # Default to 1 month if unknown
        
        try:
            url = await payment_cog.create_checkout_link(interaction.user, plan_id)
            
            # Create a simple view with the link
            view = discord.ui.View()
            view.add_item(discord.ui.Button(label="Pay Now / จ่ายเงิน", url=url, style=discord.ButtonStyle.url))
            
            await interaction.followup.send(f"Renewing **{plan_id}** plan:", view=view, ephemeral=True)
            
        except Exception as e:
            await interaction.followup.send(f"❌ Error generating link: {e}", ephemeral=True)

class Premium(commands.Cog):
    def __init__(self, bot: Cyori):
        self.bot = bot
        self.check_premium_expiry.start()

    def cog_unload(self):
        self.check_premium_expiry.cancel()

    @tasks.loop(minutes=5)
    async def check_premium_expiry(self):
        """Background task to check for expired user premiums."""
        try:
            data = await collection_myasync.find_one({}) or {}
            users_data = data.get("users", {})
            now = time.time()
            
            updates = {}
            for uid_str, u_data in users_data.items():
                expire = u_data.get("premium_expire")
                # Check if expired AND not already notified (we can check if 'premium_expire' exists but is past)
                # To avoid spamming, we should unset 'premium_expire' after notifying, OR have a 'notified' flag.
                # The user requirement implies we catch them when they match "Expired".
                
                if expire and isinstance(expire, (int, float)) and now > expire:
                    # Double check if we already handled this (e.g. if premium=False but expire is still there?)
                    # Strategy: If expired, we send DM, then remove 'premium_expire' field so we don't spam.
                    
                    try:
                        user = await self.bot.fetch_user(int(uid_str))
                        if user:
                            # Create View for renewal
                            view = RenewalView(self.bot, uid_str)
                            
                            lang = "en" # Default for DM
                            embed = discord.Embed(
                                title="⚠️ Premium Expired / พรีเมียมหมดอายุ",
                                description=self.bot.i18n.get("premium_expired_msg", lang),
                                color=ui_config.ERROR_COLOR
                            )
                            await user.send(embed=embed, view=view)
                            print(f"Sent expiry notification to {uid_str}")
                    except Exception as e:
                        print(f"Failed to DM expired user {uid_str}: {e}")

                    # Cleanup to prevent loop spam
                    updates[f"users.{uid_str}.premium_expire"] = "" # Unset
                    updates[f"users.{uid_str}.premium"] = "" # Unset (just in case)

            if updates:
                await collection_myasync.update_one({}, {"$unset": updates})

        except Exception as e:
            print(f"Error in premium expiry check: {e}")

    @check_premium_expiry.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    async def _update_controller_if_playing(self, guild_id: int):
        player = None
        for p in self.bot.voice_clients:
            if p.guild.id == guild_id:
                player = p
                break
        
        if player and player.is_playing and hasattr(player, "update_controller"):
            try:
                await player.update_controller()
            except:
                pass
        
        # Also update non-playing embed
        try:
            data = await collection_myasync.find_one({}) or {}
            if "guilds" in data and str(guild_id) in data["guilds"]:
                g_data = data["guilds"][str(guild_id)]
                await self.bot.update_guild_embed(g_data, guild_id=guild_id)
        except:
             pass

    # =========================================================================
    # KEY GENERATION (OWNER)
    # =========================================================================
    @commands.hybrid_group(name="premium", description="Premium Management Commands (Owner Only)")
    @commands.is_owner()
    async def premium_group(self, ctx: commands.Context):
        """Premium Management Commands (Owner Only)"""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @premium_group.command(name="genkey")
    async def genkey(self, ctx: commands.Context, days: int = 30, count: int = 1):
        """Generate premium keys / สร้างคีย์พรีเมียม (Admin Only)"""
        lang = await self.bot.get_lang(ctx.guild.id) if ctx.guild else "en"

        if days < 1:
            return await ctx.send("❌ Days must be at least 1.")
        
        new_keys = {}
        generated_list = []
        
        for _ in range(count):
            # Generate random key: XXXX-XXXX-XXXX
            key = f"{secrets.token_hex(2)}-{secrets.token_hex(2)}-{secrets.token_hex(2)}".upper()
            new_keys[f"premium_keys.{key}"] = days
            generated_list.append(key)
        
        # Save to DB
        await collection_myasync.update_one({}, {"$set": new_keys}, upsert=True)
        
        # Determine strict output for DM vs Channel
        msg = self.bot.i18n.get("premium_gen_key", lang, count=count, days=days)
        msg += "\n".join([f"`{k}`" for k in generated_list])
        
        try:
            await ctx.author.send(msg)
            await ctx.send(f"✅ Generated {count} keys! Sent to DM.")
        except:
            await ctx.send(msg)

    @premium_group.command(name="listkeys")
    async def listkeys(self, ctx: commands.Context):
        """List active unused keys / ดูคีย์ที่ยังไม่ได้ใช้"""
        lang = await self.bot.get_lang(ctx.guild.id) if ctx.guild else "en"

        data = await collection_myasync.find_one({}) or {}
        keys = data.get("premium_keys", {})
        
        if not keys:
            return await ctx.send(self.bot.i18n.get("premium_no_keys", lang))
        
        lines = []
        for k, d in keys.items():
            lines.append(f"`{k}` : {d} Days")
        
        # Pagination or simple split if too long
        msg = self.bot.i18n.get("premium_list_keys", lang) + "\n".join(lines)
        if len(msg) > 2000:
            msg = msg[:1990] + "..."
        await ctx.send(msg)

    @premium_group.command(name="stats")
    async def premium_stats(self, ctx: commands.Context):
        """View Premium System Statistics / ดูสถิติของระบบพรีเมียม"""
        data = await collection_myasync.find_one({}) or {}
        
        users_data = data.get("users", {})
        keys_data = data.get("premium_keys", {})
        
        now = time.time()
        total_premium = 0
        lifetime = 0
        expiring_soon = 0 # Within 7 days
        
        for u_id, u_info in users_data.items():
            is_lifetime = u_info.get("premium", False)
            expire = u_info.get("premium_expire", 0)
            
            if is_lifetime:
                lifetime += 1
                total_premium += 1
            elif expire > now:
                total_premium += 1
                if expire - now < 7 * 86400:
                    expiring_soon += 1
        
        embed = discord.Embed(title="📊 Premium Statistics", color=ui_config.EMBED_COLOR)
        embed.add_field(name="Total Premium Users", value=f"👤 {total_premium}", inline=True)
        embed.add_field(name="Lifetime Users", value=f"💎 {lifetime}", inline=True)
        embed.add_field(name="Unused Keys", value=f"🔑 {len(keys_data)}", inline=True)
        embed.add_field(name="Expiring Soon (7d)", value=f"⏳ {expiring_soon}", inline=True)
        
        await ctx.send(embed=embed)

    @premium_group.command(name="check")
    async def premium_check_user(self, ctx: commands.Context, user: discord.User = None):
        """Check premium status of a user / ตรวจสอบสถานะของสมาชิก"""
        if user is None:
            user = ctx.author

        data = await collection_myasync.find_one({}) or {}
        u_info = data.get("users", {}).get(str(user.id), {})
        
        is_lifetime = u_info.get("premium", False)
        expire = u_info.get("premium_expire", 0)
        now = time.time()
        
        if is_lifetime:
            status = "Lifetime ✅"
            expire_str = "Never"
        elif expire > now:
            status = "Active ✅"
            expire_str = datetime.datetime.fromtimestamp(expire).strftime('%d/%m/%Y %H:%M')
        else:
            status = "Inactive ❌"
            expire_str = "N/A"
            
        embed = discord.Embed(title=f"User Premium Lookup", color=ui_config.EMBED_COLOR)
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="User", value=f"{user.mention} (`{user.id}`)", inline=False)
        embed.add_field(name="Status", value=status, inline=True)
        embed.add_field(name="Expires", value=expire_str, inline=True)
        
        await ctx.send(embed=embed)

    @premium_group.command(name="extend")
    async def premium_extend(self, ctx: commands.Context, user: discord.User, days: int):
        """Extend user's premium by days / เพิ่มวันพรีเมียมให้สมาชิก"""
        if days == 0: return await ctx.send("Days cannot be 0.")
        
        data = await collection_myasync.find_one({}) or {}
        u_info = data.get("users", {}).get(str(user.id), {})
        current_expire = u_info.get("premium_expire", 0)
        
        now = time.time()
        start_from = max(current_expire, now)
        new_expire = start_from + (days * 86400)
        
        await collection_myasync.update_one(
            {}, 
            {"$set": {f"users.{user.id}.premium_expire": new_expire}}, 
            upsert=True
        )
        
        expire_str = datetime.datetime.fromtimestamp(new_expire).strftime('%d/%m/%Y %H:%M')
        await ctx.send(f"✅ Extended **{user}** premium by {days} days. New expiry: `{expire_str}`")

    @premium_group.command(name="active")
    async def premium_list_active(self, ctx: commands.Context):
        """List all active premium users / รายชื่อสมาชิกที่มีพรีเมียม"""
        data = await collection_myasync.find_one({}) or {}
        users = data.get("users", {})
        now = time.time()
        
        active = []
        for u_id, u_info in users.items():
            if u_info.get("premium", False) or u_info.get("premium_expire", 0) > now:
                active.append(f"<@{u_id}> (`{u_id}`)")
        
        if not active:
            return await ctx.send("No active premium users found.")
            
        msg = f"**Total Active Premium Users: {len(active)}**\n" + "\n".join(active[:25])
        if len(active) > 25:
            msg += f"\n...and {len(active) - 25} more."
            
        await ctx.send(msg)

    # =========================================================================
    # USER REDEMPTION
    # =========================================================================
    @commands.hybrid_command(name="redeem")
    @commands.has_permissions(manage_guild=True)
    async def redeem(self, ctx: commands.Context, key: str):
        """Redeem a Premium Key / เติมพรีเมียมด้วยคีย์"""
        await ctx.defer()
        lang = await self.bot.get_lang(ctx.guild.id) if ctx.guild else "en"
        key = key.strip().upper()
        
        # 1. Check Key
        data = await collection_myasync.find_one({}) or {}
        keys = data.get("premium_keys", {})
        
        if key not in keys:
            return await ctx.send(self.bot.i18n.get("premium_redeem_invalid", lang), ephemeral=True)
        
        days = keys[key]
        seconds_to_add = days * 24 * 3600
        
        # 2. Calculate New Expiry
        user_id = str(ctx.author.id)
        users = data.get("users", {})
        user_data = users.get(user_id, {})
        current_expire = user_data.get("premium_expire", 0)
        
        now = time.time()
        if current_expire > now:
            new_expire = current_expire + seconds_to_add
        else:
            new_expire = now + seconds_to_add
            
        # 3. Update DB: Set new expire for USER
        await collection_myasync.update_one(
            {}, 
            {
                "$set": {
                    f"users.{user_id}.premium_expire": new_expire,
                    f"users.{user_id}.premium_plan": f"{days} Days"
                },
                "$unset": {f"premium_keys.{key}": ""}
            }
        )
        
        # 4. Success Message
        expire_dt = datetime.datetime.fromtimestamp(new_expire)
        expire_str = expire_dt.strftime("%d/%m/%Y %H:%M:%S")
        
        await ctx.send(self.bot.i18n.get("premium_redeem_success", lang, days=days, expire=expire_str), ephemeral=False)
        
        # Trigger update if in voice
        if ctx.guild:
             await self._update_controller_if_playing(ctx.guild.id)


    # =========================================================================
    # PREMIUM MANAGEMENT
    # =========================================================================
    @premium_group.command(name="add")
    async def premium_add(self, ctx: commands.Context, user_id: str):
        """Enable Lifetime Premium for a User"""
        lang = await self.bot.get_lang(ctx.guild.id) if ctx.guild else "en"
        try:
            uid = int(user_id)
            await collection_myasync.update_one(
                {}, 
                {"$set": {
                    f"users.{uid}.premium": True,
                    f"users.{uid}.premium_plan": "Lifetime"
                }}, 
                upsert=True
            )
            await ctx.send(self.bot.i18n.get("premium_add_success", lang, uid=uid))
        except ValueError:
            await ctx.send(self.bot.i18n.get("premium_invalid_id", lang))
        except Exception as e:
            await ctx.send(self.bot.i18n.get("premium_error", lang, e=e))


    @premium_group.command(name="remove")
    async def premium_remove(self, ctx: commands.Context, user_id: str):
        """Disable Premium for a User"""
        lang = await self.bot.get_lang(ctx.guild.id) if ctx.guild else "en"
        try:
            uid = int(user_id)
            # Remove premium flags, BUT KEEP SETTINGS (Images/etc)
            await collection_myasync.update_one(
                {}, 
                {"$unset": {
                    f"users.{uid}.premium": "",
                    f"users.{uid}.premium_expire": ""
                }}, 
                upsert=True
            )
            await ctx.send(self.bot.i18n.get("premium_remove_success", lang, uid=uid))
        except ValueError:
            await ctx.send(self.bot.i18n.get("premium_invalid_id", lang))
        except Exception as e:
            await ctx.send(self.bot.i18n.get("premium_error", lang, e=e))



    # =========================================================================
    # CUSTOMIZATION
    # =========================================================================
    # =========================================================================
    # BRANDING (Consolidated)
    # =========================================================================
    @commands.hybrid_command(name="branding", description="Customize Bot Appearance & Music Embed / ปรับแต่งหน้าตาบอทและธีมเพลง")
    @app_commands.describe(
        nickname="Change Bot Nickname / เปลี่ยนชื่อเล่นบอท",
        avatar="Change Bot Server Avatar / เปลี่ยนรูปโปรไฟล์บอทในเซิร์ฟนี้",
        bot_banner="Change Bot Server Banner / เปลี่ยนรูปแบนเนอร์บอทในเซิร์ฟนี้",
        image="Set Music Embed Thumbnail (Logo) / รูปโลโก้มุมขวาบนของเพลง",
        banner="Set Music Embed Banner (Large Image) / รูปแบนเนอร์ใหญ่ตอนเล่นเพลง",
        color="Set Embed Color (Hex e.g. #FF0000) / สีของ Embed (รหัสสี)",
        reset="Reset all customization to default / รีเซ็ตค่าทั้งหมด"
    )
    async def branding(self, 
        ctx: commands.Context, 
        nickname: str = None, 
        avatar: discord.Attachment = None,
        bot_banner: discord.Attachment = None,
        image: discord.Attachment = None, 
        banner: discord.Attachment = None, 
        color: str = None,
        reset: bool = False
    ):
        """Customize Bot Appearance & Music Themes (Premium Only)"""
        lang = await self.bot.get_lang(ctx.guild.id) if ctx.guild else "en"

        if ctx.author.id != ctx.guild.owner_id:
             return await ctx.send(self.bot.i18n.get("premium_only_owner", lang), ephemeral=True)
        
        if not await self.bot.is_premium(ctx.author.id, guild_id=ctx.guild.id if ctx.guild else None):
             return await ctx.send(self.bot.i18n.get("premium_only_feature", lang), ephemeral=True)
        
        # Defer since it might involve image processing or DB ops
        await ctx.defer()
        
        changes = []
        guild_id = ctx.guild.id
        
        # 1. Reset
        if reset:
            # Reset DB
            await collection_myasync.update_one(
                {}, 
                {"$unset": {
                    f"guilds.{guild_id}.premium_image": "", 
                    f"guilds.{guild_id}.premium_banner": "",
                    f"guilds.{guild_id}.color": ""
                }}
            )
            # Reset Nickname
            try:
                if ctx.guild.me.nick:
                    await ctx.guild.me.edit(nick=None)
                    changes.append(self.bot.i18n.get("premium_reset_nickname", lang))
            except discord.Forbidden:
                changes.append(self.bot.i18n.get("premium_reset_nickname_err", lang))
            
            # Reset Bot Avatar & Banner
            try:
                await self.bot.http.request(
                    discord.http.Route('PATCH', '/guilds/{guild_id}/members/@me', guild_id=guild_id),
                    json={'avatar': None, 'banner': None}
                )
                changes.append(self.bot.i18n.get("premium_reset_avatar", lang)) # Re-use message or add new one
            except Exception:
                pass # Fail silently or log if needed

            changes.append(self.bot.i18n.get("premium_reset_themes", lang))
            return await ctx.send("\n".join(changes))

        # 2. Nickname
        if nickname:
            try:
                await ctx.guild.me.edit(nick=nickname)
                changes.append(self.bot.i18n.get("premium_set_nickname", lang, name=nickname))
            except discord.Forbidden:
                changes.append(self.bot.i18n.get("premium_reset_nickname_err", lang))
            except Exception as e:
                changes.append(f"❌ Failed to change Nickname: {e}")

        # 3. Bot Avatar
        if avatar:
            if not avatar.content_type.startswith('image/'):
                changes.append(self.bot.i18n.get("premium_invalid_image", lang))
            else:
                try:
                    import base64
                    image_bytes = await avatar.read()
                    b64 = base64.b64encode(image_bytes).decode('ascii')
                    data_uri = f'data:{avatar.content_type};base64,{b64}'
                    
                    await self.bot.http.request(
                        discord.http.Route('PATCH', '/guilds/{guild_id}/members/@me', guild_id=guild_id),
                        json={'avatar': data_uri}
                    )
                    changes.append(self.bot.i18n.get("premium_set_avatar", lang))
                except Exception as e:
                    changes.append(f"⚠️ Failed to set Bot Avatar: {e}")

        # 4. Bot Banner
        if bot_banner:
            if not bot_banner.content_type.startswith('image/'):
                changes.append(self.bot.i18n.get("premium_invalid_image", lang))
            else:
                try:
                    import base64
                    image_bytes = await bot_banner.read()
                    b64 = base64.b64encode(image_bytes).decode('ascii')
                    data_uri = f'data:{bot_banner.content_type};base64,{b64}'
                    
                    await self.bot.http.request(
                        discord.http.Route('PATCH', '/guilds/{guild_id}/members/@me', guild_id=guild_id),
                        json={'banner': data_uri}
                    )
                    changes.append(self.bot.i18n.get("premium_set_bot_banner", lang)) 
                except Exception as e:
                    # Often fails if server is not boosted enough, but bot profile banners might work regardless depending on bot/user flags
                    changes.append(f"⚠️ Failed to set Bot Banner: {e}")

        # 5. Music Image (Thumbnail)
        if image:
            if image.content_type.startswith("image/"):
                await collection_myasync.update_one({}, {"$set": {f"guilds.{guild_id}.premium_image": image.url}}, upsert=True)
                changes.append(self.bot.i18n.get("premium_set_music_logo", lang))
            else:
                changes.append(self.bot.i18n.get("premium_invalid_image", lang))

        # 5. Music Banner
        if banner:
            if banner.content_type.startswith("image/"):
                await collection_myasync.update_one({}, {"$set": {f"guilds.{guild_id}.premium_banner": banner.url}}, upsert=True)
                changes.append(self.bot.i18n.get("premium_set_music_banner", lang))
            else:
                changes.append(self.bot.i18n.get("premium_invalid_image", lang))

        # 6. Color
        if color:
            import re
            match = re.search(r'^#(?:[0-9a-fA-F]{3}){1,2}$', color)
            if match:
                # Store as int
                color_int = int(color.lstrip('#'), 16)
                await collection_myasync.update_one({}, {"$set": {f"guilds.{guild_id}.color": color_int}}, upsert=True)
                changes.append(self.bot.i18n.get("premium_set_color", lang, color=color))
            else:
                changes.append(self.bot.i18n.get("premium_invalid_hex", lang))

        if not changes:
            await ctx.send(self.bot.i18n.get("premium_no_changes", lang), ephemeral=True)
        else:
            await ctx.send("\n".join(changes))
            # Trigger update if playing
            await self._update_controller_if_playing(guild_id)

    # Removed redundant resettheme command as branding includes reset functionality with strict checks.

async def setup(bot: Cyori):
    await bot.add_cog(Premium(bot))
