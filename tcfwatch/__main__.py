"""CLI entry point.

Commands:
  run          continuous polling loop (default; use in Docker)
  once         single pass over all sites, then exit (good for cron)
  snapshot     fetch each site, print extracted section — verify selectors
  test-notify  send a test notification to your phone and exit
  ack SITE     acknowledge current HIGH alert for a site (stops the nag)

Exit codes for `once`: 0 = ok, 2 = at least one site errored.
"""

from __future__ import annotations

import logging
import sys
import time
from datetime import datetime, timezone

import requests

from .config import SITES, load_settings
from .monitor import CheckResult, check_site, load_state, save_state, utcnow
from .notify import Notifier, build_notifier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("tcfwatch")


def handle_result(res: CheckResult, notifier: Notifier, settings) -> None:
    site = res.site
    if res.status == "first_run":
        log.info("[%s] baseline captured (%d chars)%s",
                 site.key, len(res.detail), " — KEYWORD ALREADY PRESENT" if res.high else "")
        if res.high:
            _notify_high(res, notifier, settings)
        return

    if res.status == "unchanged":
        log.info("[%s] unchanged", site.key)
        if res.high:
            _maybe_renotify(res, notifier, settings)
        return

    if res.status == "changed":
        log.info("[%s] CHANGED (high=%s)", site.key, res.high)
        if res.high:
            _notify_high(res, notifier, settings)
        else:
            notifier.send(
                f"{site.name}: TCF page changed",
                f"The monitored section changed. Diff:\n{res.detail}"[:900],
                url=site.url,
                high=False,
            )
            _mark_notified(settings, site)
        return

    if res.status == "error":
        state = load_state(settings, site)
        fails = state.get("consecutive_failures", 0)
        log.warning("[%s] fetch error (%d consecutive): %s", site.key, fails, res.detail)
        if fails == settings.fail_alert_threshold:
            notifier.send(
                f"{site.name}: monitoring broken",
                f"{fails} consecutive fetch failures. Last error: {res.detail}"[:900],
                url=site.url,
                high=False,
            )


def _notify_high(res: CheckResult, notifier: Notifier, settings) -> None:
    site = res.site
    notifier.send(
        f"{site.name}: DEC 2026 TCF REGISTRATION",
        ("December 2026 keyword detected on the registration page. "
         "Go register NOW.\n\n" + res.detail)[:900],
        url=site.url,
        high=True,
    )
    _mark_notified(settings, site)


def _maybe_renotify(res: CheckResult, notifier: Notifier, settings) -> None:
    """Nag: while keyword present and not acked, re-send every renotify_seconds."""
    site = res.site
    state = load_state(settings, site)
    if state.get("acked"):
        return
    last = state.get("last_notified_utc")
    if last:
        elapsed = (
            datetime.now(timezone.utc)
            - datetime.fromisoformat(last)
        ).total_seconds()
        if elapsed < settings.renotify_seconds:
            return
    notifier.send(
        f"{site.name}: Dec 2026 registration still open (reminder)",
        f"Keyword still present. Run `tcfwatch ack {site.key}` to silence.",
        url=site.url,
        high=True,
    )
    _mark_notified(settings, site)


def _mark_notified(settings, site) -> None:
    state = load_state(settings, site)
    state["last_notified_utc"] = utcnow()
    save_state(settings, site, state)


def run_once(notifier: Notifier, settings, session: requests.Session) -> int:
    rc = 0
    for site in SITES:
        res = check_site(site, settings, session)
        if res.status == "error":
            rc = 2
        handle_result(res, notifier, settings)
    return rc


def heartbeat(notifier: Notifier, settings, last_beat_day: str | None) -> str | None:
    """Send one 'still alive' message per UTC day at the configured hour."""
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    if now.hour >= settings.heartbeat_hour_utc and last_beat_day != today:
        notifier.send(
            "tcf-watch heartbeat",
            f"Monitor alive. {len(SITES)} sites polled every "
            f"{settings.poll_seconds // 60} min.",
        )
        return today
    return last_beat_day


def main(argv: list[str]) -> int:
    settings = load_settings()
    cmd = argv[0] if argv else "run"

    if cmd == "ack":
        if len(argv) < 2:
            print("usage: tcfwatch ack <calgary|edmonton|vancouver>")
            return 1
        target = argv[1]
        for site in SITES:
            if site.key == target:
                state = load_state(settings, site)
                state["acked"] = True
                save_state(settings, site, state)
                print(f"Acknowledged {site.key}; reminders silenced until next change.")
                return 0
        print(f"Unknown site: {target}")
        return 1

    if cmd == "snapshot":
        from .monitor import extract_section, fetch, keyword_hit
        session = requests.Session()
        for site in SITES:
            print(f"\n===== {site.name} ({site.url}) =====")
            try:
                text = extract_section(fetch(site, settings, session), site)
                print(text[:2000])
                print(f"\n[keyword hit: {keyword_hit(text, site)}]")
            except Exception as e:  # noqa: BLE001 — diagnostic command
                print(f"ERROR: {type(e).__name__}: {e}")
        return 0

    notifier = build_notifier(settings)

    if cmd == "heartbeat":
        ok = notifier.send(
            "tcf-watch heartbeat",
            f"Monitor alive on GitHub Actions. Watching {len(SITES)} sites hourly.",
        )
        print("heartbeat", "ok" if ok else "FAILED")
        return 0 if ok else 1

    if cmd == "test-notify":
        ok = notifier.send(
            "tcf-watch test",
            "If you can read this on your phone, notifications work. "
            "A HIGH-priority test follows.",
        )
        ok2 = notifier.send(
            "tcf-watch HIGH test",
            "This is what a registration-open alert looks like.",
            url=SITES[0].url,
            high=True,
        )
        print(f"normal={'ok' if ok else 'FAILED'} high={'ok' if ok2 else 'FAILED'}")
        return 0 if (ok and ok2) else 1

    session = requests.Session()

    if cmd == "once":
        return run_once(notifier, settings, session)

    if cmd == "run":
        log.info(
            "Starting loop: %d sites, every %ds, notifier=%s",
            len(SITES), settings.poll_seconds, settings.notifier,
        )
        last_beat_day: str | None = None
        while True:
            try:
                run_once(notifier, settings, session)
                last_beat_day = heartbeat(notifier, settings, last_beat_day)
            except Exception:  # noqa: BLE001 — loop must survive anything
                log.exception("Unexpected error in poll cycle")
            time.sleep(settings.poll_seconds)

    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
