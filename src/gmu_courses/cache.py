"""Disk cache for Banner search results.

Stores the raw section dicts (not parsed `Section` objects) so model-layer
changes don't invalidate the cache. Cache key is a hash of the search params.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from platformdirs import user_cache_dir

CACHE_DIR = Path(user_cache_dir("gmu-courses"))
DEFAULT_TTL = 3600  # 1 hour


def _cache_path(term: str, subject: str | None, course: str | None, keyword: str | None) -> Path:
    key = json.dumps([term, subject, course, keyword], sort_keys=True)
    h = hashlib.sha1(key.encode()).hexdigest()[:16]
    return CACHE_DIR / f"sections_{term}_{h}.json"


def load_sections(
    term: str,
    subject: str | None,
    course: str | None,
    keyword: str | None,
    *,
    max_age: int = DEFAULT_TTL,
) -> list[dict] | None:
    p = _cache_path(term, subject, course, keyword)
    if not p.exists():
        return None
    try:
        body = json.loads(p.read_text("utf-8"))
        age = time.time() - body["fetched_at"]
        if age > max_age:
            return None
        return body["sections"]
    except (OSError, json.JSONDecodeError, KeyError):
        return None


def store_sections(
    term: str,
    subject: str | None,
    course: str | None,
    keyword: str | None,
    sections: list[dict],
) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    p = _cache_path(term, subject, course, keyword)
    body = {"fetched_at": time.time(), "sections": sections}
    p.write_text(json.dumps(body), encoding="utf-8")


def clear() -> int:
    """Delete all cached search results. Returns count removed."""
    if not CACHE_DIR.exists():
        return 0
    n = 0
    for p in CACHE_DIR.glob("sections_*.json"):
        p.unlink()
        n += 1
    return n


def find_section_by_crn(crn: str) -> tuple[dict, str] | None:
    """Scan every cached payload for a section with this CRN. Returns (raw, term_code).

    Banner's public search has no CRN-filter param, so `show <CRN>` looks in
    whatever the user has already searched for. If nothing matches, the caller
    should tell the user to run `gmu search` first.
    """
    if not CACHE_DIR.exists():
        return None
    crn = str(crn)
    for p in CACHE_DIR.glob("sections_*.json"):
        try:
            body = json.loads(p.read_text("utf-8"))
            for s in body.get("sections", []):
                if str(s.get("courseReferenceNumber")) == crn:
                    # term_code is embedded in the filename: sections_<term>_<hash>.json
                    term_code = p.stem.split("_")[1]
                    return s, term_code
        except (OSError, json.JSONDecodeError):
            continue
    return None
