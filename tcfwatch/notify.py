"""Notification backends behind a single Notifier protocol.

Selected by TCF_NOTIFIER env var: "telegram" (default), "pushover",
or "console" (for local dev / tests without credentials).
"""

from __future__ import annotations

import logging
from typing import Protocol

import requests

from .config import Settings

log = logging.getLogger("tcfwatch.notify")


class Notifier(Protocol):
    def send(self, title: str, message: str, url: str | None = None, high: bool = False) -> bool:
        """Return True if the provider accepted the message."""
        ...


class ConsoleNotifier:
    def send(self, title: str, message: str, url: str | None = None, high: bool = False) -> bool:
        log.info("[NOTIFY%s] %s :: %s %s", " HIGH" if high else "", title, message, url or "")
        return True


class TelegramNotifier:
    API = "https://api.telegram.org"

    def __init__(self, settings: Settings, session: requests.Session | None = None):
        if not settings.telegram_token or not settings.telegram_chat_id:
            raise ValueError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set")
        self.token = settings.telegram_token
        self.chat_id = settings.telegram_chat_id
        self.timeout = settings.request_timeout
        self.session = session or requests.Session()

    def send(self, title: str, message: str, url: str | None = None, high: bool = False) -> bool:
        prefix = "\N{POLICE CARS REVOLVING LIGHT} " if high else "\N{BELL} "
        text = f"{prefix}<b>{title}</b>\n{message}"
        if url:
            text += f'\n<a href="{url}">Open registration page</a>'
        try:
            r = self.session.post(
                f"{self.API}/bot{self.token}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": False,
                },
                timeout=self.timeout,
            )
            ok = r.status_code == 200 and r.json().get("ok", False)
            if not ok:
                log.error("Telegram rejected message: %s %s", r.status_code, r.text[:300])
            return ok
        except requests.RequestException as e:
            log.error("Telegram send failed: %s", e)
            return False


class PushoverNotifier:
    API = "https://api.pushover.net/1/messages.json"

    def __init__(self, settings: Settings, session: requests.Session | None = None):
        if not settings.pushover_token or not settings.pushover_user:
            raise ValueError("PUSHOVER_APP_TOKEN and PUSHOVER_USER_KEY must be set")
        self.token = settings.pushover_token
        self.user = settings.pushover_user
        self.priority_high = settings.pushover_priority_high
        self.timeout = settings.request_timeout
        self.session = session or requests.Session()

    def send(self, title: str, message: str, url: str | None = None, high: bool = False) -> bool:
        payload: dict = {
            "token": self.token,
            "user": self.user,
            "title": title,
            "message": message,
            "priority": self.priority_high if high else 0,
        }
        if url:
            payload["url"] = url
            payload["url_title"] = "Open registration page"
        # priority 2 requires retry/expire
        if payload["priority"] == 2:
            payload["retry"] = 60
            payload["expire"] = 3600
        try:
            r = self.session.post(self.API, data=payload, timeout=self.timeout)
            ok = r.status_code == 200 and r.json().get("status") == 1
            if not ok:
                log.error("Pushover rejected message: %s %s", r.status_code, r.text[:300])
            return ok
        except requests.RequestException as e:
            log.error("Pushover send failed: %s", e)
            return False


def build_notifier(settings: Settings) -> Notifier:
    kind = settings.notifier.lower()
    if kind == "telegram":
        return TelegramNotifier(settings)
    if kind == "pushover":
        return PushoverNotifier(settings)
    if kind == "console":
        return ConsoleNotifier()
    raise ValueError(f"Unknown TCF_NOTIFIER: {settings.notifier!r}")
