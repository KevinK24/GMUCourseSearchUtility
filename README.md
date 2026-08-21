# gmu-courses

[![tests](https://github.com/KevinK24/GMUCourseSearchUtility/actions/workflows/test.yml/badge.svg)](https://github.com/KevinK24/GMUCourseSearchUtility/actions/workflows/test.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

A command-line tool for searching **George Mason University's Schedule of
Classes**. Filter by day, time, modality, and course level; see at a glance
which sections clash with what you're already taking; and export your semester
to a calendar file.

It reads Banner 9's JSON API directly — the same endpoints the public
[Schedule of Classes](https://ssbstureg.gmu.edu/StudentRegistrationSsb/ssb/term/termSelection?mode=search)
page uses — so **no Patriot Web login is required**.

```
                        4 section(s) — subject=ISA, level>=500   — Fall 2026
┏━━━━━━━┳━━━━━━━━━┳━━━━━┳━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━┳━━━━━━━┓
┃ CRN   ┃ Course  ┃ Sec ┃ Title          ┃ Meetings      ┃ Instructor     ┃ Mod       ┃ Cr ┃ Seats ┃
┡━━━━━━━╇━━━━━━━━━╇━━━━━╇━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━╇━━━━━━━┩
│ 78073 │ ISA 562 │ 001 │ Info Security  │ R 16:30-19:10 │ Itani, Wassim  │ in-person │ 3  │ 39/65 │
│       │         │     │ Theory/Practi… │               │                │           │    │       │
│ 78074 │ ISA 564 │ 202 │ Security       │ M 16:30-19:10 │ Zhang,         │ in-person │ 3  │ 10/15 │
│       │         │     │ Laboratory     │               │ Xiaokuan       │           │    │       │
│ 78075 │ ISA 673 │ 001 │ Operating      │ W 16:30-19:10 │ Wang, Xinyuan  │ in-person │ 3  │ 24/30 │
│       │         │     │ Systems        │               │                │           │    │       │
│       │         │     │ Security       │               │                │           │    │       │
│ 78123 │ ISA 681 │ 001 │ Secure Sftwr   │ M 16:30-19:10 │ Luo, Lannan    │ in-person │ 3  │  7/16 │
│       │         │     │ Design/Prog    │               │                │           │    │       │
└───────┴─────────┴─────┴────────────────┴───────────────┴────────────────┴───────────┴────┴───────┘
```

---

**Contents** — [Requirements](#requirements) · [Install](#install) ·
[First run](#first-run) · [Commands](#command-reference) ·
[Search filters](#search-filters) · [Row colors](#row-colors) ·
[Interactive menu](#interactive-menu) · [Calendar export](#calendar-export) ·
[Your files](#where-your-files-live) · [Troubleshooting](#troubleshooting) ·
[How it works](#how-it-works) · [Development](#development) ·
[Project status](#project-status)

---

## Requirements

- **Python 3.11 or newer.** Check with `python --version`. If you don't have
  it, grab it from [python.org/downloads](https://www.python.org/downloads/)
  (on Windows, tick **"Add Python to PATH"** in the installer).
- An internet connection. No GMU credentials, no API key, no account.

**Platform support:** developed and used daily on Windows 11. The test suite
runs on Linux in CI across Python 3.11–3.13, and every dependency is
cross-platform, so macOS and Linux should work — but the live-API path is
routinely exercised only on Windows. The double-click launcher in `launcher/`
is Windows-only; `gmu menu` gives you the same thing everywhere.

> **Not on PyPI**, deliberately — `pip install gmu-courses` won't find it.
> See [Project status](#project-status) for the reasoning. Installing from
> this repo is a single command either way.

## Install

### Recommended — pipx

[pipx](https://pipx.pypa.io/) installs command-line tools into their own
isolated environment and puts them on your PATH. It also sidesteps the
`externally-managed-environment` error that `pip` throws on modern Linux and
Homebrew Python.

```bash
python -m pip install --user pipx
python -m pipx ensurepath
pipx install https://github.com/KevinK24/GMUCourseSearchUtility/archive/refs/heads/main.zip
```

Reopen your terminal after `ensurepath` so the PATH change takes effect.

That form needs **no git installed** — pip downloads the repo as a zip. If you
do have git, this alternative supports in-place upgrades:

```bash
pipx install git+https://github.com/KevinK24/GMUCourseSearchUtility.git
pipx upgrade gmu-courses     # pull the latest later
```

Either way, `pipx uninstall gmu-courses` removes it cleanly.

### Alternative — pip into a virtual environment

```bash
python -m venv ~/.venvs/gmu
# Windows PowerShell:  ~\.venvs\gmu\Scripts\Activate.ps1
# macOS / Linux:       source ~/.venvs/gmu/bin/activate
pip install https://github.com/KevinK24/GMUCourseSearchUtility/archive/refs/heads/main.zip
```

You'll need to activate that environment each time, or call the script by its
full path (`~/.venvs/gmu/bin/gmu`, or `...\Scripts\gmu.exe` on Windows).

### For development

`-e` (editable) means your edits take effect immediately with no reinstall.

```bash
git clone https://github.com/KevinK24/GMUCourseSearchUtility.git
cd GMUCourseSearchUtility
pip install -e ".[dev]"
pytest -q
```

### Verify it worked

```bash
gmu --version        # gmu, version 0.1.0
gmu terms            # should list GMU semesters — this hits the live API
```

If `gmu` isn't found, see [Troubleshooting](#troubleshooting).

## First run

New to the tool? Run `gmu menu` for a guided, prompt-driven version of
everything below — nothing to memorize. Otherwise:

```bash
# 1. What semesters exist? (Note the term codes.)
gmu terms

# 2. Search a subject. Defaults to the next registerable term.
gmu search -s CS

# 3. Narrow it down.
gmu search -s CS --min-level 500 --modality in-person --open

# 4. Record what you're enrolled in, so clashes get flagged.
gmu schedule add 77863

# 5. Record what you've already taken, so it stops showing up.
gmu history add CS 112

# 6. Search again — rows are now color-coded against both lists.
gmu search -s CS
```

At least one of `--subject`, `--course`, or `--keyword` is required. An
unbounded query would pull ~6,700 sections for a term, so the tool asks you
to narrow it first.

## Command reference

```
gmu menu                               Guided interactive mode — no flags to remember
gmu terms                              List semesters with their codes
gmu search [filters]                   Search for sections (see filters below)
gmu show <CRN>                         Full detail for one section (looks in the cache)

gmu schedule show | path | edit        Inspect / edit the CRNs you're taking
gmu schedule add <CRN>                 Append a CRN
gmu schedule remove <CRN>              Comment out that line (recoverable)
gmu schedule export [-o FILE]          Write the schedule as a .ics calendar file

gmu history show | path | edit         Inspect / edit the courses you've taken
gmu history add <SUBJECT> <NUMBER>     Mark a course as taken (e.g. `gmu history add CS 211`)
gmu history remove <SUBJECT> <NUMBER>  Comment out that line

gmu cache path | clear                 Manage the local result cache
```

Every command accepts `-h` / `--help`.

### Search filters

| Flag | Effect |
|---|---|
| `-t`, `--term <code>` | Term code (default: next registerable term, e.g. `202670` = Fall 2026) |
| `-s`, `--subject <SUBJ>` | Subject code — `CS`, `ISA`, `MATH`, `ENGH`, … |
| `-c`, `--course <NUMBER>` | Course number — `211`, `699`, … |
| `-k`, `--keyword <text>` | Title keyword (matched server-side by Banner) |
| `--days <DAYS>` | Keep sections meeting *only* on these days. Codes: `M T W R F S U` — **R = Thursday**, `U` = Sunday |
| `--after HH:MM` | Every meeting must start at or after this time |
| `--before HH:MM` | Every meeting must end at or before this time |
| `--modality in-person\|online\|hybrid` | Filter by delivery mode |
| `--min-level <N>` | Course number ≥ N (`--min-level 500` for graduate) |
| `--max-level <N>` | Course number ≤ N (pair with `--min-level` for a range) |
| `--open` | Only sections with seats remaining |
| `--no-conflicts` | Hide sections that overlap anything in your schedule |
| `--pick` | After the table, open a checkbox picker to add CRNs to your schedule |
| `--fresh` | Skip the cache and re-fetch from Banner |

```bash
# Graduate CS, in person, seats left, nothing clashing with my schedule
gmu search -s CS --min-level 500 --modality in-person --open --no-conflicts

# Anything about machine learning, Tue/Thu only, afternoons
gmu search -k "machine learning" --days TR --after 12:00

# Doctoral-level ISA
gmu search -s ISA --min-level 650
```

### Row colors

Applied automatically — no flag needed. Priority runs top to bottom:

| Color | Meaning |
|---|---|
| 🔴 red | You've already taken this course (it's in `my_history.txt`) |
| 🟡 yellow | This exact CRN is in your schedule |
| 🟣 magenta | Overlaps a meeting time in your schedule |
| 🟢 green | No constraint — fair game |

Colors only appear once you've put something in your schedule or history.
Use `--no-conflicts` to hide clashes entirely rather than tint them.

## Interactive menu

`gmu menu` drives everything through prompts:

```
? What would you like to do?
❯ Search for courses
  View my schedule
  Courses I've taken (view / add / remove)
  Export schedule to calendar (.ics)
  Change term (currently Fall 2026)
  Quit
```

Search walks you through subject → course → keyword, then a checkbox of
filter presets (open seats, hide conflicts, in-person/online, and level
presets for 300+, 500+, and 650+). Results render as the same colored table,
and you can add CRNs to your schedule right from them.

### Desktop launcher (Windows)

To get a double-clickable icon instead of a terminal command:

```powershell
powershell -ExecutionPolicy Bypass -File .\launcher\install-shortcut.ps1
```

That creates **"GMU Course Search"** on your Desktop pointing at
`launcher\gmu-menu.bat`. The batch file sets a UTF-8 console, prefers the
installed `gmu` command, and falls back to `python -m gmu_courses.cli menu`
if the Scripts directory isn't on PATH. A clean quit closes the window; an
error keeps it open so you can read it.

## Calendar export

Once your schedule has CRNs in it (and you've searched their subjects at least
once, so they're cached):

```bash
gmu schedule export -o fall26.ics
# Wrote 8 event(s) for 5 section(s) to fall26.ics.
```

The file is standard [RFC 5545](https://datatracker.ietf.org/doc/html/rfc5545)
iCalendar with a proper `VTIMEZONE` for America/New_York, so daylight saving
is handled correctly. Import it into:

- **Apple Calendar** — double-click the file; it prompts for a target calendar.
- **Google Calendar** — Settings → Import & export → select file and calendar.
- **Outlook** — File → Open & Export → Import/Export → "Import an iCalendar
  (.ics) or vCalendar file".

Each meeting becomes a weekly recurring event from the term's first matching
weekday through its end date, with room and instructor in the description.
Fully-async sections are skipped — they have no time slot to put on a calendar.

Event UIDs are derived from the CRN, so re-importing an updated export
**updates** existing events rather than duplicating them.

## Where your files live

Two plain-text files hold your data. Ask the tool rather than guessing:

```bash
gmu schedule path
gmu history path
gmu cache path
```

On Windows these land in `%LOCALAPPDATA%\gmu-courses\gmu-courses\`. macOS and
Linux follow the usual [platformdirs](https://pypi.org/project/platformdirs/)
conventions (`~/Library/Application Support/…` and `~/.config/…`).

### `my_schedule.txt` — what you're taking

```
# One CRN per line. Everything after a # is a comment.
77863    # CS 211 sec 001 — MW 13:30-14:45
77866    # CS 211 lab sec 201 — R 11:30-12:20
78073    # ISA 562 — R 16:30-19:10
```

Conflict detection needs each CRN's meeting times, which come from the cache.
If you list a CRN whose subject you haven't searched yet, the tool tells you
which one and how to fix it rather than silently ignoring it.

### `my_history.txt` — what you've already taken

```
# One course per line. "cs211", "CS 211", and "CS  211" all mean the same thing.
CS 112        # spring 2025
ISA 562
ISA 650
```

Matching is per **course**, not per section — so one line covers every section
in every term. Add several at once from the menu (comma-separated), which is
the quickest way to enter a transcript.

## Troubleshooting

**`gmu: command not found` / `'gmu' is not recognized`**

The package installed but its scripts directory isn't on your PATH.

- *Installed with pipx?* Run `pipx ensurepath`, then open a new terminal.
- *Installed with pip on Windows?* Scripts land in
  `%APPDATA%\Python\Python3XX\Scripts\`. Add it:
  ```powershell
  $s = "$env:APPDATA\Python\Python311\Scripts"   # match your version
  [Environment]::SetEnvironmentVariable("Path", [Environment]::GetEnvironmentVariable("Path","User") + ";$s", "User")
  ```
  Then **open a fresh terminal** — a running shell won't pick up the change.
- *Just want it to work?* `python -m gmu_courses.cli` does everything `gmu`
  does, no PATH required.

**`error: externally-managed-environment`**

Your Python (Debian/Ubuntu, or Homebrew) refuses global pip installs. Use
[pipx](#recommended--pipx) or a [venv](#alternative--pip-into-a-virtual-environment).

**`CERTIFICATE_VERIFY_FAILED`**

GMU's server presents a certificate chain that `certifi`'s bundle doesn't
complete. That's why [`truststore`](https://pypi.org/project/truststore/) is a
dependency — it makes Python use your OS trust store instead, which does have
the missing intermediate. If you hit this anyway, confirm truststore installed:
`python -c "import truststore; print(truststore.__version__)"`.

**"CRN not found in local cache"**

Banner's public search has no lookup-by-CRN endpoint, so `gmu show` and
conflict detection work off sections you've already searched. Run a search
covering that CRN's subject (`gmu search -s ISA`) and try again.

**Search returns nothing**

Check the term — the default is the next *registerable* term, which may not be
the one you have in mind. `gmu terms` lists them; `--term 202670` picks one
explicitly. Terms marked *(View Only)* are past semesters.

**Results look stale**

Results cache for one hour. Add `--fresh` to bypass it, or `gmu cache clear`
to wipe it.

## How it works

```
src/gmu_courses/
├── banner.py     # Banner 9 JSON API client — session handling, paging
├── models.py     # Section + MeetingTime dataclasses; JSON → domain mapping
├── filters.py    # Day/time/modality/level/conflict predicates (pure functions)
├── search.py     # Term resolution + cache-aware fetch, shared by CLI and menu
├── cache.py      # Disk cache of raw API payloads (1-hour TTL)
├── schedule.py   # my_schedule.txt parsing, CRN add/remove
├── history.py    # my_history.txt parsing, course add/remove, normalization
├── ical.py       # RFC 5545 calendar generation
├── render.py     # Rich tables, row coloring
├── menu.py       # Interactive menu and section picker
└── cli.py        # Click entry point

launcher/         # Windows double-click launcher + shortcut installer
tests/fixtures/   # Real captured API responses, so tests run offline
```

### Banner 9 API notes

Banner's search is **stateful per session** — a query inherits the previous
query's filters unless you reset first. The client does this dance for every
search:

```
POST /ssb/classSearch/resetDataForm         clear prior filters
GET  /ssb/term/termSelection?mode=search    open a search session
POST /ssb/term/search?mode=search           bind it to a term
GET  /ssb/searchResults/searchResults?…     paginated JSON results
```

`banner.py` and `Section.from_json` in `models.py` are the layers most exposed
to Ellucian changing something. Fixtures under `tests/fixtures/` are real
captured responses, so the suite fails loudly if the shape drifts.

## Development

```bash
git clone https://github.com/KevinK24/GMUCourseSearchUtility.git
cd GMUCourseSearchUtility
pip install -e ".[dev]"
pytest -q
```

Tests run offline against captured fixtures — no network needed, so they're
fast and deterministic. CI runs the suite on Python 3.11, 3.12, and 3.13 on
every push and pull request.

A second set of tests checks the live Banner API and is **deselected by
default**, so `pytest` stays offline. Run them deliberately when you suspect
GMU changed something:

```bash
pytest -m live -v
```

These are what the weekly [live-api-check](.github/workflows/live-api-check.yml)
workflow runs. A failure means either Banner drifted or GMU's servers were
briefly down — re-run before assuming the former.

Contributions welcome. Some things deliberately left undone, if you want a
starting point: Mason Core / section-attribute filtering (Banner already
returns `sectionAttributes`, the code just ignores it), seat-watch diffing
between snapshots, and shell tab-completion.

## Project status

This is a personal tool, shared because it may be useful to other GMU
students. It works and it's tested, but it comes with no support promise —
please read that as honesty rather than discouragement.

**It depends on an API nobody documents.** Banner's JSON endpoints are an
internal detail of GMU's registration site, not a published interface. GMU can
change them at any time and owes no notice.

Two things make that less painful than it sounds:

- **A scheduled GitHub Action re-checks the live API every week**
  ([`live-api-check.yml`](.github/workflows/live-api-check.yml)). If the
  contract drifts, the job fails and the maintainer gets an email — nobody has
  to keep an eye on Ellucian's release notes.
- **When something does break, the tool says so plainly.** You get an
  explanation naming what changed and a link to open an issue, not a stack
  trace:

  ```
  Error: Banner returned non-JSON for /ssb/classSearch/getTerms.

  This usually means GMU changed something about Banner and gmu-courses
  hasn't caught up yet.
  It is not something you did wrong, and no setting on your end will fix it.
  Please check for a newer version, or report it here:
    https://github.com/KevinK24/GMUCourseSearchUtility/issues
  ```

**Why not PyPI?** Publishing there implies a release cadence and version
discipline this project isn't promising. A stale package on an index is worse
for you than a repo — you'd install a broken version with no signal, whereas
here you can see the last commit and any open issues before you install.
Installing from this repo is one command regardless, so the only thing PyPI
would add is the implication of support.

Issues and pull requests are welcome, and fixing Banner drift is usually a
small change confined to `banner.py` and `models.py`.

## What this doesn't do

- **Degree audit / Mason Core matching** — no knowledge of your program's
  requirements. Use DegreeWorks for that.
- **Registration** — read-only. Take the CRNs to Patriot Web to actually
  enroll.
- **Multiple candidate schedules** — there's one `my_schedule.txt`, not a
  shopping cart of alternatives.
- **Real-time seat counts** — seat numbers are whatever the public search
  returned when fetched, which can lag the registration system.

## License

MIT — see [LICENSE](LICENSE).

## Disclaimer

Not affiliated with, endorsed by, or supported by George Mason University or
Ellucian. Banner 9's JSON endpoints are not a documented public API; they may
change without notice and break this tool until it's updated. Be reasonable
with request volume — the caching exists partly for that reason.
