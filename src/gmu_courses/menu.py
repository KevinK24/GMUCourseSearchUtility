"""Interactive menu — the double-click-friendly front end.

Wraps the same search/schedule/history machinery the flag-driven CLI uses,
but drives it with prompts so nothing has to be memorized. `questionary` is
imported lazily so the rest of the CLI stays fast and works without it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import click
import httpx
from rich.panel import Panel

from . import filters as F
from . import history as hist
from . import ical
from . import schedule as sched
from . import search as S
from .banner import BannerClient, BannerError
from .models import Section, Term
from .render import console, render_sections


class MenuUnavailable(RuntimeError):
    """Raised when the menu can't run (no TTY, or questionary missing)."""


def _require_questionary():
    try:
        import questionary
    except ImportError as e:  # pragma: no cover - depends on install state
        raise MenuUnavailable(
            "The interactive menu needs the `questionary` package.\n"
            "Install it with:  pip install questionary"
        ) from e
    return questionary


def _require_tty() -> None:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise MenuUnavailable(
            "The interactive menu needs a real terminal — it can't run when "
            "input or output is piped/redirected."
        )


def _blank_to_none(s: str | None) -> str | None:
    if s is None:
        return None
    s = s.strip()
    return s or None


# --------------------------------------------------------------------------
# section picker (also used by `gmu search --pick`)
# --------------------------------------------------------------------------

def _section_label(s: Section) -> str:
    if s.meetings and s.meetings[0].begin is not None:
        m = s.meetings[0]
        days = "".join(d for d in "MTWRFSU" if d in m.days)
        when = (
            f"{m.begin.strftime('%H:%M')}-{m.end.strftime('%H:%M')}"
            if m.end
            else m.begin.strftime("%H:%M")
        )
    else:
        days, when = "async", ""
    seats = f"{s.seats_available}/{s.seats_total}"
    instructor = s.instructors[0].split(",")[0] if s.instructors else "TBA"
    return (
        f"{s.crn}  {s.subject_course:9s} sec {s.section_number or '?':<3s}  "
        f"{days:5s} {when:<11s}  {instructor:<20s}  {seats:>7s}  {s.title}"
    )


def interactive_pick(
    sections: list[Section],
    my_sections: list[Section],
    taken: set[str],
) -> int:
    """Checkbox picker over add-able sections. Returns how many CRNs were added."""
    try:
        _require_tty()
        questionary = _require_questionary()
    except MenuUnavailable as e:
        console.print(f"[yellow]({e})[/yellow]")
        return 0

    scheduled_crns = {s.crn for s in my_sections}
    candidates = [
        s
        for s in sections
        if s.subject_course not in taken and s.crn not in scheduled_crns
    ]
    if not candidates:
        console.print("[yellow](nothing to pick — every result is already in your schedule or history)[/yellow]")
        return 0

    choices = [questionary.Choice(title=_section_label(s), value=s) for s in candidates]
    picked = questionary.checkbox(
        f"Select CRN(s) to add to your schedule "
        f"({len(candidates)} option(s); space=toggle, enter=confirm):",
        choices=choices,
    ).ask()

    if not picked:
        console.print("[dim](nothing added)[/dim]")
        return 0

    added = 0
    for s in picked:
        note = f"{s.subject_course} sec {s.section_number or '?'}"
        if sched.add_crn(s.crn, note=note):
            added += 1
    if added:
        console.print(f"[green]Added {added} CRN(s)[/green] to {sched.SCHEDULE_FILE.name}.")
    else:
        console.print("[yellow](all selected CRNs were already in your schedule)[/yellow]")
    return added


# --------------------------------------------------------------------------
# menu actions
# --------------------------------------------------------------------------

def _choose_term(questionary, terms: list[Term], current: Term | None) -> Term | None:
    choices = [
        questionary.Choice(
            title=f"{t.description}  ({t.code})",
            value=t,
            checked=False,
        )
        for t in terms
    ]
    default = None
    if current is not None:
        default = next((c for c in choices if c.value.code == current.code), None)
    return questionary.select("Which term?", choices=choices, default=default).ask()


