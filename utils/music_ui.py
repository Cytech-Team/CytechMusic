import discord
import time
from cytechlink.objects import Track
from cytechlink.formatter import decode
from cytechlink.enums import LoopType
from bot import Cyori, db_manager

loop_emoji = {
    "Off": "🚫",
    "Track": "<:repeatonce:1416275503840624670>",
    "Queue": "<:repeat:1416274830851965012>",
}


async def safe_get_guild_data(guild_id: str):
    """Return guild_data dict guaranteed to exist in DB (and ensure DB upsert)."""
    data = await db_manager.get_guild(guild_id)
    if not data:
        update_dict = {
            "autoplay": False,
            "24/7": False,
            "channel_id": None,
            "queue_embed_id": None,
            "play_embed_id": None,
            "dj_role": None,
            "dj_mode": False,
            "vote_mode": False,
        }
        await db_manager.update_guild(guild_id, update_dict)
        return update_dict
    return data


async def safe_delete(msg):
    if not msg or not msg.guild:
        return None
    guild_data: dict = await safe_get_guild_data(str(msg.guild.id))
    if guild_data:
        if (
            guild_data.get("play_embed_id") == msg.id
            or guild_data.get("queue_embed_id") == msg.id
        ):
            return None

    try:
        return await msg.delete()
    except Exception:
        return None


async def safe_call(func):
    try:
        return await func()
    except Exception:
        return None


async def safe_fetch_message(bot: Cyori, channel_id: int, message_id: int):
    """Fetch channel and message safely, return (channel, message) or (None, None)"""
    try:
        channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
        if not channel:
            return None, None
        message = await channel.fetch_message(message_id)
        return channel, message
    except Exception as e:
        print(
            f"safe_fetch_message failed: channel_id={channel_id} message_id={message_id} -> {e}"
        )
        return None, None


def safe_text(value: str):
    """Try to ensure string is printable; keep as-is if not possible."""
    if value is None:
        return ""
    try:
        return value.encode("utf-16", "surrogatepass").decode("utf-16")
    except Exception:
        return str(value)


def loop_mode_to_str(mode):
    if mode is None:
        return "Off"
    try:
        if mode is LoopType.track:
            return "Track"
        if mode is LoopType.queue:
            return "Queue"
    except Exception:
        pass
    return "Off"


def loop_emoji_safe(mode_str):
    try:
        return loop_emoji.get(mode_str, "")
    except Exception:
        return ""


async def save_data_247(guild_id, key):
    await db_manager.update_guild(guild_id, {"24/7": key})


async def save_data_autoplay(guild_id, key):
    await db_manager.update_guild(guild_id, {"autoplay": key})


