"""Telegram channel for Longrun — one bot, one dedicated session, full parity.

A Telegram user DMs the bot; the message becomes a turn of the Longrun session
`telegram` (the SAME chat engine the WebUI drives), and the answer — plus tool
activity and approval prompts, with inline buttons — comes back on Telegram. The
session is a TWIN of the Architect A1 (same capabilities and authorisations, so
every architectural change to the Architect applies here automatically) but keeps
its OWN transcript and, unlike the Architect, CAN be deleted (deleting it clears
the binding and the channel must be re-onboarded).

Entry points used elsewhere in the codebase (all cheap; heavy modules import
lazily inside the functions):

    status()                       channel + bot + pairing state for the UI/diagnostics
    start() / stop()               the in-process long-poll thread (boot / shutdown)
    setup(token, owner_chat_id=None)  onboarding: validate, persist, create the session
    pair(code) / unpair(chat_id)   the OpenClaw-style pairing gate
    reconnect()                    re-read the environment and re-arm the channel
    on_session_deleted(sid)        the bound session was deleted ⇒ re-onboarding
    commands()                     the native `/` menu, from the ONE slash catalogue
"""
from __future__ import annotations

SESSION_ID = "telegram"
TITLE = "Telegram"


def _channel():
    from longrun.core.telegram import channel
    return channel


def status():
    """The channel's live state (never raises)."""
    return _channel().status()


def start():
    """Arm the channel if a token is configured (idempotent, never raises)."""
    return _channel().start()


def stop():
    """Stop the long-poll thread (used on shutdown / session deletion)."""
    return _channel().stop()


def setup(token, owner_chat_id=None):
    """Onboarding: validate the token, persist it, create the bound session."""
    return _channel().setup(token, owner_chat_id=owner_chat_id)


def pair(code):
    """Approve a pending pairing code (authorise that chat)."""
    return _channel().pair(code)


def unpair(chat_id=None):
    """Revoke a chat's authorisation (all chats when `chat_id` is None)."""
    return _channel().unpair(chat_id)


def reconnect():
    """Re-read `TELEGRAM_BOT_TOKEN` and (re)arm the channel."""
    return _channel().reconnect()


def logout():
    """Forget the bot identity + pairing and stop: the channel needs re-onboarding."""
    return _channel().logout()


def on_session_deleted(sid):
    """Hook: when the bound session is deleted, clear the binding."""
    return _channel().on_session_deleted(sid)


def commands():
    """The native Telegram command menu, derived from `core.slash`."""
    return _channel().commands()
