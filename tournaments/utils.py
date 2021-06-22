import asyncio
import logging
import discord

from achallonge import ChallongeException
from typing import Optional

from redbot.core import commands
from redbot.core.i18n import Translator
from redbot.core.utils.menus import start_adding_reactions
from redbot.core.utils.predicates import ReactionPredicate

from .objects import Tournament

log = logging.getLogger("red.laggron.tournaments")
_ = Translator("Tournaments", __file__)

COG_NAME = "Tournaments"


def credentials_check(command: commands.Command) -> commands.Command:
    """
    Verifies if context guild has challonge username and API key setup.
    """

    async def hook(cog, ctx: commands.Context):
        credentials = await cog.data.guild(ctx.guild).credentials()
        if any([x is None for x in credentials.values()]):
            raise commands.UserFeedbackCheckFailure(
                _(
                    "You need to set your Challonge credentials before using this "
                    "command! Use `{prefix}help challongeset` for more info."
                ).format(prefix=ctx.clean_prefix)
            )

    command.before_invoke(hook)
    return command


def only_phase(*allowed_phases):
    """
    Verifies if the current phrase of the tournament on the guild is in the list.
    """

    def wrapper(command: commands.Command) -> commands.Command:
        async def hook(cog, ctx: commands.Context):
            try:
                tournament = cog.tournaments[ctx.guild.id]
            except KeyError:
                raise commands.UserFeedbackCheckFailure(_("There's no ongoing tournament."))
            if not allowed_phases:
                return  # just checking if tournament exists
            if tournament.phase not in allowed_phases:
                raise commands.UserFeedbackCheckFailure(
                    _("This command cannot be executed right now.")
                )

        command.before_invoke(hook)
        return command

    return wrapper


def mod_or_to():
    async def check(ctx: commands.Context):
        if ctx.guild is None:
            return False
        if ctx.author.id == ctx.guild.owner_id:
            return True
        if ctx.author.guild_permissions.administrator:
            return True
        if await ctx.bot.is_mod(ctx.author):
            return True
        if await ctx.bot.is_owner(ctx.author):
            return True
        try:
            tournament: Tournament = ctx.cog.tournaments[ctx.guild.id]
        except KeyError:
            return False
        if tournament.to_role and tournament.to_role in ctx.author.roles:
            return True
        return False

    return commands.check(check)


async def async_http_retry(coro):
    """
    Retries the operation in case of a timeout.

    This function is made by Wonderfall.
    https://github.com/Wonderfall/ATOS/blob/cac2c561c8f1ce23277765bcb43cd6421129d8a1/utils/http_retry.py#L6
    """
    last_exc = None
    for retry in range(1):
        try:
            return await coro
        except ChallongeException as e:
            last_exc = e
            if "504" in str(e):  # Gateway timeout
                await asyncio.sleep(1 + retry)
            else:
                raise
        except asyncio.exceptions.TimeoutError as e:
            last_exc = e
            continue
    else:
        raise asyncio.TimeoutError from last_exc


async def prompt_yes_or_no(
    ctx: commands.Context,
    content: Optional[str] = None,
    *,
    embed: Optional[discord.Embed] = None,
    timeout: int = 30,
    delete_after: bool = True,
    negative_response: bool = True,
) -> bool:
    """
    Sends a message and waits for used confirmation, using buttons.

    Credit to TrustyJAID for the stuff with buttons. Source:
    https://github.com/TrustyJAID/Trusty-cogs/blob/f6ceb28ff592f664070a89282288452d615d7dc5/eventposter/eventposter.py#L750-L777

    Parameters
    ----------
    ctx: commands.Context
        Context of the command
    content: Union[str, discord.Embed]
        Either text or an embed to send.
    timeout: int
        Time before timeout. Defaults to 30 seconds.
    delete_after: bool
        Should the message be deleted after a positive response/timeout? Defaults to True.
    negative_response: bool
        If the bot should send "Cancelled." after a negative response. Defaults to True.

    Returns
    -------
    bool
        False if the user declined, if the request timed out, or if there are insufficient
        permissions, else True.
    """
    view = discord.ui.View()
    approve_button = discord.ui.Button(
        style=discord.ButtonStyle.green,
        emoji="\N{HEAVY CHECK MARK}\N{VARIATION SELECTOR-16}",
        custom_id=f"yes-{ctx.message.id}",
    )
    deny_button = discord.ui.Button(
        style=discord.ButtonStyle.red,
        emoji="\N{HEAVY MULTIPLICATION X}\N{VARIATION SELECTOR-16}",
        custom_id=f"no-{ctx.message.id}",
    )
    view.add_item(approve_button)
    view.add_item(deny_button)
    message = await ctx.send(content, embed=embed, view=view)

    def check_same_user(interaction):
        return interaction.user.id == ctx.author.id

    try:
        x = await ctx.bot.wait_for("interaction", check=check_same_user, timeout=timeout)
    except asyncio.TimeoutError:
        await ctx.send(_("Request timed out."))
        return False
    else:
        custom_id = x.data.get("custom_id")
        if custom_id == f"yes-{ctx.message.id}":
            return True
        if negative_response:
            await ctx.send(_("Cancelled."))
        return False
    finally:
        if delete_after:
            await message.delete()
        else:
            await message.edit(content=message.content, embed=embed, view=None)
