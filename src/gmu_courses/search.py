"""Shared search plumbing.

Both the `gmu search` command and the interactive menu need term resolution
and cache-aware fetching. This module owns that logic so neither duplicates it.
Nothing here touches the terminal — callers handle their own spinners/output.
"""
from __future__ import annotations

from . import cache
from .banner import BannerClient
from .models import Section, Term


def pick_default_term(client: BannerClient) -> Term:
    """First term not marked '(View Only)' — i.e. the next registerable term."""
    terms = client.list_terms(max_results=10)
    for t in terms:
        if "view only" not in t.description.lower():
            return t
    return terms[0]


def resolve_term(client: BannerClient, code: str | None) -> Term:
    """Look up a term by code, or pick the default when `code` is None."""
    if code is None:
        return pick_default_term(client)
    for t in client.list_terms(max_results=20):
        if t.code == code:
            return t
    # Unknown code — let the caller proceed; the search call will surface the error.
    return Term(code=code, description=f"term {code}")


def fetch_sections(
    client: BannerClient,
    term_code: str,
    *,
    subject: str | None = None,
    course_number: str | None = None,
    keyword: str | None = None,
    fresh: bool = False,
) -> tuple[list[Section], str]:
    """Fetch sections, preferring the disk cache unless `fresh`.

    Returns (sections, source) where source is "live" or "cached".
    """
    raw: list[dict] | None = None
    if not fresh:
        raw = cache.load_sections(term_code, subject, course_number, keyword)
    if raw is None:
        raw = list(
            client.search_raw(
                term_code,
                subject=subject,
                course_number=course_number,
                keyword=keyword,
            )
        )
        cache.store_sections(term_code, subject, course_number, keyword, raw)
        source = "live"
    else:
        source = "cached"
    return [Section.from_json(d) for d in raw], source
