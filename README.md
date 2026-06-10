# gmu-courses

A small command-line tool for searching George Mason University's Schedule of
Classes — with day/time/level filters, conflict-aware coloring against your
saved schedule, and a "courses I've already taken" file so the same red row
doesn't keep tempting you.

It hits Banner 9's public JSON API directly (the same endpoints `patriotweb`
uses for the no-login Schedule of Classes page), so no authentication is
required for read-only browsing.

```
$ gmu search -s CS --min-level 500 --modality in-person --no-conflicts
  17 section(s) — subject=CS, min-level=500, mod=in-person, no-conflicts
   (17/30 after filters)  [live] — Fall 2026

  CRN    Course   Sec  Title                            Meetings       Instructor       Mod        Cr  Seats
  ─────  ──────   ──   ──────────────────────────────   ─────────────  ──────────────   ────────   ──  ────────
  77891  CS 540   001  Language Processors and Compi…   MW 16:30-17:45 Snyder, Andrew   in-person  3   12/30
  77892  CS 550   001  Database Systems                 TR 13:30-14:45 Liang, Yifan     in-person  3    4/30
  77893  CS 570   001  Operating Systems                MW 19:20-20:35 Wijesekera, D.   in-person  3    8/30
  ...

  green = open to take   yellow = in your schedule   magenta = conflicts   red = already taken
```

## Why this exists

