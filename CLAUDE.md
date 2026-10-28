# RMV commute notifier

Personal commute and morning-brief notifier for one person in Frankfurt, run entirely on GitHub Actions.
It pings a phone through ntfy.sh and publishes two pages to GitHub Pages:
`/` (live commute page) and `/brief/` (morning brief).

**This repo and its Pages site are public.** Never commit an address, coordinates, key, token or the ntfy topic.
They live only in repo secrets.

## What runs when (Europe/Berlin)

| Time | What | Code |
|---|---|---|
| 06:45 Mon–Fri | Morning brief ping + `/brief/` page; then watches the 07:30 trips until 07:00 | `brief.py` (morning) |
| 07:00–09:00 Mon–Fri | Live session home → work: check every 5 min, hourly status ping, instant ping on new delay/cancellation, "time to go" ping ~10 min before the first clean trip from 07:30 | `commute.py --watch` |
| 15:00–17:30 Mon–Fri | Live session work → home (time-to-go only if `WORK_LEAVE` is set) | `commute.py --watch` |
| 20:00 daily | Evening heads-up for tomorrow, sent only when something needs doing. Before a workday it's the full preview (Sunday always sends). Before a weekend/holiday it only checks bins, reminders and DWD warnings | `brief.py` (evening) |

No brief and no live sessions on Hesse public holidays (`commute.holiday()`).

## How it gets triggered — important

**GitHub's own `schedule:` cron is not reliable for this repo.** In October 2026 it started runs 4–5 hours late (or not at all),
so every run missed its window and quit silently. The real trigger is **cron-job.org**:

- One job POSTs to `https://api.github.com/repos/smarthipad-ai/commute/actions/workflows/tick.yml/dispatches`
  with body `{"ref":"main"}` at **06:15, 14:15 and 19:15 Europe/Berlin** (crontab `15 6,14,19 * * *`).
- Headers: `Authorization: Bearer <fine-grained PAT>`, `Accept: application/vnd.github+json`, `Content-Type: application/json`, `User-Agent: cron-job-commute`.
- The PAT is fine-grained, scoped to this repo only, with **Actions: Read and write**. A 403 from the job means the token lost access or permission.
- `tick.yml` starts `brief.yml` (`auto=true`) and `commute.yml` (`session=true`). Each script decides from the **actual clock** what to do,
  so extra or late runs are harmless.
- The GitHub crons in `brief.yml` / `commute.yml` are kept only as a slow fallback.

Duplicate protection: `brief.py` tags each ping with a marker (`brief-YYYY-MM-DD`, `evening-YYYY-MM-DD`, `late-YYYY-MM-DD`)
and `sent_today()` checks ntfy's ~12 h message cache before sending. A morning run that starts after 09:00 sends one
"Morning brief skipped" notice instead of failing silently.

Workflow inputs: `brief.yml` `evening` (send heads-up now) and `auto` (behave like a scheduled run); `commute.yml` `session`
(run the live session for the current window). A plain manual dispatch (no inputs) sends one ping right away (`FORCE=true`).

## Files

- `commute.py` — RMV HAPI client (`hapi`, `trips`, `model`), live session (`watch`, `session`, `go_ping`), live page (`render`),
  shared helpers (`get` with retries, `now`, `hm`, `holiday`, `publish`). Also runs standalone: `--live`, `--back`, `--check`.
- `brief.py` — the brief. Each section is `f(d, evening) -> Sec | None` in `SECTIONS`; one failing section shows as "unavailable"
  instead of breaking the brief. `message()` builds the ping, `run()` builds and publishes the page, `main()` decides morning/evening.
- `brief_ui.py` — HTML for `/brief/`: renderers keyed by `Sec.kind` in `RENDER`, page order in `ORDER`, inline CSS/JS,
  home-screen app files (`app_files()`, generated PNG icons).
- `brief_data.py` — static content: quotes, German words of the day, bin colours.
- `.github/workflows/` — `tick.yml` (timer entry point), `brief.yml`, `commute.yml`.

## Secrets and variables

