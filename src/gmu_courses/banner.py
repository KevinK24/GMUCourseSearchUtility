"""Banner 9 Student Self-Service JSON API client for GMU.

GMU's Banner 9 SSB at ssbstureg.gmu.edu serves a stateful JSON API. Every
search reuses session state on the server, so we must reset between searches
or filters from the previous query leak into the next one.
"""
from __future__ import annotations

import truststore
truststore.inject_into_ssl()  # use the OS cert store; GMU's cert chain is incomplete in certifi's bundle

from typing import Any, Iterator

import httpx

# Re-exported so callers can keep importing these from .banner.
from .errors import BannerAPIChanged, BannerError
from .models import Section, Term

BASE_URL = "https://ssbstureg.gmu.edu/StudentRegistrationSsb"
_UA = "gmu-courses/0.1 (personal course-planning CLI)"

__all__ = ["BASE_URL", "BannerAPIChanged", "BannerClient", "BannerError"]


class BannerClient:
    def __init__(self, *, timeout: float = 30.0) -> None:
        self._client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": _UA, "Accept": "application/json"},
            follow_redirects=True,
        )
        self._term_in_session: str | None = None

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "BannerClient":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _request_json(self, method: str, url: str, **kwargs) -> Any:
        """Issue a request and decode JSON, turning contract drift into BannerAPIChanged.

        Connection-level failures stay as httpx errors — those are the user's
        network, not Banner's schema, and deserve a different message.
        """
        response = self._client.request(method, url, **kwargs)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise BannerAPIChanged(
                f"Banner returned HTTP {e.response.status_code} for "
                f"{url.replace(BASE_URL, '')}, which this tool doesn't expect."
            ) from e
        try:
            return response.json()
        except ValueError as e:
            preview = response.text[:120].replace("\n", " ")
            raise BannerAPIChanged(
                f"Banner returned non-JSON for {url.replace(BASE_URL, '')}. "
                f"First bytes: {preview!r}"
            ) from e

    def list_terms(self, *, max_results: int = 20) -> list[Term]:
        payload = self._request_json(
            "GET",
            f"{BASE_URL}/ssb/classSearch/getTerms",
            params={"searchTerm": "", "offset": 1, "max": max_results},
        )
        try:
            return [Term(code=t["code"], description=t["description"]) for t in payload]
        except (KeyError, TypeError) as e:
            raise BannerAPIChanged(
                f"The term list is missing fields this tool needs ({e})."
            ) from e

    def _select_term(self, term_code: str) -> None:
        """Set the active term in session state. Resets prior search filters."""
        # Always reset, even if same term — Banner keeps prior search params otherwise.
        self._client.post(f"{BASE_URL}/ssb/classSearch/resetDataForm")
        self._client.get(f"{BASE_URL}/ssb/term/termSelection", params={"mode": "search"})
        self._request_json(
            "POST",
            f"{BASE_URL}/ssb/term/search",
            params={"mode": "search"},
            data={
                "term": term_code,
                "studyPath": "",
                "studyPathText": "",
                "startDatepicker": "",
                "endDatepicker": "",
            },
        )
        self._term_in_session = term_code

    def search(
        self,
        term_code: str,
        *,
        subject: str | None = None,
        course_number: str | None = None,
        keyword: str | None = None,
        page_size: int = 50,
    ) -> Iterator[Section]:
        for raw in self.search_raw(
            term_code,
            subject=subject,
            course_number=course_number,
            keyword=keyword,
            page_size=page_size,
        ):
            yield Section.from_json(raw)

    def search_raw(
        self,
        term_code: str,
        *,
        subject: str | None = None,
        course_number: str | None = None,
        keyword: str | None = None,
        page_size: int = 50,
    ) -> Iterator[dict]:
        if not any((subject, course_number, keyword)):
            raise BannerError(
                "Pass at least one of subject / course_number / keyword — "
                "an unbounded query returns thousands of sections."
            )
        self._select_term(term_code)
        offset = 0
        while True:
            params: dict[str, str | int] = {
                "txt_term": term_code,
                "pageOffset": offset,
                "pageMaxSize": page_size,
                "sortColumn": "subjectDescription",
                "sortDirection": "asc",
            }
            if subject:
                params["txt_subject"] = subject.upper()
            if course_number:
                params["txt_courseNumber"] = course_number
            if keyword:
                params["txt_keywordlike"] = keyword
            payload = self._request_json(
                "GET", f"{BASE_URL}/ssb/searchResults/searchResults", params=params
            )
            if not isinstance(payload, dict) or "data" not in payload:
                raise BannerAPIChanged(
                    "Search results came back without the expected 'data' field "
                    f"(got keys: {sorted(payload)[:8] if isinstance(payload, dict) else type(payload).__name__})."
                )
            sections = payload.get("data") or []
            if not sections:
                break
            for s in sections:
                yield s
            offset += len(sections)
            total = payload.get("totalCount") or 0
            if offset >= total:
                break

