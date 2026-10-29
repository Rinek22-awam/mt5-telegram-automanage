"""Minimal Telegram Bot API client (standard library only, no extra package)."""
import json
import logging
import urllib.error
import urllib.request

log = logging.getLogger(__name__)


class TelegramBot:
    def __init__(self, token: str, timeout: float = 15):
        self.base = f"https://api.telegram.org/bot{token}/"
        self.timeout = timeout

    def call(self, method: str, http_timeout: float = None, **params):
        data = json.dumps({k: v for k, v in params.items() if v is not None}).encode()
        req = urllib.request.Request(self.base + method, data=data,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=http_timeout or self.timeout) as r:
                body = json.load(r)
        except urllib.error.HTTPError as e:
            body = json.loads(e.read() or b"{}")
        if not body.get("ok"):
            raise RuntimeError(f"Telegram {method}: {body.get('description', 'error')}")
        return body["result"]

    def get_updates(self, offset: int, wait: int = 1):
        # a stuck request must not hold up the position guard for long
        return self.call("getUpdates", http_timeout=wait + 9, offset=offset, timeout=wait,
                         allowed_updates=["channel_post", "message", "callback_query"])

    def send(self, chat_id, text: str, buttons=None, reply_to=None):
        markup = None
        if buttons:
            markup = {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in row]
                                          for row in buttons]}
        return self.call("sendMessage", chat_id=chat_id, text=text, reply_markup=markup,
                         reply_to_message_id=reply_to)

    def edit(self, chat_id, message_id: int, text: str):
        return self.call("editMessageText", chat_id=chat_id, message_id=message_id, text=text)

    def answer(self, callback_id: str, text: str = ""):
        return self.call("answerCallbackQuery", callback_query_id=callback_id, text=text)
