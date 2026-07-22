from __future__ import annotations

import json
from pathlib import Path

import pytest
import responses as responses_lib

from tcfwatch.config import SITES, Settings, Site
from tcfwatch.monitor import (
    check_site,
    diff_snippet,
    extract_section,
    keyword_hit,
    load_state,
    save_state,
)
from tcfwatch.notify import PushoverNotifier, TelegramNotifier

FIX = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIX / name).read_text()


def site_by_key(key: str) -> Site:
    return next(s for s in SITES if s.key == key)


@pytest.fixture
def settings(tmp_path):
    return Settings(state_dir=str(tmp_path))


# ---------- extraction ----------

class TestExtraction:
    def test_vancouver_main_selected_scripts_dropped(self):
        text = extract_section(fixture("vancouver_before.html"), site_by_key("vancouver"))
        assert "Next Session: October 2026" in text
        assert "var t=1" not in text
        # footer outside <main> excluded
        assert "Page generated" not in text

    def test_edmonton_datatable_selected(self):
        text = extract_section(fixture("edmonton_table.html"), site_by_key("edmonton"))
        assert "December 2026" in text
        assert "Sold out" in text

    def test_fallback_to_body_when_no_selector_matches(self):
        site = Site(key="x", name="X", url="http://x", selectors=("#nope",))
        text = extract_section("<html><body><p>hello world</p></body></html>", site)
        assert text == "hello world"

    def test_normalization_collapses_whitespace(self):
        site = Site(key="x", name="X", url="http://x")
        text = extract_section("<body><p>a    b\n\n\n c</p></body>", site)
        # in-line whitespace collapsed, blank lines dropped, line breaks kept
        assert text == "a b\nc"


# ---------- keywords ----------

class TestKeywords:
    @pytest.mark.parametrize(
        "phrase",
        ["December 2026", "décembre 2026", "DEC 2026", "session 2026-12 open"],
    )
    def test_variants_hit(self, phrase):
        assert keyword_hit(f"registration {phrase}", site_by_key("calgary"))

    def test_no_hit_on_other_months(self):
        text = extract_section(fixture("calgary_no_dec.html"), site_by_key("calgary"))
        assert not keyword_hit(text, site_by_key("calgary"))

    def test_no_hit_on_dec_2025(self):
        assert not keyword_hit("December 2025 session", site_by_key("calgary"))


# ---------- change detection ----------

class TestChangeDetection:
    def _mock_get(self, rsps, site: Site, body: str, status: int = 200):
        rsps.get(site.url, body=body, status=status)

    def test_first_run_then_unchanged_then_changed(self, settings):
        site = site_by_key("vancouver")
        with responses_lib.RequestsMock() as rsps:
            self._mock_get(rsps, site, fixture("vancouver_before.html"))
            assert check_site(site, settings).status == "first_run"
        with responses_lib.RequestsMock() as rsps:
            self._mock_get(rsps, site, fixture("vancouver_before.html"))
            assert check_site(site, settings).status == "unchanged"
        with responses_lib.RequestsMock() as rsps:
            self._mock_get(rsps, site, fixture("vancouver_after.html"))
            res = check_site(site, settings)
        assert res.status == "changed"
        assert res.high is True  # December 2026 appeared
        assert "December 2026" in res.detail

    def test_change_resets_ack(self, settings):
        site = site_by_key("vancouver")
        with responses_lib.RequestsMock() as rsps:
            self._mock_get(rsps, site, fixture("vancouver_before.html"))
            check_site(site, settings)
        state = load_state(settings, site)
        state["acked"] = True
        save_state(settings, site, state)
        with responses_lib.RequestsMock() as rsps:
            self._mock_get(rsps, site, fixture("vancouver_after.html"))
            check_site(site, settings)
        assert load_state(settings, site)["acked"] is False

    def test_fetch_error_increments_counter(self, settings):
        site = site_by_key("calgary")
        for expected in (1, 2, 3):
            with responses_lib.RequestsMock() as rsps:
                self._mock_get(rsps, site, "boom", status=503)
                res = check_site(site, settings)
            assert res.status == "error"
            assert load_state(settings, site)["consecutive_failures"] == expected

    def test_success_resets_failure_counter(self, settings):
        site = site_by_key("calgary")
        with responses_lib.RequestsMock() as rsps:
            self._mock_get(rsps, site, "x", status=500)
            check_site(site, settings)
        with responses_lib.RequestsMock() as rsps:
            self._mock_get(rsps, site, fixture("calgary_no_dec.html"))
            check_site(site, settings)
        assert load_state(settings, site)["consecutive_failures"] == 0

    def test_state_survives_corrupt_file(self, settings):
        site = site_by_key("calgary")
        p = Path(settings.state_dir) / f"{site.key}.json"
        p.write_text("{not json")
        state = load_state(settings, site)
        assert state["hash"] is None  # clean reset, no crash


