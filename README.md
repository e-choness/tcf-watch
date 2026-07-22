# tcf-watch

Monitors TCF exam registration pages at Alliance Française **Calgary**, **Edmonton**, and **Vancouver**, and pushes a phone notification the moment the **December 2026** session appears — then keeps nagging every 15 minutes until you acknowledge.

## How it works

Every 30 minutes (configurable) it fetches each page, extracts the main content section, and:

1. **HIGH alert** — if any December-2026 keyword appears (`december 2026`, `décembre 2026`, `dec 2026`, `12/2026`, `2026-12`, EN+FR), you get an urgent notification with a direct link, repeated every `TCF_RENOTIFY_SECONDS` until you run `ack`.
2. **Change alert** — if the section changed but no keyword matched, you get a normal notification with a diff (catches "registration opens soon" announcements phrased unexpectedly).
3. **Broken-monitor alert** — if a site fails 4 fetches in a row (~2 h), you're told monitoring is down instead of it failing silently.
4. **Daily heartbeat** — one "still alive" message per day, so silence in December means *no news*, not *dead script*.

State (hashes, ack flags, failure counters) lives in a Docker volume, so restarts don't re-fire old alerts.

## Setup (Telegram, free)

1. In Telegram, message **@BotFather** → `/newbot` → copy the token.
2. Send your new bot any message, then open
   `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser and copy the `chat.id` value.
3. ```bash
   cp .env.example .env   # fill in TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID
   ```

For Pushover instead: set `TCF_NOTIFIER=pushover` and the two Pushover keys in `.env`.

## Verify it works on your phone (do this first)

```bash
docker compose build

# 1. Notification path — you should get TWO messages on your phone
#    (one normal, one high-priority) within seconds:
docker compose run --rm tcf-watch test-notify

# 2. Scraper path — prints what each site's extracted section looks like
#    and whether the Dec-2026 keyword currently matches. If a section looks
#    wrong/empty, adjust that site's `selectors` in tcfwatch/config.py:
docker compose run --rm tcf-watch snapshot
```

Then start it for real:

```bash
docker compose up -d
docker compose logs -f     # watch a couple of poll cycles
```

## When the alert fires

Tap the link in the notification, register, then silence the reminders:

```bash
docker compose exec tcf-watch python -m tcfwatch ack vancouver   # or calgary / edmonton
```

(Any subsequent page change automatically re-arms alerts.)

## Unit tests

```bash
docker run --rm -v "$PWD":/app -w /app python:3.12-slim bash -c \
  "pip install -q -r requirements-dev.txt && python -m pytest tests/ -q"
```

22 tests cover: section extraction per site, EN/FR keyword variants (and non-matches like Dec 2025), first-run/unchanged/changed transitions, ack reset on new changes, failure-counter behavior, corrupt-state recovery, diff capping, and both notifier payloads (mocked HTTP — no real messages sent).

## Ops notes

- **Politeness**: 30-min polling, honest User-Agent, one request per site per cycle. Don't crank `TCF_POLL_SECONDS` below ~600 — these are small nonprofit sites, and aggressive polling risks an IP block right when you need access.
- **Timing**: based on past patterns, registration for a December session typically opens ~3–5 weeks prior (early–mid November). The monitor is cheap to run from now, but November is when it matters.
- **JS-rendered content**: if `snapshot` shows the Edmonton table missing (rendered client-side), the fallback is that any change to the surrounding page still triggers a normal alert. If that proves too weak, swap `fetch()` for a Playwright-based fetch — the rest of the pipeline is unchanged.
- **Where to run**: any always-on Docker host (home server, NAS, $4 VPS). A laptop that sleeps will miss polls.
