"""Defense-in-depth permission guards for sensitive hybrid settings commands."""
import discord


RESTRICTED_MANAGE_GUILD_COMMANDS = {"djrole", "djmode", "vote_mode"}


def _has_manage_guild(member) -> bool:
    permissions = getattr(member, "guild_permissions", None)
    return bool(
        permissions
        and (permissions.administrator or permissions.manage_guild)
    )


def install_settings_permission_guard(bot) -> None:
    """Protect both prefix and application-command entry points."""

    async def prefix_settings_check(ctx):
        command = getattr(ctx, "command", None)
        if not command or command.qualified_name not in RESTRICTED_MANAGE_GUILD_COMMANDS:
            return True
        if ctx.guild and _has_manage_guild(ctx.author):
            return True
        try:
            await ctx.send(
                "You need Manage Server permission to change this setting.",
                delete_after=10,
            )
        except Exception:
            pass
        return False

    bot.add_check(prefix_settings_check)

    previous_interaction_check = bot.tree.interaction_check

    async def secured_interaction_check(interaction: discord.Interaction) -> bool:
        if previous_interaction_check is not None:
            allowed = await previous_interaction_check(interaction)
            if not allowed:
                return False

        command = getattr(interaction, "command", None)
        if not command or command.qualified_name not in RESTRICTED_MANAGE_GUILD_COMMANDS:
            return True

        member = interaction.user
        if interaction.guild and _has_manage_guild(member):
            return True

        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "You need Manage Server permission to change this setting.",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    "You need Manage Server permission to change this setting.",
                    ephemeral=True,
                )
        except Exception:
            pass
        return False

    bot.tree.interaction_check = secured_interaction_check
