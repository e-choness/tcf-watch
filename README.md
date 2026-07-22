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

For Pushover instead: set `TCF_NOTIFIER=pushover` and the two Pushover keys.

## Deploy on GitHub Actions (recommended — no always-on machine)

1. Create a repo (private is fine) and push this project to it.
2. Repo → **Settings → Secrets and variables → Actions** → add:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
3. **Verify on your phone**: Actions tab → *Daily heartbeat* → **Run workflow**.
   You should get a message within a minute.
4. **Verify the scraper**: Actions tab → *Check TCF registration pages* → **Run workflow**.
   First run captures baselines and commits `state/*.json`; from then on, every hourly
   run notifies you of **any change** to the monitored sections (with a diff), and
   escalates December-2026 mentions to HIGH with hourly reminders.
5. When you get a HIGH alert and have registered: Actions tab → *Acknowledge alert* →
   **Run workflow** → pick the site. Reminders stop; any later page change re-arms them.

How the free-plan constraints are handled:

- **Minutes**: hourly checks + daily heartbeat ≈ 760 of your 2,000 free minutes/month
  on a private repo (`timeout-minutes: 5` caps runaway runs). Public repos have
  unlimited minutes if you ever want 30-min polling — but see politeness below.
- **Cron drift**: GitHub cron is best-effort and can run 5–30 min late. Schedules use
  odd minutes (`:23`, `:37`) to dodge peak congestion. Hourly granularity is fine —
  these registrations stay open for days, not minutes.
- **60-day auto-disable**: GitHub disables cron workflows in inactive repos. The
  heartbeat workflow makes a keepalive commit on the 1st of each month, and state
  commits count as activity too. If the daily heartbeat ever stops arriving,
  check the Actions tab first.
- **No disk**: state is committed back to the repo (`TCF_LEAN_STATE=1` strips
  per-run timestamps, so commits happen only when content or flags actually change —
  the commit history doubles as a changelog of what the sites did).

## Alternative: run locally with Docker

```bash
cp .env.example .env   # fill in credentials
docker compose build
docker compose run --rm tcf-watch test-notify   # two messages should hit your phone
docker compose run --rm tcf-watch snapshot      # inspect what's being monitored
docker compose up -d
```

Ack locally: `docker compose exec tcf-watch python -m tcfwatch ack vancouver`.

## Unit tests

```bash
docker run --rm -v "$PWD":/app -w /app python:3.12-slim bash -c \
  "pip install -q -r requirements-dev.txt && python -m pytest tests/ -q"
```

22+ tests cover: section extraction per site, EN/FR keyword variants (and non-matches like Dec 2025), first-run/unchanged/changed transitions, ack reset on new changes, failure-counter behavior, corrupt-state recovery, diff capping, lean-state stability (no spurious git commits), and both notifier payloads (mocked HTTP — no real messages sent).

## Ops notes

- **Politeness / ban risk**: hourly polling = 24 requests/day/site with an honest
  User-Agent — orders of magnitude below anything that triggers rate limiting.
  If you ever shorten the interval, stay above ~10 min; these are small nonprofit
  sites, and an IP block right before December is the worst possible failure mode.
  Note GitHub-hosted runners use shared IP ranges — one more reason to keep the
  interval generous.
- **Timing**: based on past patterns, registration for a December session typically opens ~3–5 weeks prior (early–mid November). The monitor is cheap to run from now, but November is when it matters.
- **JS-rendered content**: if `snapshot` shows the Edmonton table missing (rendered client-side), the fallback is that any change to the surrounding page still triggers a normal alert. If that proves too weak, swap `fetch()` for a Playwright-based fetch — the rest of the pipeline is unchanged.
- **First real validation**: per the Vancouver page, sessions are announced with registration dates roughly monthly — so within ~a few weeks of enabling this you should see a real "page changed" notification for an earlier session, confirming the pipeline end-to-end well before December.