def _prompt_search_params(questionary) -> dict | None:
    """Collect subject/course/keyword plus filters. None if the user aborts."""
    while True:
        subject = _blank_to_none(
            questionary.text("Subject code (e.g. CS, ISA, MATH) — blank to skip:").ask()
        )
        course = _blank_to_none(
            questionary.text("Course number (e.g. 211) — blank to skip:").ask()
        )
        keyword = _blank_to_none(
            questionary.text("Title keyword (e.g. security) — blank to skip:").ask()
        )
        if any((subject, course, keyword)):
            break
        retry = questionary.confirm(
            "You need at least one of subject / course / keyword. Try again?",
            default=True,
        ).ask()
        if not retry:
            return None

    flags = questionary.checkbox(
        "Filters (space to toggle, enter to continue — none is fine):",
        choices=[
            questionary.Choice("Open seats only", value="open"),
            questionary.Choice("Hide conflicts with my schedule", value="no_conflicts"),
            questionary.Choice("In-person only", value="in-person"),
            questionary.Choice("Online only", value="online"),
            questionary.Choice("Upper-level only (300+)", value="min300"),
            questionary.Choice("Graduate only (500+)", value="min500"),
            questionary.Choice("Doctoral only (650+)", value="min650"),
            questionary.Choice("More filters (days / time window)…", value="advanced"),
        ],
    ).ask()
    if flags is None:
        return None
    flags = set(flags)

    days_spec = after_spec = before_spec = None
    if "advanced" in flags:
        days_spec = _blank_to_none(
            questionary.text(
                "Days — only meet on these (M T W R F, R=Thu). e.g. MWF — blank for any:"
            ).ask()
        )
        after_spec = _blank_to_none(
            questionary.text("Start no earlier than (HH:MM) — blank for any:").ask()
        )
        before_spec = _blank_to_none(
            questionary.text("End no later than (HH:MM) — blank for any:").ask()
        )

    return {
        "subject": subject,
        "course_number": course,
        "keyword": keyword,
        "flags": flags,
        "days_spec": days_spec,
        "after_spec": after_spec,
        "before_spec": before_spec,
    }


# Most restrictive first — _build_predicates applies the first match and stops.
_LEVEL_PRESETS = (("min650", 650), ("min500", 500), ("min300", 300))

# How each filter flag reads in the results header. "advanced" is UI-only.
_FLAG_LABELS = {
    "open": "open",
    "no_conflicts": "no-conflicts",
    "in-person": "in-person",
    "online": "online",
    "min300": "level>=300",
    "min500": "level>=500",
    "min650": "level>=650",
}


def _build_predicates(params: dict, my_sections: list[Section]) -> tuple[list, list[str]]:
    """Turn menu params into filter predicates. Returns (predicates, warnings).

    Mutates `params`: a day/time spec that fails to parse is set back to None so
    the results header only advertises filters that actually took effect.
    """
    flags = params["flags"]
    predicates: list[F.SectionFilter] = []
    warnings: list[str] = []

    for key, factory, label in (
        ("days_spec", lambda v: F.days_subset(F.parse_days(v)), "days"),
        ("after_spec", lambda v: F.begins_at_or_after(F.parse_time(v)), "start time"),
        ("before_spec", lambda v: F.ends_at_or_before(F.parse_time(v)), "end time"),
    ):
        spec = params[key]
        if not spec:
            continue
        try:
            predicates.append(factory(spec))
        except ValueError as e:
            warnings.append(f"Ignoring {label} filter — {e}")
            params[key] = None

    if "in-person" in flags:
        predicates.append(F.modality_is("in-person"))
    if "online" in flags:
        predicates.append(F.modality_is("online"))
    # Level presets are cumulative in intent, so the most restrictive one wins.
    for flag, level in _LEVEL_PRESETS:
        if flag in flags:
            predicates.append(F.min_level(level))
            break
    if "open" in flags:
        predicates.append(F.open_seats)
    if "no_conflicts" in flags:
        if my_sections:
            predicates.append(F.no_conflicts(my_sections))
        else:
            warnings.append(
                "Nothing resolvable in your schedule — conflict filter had no effect."
            )
    return predicates, warnings


def _describe(params: dict, kept: int, total: int, source: str) -> str:
    parts = []
    if params["subject"]:
        parts.append(f"subject={params['subject'].upper()}")
    if params["course_number"]:
        parts.append(f"course={params['course_number']}")
    if params["keyword"]:
        parts.append(f"keyword={params['keyword']!r}")
    for key, label in (("days_spec", "days"), ("after_spec", "after"), ("before_spec", "before")):
        if params[key]:
            parts.append(f"{label}={params[key]}")
    for flag in sorted(params["flags"] - {"advanced"}):
        parts.append(_FLAG_LABELS.get(flag, flag))
    desc = ", ".join(parts) or "all sections"
    if kept != total:
        desc += f"  ({kept}/{total} after filters)"
    return desc + f"  [{source}]"


