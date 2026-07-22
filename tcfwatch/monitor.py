"""Fetch pages, extract the monitored section, detect changes, keep state.

State is a JSON file per site under TCF_STATE_DIR:
  {
    "hash": "...",            # sha256 of normalized section text
    "text": "...",            # last normalized section text (for diffs)
    "keyword_hit": false,      # whether keywords currently match
    "acked": false,            # user acknowledged current HIGH alert
    "consecutive_failures": 0,
    "last_ok_utc": "...",
    "last_notified_utc": "..."
  }
"""

from __future__ import annotations

import difflib
import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from .config import Settings, Site

log = logging.getLogger("tcfwatch.monitor")


# ---------- extraction ----------

def extract_section(html: str, site: Site) -> str:
    """Return normalized text of the first matching selector (fallback: body)."""
    soup = BeautifulSoup(html, "html.parser")
    for junk in soup(["script", "style", "noscript", "iframe"]):
        junk.decompose()

    node = None
    for sel in site.selectors:
        node = soup.select_one(sel)
        if node is not None:
            break
    if node is None:
        node = soup.body or soup

    text = node.get_text(separator="\n")
    return normalize(text)


def normalize(text: str) -> str:
    """Collapse whitespace and strip volatile noise so hashes are stable."""
    lines = []
    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if not line:
            continue
        # Drop lines that are pure timestamps/counters (common cache-busters)
        if re.fullmatch(r"(page generated|rendered|updated).*\d{4}.*", line, re.I):
            continue
        lines.append(line)
    return "\n".join(lines)


def keyword_hit(text: str, site: Site) -> bool:
    lowered = text.lower()
    return any(k in lowered for k in site.keywords)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def diff_snippet(old: str, new: str, max_lines: int = 12) -> str:
    """Human-readable summary of what changed, capped for notification size."""
    delta = [
        line
        for line in difflib.unified_diff(
            old.splitlines(), new.splitlines(), lineterm="", n=0
        )
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    ]
    if not delta:
        return "(content reordered)"
    shown = delta[:max_lines]
    more = len(delta) - len(shown)
    out = "\n".join(shown)
    if more > 0:
        out += f"\n… and {more} more changed lines"
    return out


# ---------- fetching ----------

def fetch(site: Site, settings: Settings, session: requests.Session | None = None) -> str:
    s = session or requests.Session()
    r = s.get(
        site.url,
        headers={
            "User-Agent": settings.user_agent,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-CA,en;q=0.9,fr;q=0.8",
        },
        timeout=settings.request_timeout,
    )
    r.raise_for_status()
    return r.text


# ---------- state ----------

def state_path(settings: Settings, site: Site) -> Path:
    return Path(settings.state_dir) / f"{site.key}.json"


def load_state(settings: Settings, site: Site) -> dict:
    p = state_path(settings, site)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError:
            log.warning("Corrupt state for %s; resetting", site.key)
    return {
        "hash": None,
        "text": "",
        "keyword_hit": False,
        "acked": False,
        "consecutive_failures": 0,
        "last_ok_utc": None,
        "last_notified_utc": None,
    }


def save_state(settings: Settings, site: Site, state: dict) -> None:
    p = state_path(settings, site)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(p)


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------- per-site check result ----------

@dataclass
class CheckResult:
    site: Site
    status: str          # "unchanged" | "changed" | "error" | "first_run"
    high: bool = False   # keyword matched → escalate
    detail: str = ""


def check_site(
    site: Site,
    settings: Settings,
    session: requests.Session | None = None,
) -> CheckResult:
    state = load_state(settings, site)
    try:
        html = fetch(site, settings, session)
    except requests.RequestException as e:
        state["consecutive_failures"] = state.get("consecutive_failures", 0) + 1
        save_state(settings, site, state)
        return CheckResult(site, "error", detail=f"{type(e).__name__}: {e}")

    text = extract_section(html, site)
    new_hash = sha(text)
    hit = keyword_hit(text, site)
    now = utcnow()

    prev_hash = state.get("hash")
    prev_text = state.get("text", "")
    state.update(
        {
            "hash": new_hash,
            "text": text,
            "keyword_hit": hit,
            "consecutive_failures": 0,
            "last_ok_utc": now,
        }
    )

    if prev_hash is None:
        state["acked"] = False
        save_state(settings, site, state)
        return CheckResult(site, "first_run", high=hit, detail=text[:400])

    if new_hash == prev_hash:
        save_state(settings, site, state)
        return CheckResult(site, "unchanged", high=hit and not state.get("acked", False))

    # Changed: reset ack so a new alert can nag again
    state["acked"] = False
    save_state(settings, site, state)
    return CheckResult(site, "changed", high=hit, detail=diff_snippet(prev_text, text))
