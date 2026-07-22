"""Site definitions and runtime configuration.

Each site entry defines:
  - url: page to poll
  - selectors: CSS selectors tried in order; first match wins. The matched
    element's text is the "monitored section". Falls back to <body>.
  - keywords: if ANY keyword (case-insensitive) appears in the monitored
    section, the alert is escalated to HIGH (registration likely open for
    the target window). Otherwise a plain "page changed" alert is sent.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Site:
    key: str
    name: str
    url: str
    selectors: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()


# Keywords that indicate the December-2026 window is being referenced.
# French + English variants; sites mix languages.
DEC_2026_KEYWORDS: tuple[str, ...] = (
    "december 2026",
    "décembre 2026",
    "decembre 2026",
    "dec 2026",
    "déc 2026",
    "12/2026",
    "2026-12",
)

SITES: tuple[Site, ...] = (
    Site(
        key="calgary",
        name="AF Calgary",
        url="https://www.afcalgary.ca/exams/tcf/registration-process/",
        # WordPress site; main content column. Verify with `tcfwatch snapshot`.
        selectors=("main", "article", "#content", ".entry-content"),
        keywords=DEC_2026_KEYWORDS,
    ),
    Site(
        key="edmonton",
        name="AF Edmonton",
        url="https://www.afedmonton.com/en/exams/tcf/?s8-datatable1_rows=75",
        # Session list rendered in a datatable widget.
        selectors=(
            "[id*='datatable']",
            "table",
            "main",
            "#content",
        ),
        keywords=DEC_2026_KEYWORDS,
    ),
    Site(
        key="vancouver",
        name="AF Vancouver",
        url="https://www.alliancefrancaise.ca/en/language/exams/tcf-canada/",
        # "Next sessions" block lives in the main content region.
        selectors=("main", "article", "#content", ".content"),
        keywords=DEC_2026_KEYWORDS,
    ),
)


@dataclass(frozen=True)
class Settings:
    notifier: str = os.getenv("TCF_NOTIFIER", "telegram")  # telegram | pushover | console
    poll_seconds: int = int(os.getenv("TCF_POLL_SECONDS", "1800"))  # 30 min
    renotify_seconds: int = int(os.getenv("TCF_RENOTIFY_SECONDS", "900"))  # 15 min nag
    state_dir: str = os.getenv("TCF_STATE_DIR", "/data")
    fail_alert_threshold: int = int(os.getenv("TCF_FAIL_THRESHOLD", "4"))
    heartbeat_hour_utc: int = int(os.getenv("TCF_HEARTBEAT_HOUR_UTC", "15"))
    user_agent: str = os.getenv(
        "TCF_USER_AGENT",
        "tcf-watch/1.0 (personal registration monitor; contact via repo)",
    )
    request_timeout: int = int(os.getenv("TCF_TIMEOUT", "30"))

    # Telegram
    telegram_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")

    # Pushover
    pushover_token: str = os.getenv("PUSHOVER_APP_TOKEN", "")
    pushover_user: str = os.getenv("PUSHOVER_USER_KEY", "")
    pushover_priority_high: int = int(os.getenv("PUSHOVER_PRIORITY_HIGH", "1"))


def load_settings() -> Settings:
    return Settings()