class TestDiff:
    def test_diff_shows_added_and_removed(self):
        d = diff_snippet("a\nb\nc", "a\nB\nc")
        assert "-b" in d and "+B" in d

    def test_diff_caps_length(self):
        old = "\n".join(f"line{i}" for i in range(100))
        d = diff_snippet(old, "totally different")
        assert "more changed lines" in d


# ---------- notifiers ----------

class TestTelegram:
    def _settings(self, tmp_path):
        return Settings(
            state_dir=str(tmp_path),
            telegram_token="123:abc",
            telegram_chat_id="42",
        )

    def test_payload_and_success(self, tmp_path):
        with responses_lib.RequestsMock() as rsps:
            rsps.post(
                "https://api.telegram.org/bot123:abc/sendMessage",
                json={"ok": True},
            )
            n = TelegramNotifier(self._settings(tmp_path))
            assert n.send("T", "msg", url="https://x.example", high=True) is True
            body = json.loads(rsps.calls[0].request.body)
        assert body["chat_id"] == "42"
        assert "T" in body["text"] and "https://x.example" in body["text"]

    def test_api_rejection_returns_false(self, tmp_path):
        with responses_lib.RequestsMock() as rsps:
            rsps.post(
                "https://api.telegram.org/bot123:abc/sendMessage",
                json={"ok": False}, status=400,
            )
            n = TelegramNotifier(self._settings(tmp_path))
            assert n.send("T", "msg") is False

    def test_missing_creds_raise(self, tmp_path):
        with pytest.raises(ValueError):
            TelegramNotifier(Settings(state_dir=str(tmp_path)))


class TestPushover:
    def _settings(self, tmp_path, prio=1):
        return Settings(
            state_dir=str(tmp_path),
            pushover_token="app", pushover_user="usr",
            pushover_priority_high=prio,
        )

    def test_high_priority_set(self, tmp_path):
        with responses_lib.RequestsMock() as rsps:
            rsps.post(PushoverNotifier.API, json={"status": 1})
            n = PushoverNotifier(self._settings(tmp_path))
            assert n.send("T", "m", high=True) is True
            assert "priority=1" in rsps.calls[0].request.body

    def test_emergency_priority_adds_retry_expire(self, tmp_path):
        with responses_lib.RequestsMock() as rsps:
            rsps.post(PushoverNotifier.API, json={"status": 1})
            n = PushoverNotifier(self._settings(tmp_path, prio=2))
            n.send("T", "m", high=True)
            body = rsps.calls[0].request.body
        assert "retry=60" in body and "expire=3600" in body


# ---------- GitHub Actions (lean state) mode ----------

class TestLeanState:
    def test_lean_state_omits_timestamps(self, tmp_path):
        settings = Settings(state_dir=str(tmp_path), lean_state=True)
        site = site_by_key("vancouver")
        save_state(settings, site, {
            "hash": "h", "text": "t", "keyword_hit": False, "acked": False,
            "consecutive_failures": 0,
            "last_ok_utc": "2026-07-22T00:00:00+00:00",
            "last_notified_utc": "2026-07-22T00:00:00+00:00",
        })
        raw = json.loads((Path(settings.state_dir) / "vancouver.json").read_text())
        assert "last_ok_utc" not in raw and "last_notified_utc" not in raw
        assert raw["hash"] == "h"

    def test_lean_state_stable_across_identical_runs(self, tmp_path):
        """Two polls of identical content must write byte-identical state
        (so the Actions workflow makes no commit)."""
        settings = Settings(state_dir=str(tmp_path), lean_state=True)
        site = site_by_key("vancouver")
        body = fixture("vancouver_before.html")
        p = Path(settings.state_dir) / "vancouver.json"
        with responses_lib.RequestsMock() as rsps:
            rsps.get(site.url, body=body)
            check_site(site, settings)
        first = p.read_bytes()
        with responses_lib.RequestsMock() as rsps:
            rsps.get(site.url, body=body)
            check_site(site, settings)
        assert p.read_bytes() == first

    def test_default_mode_keeps_timestamps(self, tmp_path):
        settings = Settings(state_dir=str(tmp_path))
        site = site_by_key("vancouver")
        with responses_lib.RequestsMock() as rsps:
            rsps.get(site.url, body=fixture("vancouver_before.html"))
            check_site(site, settings)
        raw = json.loads((Path(settings.state_dir) / "vancouver.json").read_text())
        assert raw["last_ok_utc"] is not None
