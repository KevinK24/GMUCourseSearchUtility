"""Interactive menu — the double-click-friendly front end.

Wraps the same search/schedule/history machinery the flag-driven CLI uses,
but drives it with prompts so nothing has to be memorized. `questionary` is
imported lazily so the rest of the CLI stays fast and works without it.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable

import click
import httpx
from rich.panel import Panel

from . import cache
from . import filters as F
from . import history as hist
from . import ical
from . import schedule as sched
from . import search as S
from .banner import BannerClient, BannerError
from .models import Section, Term
from .render import console, render_schedule, render_sections


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

        course_numbers: list[str] = []
        while True:
            raw = questionary.text(
                "Course number(s) — one, or a comma-separated list "
                "(e.g. 530, 542, 618) — blank for all:"
            ).ask()
            if raw is None:
                return None
            try:
                course_numbers = F.parse_course_numbers(raw)
                break
            except ValueError as e:
                console.print(f"[yellow]{e}[/yellow]")

        keyword = _blank_to_none(
            questionary.text("Title keyword (e.g. security) — blank to skip:").ask()
        )

        if not any((subject, course_numbers, keyword)):
            retry = questionary.confirm(
                "You need at least one of subject / course number / keyword. Try again?",
                default=True,
            ).ask()
            if not retry:
                return None
            continue

        # A list of numbers is filtered client-side, so the fetch itself still
        # needs something to bound it.
        if len(course_numbers) > 1 and not (subject or keyword):
            console.print(
                "[yellow]Searching several course numbers needs a subject (or a "
                "keyword) to narrow the fetch — otherwise it would pull every "
                "section in the term.[/yellow]"
            )
            retry = questionary.confirm("Try again?", default=True).ask()
            if not retry:
                return None
            continue

        break

    flags = questionary.checkbox(
        "Filters (space to toggle, enter to continue — none is fine):",
        choices=[
            questionary.Choice("Open seats only", value="open"),
            questionary.Choice("Hide conflicts with my schedule", value="no_conflicts"),
            questionary.Choice("In-person only", value="in-person"),
            questionary.Choice("Online only", value="online"),
            questionary.Choice("More filters (days / time window)…", value="advanced"),
        ],
    ).ask()
    if flags is None:
        return None
    flags = set(flags)

    # Course level is a single value, so it gets a single-select. As checkboxes
    # it was possible to tick two floors and have one silently ignored.
    min_level = questionary.select(
        "Course level:",
        choices=[
            questionary.Choice("Any level", value=None),
            questionary.Choice("Upper division and above (300+)", value=300),
            questionary.Choice("Graduate and above (500+)", value=500),
            questionary.Choice("Doctoral and above (650+)", value=650),
            questionary.Choice("Custom minimum…", value="custom"),
        ],
    ).ask()
    if min_level == "custom":
        while True:
            raw = questionary.text(
                "Minimum course number (e.g. 400) — blank for any:"
            ).ask()
            if raw is None:
                return None
            raw = raw.strip()
            if not raw:
                min_level = None
                break
            if raw.isdigit():
                min_level = int(raw)
                break
            console.print(
                f"[yellow]{raw!r} isn't a number. Enter a course number like 400.[/yellow]"
            )

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
        "course_numbers": course_numbers,
        "keyword": keyword,
        "min_level": min_level,
        "flags": flags,
        "days_spec": days_spec,
        "after_spec": after_spec,
        "before_spec": before_spec,
    }


# How each filter flag reads in the results header. "advanced" is UI-only.
_FLAG_LABELS = {
    "open": "open",
    "no_conflicts": "no-conflicts",
    "in-person": "in-person",
    "online": "online",
}


def _build_predicates(params: dict, my_sections: list[Section]) -> tuple[list, list[str]]:
    """Turn menu params into filter predicates. Returns (predicates, warnings).

    Mutates `params`: a day/time spec that fails to parse is set back to None so
    the results header only advertises filters that actually took effect.
    """
    flags = params["flags"]
    predicates: list[F.SectionFilter] = []
    warnings: list[str] = []

    # One number is handed to Banner directly; several are filtered here, since
    # its search takes a single course number.
    if len(params.get("course_numbers") or []) > 1:
        predicates.append(F.course_number_in(params["course_numbers"]))

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
    if params.get("min_level") is not None:
        predicates.append(F.min_level(params["min_level"]))
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
    if params.get("course_numbers"):
        parts.append("course=" + ",".join(params["course_numbers"]))
    if params["keyword"]:
        parts.append(f"keyword={params['keyword']!r}")
    for key, label in (("days_spec", "days"), ("after_spec", "after"), ("before_spec", "before")):
        if params[key]:
            parts.append(f"{label}={params[key]}")
    if params.get("min_level") is not None:
        parts.append(f"level>={params['min_level']}")
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

    # Sections from another term can't clash with these results.
    my_term_sections = sched.sections_in_term(my_sections, term.code)
    if my_sections and not my_term_sections:
        console.print(
            f"[yellow]Your schedule has no sections in {term.description},[/yellow] "
            "[dim]so conflict checks are skipped — the saved CRNs are from "
            "another term.[/dim]"
        )

    predicates, warnings = _build_predicates(params, my_term_sections)
    for w in warnings:
        console.print(f"[yellow]{w}[/yellow]")

    # Banner accepts a single course number; a list is narrowed client-side, so
    # the fetch stays subject-wide (and reuses that cache entry).
    numbers = params.get("course_numbers") or []
    server_course = numbers[0] if len(numbers) == 1 else None

    try:
        with console.status(f"Querying {term.description}…", spinner="dots"):
            fetched, source = S.fetch_sections(
                client,
                term.code,
                subject=params["subject"],
                course_number=server_course,
                keyword=params["keyword"],
            )
    except BannerError as e:
        console.print(f"[red]{e}[/red]")
        return
    except httpx.HTTPError as e:
        console.print(
            "[red]Couldn't reach Banner at ssbstureg.gmu.edu.[/red] "
            f"Check your internet connection.\n[dim]({e})[/dim]"
        )
        return

    sections = F.apply_filters(fetched, predicates) if predicates else fetched

    if len(numbers) > 1:
        absent = F.unmatched_course_numbers(sections, numbers)
        if absent:
            console.print(
                f"[yellow]No sections matched: {', '.join(absent)}[/yellow] "
                "[dim](not offered this term, or removed by your filters)[/dim]"
            )

    taken = hist.read_courses()
    render_sections(
        sections,
        term.description,
        _describe(params, len(sections), len(fetched), source),
        taken_courses=taken or None,
        scheduled_sections=my_term_sections or None,
    )

    if sections and questionary.confirm(
        "Add any of these to your schedule?", default=False
    ).ask():
        interactive_pick(sections, my_term_sections, taken)


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
        render_schedule(resolved)
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


def split_crn_specs(raw: str) -> list[str]:
    """Split a comma-separated CRN list into individual entries."""
    return [chunk.strip() for chunk in raw.split(",") if chunk.strip()]


def add_crns_to_schedule(raw: str) -> tuple[list[str], list[str], list[str]]:
    """Add every CRN in a comma-separated string.

    Annotates each line with the course and section when that CRN is already
    in the cache, so the file stays readable. Returns
    (added, already_present, unparseable).
    """
    added: list[str] = []
    duplicates: list[str] = []
    bad: list[str] = []
    for crn in split_crn_specs(raw):
        if not crn.isdigit():
            bad.append(crn)
            continue
        note = ""
        hit = cache.find_section_by_crn(crn)
        if hit is not None:
            section = Section.from_json(hit[0])
            note = f"{section.subject_course} sec {section.section_number or '?'}"
        if sched.add_crn(crn, note=note):
            added.append(crn)
        else:
            duplicates.append(crn)
    return added, duplicates, bad


def _do_add_schedule(questionary) -> None:
    raw = questionary.text(
        "CRN(s) to add — comma-separated (e.g. 77863, 77866):"
    ).ask()
    if not raw or not raw.strip():
        console.print("[dim](nothing added)[/dim]")
        return

    added, duplicates, bad = add_crns_to_schedule(raw)

    if added:
        console.print(f"[green]Added {len(added)}:[/green] {', '.join(added)}")
    if duplicates:
        console.print(
            f"[yellow]Already in your schedule ({len(duplicates)}):[/yellow] "
            f"{', '.join(duplicates)}"
        )
    if bad:
        console.print(
            f"[red]Not a CRN ({len(bad)}):[/red] {', '.join(repr(b) for b in bad)}\n"
            "[dim]CRNs are numeric, e.g. 77863.[/dim]"
        )
    if not (added or duplicates or bad):
        console.print("[dim](nothing added)[/dim]")


def remove_crns_from_schedule(crns: Iterable[str]) -> tuple[list[str], list[str]]:
    """Remove each CRN. Returns (removed, not_found).

    Removal comments the line out rather than deleting it, so a mistake is
    recoverable by editing the file.
    """
    removed: list[str] = []
    missing: list[str] = []
    for crn in crns:
        (removed if sched.remove_crn(crn) else missing).append(crn)
    return removed, missing


def _do_remove_schedule(questionary) -> None:
    entries = sched.read_entries()
    if not entries:
        console.print("[yellow]Schedule is empty — nothing to remove.[/yellow]")
        return

    resolved, _missing = sched.resolve(entries)
    by_crn = {s.crn: s for s in resolved}

    choices = []
    for entry in entries:
        section = by_crn.get(entry.crn)
        if section is not None:
            title = _section_label(section)
        else:
            # Not cached, so we can't describe it — fall back to the user's own
            # note, which is usually what they wrote when they added it.
            suffix = f" — {entry.note}" if entry.note else ""
            title = f"{entry.crn}  (not cached{suffix})"
        choices.append(questionary.Choice(title=title, value=entry.crn))

    picked = questionary.checkbox(
        "Select CRN(s) to remove (space=toggle, enter=confirm):",
        choices=choices,
    ).ask()
    if not picked:
        console.print("[dim](nothing removed)[/dim]")
        return

    removed, _missing = remove_crns_from_schedule(picked)
    if removed:
        console.print(f"[green]Removed {len(removed)}:[/green] {', '.join(removed)}")
        console.print(
            "[dim]Lines are commented out rather than deleted, so you can undo "
            f"this by editing {sched.SCHEDULE_FILE.name}.[/dim]"
        )
    else:
        console.print("[yellow](nothing matched)[/yellow]")


def _do_schedule_menu(questionary) -> None:
    """Submenu for viewing and editing the CRNs you're taking."""
    while True:
        _do_show_schedule()
        action = questionary.select(
            "My schedule:",
            choices=[
                questionary.Choice("Add CRN(s)", value="add"),
                questionary.Choice("Remove CRN(s)", value="remove"),
                questionary.Choice("Open the file in my editor", value="edit"),
                questionary.Choice("Back to main menu", value="back"),
            ],
        ).ask()
        if action is None or action == "back":
            return
        if action == "add":
            _do_add_schedule(questionary)
        elif action == "remove":
            _do_remove_schedule(questionary)
        elif action == "edit":
            path = sched.ensure_file()
            console.print(f"[dim]Opening {path}…[/dim]")
            click.launch(str(path))
        console.print()


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
                        questionary.Choice(
                            "My schedule (view / add / remove)", value="schedule"
                        ),
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
                    _do_schedule_menu(questionary)
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
    except BannerError as e:
        # Already carries its own explanation (and reporting link, if drift).
        console.print(f"[red]{e}[/red]")
        return
    except httpx.HTTPError as e:
        console.print(
            "[red]Couldn't reach Banner at ssbstureg.gmu.edu.[/red] "
            f"Check your internet connection.\n[dim]({e})[/dim]"
        )
        return
    except KeyboardInterrupt:
        pass

    console.print("[dim]Bye.[/dim]")