Required secrets: `RMV_KEY`, `NTFY_TOPIC`, `HOME_ADDR`, `WORK_ADDR`.
Optional secrets: `REMINDERS` (format in `brief.reminders()` docstring), `GCAL_ICS` (Google Calendar secret iCal URL),
`FES_ICS` (FrankfurtPlus bin calendar iCal), `WATCHLIST` (`SYMBOL:Label, …`, Yahoo Finance symbols),
`GEMINI_API_KEY` (free-tier Google AI Studio key for the news summary; without it the News card shows headlines only).
Optional repo variables: `FX` (default `INR`), `WORK_LEAVE` (e.g. `17:00`), `GEMINI_MODEL` (default `gemini-3.8-flash`,
falls back to `gemini-3.5-flash-lite`).
The user keeps reminders in a git-ignored local `reminders.txt` and uploads it with `gh secret set REMINDERS < reminders.txt`.

## Rules to keep

- **Privacy:** sections with personal data (`calendar`, `notes`/reminders, `bins`) are `Sec(private=True)`. They go only into the ntfy
  ping — never onto the public page (it shows a 🔒 placeholder) and never into the public Actions log (`send(..., log=...)` prints the
  public version). The radar is centred on the city, rounded to 0.1°, never on the home address. Don't print secrets or raw
  reminder lines.
- **gh-pages is one orphan commit**, force-pushed with `--force-with-lease` and retried if the other workflow raced it. This keeps
  old pages out of the public history. Use `publish(html, path, extra=…)`; don't push to gh-pages any other way.
- **Decide from the real clock, not the cron time.** `brief.mode()` and `commute.session()` use `now()` windows.
- **Ping limits:** ntfy rejects or attaches messages over 4096 bytes; `send()` truncates at ~3.8 KB. Notification links get `?v=<timestamp>`
  so the phone never shows a cached page (GitHub Pages caches ~10 min). Pages builds are soft-limited to ~10/hour, so the live session
  republishes at most every 10 min.
- **All outside calls go through `commute.get()`** (retries timeouts, resets, 5xx and 429; not other 4xx). ntfy posts use `tries=5`
  (~2 min), because a missed ping is the failure that matters most.

## Gotchas learned the hard way

- **RMV trip legs:** `JNY` = scheduled ride; `TETA`/`TAXI` = on-demand shuttle (e.g. KNUT, evenings; must be booked in an app), modelled as
  `kind="demand"`, and trips without one are preferred; anything else = walk/transfer. Use RMV's own first-origin / last-destination times
  for leave/arrive; summing only one walk leg was wrong by up to 30 min. Occupancy `raw` 11–14 = quiet…packed.
- **RMV alerts (`himsearch`):** the `lines=` filter matches by name (bus "64" exists in many towns), so match on `lineId` and check the
  alert text mentions the line; respect `dailyStartingAt`/`dailyDuration` (night-only works).
- **Open-Meteo** applies one UTC offset to the whole response, so after a clock change its times are an hour off;
  `brief.local_times()` re-anchors them.
- **Yahoo chart closes are float32**, so compare prices loosely. CARTO basemaps now need a key, so the radar uses OpenStreetMap tiles
  + RainViewer frames (max native zoom 7) in the browser.
- **GitHub runner** is pinned to `ubuntu-24.04`; actions are `checkout@v5`, `setup-python@v6` (Node 24).

## Testing

There are no unit test files; test by running pieces locally with real or faked inputs:

- `python commute.py --live` writes `commute.html`; `python brief.py --now` (or `--evening`) prints the ping and writes `brief_index.html`.
  Without `GH_REMOTE`/`NTFY_TOPIC` nothing is published or sent. Delete these output files afterwards; they are not meant for the repo.
- The brief needs `pip install icalendar==6.3.2 recurring-ical-events==3.8.0` (use a venv in the scratchpad).
- Time logic: monkeypatch `commute.datetime` / `brief.datetime` (or `commute.now`) and `time.sleep` to simulate a day; check `mode()`,
  `session()`, `watch()` ping timing, summer and winter time.
- `publish()` can be tested against a local bare repo (`git init --bare -b gh-pages`) as `GH_REMOTE`.
- To check on GitHub, POST the same dispatch request cron-job.org sends to `tick.yml` (no ping on most times of day),
  or run `gh workflow run brief.yml` / `commute.yml` (sends a real test ping). Run logs: `gh api repos/smarthipad-ai/commute/actions/runs/<id>/logs` (zip).
- Before committing: `grep` the code for anything address-, key- or topic-like, and view `/brief/` on a phone-sized viewport.

## Style

Terse Python in the existing style: short helpers, comments only where the *why* isn't obvious, no new dependencies unless the
workflow installs them. Commit messages explain what changed and why.