def _do_search(questionary, client: BannerClient, term: Term) -> None:
    params = _prompt_search_params(questionary)
    if params is None:
        return

    entries = sched.read_entries()
    my_sections, missing = sched.resolve(entries) if entries else ([], [])
    if missing:
        console.print(
            f"[yellow](note: {len(missing)} schedule CRN(s) not cached yet, "
            f"conflict checks skip them: {', '.join(missing)})[/yellow]"
        )

    predicates, warnings = _build_predicates(params, my_sections)
    for w in warnings:
        console.print(f"[yellow]{w}[/yellow]")

    try:
        with console.status(f"Querying {term.description}…", spinner="dots"):
            fetched, source = S.fetch_sections(
                client,
                term.code,
                subject=params["subject"],
                course_number=params["course_number"],
                keyword=params["keyword"],
            )
    except BannerError as e:
        console.print(f"[red]{e}[/red]")
        return
    except httpx.HTTPError as e:
        console.print(f"[red]Network error talking to Banner: {e}[/red]")
        return

    sections = F.apply_filters(fetched, predicates) if predicates else fetched
    taken = hist.read_courses()
    render_sections(
        sections,
        term.description,
        _describe(params, len(sections), len(fetched), source),
        taken_courses=taken or None,
        scheduled_sections=my_sections or None,
    )

    if sections and questionary.confirm(
        "Add any of these to your schedule?", default=False
    ).ask():
        interactive_pick(sections, my_sections, taken)


def _do_show_schedule() -> None:
    entries = sched.read_entries()
    if not entries:
        console.print(
            f"[yellow]Schedule is empty.[/yellow] Add CRNs from a search, "
            f"or edit {sched.SCHEDULE_FILE}."
        )
        return
    resolved, missing = sched.resolve(entries)
    if resolved:
        render_sections(resolved, "your schedule", f"{len(resolved)} CRN(s) resolved")
    if missing:
        console.print(
            f"[yellow]Could not resolve {len(missing)} CRN(s) — not cached yet: "
            f"{', '.join(missing)}.[/yellow]\nSearch their subject once, then revisit."
        )


def _do_show_history() -> None:
    courses = sorted(hist.read_courses())
    if not courses:
        console.print(
            f"[yellow]History is empty.[/yellow] Use \"Add course(s)\" below, or "
            f"edit {hist.HISTORY_FILE}."
        )
        return
    console.print(
        Panel(
            "\n".join(f"  {c}" for c in courses),
            title=f"{len(courses)} course(s) already taken",
            expand=False,
        )
    )


def split_course_specs(raw: str) -> list[str]:
    """Split a comma-separated course list into individual specs.

    Commas only — 'CS 555' contains a space, so splitting on whitespace would
    break the common 'SUBJECT NUMBER' form.
    """
    return [chunk.strip() for chunk in raw.split(",") if chunk.strip()]


def add_courses_to_history(raw: str) -> tuple[list[str], list[str], list[str]]:
    """Add every course in a comma-separated string.

    Returns (added, already_present, unparseable).
    """
    added: list[str] = []
    duplicates: list[str] = []
    bad: list[str] = []
    for spec in split_course_specs(raw):
        ok, norm = hist.add_course(spec)
        if norm is None:
            bad.append(spec)
        elif ok:
            added.append(norm)
        else:
            duplicates.append(norm)
    return added, duplicates, bad


def _do_add_history(questionary) -> None:
    raw = questionary.text(
        "Course(s) you've taken — comma-separated (e.g. CS 555, ISA 650, CS583):"
    ).ask()
    if not raw or not raw.strip():
        console.print("[dim](nothing added)[/dim]")
        return

    added, duplicates, bad = add_courses_to_history(raw)

    if added:
        console.print(f"[green]Added {len(added)}:[/green] {', '.join(added)}")
    if duplicates:
        console.print(f"[yellow]Already there ({len(duplicates)}):[/yellow] {', '.join(duplicates)}")
    if bad:
        console.print(
            f"[red]Couldn't parse ({len(bad)}):[/red] {', '.join(repr(b) for b in bad)}\n"
            "[dim]Expected 'SUBJECT NUMBER' like 'CS 555' or 'cs555'.[/dim]"
        )
    if not (added or duplicates or bad):
        console.print("[dim](nothing added)[/dim]")


