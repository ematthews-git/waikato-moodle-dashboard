# Waikato Moodle dashboard

Pulls your own courses, grades and deadlines from the University of Waikato's Moodle and
shows them in a local dashboard: average grade, per-course progress, "what do I need on the
remaining work to pass", upcoming deadlines, and your marks over time.

```
python -m moodle_dash serve --demo   # try it now with invented data, no login
python -m moodle_dash login          # sign in once through your browser
python -m moodle_dash sync           # fetch your courses, grades and deadlines
python -m moodle_dash serve          # open the dashboard (localhost only)
```

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install playwright          # only `login` needs it; everything else is standard library
python -m moodle_dash serve --demo
```

`login` opens your installed Chrome (or Edge) so there is no browser download. If you'd
rather use Playwright's own Chromium, run `playwright install chromium`.

## How it works, and why it isn't HTML scraping

Checked against the live site before writing any code:

- Waikato's Moodle is at **`elearn.waikato.ac.nz`** (not `moodle.`).
- Sign-in is **Microsoft SSO (SAML)**, so there's no username/password endpoint, and this
  tool never sees your password or MFA codes.
- Its mobile web service is switched on: `/admin/tool/mobile/launch.php` redirects to
  sign-in rather than returning "service not available". That's the API Waikato's own
  Moodle app uses.

So instead of scraping pages, which breaks whenever the theme changes, the tool uses the
same supported API as the app:

1. **`login`** opens `launch.php` in a browser window. You sign in with Microsoft as normal.
   Moodle then redirects to `moodlemobile://token=…` (exactly what the app receives); we read
   that redirect instead of letting it launch an app, and keep the 32-character token.
2. **`sync`** calls six web-service functions (all in Moodle's official mobile service):
   `core_webservice_get_site_info`, `core_enrol_get_users_courses`,
   `core_course_get_courses_by_field`, `gradereport_user_get_grade_items`,
   `gradereport_overview_get_course_grades`, `core_calendar_get_action_events_by_timesort`.
   It makes roughly `3 + courses` requests, one at a time with a short pause.
3. **`serve`** shows `dashboard/index.html`, a single self-contained page, with no external
   scripts, fonts or requests, reading `data/data.json`.

`login --paste` is a fallback if the browser capture ever fails: paste the
`moodlemobile://token=…` address, the base64 part, or a bare token.

## Security: read this

- **The token is a key to your Moodle account's mobile API** (your grades and course content).
  It's stored in `.state/session.json`, owner-only (`0600`). Don't commit it or share it.
  Revoke it any time in Moodle under *Preferences > Security keys*.
- `.state/browser-profile/` holds your Microsoft session cookies so re-login is quick.
  Delete that folder to forget them.
- `data/data.json` contains your grades, also owner-only. `.state/` and `data/` are gitignored.
- The server binds to `127.0.0.1` and rejects requests with a foreign `Host` header, so a
  web page can't read your grades through it.
- The client refuses to send a token over plain `http://` except to localhost.
- Only use this on **your own account**. The API is the one Waikato's app uses, but check the
  university's ICT acceptable-use policy if you're unsure, and don't sync more than a few
  times a day.

## Status: what's verified and what isn't

Verified (28 tests, plus looking at the dashboard in a browser at desktop and phone width,
light and dark):

- API response shapes read from Moodle's own source (the 4.5 branch) rather than assumed.
- The whole pipeline (client, collector, projections, CLI, file permissions, local server)
  against a fake Moodle that speaks the real response format, including expired tokens,
  denied functions, and hidden grades.
- Token capture from a `moodlemobile://` redirect in real Chrome, headless and headed.

**Not verified: a run against the real `elearn.waikato.ac.nz` with a real account.** That
needs your Microsoft sign-in. The most likely first-run problems, in order:

1. The SSO capture. If a conditional-access policy blocks automated browsers, use `login --paste`.
2. A grade function returning different fields than Moodle 4.5's. Failures become warnings in
   the dashboard footer instead of crashing the sync, so you'd see a missing section, not nothing.
3. The tool uses Waikato's letter scale (A+ ≥ 90 … C- ≥ 50, D ≥ 40) and a 50% pass mark. These
   are assumptions in `moodle_dash/config.py`; check your paper outlines.

## Known limits

- The pass maths only shows when item weights add up to about 100%. With nested grade
  categories Moodle can report weights relative to a sub-total, and the tool then says so instead
  of showing a confident wrong number.
- Deadlines are Moodle's "action events": things you still have to do. Submitted work drops off.
- The hero figure is a simple average of course grades, not weighted by credit points.
- Tokens expire (often after a few weeks). `sync` tells you when to `login` again.

## Layout

```
moodle_dash/   auth.py (SSO token) · client.py (REST) · collect.py (data model, projections)
               server.py (localhost) · demo.py (fake Moodle) · __main__.py (CLI)
dashboard/     index.html: the whole UI
tests/         python -m unittest discover -s tests -t .
```

Ideas if you want to extend it: keep a snapshot per sync to chart how grades change, run
`sync` on a schedule (cron/launchd), or notify when a new mark appears.
