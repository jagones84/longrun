"""Telegram Bot API client — stdlib only (urllib), token never logged.

The channel (`core/telegram/channel.py`) talks to Telegram through THIS module and
nothing else, exactly as `integrations/paperclip_adapter.py` owns the REST/SSE
client for Paperclip. Longrun ships stdlib-only, so there is no
`python-telegram-bot`: this is a thin, injectable wrapper over
`https://api.telegram.org/bot<TOKEN>/<method>`.

Rules this module enforces:

  * **The token travels only in the URL path** and never reaches an exception
    message, a log line or an event payload. Every error is sanitised by
    `_sanitize`, which also scrubs a token that slipped into a transport string.
  * **`opener` is injected** (defaults to `urllib.request.urlopen`) and called as
    `opener(request, timeout=...)`, so the acceptance test drives the whole channel
    offline with a fake Bot API and no network.
  * **A non-`ok` answer is a `TelegramError`** carrying Telegram's own `description`
    (bounded), never a raw body that could echo the request URL.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

#: Telegram's production endpoint. Overridable for a local probe server.
API_BASE = "https://api.telegram.org"
DEFAULT_TIMEOUT = 60.0
MAX_ERROR_CHARS = 400
#: A `getUpdates` long-poll must outlast the server-side timeout.
LONGPOLL_SLACK = 10.0


class TelegramError(RuntimeError):
    """A Bot API call failed — transport error or an `ok:false` answer."""


def _sanitize(text, token=""):
    """Collapse whitespace, cap length, and never leak the token."""
    out = " ".join(str(text or "").split())
    if token:
        out = out.replace(str(token), "<token>")
    return out[:MAX_ERROR_CHARS]


class BotClient:
    """One bot identity (`url` prefix holds the token). Stateless, thread-safe."""

    def __init__(self, token, opener=None, timeout=DEFAULT_TIMEOUT, base=API_BASE):
        self.token = str(token or "").strip()
        self.base = str(base or API_BASE).rstrip("/")
        self.timeout = float(timeout)
        self._opener = opener or urllib.request.urlopen

    # ------------------------------------------------------------- transport --
    def call(self, method, params=None, timeout=None):
        """POST one Bot API method; return `result` or raise `TelegramError`.

        `params=None` sends no body (methods like `getMe`/`deleteWebhook` take
        none); otherwise the body is JSON, which Telegram accepts alongside
        form-encoding and keeps the wrapper free of quoting bugs.
        """
        if not self.token:
            raise TelegramError("no bot token configured")
        url = "%s/bot%s/%s" % (self.base, self.token, method)
        data = None
        headers = {}
        if params is not None:
            data = json.dumps(params, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            response = self._opener(request, timeout=timeout or self.timeout)
        except urllib.error.HTTPError as exc:
            raise TelegramError(self._http_error(exc)) from None
        except BaseException as exc:  # timeout, DNS, connection reset
            raise TelegramError(_sanitize(
                "%s: %s" % (type(exc).__name__, exc), self.token)) from None
        try:
            raw = response.read()
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                try:
                    close()
                except BaseException:  # noqa: BLE001 — a broken socket must not mask the reply
                    pass
        try:
            doc = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError, AttributeError):
            raise TelegramError("unreadable Bot API reply") from None
        if not isinstance(doc, dict) or not doc.get("ok"):
            desc = doc.get("description") if isinstance(doc, dict) else ""
            raise TelegramError(_sanitize(desc or "Bot API refused the call", self.token))
        return doc.get("result")

    def _http_error(self, exc):
        """Telegram's own `description` (4xx carry a JSON body); never the URL."""
        try:
            body = exc.read()
            doc = json.loads(body.decode("utf-8"))
            desc = doc.get("description") if isinstance(doc, dict) else ""
        except Exception:  # noqa: BLE001 — a body we cannot read is not the point
            desc = ""
        code = getattr(exc, "code", "?")
        return _sanitize(desc or ("HTTP %s" % code), self.token)

    # --------------------------------------------------------------- methods --
    def get_me(self):
        return self.call("getMe")

    def delete_webhook(self, drop_pending=True):
        """Clear any webhook so long polling can never answer with HTTP 409."""
        return self.call("deleteWebhook", {"drop_pending_updates": bool(drop_pending)})

    def get_updates(self, offset=None, timeout=30, allowed_updates=None, limit=100):
        params = {"timeout": int(timeout), "limit": int(limit)}
        if offset is not None:
            params["offset"] = int(offset)
        if allowed_updates:
            params["allowed_updates"] = list(allowed_updates)
        return self.call("getUpdates", params,
                         timeout=float(timeout) + LONGPOLL_SLACK)

    def send_message(self, chat_id, text, reply_to=None, keyboard=None,
                     disable_preview=True, parse_mode=None):
        params = {"chat_id": chat_id, "text": str(text)[:4096],
                  "disable_web_page_preview": bool(disable_preview)}
        if reply_to is not None:
            params["reply_to_message_id"] = int(reply_to)
        if keyboard is not None:
            params["reply_markup"] = {"inline_keyboard": keyboard}
        if parse_mode:
            params["parse_mode"] = str(parse_mode)
        return self.call("sendMessage", params)

    def edit_message_text(self, chat_id, message_id, text, keyboard=None,
                          parse_mode=None):
        params = {"chat_id": chat_id, "message_id": int(message_id),
                  "text": str(text)[:4096],
                  "disable_web_page_preview": True}
        if keyboard is not None:
            params["reply_markup"] = {"inline_keyboard": keyboard}
        if parse_mode:
            params["parse_mode"] = str(parse_mode)
        return self.call("editMessageText", params)

    def send_chat_action(self, chat_id, action="typing"):
        return self.call("sendChatAction", {"chat_id": chat_id, "action": action})

    def answer_callback_query(self, callback_query_id, text=None, show_alert=False):
        params = {"callback_query_id": callback_query_id}
        if text:
            params["text"] = str(text)[:200]
        if show_alert:
            params["show_alert"] = True
        return self.call("answerCallbackQuery", params)

    def set_my_commands(self, commands, scope=None):
        """Publish the native command menu (list of `{command, description}`)."""
        params = {"commands": list(commands or [])}
        if scope is not None:
            params["scope"] = scope
        return self.call("setMyCommands", params)