def _do_remove_history(questionary) -> None:
    courses = sorted(hist.read_courses())
    if not courses:
        console.print("[yellow]History is empty — nothing to remove.[/yellow]")
        return
    picked = questionary.checkbox(
        "Select course(s) to remove (space=toggle, enter=confirm):",
        choices=courses,
    ).ask()
    if not picked:
        console.print("[dim](nothing removed)[/dim]")
        return
    removed = [c for c in picked if hist.remove_course(c)[0]]
    if removed:
        console.print(f"[green]Removed {len(removed)}:[/green] {', '.join(removed)}")
    else:
        console.print("[yellow](nothing matched)[/yellow]")


def _do_history_menu(questionary) -> None:
    """Submenu for viewing and editing the taken-courses list."""
    while True:
        _do_show_history()
        action = questionary.select(
            "Courses I've taken:",
            choices=[
                questionary.Choice("Add course(s)", value="add"),
                questionary.Choice("Remove course(s)", value="remove"),
                questionary.Choice("Open the file in my editor", value="edit"),
                questionary.Choice("Back to main menu", value="back"),
            ],
        ).ask()
        if action is None or action == "back":
            return
        if action == "add":
            _do_add_history(questionary)
        elif action == "remove":
            _do_remove_history(questionary)
        elif action == "edit":
            path = hist.ensure_file()
            console.print(f"[dim]Opening {path}…[/dim]")
            click.launch(str(path))
        console.print()


def _do_export(questionary) -> None:
    entries = sched.read_entries()
    if not entries:
        console.print("[yellow]Schedule is empty — nothing to export.[/yellow]")
        return
    resolved, missing = sched.resolve(entries)
    if missing:
        console.print(
            f"[yellow]Skipping {len(missing)} unresolved CRN(s): {', '.join(missing)}[/yellow]"
        )
    if not resolved:
        console.print(
            "[red]None of your CRNs could be resolved from the cache.[/red] "
            "Search their subjects first."
        )
        return
    raw_path = questionary.text(
        "Save calendar to:", default=str(Path.home() / "Desktop" / "my_gmu_schedule.ics")
    ).ask()
    if not raw_path:
        return
    out = Path(raw_path).expanduser()
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        body = ical.build_calendar(resolved)
        out.write_text(body, encoding="utf-8", newline="")
    except OSError as e:
        console.print(f"[red]Couldn't write {out}: {e}[/red]")
        return
    console.print(
        f"[green]Wrote {body.count('BEGIN:VEVENT')} event(s)[/green] for "
        f"{len(resolved)} section(s) to {out}\n"
        "[dim]Double-click it to import into Apple Calendar or Outlook; "
        "in Google Calendar use Settings > Import & export.[/dim]"
    )


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

_BANNER = """[bold]GMU Course Search[/bold]
[dim]Interactive mode — arrow keys to move, enter to select, Ctrl-C to back out.[/dim]"""


def run_menu() -> None:
    """Run the interactive menu loop until the user quits."""
    _require_tty()
    questionary = _require_questionary()

    console.print(Panel(_BANNER, expand=False))

    try:
        with BannerClient() as client:
            with console.status("Loading terms…", spinner="dots"):
                terms = client.list_terms(max_results=12)
            term = S.pick_default_term(client)
            console.print(f"Term: [cyan]{term.description}[/cyan]  [dim]({term.code})[/dim]\n")

            while True:
                action = questionary.select(
                    "What would you like to do?",
                    choices=[
                        questionary.Choice("Search for courses", value="search"),
                        questionary.Choice("View my schedule", value="schedule"),
                        questionary.Choice(
                            "Courses I've taken (view / add / remove)", value="history"
                        ),
                        questionary.Choice("Export schedule to calendar (.ics)", value="export"),
                        questionary.Choice(
                            f"Change term (currently {term.description})", value="term"
                        ),
                        questionary.Choice("Quit", value="quit"),
                    ],
                ).ask()

                if action is None or action == "quit":
                    break
                if action == "search":
                    _do_search(questionary, client, term)
                elif action == "schedule":
                    _do_show_schedule()
                elif action == "history":
                    _do_history_menu(questionary)
                elif action == "export":
                    _do_export(questionary)
                elif action == "term":
                    chosen = _choose_term(questionary, terms, term)
                    if chosen is not None:
                        term = chosen
                        console.print(f"Term set to [cyan]{term.description}[/cyan]\n")
                console.print()
    except (BannerError, httpx.HTTPError) as e:
        console.print(f"[red]Could not reach Banner: {e}[/red]")
        return
    except KeyboardInterrupt:
        pass

    console.print("[dim]Bye.[/dim]")
