"""Banner contract drift must produce an explanation, not a traceback.

The tool talks to an undocumented API. When GMU changes it, the failure should
tell the user what happened and where to report it — they can't fix it, and
the maintainer needs to hear about it.
"""
import httpx
import pytest

from gmu_courses.banner import BASE_URL, BannerAPIChanged, BannerClient, BannerError
from gmu_courses.errors import ISSUES_URL
from gmu_courses.models import Section


def _client_returning(handler) -> BannerClient:
    """A BannerClient wired to a mock transport instead of the network."""
    client = BannerClient()
    client._client = httpx.Client(
        transport=httpx.MockTransport(handler), base_url=BASE_URL
    )
    return client


def test_api_changed_is_a_banner_error():
    """Callers that catch BannerError keep working without changes."""
    assert issubclass(BannerAPIChanged, BannerError)


def test_drift_message_tells_the_user_it_is_not_their_fault():
    e = BannerAPIChanged("the shape changed")
    text = str(e)
    assert "the shape changed" in text
    assert ISSUES_URL in text
    assert "not something you did wrong" in text


def test_unexpected_status_becomes_api_changed():
    c = _client_returning(lambda request: httpx.Response(404, text="gone"))
    with pytest.raises(BannerAPIChanged) as exc:
        c.list_terms()
    assert "404" in str(exc.value)
    assert ISSUES_URL in str(exc.value)


def test_html_instead_of_json_becomes_api_changed():
    """Banner serving a login page or error page instead of JSON."""
    c = _client_returning(
        lambda request: httpx.Response(200, text="<html>Maintenance</html>")
    )
    with pytest.raises(BannerAPIChanged) as exc:
        c.list_terms()
    assert "non-JSON" in str(exc.value)


def test_terms_missing_expected_fields_becomes_api_changed():
    c = _client_returning(
        lambda request: httpx.Response(200, json=[{"termCode": "202670"}])
    )
    with pytest.raises(BannerAPIChanged) as exc:
        c.list_terms()
    assert "missing fields" in str(exc.value)


def test_search_results_without_data_key_becomes_api_changed():
    def handler(request):
        if "getTerms" in str(request.url):
            return httpx.Response(200, json=[{"code": "202670", "description": "Fall"}])
        if "searchResults" in str(request.url):
            return httpx.Response(200, json={"results": [], "totalCount": 0})
        return httpx.Response(200, json={})

    c = _client_returning(handler)
    with pytest.raises(BannerAPIChanged) as exc:
        list(c.search_raw("202670", subject="CS"))
    assert "data" in str(exc.value)


def test_section_missing_required_field_becomes_api_changed():
    with pytest.raises(BannerAPIChanged) as exc:
        Section.from_json({"courseReferenceNumber": "12345"})  # no subject/courseNumber
    assert "12345" in str(exc.value)
    assert ISSUES_URL in str(exc.value)


def test_section_with_malformed_meeting_time_becomes_api_changed():
    bad = {
        "courseReferenceNumber": "54321",
        "subject": "CS",
        "courseNumber": "211",
        "courseTitle": "Test",
        "meetingsFaculty": [{"meetingTime": {"beginTime": "not-a-time", "monday": True}}],
    }
    with pytest.raises(BannerAPIChanged) as exc:
        Section.from_json(bad)
    assert "54321" in str(exc.value)


def test_network_failure_is_not_reported_as_api_drift():
    """A dead connection is the user's network, not a Banner schema change."""
    def handler(request):
        raise httpx.ConnectError("no route to host")

    c = _client_returning(handler)
    with pytest.raises(httpx.ConnectError):
        c.list_terms()