class Tracks(discord.ui.Select):
    def __init__(self, player, author):
        self.player = player
        self.author: discord.Member = author

        options = []
        for index, tracks in enumerate(self.player.queue.tracks(), start=1):
            track: Track = Track(
                track_id=tracks.track_id,
                info=decode(tracks.track_id),
                requester=tracks.requester,
            )
            if index > 10:
                break
            try:
                options.append(
                    discord.SelectOption(
                        label=f"{index}. {track.title[:40].encode('utf-16', 'surrogatepass').decode('utf-16')}",
                        description=f"{track.author[:30].encode('utf-16', 'surrogatepass').decode('utf-16')} · "
                        + ("Live" if track.is_stream else track.formatted_length),
                    )
                )
            except Exception:
                options.append(
                    discord.SelectOption(
                        label=f"{index}. {track.title[:40]}",
                        description=f"{track.author[:30]} · "
                        + ("Live" if track.is_stream else track.formatted_length),
                    )
                )

        # Cannot query client DB directly in init, getting lang properly handled later
        lang = "th"

        super().__init__(
            placeholder=self.player.bot.i18n.get("select_skip_placeholder", lang),
            min_values=1,
            max_values=1,
            options=options,
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        await interaction.response.defer(thinking=True, ephemeral=True)
        if interaction.user != self.author:
            if not self.player:
                return await interaction.followup.send(
                    "No player has found on this server.", ephemeral=True
                )
            if not await self.player.is_privileged(interaction.user):
                await interaction.followup.send(
                    content="You don't have permission to press this button.",
                    ephemeral=True,
                )
                return False
        return True

    async def callback(self, interaction: discord.Interaction):
        if not self.player:
            return await interaction.followup.send(
                "No player has found on this server.", ephemeral=True
            )
        lang = await self.player.bot.get_lang(interaction.guild.id)
        try:
            index = int(self.values[0].split(". ")[0])
            if index < 1:
                index = 1
            self.player.queue.skipto(index)
            await self.player.stop()
            await interaction.followup.send(
                content=self.player.bot.i18n.get(
                    "msg_skip_to", lang, title=self.values[0]
                ),
                ephemeral=True,
            )
        except Exception as e:
            await interaction.followup.send(
                content=f"Error skipping: {e}", ephemeral=True
            )


class VolumeModal(discord.ui.Modal, title="🔊 Volume Control"):
    volume = discord.ui.TextInput(
        label="Enter volume (0-100)",
        placeholder="Example: 75",
        required=True,
        max_length=3,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            vol = int(self.volume.value)
            if vol < 0 or vol > 100:
                await interaction.response.send_message(
                    "❌ Please enter a number between 0 and 150.", ephemeral=True
                )
                self.result = None
            else:
                self.result = vol
                await interaction.response.defer(ephemeral=True)
        except ValueError:
            await interaction.response.send_message(
                "❌ Invalid input. Please enter a number.", ephemeral=True
            )
            self.result = None
        finally:
            self.stop()


class MusicControls(discord.ui.View):
    def __init__(self, player, author) -> None:
        super().__init__(timeout=None)
        self.player = player
        self.author: discord.Member = author
        if not player.queue.is_empty:
            self.add_item(Tracks(self.player, self.author))
        self._current_embed = None
        self.update_all_labels()

    def update_all_labels(self):
        lang = "th"  # fallback initialization lang

        for item in self.children:
            if item.custom_id == "play_pause_button":
                item.emoji = (
                    "<:play:1416273270692515940>"
                    if self.player.is_paused
                    else "<:pause:1416275225179459594>"
                )
                item.style = (
                    discord.ButtonStyle.blurple
                    if self.player.is_paused
                    else discord.ButtonStyle.gray
                )
            elif item.custom_id == "loop_button":
                loop_mode = self.player.queue._repeat.mode
                if loop_mode is LoopType.off:
                    item.emoji = "<:repeat:1416274830851965012>"
                    item.label = self.player.bot.i18n.get("loop_mode_queue", lang)
                    item.style = discord.ButtonStyle.blurple
                elif loop_mode is LoopType.queue:
                    item.emoji = "<:repeatonce:1416275503840624670>"
                    item.label = self.player.bot.i18n.get("loop_mode_track", lang)
                    item.style = discord.ButtonStyle.blurple
                else:
                    item.emoji = "<:repeat:1416274830851965012>"
                    item.label = self.player.bot.i18n.get("loop_disable", lang)
                    item.style = discord.ButtonStyle.gray
            elif item.custom_id == "volume_button":
                item.label = self.player.bot.i18n.get(
                    "vol_level", lang, volume=self.player.volume
                )
            elif item.custom_id == "autoplay_button":
                item.style = (
                    discord.ButtonStyle.blurple
                    if self.player.autoplay
                    else discord.ButtonStyle.gray
                )
            elif item.custom_id == "playforever_button":
                item.style = (
                    discord.ButtonStyle.blurple
                    if self.player.mode247
                    else discord.ButtonStyle.gray
                )
            elif item.custom_id == "random_button":
                item.label = self.player.bot.i18n.get("btn_random", lang)

    async def update_label(self, message: discord.Message):
        self.update_all_labels()
        await self.player.update_controller(force=True)

    async def on_interaction(self, interaction: discord.Interaction):
        await super().on_interaction(interaction)
        await self.update_label(interaction.message)

    async def check_vote(self, user_id: int) -> bool:
        try:
            is_premium = False
            if hasattr(self.player.bot, "is_premium"):
                is_premium = await self.player.bot.is_premium(user_id)

            if is_premium:
                return True

            has_voted = await self.player.bot.check_vote(user_id, self.player.guild.id)
            return has_voted
        except Exception as e:
            print(f"Error checking vote: {e}")
            return False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        custom_id = interaction.data.get("custom_id")
        if custom_id != "volume_button":
            if not interaction.response.is_done():
                try:
                    await interaction.response.defer(thinking=True, ephemeral=True)
                except Exception:
                    pass

        if not self.player:
            await interaction.followup.send(
                "❌ | No player has been found on this server.", ephemeral=True
            )
            return False

        if interaction.user != self.author:
            pass

        return True

    @discord.ui.button(
        emoji="<:stop:1416272736552226908>",
        custom_id="stop_button",
        style=discord.ButtonStyle.red,
    )
    async def stop_button_callback(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        lang = await self.player.bot.get_lang(interaction.guild.id)

        if await self.player.is_privileged(interaction.user):
            await self.player.teardown()
            await interaction.followup.send(
                self.player.bot.i18n.get("msg_stop", lang), ephemeral=True
            )
            return

        guild_data = await safe_get_guild_data(str(interaction.guild.id))
        vote_mode = guild_data.get("vote_mode", False)

        if not vote_mode:
            return await interaction.followup.send(
                self.player.bot.i18n.get("dj_required", lang), ephemeral=True
            )

        if interaction.user.id in self.player.stop_votes:
            return await interaction.followup.send(
                self.player.bot.i18n.get("vote_already", lang), ephemeral=True
            )

        self.player.stop_votes.add(interaction.user.id)
        required = self.player.required(leave=True)
        current_votes = len(self.player.stop_votes)

        if current_votes >= required:
            await self.player.teardown()
            await interaction.followup.send(
                self.player.bot.i18n.get("msg_stop", lang), ephemeral=True
            )
        else:
            await interaction.followup.send(
                self.player.bot.i18n.get(
                    "vote_detected", lang, current=current_votes, required=required
                ),
                ephemeral=True,
            )

    @discord.ui.button(
        emoji="<:previous:1416273087783243806>",
        custom_id="back_button",
        style=discord.ButtonStyle.gray,
    )
    async def back_button_callback(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        lang = await self.player.bot.get_lang(interaction.guild.id)
        if self.player.queue.history == 0:
            return await interaction.followup.send(
                self.player.bot.i18n.get("msg_no_history", lang), ephemeral=True
            )

        if await self.player.is_privileged(interaction.user):
            current = self.player.current
            self.player.queue.backto(2)
            await self.player.stop()
            await interaction.followup.send(
                self.player.bot.i18n.get("msg_back_to", lang, title=current),
                ephemeral=True,
            )
            return

        guild_data = await safe_get_guild_data(str(interaction.guild.id))
        vote_mode = guild_data.get("vote_mode", False)

        if not vote_mode:
            return await interaction.followup.send(
                self.player.bot.i18n.get("dj_required", lang), ephemeral=True
            )

        if interaction.user.id in self.player.previous_votes:
            return await interaction.followup.send(
                self.player.bot.i18n.get("vote_already", lang), ephemeral=True
            )

        self.player.previous_votes.add(interaction.user.id)
        required = self.player.required()
        current_votes = len(self.player.previous_votes)

        if current_votes >= required:
            current = self.player.current
            self.player.queue.backto(2)
            await self.player.stop()
            await interaction.followup.send(
                self.player.bot.i18n.get("msg_back_to", lang, title=current),
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                self.player.bot.i18n.get(
                    "vote_detected", lang, current=current_votes, required=required
                ),
                ephemeral=True,
            )

    @discord.ui.button(
        emoji="<:pause:1416275225179459594>",
        custom_id="play_pause_button",
        style=discord.ButtonStyle.gray,
    )
    async def play_pause_button_callback(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        lang = await self.player.bot.get_lang(interaction.guild.id)

        if not await self.player.is_privileged(interaction.user):
            return await interaction.followup.send(
                self.player.bot.i18n.get("dj_required", lang), ephemeral=True
            )

        if self.player.is_paused:
            await self.player.set_pause(False, self.author)
            await interaction.followup.send(
                self.player.bot.i18n.get("msg_resume", lang), ephemeral=True
            )
            await self.update_label(interaction.message)
        else:
            await self.player.set_pause(True, self.author)
            await interaction.followup.send(
                self.player.bot.i18n.get("msg_pause", lang), ephemeral=True
            )
            await self.update_label(interaction.message)

    @discord.ui.button(
        emoji="<:next:1416273434865959045>",
        custom_id="skip_button",
        style=discord.ButtonStyle.gray,
    )
    async def skip_button_callback(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        lang = await self.player.bot.get_lang(interaction.guild.id)

        if await self.player.is_privileged(interaction.user):
            await self.player.stop()
            await interaction.followup.send(
                self.player.bot.i18n.get("skipped", lang, author=interaction.user),
                ephemeral=True,
            )
            return

        guild_data = await safe_get_guild_data(str(interaction.guild.id))
        vote_mode = guild_data.get("vote_mode", False)

        if not vote_mode:
            return await interaction.followup.send(
                self.player.bot.i18n.get("dj_required", lang), ephemeral=True
            )

        if interaction.user.id in self.player.skip_votes:
            return await interaction.followup.send(
                self.player.bot.i18n.get("vote_already", lang), ephemeral=True
            )

        self.player.skip_votes.add(interaction.user.id)
        required = self.player.required()
        current_votes = len(self.player.skip_votes)

        if current_votes >= required:
            await self.player.stop()
            await interaction.followup.send(
                self.player.bot.i18n.get("skipped", lang, author=interaction.user),
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                self.player.bot.i18n.get(
                    "vote_detected", lang, current=current_votes, required=required
                ),
                ephemeral=True,
            )

    @discord.ui.button(
        emoji="<:shuffle:1416273559923462277>",
        custom_id="shuffle_button",
        style=discord.ButtonStyle.gray,
    )
    async def shuffle_button_callback(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        lang = await self.player.bot.get_lang(interaction.guild.id)

        if not await self.player.is_privileged(interaction.user):
            return await interaction.followup.send(
                self.player.bot.i18n.get("dj_required", lang), ephemeral=True
            )

        queue = self.player.queue.tracks()
        if not queue:
            return await interaction.followup.send(
                self.player.bot.i18n.get("msg_shuffle_error", lang), ephemeral=True
            )
        await self.player.shuffle("queue", requester=interaction.user)
        await interaction.followup.send(
            self.player.bot.i18n.get("msg_shuffled", lang), ephemeral=True
        )

    @discord.ui.button(
        emoji="<:volume:1416274145762607238>",
        label="Level: 100%",
        custom_id="volume_button",
        style=discord.ButtonStyle.gray,
    )
    async def volume_button_callback(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        lang = await self.player.bot.get_lang(interaction.guild.id)

        if not await self.player.is_privileged(interaction.user):
            return await interaction.response.send_message(
                self.player.bot.i18n.get("dj_required", lang), ephemeral=True
            )

        modal = VolumeModal()
        await interaction.response.send_modal(modal)
        await modal.wait()

        if not hasattr(modal, "result") or modal.result is None:
            return

        volume = modal.result
        await self.player.set_volume(volume, interaction.user)

        lang = await self.player.bot.get_lang(interaction.guild.id)
        if volume == 0:
            await interaction.followup.send(
                self.player.bot.i18n.get("msg_muted", lang), ephemeral=True
            )
        else:
            await interaction.followup.send(
                self.player.bot.i18n.get(
                    "msg_vol_set_c", lang, volume=self.player.volume
                ),
                ephemeral=True,
            )

        await self.update_label(interaction.message)

    @discord.ui.button(
        emoji="<:repeat:1416274830851965012>",
        label="Disable",
        custom_id="loop_button",
        style=discord.ButtonStyle.gray,
    )
    async def loop_button_callback(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        lang = await self.player.bot.get_lang(interaction.guild.id)

        if not await self.player.is_privileged(interaction.user):
            return await interaction.followup.send(
                self.player.bot.i18n.get("dj_required", lang), ephemeral=True
            )

        loop_mode = self.player.queue._repeat.mode
        if loop_mode is LoopType.track:
            await self.player.set_repeat("off")
            await self.update_label(interaction.message)
            return await interaction.followup.send(
                f"🚫 | {self.player.bot.i18n.get('loop_mode_label', lang)}: {self.player.bot.i18n.get('loop_disable', lang)}",
                ephemeral=True,
            )
        elif loop_mode is LoopType.off:
            await self.player.set_repeat("queue")
            await self.update_label(interaction.message)
            return await interaction.followup.send(
                f"🔁 | {self.player.bot.i18n.get('loop_mode_label', lang)}: {self.player.bot.i18n.get('loop_mode_queue', lang)}",
                ephemeral=True,
            )
        else:
            await self.player.set_repeat("track")
            await self.update_label(interaction.message)
            return await interaction.followup.send(
                f"🔂 | {self.player.bot.i18n.get('loop_mode_label', lang)}: {self.player.bot.i18n.get('loop_mode_track', lang)}",
                ephemeral=True,
            )

    @discord.ui.button(
        emoji="<:playlist:1416274601851359395>",
        label="Autoplay",
        custom_id="autoplay_button",
        style=discord.ButtonStyle.gray,
    )
    async def autoplay_button_callback(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not await self.player.is_privileged(interaction.user, strict=True):
            return await interaction.followup.send(
                self.player.bot.i18n.get(
                    "dj_required", await self.player.bot.get_lang(interaction.guild.id)
                ),
                ephemeral=True,
            )

        can_use = await self.check_vote(interaction.user.id)

        if can_use:
            guild_data = await db_manager.get_guild(interaction.guild.id)
            key = guild_data.get("autoplay", False)

            key = not key
            await save_data_autoplay(interaction.guild.id, key)
            self.player.autoplay = key
            await self.update_label(interaction.message)

            lang = await self.player.bot.get_lang(interaction.guild.id)
            state = self.player.bot.i18n.get("enabled" if key else "disabled", lang)
            await interaction.followup.send(
                self.player.bot.i18n.get("msg_autoplay_bool", lang, state=state),
                ephemeral=True,
            )

            if not self.player.is_playing:
                await self.player.do_next()
        else:
            view = discord.ui.View()
            view.add_item(
                discord.ui.Button(
                    style=discord.ButtonStyle.link,
                    label="Vote",
                    url="https://top.gg/bot/1469606905948405833",
                )
            )
            view.add_item(
                discord.ui.Button(
                    style=discord.ButtonStyle.link,
                    label="Premium",
                    url="https://discord.gg/cytech",
                )
            )
            await interaction.followup.send(
                embed=discord.Embed(
                    title="Premium / Vote Required",
                    description="You must vote on Top.gg OR be a Premium user to use Autoplay.",
                    color=0xFFD700,
                ),
                view=view,
                ephemeral=True,
            )

    @discord.ui.button(
        label="⌛ 24/7", custom_id="playforever_button", style=discord.ButtonStyle.gray
    )
    async def playforever_button_callback(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not await self.player.is_privileged(interaction.user, strict=True):
            return await interaction.followup.send(
                self.player.bot.i18n.get(
                    "dj_required", await self.player.bot.get_lang(interaction.guild.id)
                ),
                ephemeral=True,
            )

        can_use = await self.check_vote(interaction.user.id)

        if can_use:
            guild_data = await db_manager.get_guild(interaction.guild.id)
            key = guild_data.get("24/7", False)

            key = not key
            await save_data_247(interaction.guild.id, key)
            self.player.mode247 = key
            await self.update_label(interaction.message)

            lang = await self.player.bot.get_lang(interaction.guild.id)
            state = self.player.bot.i18n.get("enabled" if key else "disabled", lang)
            await interaction.followup.send(
                self.player.bot.i18n.get("msg_247_bool", lang, state=state),
                ephemeral=True,
            )
        else:
            view = discord.ui.View()
            view.add_item(
                discord.ui.Button(
                    style=discord.ButtonStyle.link,
                    label="Vote",
                    url="https://top.gg/bot/1469606905948405833",
                )
            )
            view.add_item(
                discord.ui.Button(
                    style=discord.ButtonStyle.link,
                    label="Premium",
                    url="https://discord.gg/cytech",
                )
            )
            await interaction.followup.send(
                embed=discord.Embed(
                    title="Premium / Vote Required",
                    description="You must vote on Top.gg OR be a Premium user to use 24/7 Mode.",
                    color=0xFFD700,
                ),
                view=view,
                ephemeral=True,
            )

    @discord.ui.button(
        emoji="❤️",
        label="Save",
        custom_id="fav_button",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def fav_button_callback(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not self.player.current:
            return await interaction.followup.send(
                "❌ Nothing is playing.", ephemeral=True
            )

        track = self.player.current
        song_data = {
            "title": track.title,
            "uri": track.uri,
            "author": track.author,
            "identifier": track.identifier,
            "thumbnail": track.thumbnail,
            "length": track.length,
            "added_at": int(time.time()),
        }

        user_id = str(interaction.user.id)

        try:
            await db_manager.update_user_doc(
                user_id, {"$addToSet": {"favorites": song_data}}
            )

            await interaction.followup.send(
                f"❤️ **Saved to Collection:**\n[{track.title}]({track.uri})",
                ephemeral=True,
            )
        except Exception as e:
            print(f"Fav Error: {e}")
            await interaction.followup.send("❌ Failed to save track.", ephemeral=True)

    @discord.ui.button(
        emoji="🎲",
        label="Random",
        custom_id="random_button",
        style=discord.ButtonStyle.gray,
        row=2,
    )
    async def random_button_callback(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        lang = await self.player.bot.get_lang(interaction.guild.id)

        if not interaction.user.voice or not interaction.user.voice.channel:
            return await interaction.followup.send(
                self.player.bot.i18n.get("error_voice_required", lang), ephemeral=True
            )

        if not await self.player.is_privileged(interaction.user):
            return await interaction.followup.send(
                self.player.bot.i18n.get("dj_required", lang), ephemeral=True
            )

        import random

        search_query = (
            "ytmsearch:Trending Music Thailand"
            if lang == "th"
            else "ytmsearch:Trending Global Hits"
        )

        await interaction.followup.send(
            self.player.bot.i18n.get("msg_random_searching", lang), ephemeral=True
        )

        try:
            load_res = await self.player.node.get_tracks(
                search_query, requester=interaction.user
            )
            tracks = (
                load_res
                if isinstance(load_res, list)
                else getattr(load_res, "tracks", [])
            )

            if tracks:
                track = random.choice(tracks[:15])  # Pick from top 15
                await self.player.add_track(track)
                await interaction.followup.send(
                    self.player.bot.i18n.get(
                        "msg_random_selection", lang, title=track.title, uri=track.uri
                    ),
                    ephemeral=True,
                )

                if not self.player.is_playing:
                    await self.player.do_next()
                else:
                    await self.player.update_controller(force=True)
            else:
                await interaction.followup.send(
                    self.player.bot.i18n.get("msg_random_not_found", lang),
                    ephemeral=True,
                )
        except Exception as e:
            await interaction.followup.send(
                self.player.bot.i18n.get("msg_random_failed", lang, e=e), ephemeral=True
            )


class JukeboxIdleView(discord.ui.View):
    def __init__(self, player, bot=None, lang=None) -> None:
        super().__init__(timeout=None)
        self.player = player
        self.bot = bot
        self.lang = lang
        self.update_all_labels()

    def update_all_labels(self):
        bot = self.bot
        lang = self.lang or "th"
        if self.player:
            bot = bot or self.player.bot

        for item in self.children:
            if item.custom_id == "idle_random_button":
                if bot:
                    item.label = bot.i18n.get("btn_random", lang)
                else:
                    item.label = "สุ่มเพลง" if lang == "th" else "Random"

    @discord.ui.button(
        emoji="🎲",
        label="Random",
        custom_id="idle_random_button",
        style=discord.ButtonStyle.gray,
    )
    async def idle_random_button_callback(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not interaction.response.is_done():
            try:
                await interaction.response.defer(thinking=True, ephemeral=True)
            except Exception:
                pass

        bot = self.player.bot if self.player else interaction.client
        lang = await bot.get_lang(interaction.guild.id)

        if not interaction.user.voice or not interaction.user.voice.channel:
            return await interaction.followup.send(
                bot.i18n.get("error_voice_required", lang), ephemeral=True
            )

        player = self.player
        if not player:
            player = interaction.guild.voice_client
            if not player:
                try:
                    from cytechlink.player import connect_channel

                    player = await connect_channel(interaction)
                    self.player = player
                except Exception as e:
                    return await interaction.followup.send(
                        f"❌ Failed to join voice: {e}", ephemeral=True
                    )

        if not await player.is_privileged(interaction.user):
            return await interaction.followup.send(
                bot.i18n.get("dj_required", lang), ephemeral=True
            )

        import random

        search_query = (
            "ytmsearch:Trending Music Thailand"
            if lang == "th"
            else "ytmsearch:Trending Global Hits"
        )

        await interaction.followup.send(
            bot.i18n.get("msg_random_searching", lang), ephemeral=True
        )

        try:
            node = player.node
            load_res = await node.get_tracks(search_query, requester=interaction.user)
            tracks = (
                load_res
                if isinstance(load_res, list)
                else getattr(load_res, "tracks", [])
            )

            if tracks:
                track = random.choice(tracks[:15])  # Pick from top 15
                await player.add_track(track)
                await interaction.followup.send(
                    bot.i18n.get(
                        "msg_random_selection", lang, title=track.title, uri=track.uri
                    ),
                    ephemeral=True,
                )

                if not player.is_playing:
                    await player.do_next()
                else:
                    await player.update_controller(force=True)
            else:
                await interaction.followup.send(
                    bot.i18n.get("msg_random_not_found", lang), ephemeral=True
                )
        except Exception as e:
            await interaction.followup.send(
                bot.i18n.get("msg_random_failed", lang, e=e), ephemeral=True
            )