[SRCT's `schedules`](https://github.com/srct/schedules) project covered this
ground but was archived in late 2022, was a Rails web app (not a CLI), and
predates GMU's migration to the current Banner 9 stack at `ssbstureg.gmu.edu`.
This is a fresh, terminal-native take aimed at "I want to plan a semester
without clicking through Patriot Web's pagination."

## What you can do

- **Search** by subject (`-s CS`), course number (`-c 211`), or title keyword
  (`-k "machine learning"`). Filter further by:
  - Days of the week (`--days MWF`)
  - Time window (`--after 10:00 --before 16:00`)
  - Modality (`--modality in-person` / `online` / `hybrid`)
  - Course level (`--min-level 300 --max-level 499` for undergrad upper)
  - Open seats only (`--open`)
  - No conflicts with your saved schedule (`--no-conflicts`)
- **See conflicts at a glance** — every search result is color-coded against
  your saved schedule and history. No flag needed; the coloring is always on.
- **Track what you're taking** — a plain text `my_schedule.txt` file lists
  CRNs; conflict detection compares every search result against their
  meeting times.
- **Track what you've already taken** — a plain text `my_history.txt` file
  lists courses (`CS 211`, `MATH 113`); those rows show in red so you don't
  re-take them by accident.
- **Cache results on disk** — a 1-hour TTL means re-searching the same
  subject is instant. `--fresh` bypasses, `gmu cache clear` resets.

## Install

Requires Python 3.11+ (developed and tested on 3.14).

```bash
git clone https://github.com/KevinK24/GMUCourseSearchUtility.git
cd GMUCourseSearchUtility
pip install -e .
```

The `gmu` command should now be on your PATH. If it isn't, your Python
user-scripts directory needs to go on PATH — see [Windows PATH notes](#windows-path-notes).

### Windows PATH notes

On Windows, `pip install -e .` installs `gmu.exe` into
`%APPDATA%\Python\PythonXY\Scripts\` (e.g. `C:\Users\You\AppData\Roaming\Python\Python314\Scripts\`).
If that directory isn't already on your user PATH, add it from PowerShell:

```powershell
$scripts = Join-Path $env:APPDATA "Python\Python314\Scripts"
[Environment]::SetEnvironmentVariable("Path", [Environment]::GetEnvironmentVariable("Path","User") + ";$scripts", "User")
```

…then open a fresh PowerShell window. (`SetEnvironmentVariable` writes to the
registry; the new shell will pick it up at launch.)

### Why `truststore`?

GMU's Banner server presents a TLS certificate whose intermediate isn't in
the default `certifi` bundle that `httpx` uses. Rather than disable TLS
verification, this project pulls in [`truststore`](https://pypi.org/project/truststore/)
and calls `truststore.inject_into_ssl()` at import — making `httpx` (and
everything else SSL) use the operating system's trust store, which does
include the intermediate. No extra setup on your part.

## Quickstart

```bash
# 1. See what semesters are available
gmu terms

# 2. Search a subject (defaults to next registerable term)
gmu search -s CS

# 3. Tighten it up
gmu search -s CS --min-level 500 --modality in-person --open

# 4. Save your current/planned schedule for conflict awareness
gmu schedule add 77863       # CS 211 sec 001
gmu schedule add 77866       # CS 211 lab sec 201

# 5. Save courses you've already taken
gmu history add CS 100
gmu history add "MATH 113"

# 6. Now search results color-code automatically
gmu search -s CS             # CS 100 is red, sec 001 is yellow, conflicts are magenta
```

## Command reference

```
gmu terms                              List semesters with their codes
gmu search [filters]                   Search for sections (see filters below)
gmu show <CRN>                         Full detail for a section by CRN (cache lookup)

gmu schedule path | edit | show        Inspect / edit your schedule file
gmu schedule add <CRN>                 Append a CRN
gmu schedule remove <CRN>              Comment out the line (recoverable)

gmu history path | edit | show         Inspect / edit your taken-courses file
gmu history add <SUBJECT> <NUMBER>     Mark a course as already taken (forgiving parser)
gmu history remove <SUBJECT> <NUMBER>  Comment out the line

gmu cache path | clear                 Manage the disk cache
```

### `gmu search` filters

| Flag | Effect |
|---|---|
| `-t / --term <code>` | Term code (default: next registerable, e.g. `202670` = Fall 2026) |
| `-s / --subject <SUBJ>` | Subject code (`CS`, `MATH`, `ENGH`, …) |
| `-c / --course <NUMBER>` | Course number (`211`, `699`, …) |
| `-k / --keyword <text>` | Title keyword (server-side) |
| `--days <DDDD>` | Restrict to sections meeting *only* on these days. Codes: `M T W R F S U` (R=Thu) |
| `--after HH:MM` | Every meeting must begin at or after this time |
| `--before HH:MM` | Every meeting must end at or before this time |
| `--modality {in-person, online, hybrid}` | Filter by modality |
| `--min-level <N>` | Course number ≥ N |
| `--max-level <N>` | Course number ≤ N (pair with `--min-level` for ranges) |
| `--open` | Only sections with open seats |
| `--no-conflicts` | Hide sections that overlap any CRN in your schedule |
| `--fresh` | Bypass disk cache, re-fetch from Banner |

At least one of `--subject`, `--course`, or `--keyword` is required — an
unbounded query would pull thousands of sections per term.

### Row colors

Applied automatically, in priority order:

| Color | Meaning |
|---|---|
| 🔴 **red** | Section's course (subject + number) is in your `my_history.txt` |
| 🟡 **yellow** | Section's CRN is in your `my_schedule.txt` |
| 🟣 **magenta** | Section conflicts (same day, overlapping time) with any CRN in your schedule |
| 🟢 **green** | No constraint — open to take |

If you'd rather hide conflicts entirely instead of just coloring them, add
`--no-conflicts`.

## File formats

Both files live under the platform-appropriate config directory. On Windows,
that's `%LOCALAPPDATA%\gmu-courses\Config\`. Run `gmu schedule path` or
`gmu history path` to see the exact location.

### `my_schedule.txt`

```
# One CRN per line. Lines starting with # are comments.
# Anything after a # on a line is also a comment, so annotate freely.
77863    # CS 211 sec 001 — MW 13:30-14:45
77866    # CS 211 lab sec 201 — R 11:30-12:20
70644    # ISA 562 sec DL1 — online async
```

CRNs must be present in the local cache to participate in conflict checking.
If a CRN can't be resolved (because you haven't searched its subject yet),
the CLI prints a one-line note on stderr telling you which one and
suggesting a `gmu search` to fix it.

### `my_history.txt`

```
# One course per line, normalized to "SUBJECT NUMBER".
# Parser is forgiving — "cs211", "CS 211", "CS  211" all normalize the same.
CS 100        # spring 2024
CS 112
ISA 562       # transferred credit
ISA 650
```

Matching is at the **course** level (`CS 211`), not the section level, so
adding a course hides it across every section, term, and year.

## How it works

```
src/gmu_courses/
├── banner.py     # Banner 9 SSB JSON API client (session, term, search, paging)
├── models.py     # Section + MeetingTime dataclasses; JSON-to-domain mapping
├── filters.py    # Day/time/modality/level/conflict predicates (pure)
├── cache.py      # Disk cache for raw search payloads (1-hour TTL)
├── schedule.py   # my_schedule.txt parser + CRN add/remove
├── history.py    # my_history.txt parser + course add/remove (with normalization)
├── render.py     # Rich-based table rendering with row coloring
└── cli.py        # click entrypoint, wires everything together
```

The two most fragile layers — and the only ones likely to need attention when
Ellucian ships a Banner update — are `banner.py` (HTTP contract) and
`Section.from_json` in `models.py` (field shapes). Fixtures under
`tests/fixtures/` are real captured API responses, so the test suite will
fail loudly if either drifts.

### Banner 9 API notes

The three-step session dance the client implements:

```
GET  /ssb/classSearch/getTerms                 → JSON list of terms
POST /ssb/term/search?mode=search              → establishes session for that term
GET  /ssb/searchResults/searchResults?…        → paginated JSON section list
```

Banner is **stateful** on the server side — every search reuses the previous
search's filters unless you reset between calls. `BannerClient._select_term`
calls `/ssb/classSearch/resetDataForm` before each query for that reason.

## Development

```bash
pip install -e ".[dev]"
pytest -q
```

Tests are offline-by-default — model and filter tests run against captured
fixtures in `tests/fixtures/`. The fixtures can be regenerated against the
live API by hitting the same endpoints `BannerClient` uses.

## What this doesn't do

Out of scope, for now:

- **Degree audit / Mason Core matching** — there's no integration with what
  your major actually requires. You still need DegreeWorks for that.
- **Authenticated registration** — read-only browsing only. To actually
  enroll, copy CRNs into Patriot Web.
- **Multi-schedule comparison / shopping cart** — there's one
  `my_schedule.txt`, not several candidate schedules.
- **Live seat counts** — `seatsAvailable` is whatever Banner's public search
  exposed at fetch time (and may be slightly behind the registration system).

## License

MIT — see [LICENSE](LICENSE).

## Disclaimer

Not affiliated with George Mason University or Ellucian. Banner 9's JSON
endpoints are not a documented public API; they could change without notice,
and a future Banner update may break this tool until it's adapted.
