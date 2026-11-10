"""Tests for the single read-only HTTP boundary."""

from __future__ import annotations

import gzip

import httpx
import pytest

from vgi_nfl import __version__, api
from vgi_nfl.api import _pace as original_pace


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_sends_honest_user_agent_and_reads_cache_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NFL_ESPN_SITE_URL", "https://example.test/nfl")
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True}, headers={"Cache-Control": "max-age=120"})

    with _client(handler) as client:
        payload, ttl = api.fetch_json(api.ESPN_SITE, "scoreboard", {"week": 1}, client=client)
    assert payload == {"ok": True}
    assert ttl == 120
    request = seen[0]
    assert request.url.path == "/nfl/scoreboard"
    assert request.url.params["week"] == "1"
    assert request.headers["User-Agent"] == (
        f"vgi-nfl/{__version__} (+https://github.com/Query-farm/vgi-nfl)"
    )


def test_responses_are_cached_in_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NFL_SLEEPER_URL", "https://example.test/v1")
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"season": "2026"})

    with _client(handler) as client:
        first = api.fetch_json(api.SLEEPER, "state/nfl", client=client)
        second = api.fetch_json(api.SLEEPER, "state/nfl", client=client)
    assert first[0] == second[0] == {"season": "2026"}
    assert calls == 1
    assert second[1] <= first[1]


def test_ttl_policy_is_clamped_per_source() -> None:
    assert api.ttl_for(api.ESPN_SITE, "max-age=5") == api.ESPN_SITE.min_ttl
    assert api.ttl_for(api.ESPN_SITE, "public, max-age=202") == 202
    assert api.ttl_for(api.ESPN_SITE, "max-age=999999") == api.ESPN_SITE.max_ttl
    assert api.ttl_for(api.NFLVERSE, "") == api.NFLVERSE.min_ttl
    assert api.ttl_for(api.ESPN_SITE, "no-store") == api.ESPN_SITE.min_ttl


def test_retryable_response_honors_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NFL_ESPN_SITE_URL", "https://example.test/nfl")
    sleeps: list[float] = []
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": "2"})
        if attempts == 2:
            return httpx.Response(503)
        return httpx.Response(200, json={"events": []})

    monkeypatch.setattr("vgi_nfl.api.time.sleep", sleeps.append)
    with _client(handler) as client:
        payload, _ttl = api.fetch_json(api.ESPN_SITE, "scoreboard", client=client)
    assert payload == {"events": []}
    assert attempts == 3
    assert sleeps[0] == 2.0
    assert 0 < sleeps[1] <= api.MAX_RETRY_DELAY


def test_transport_errors_are_retried_then_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NFL_ESPN_SITE_URL", "https://example.test/nfl")
    monkeypatch.setattr("vgi_nfl.api.time.sleep", lambda seconds: None)
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectError("refused", request=request)

    with _client(handler) as client, pytest.raises(httpx.ConnectError):
        api.fetch(api.ESPN_SITE, "teams", client=client)
    assert attempts == api.MAX_ATTEMPTS


def test_http_errors_are_descriptive_and_not_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NFL_ESPN_SITE_URL", "https://example.test/nfl")
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(404, text="  event\n not found ")

    with _client(handler) as client:
        for _ in range(2):
            with pytest.raises(
                api.NflApiError, match="ESPN site API returned HTTP 404 for summary: event not found"
            ):
                api.fetch(api.ESPN_SITE, "summary", {"event": "1"}, client=client)
    assert calls == 2


def test_validation_failure_is_never_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NFL_ESPN_SITE_URL", "https://example.test/nfl")
    bodies = iter([b"not json", b'{"fine": 1}'])
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=next(bodies)))
    with httpx.Client(transport=transport) as client:
        with pytest.raises(ValueError, match="non-JSON"):
            api.fetch_json(api.ESPN_SITE, "teams", client=client)
        assert api.fetch_json(api.ESPN_SITE, "teams", client=client)[0] == {"fine": 1}


def test_stray_gzip_body_is_decoded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NFL_ESPN_SITE_URL", "https://example.test/nfl")
    compressed = gzip.compress(b'{"a": 1}')
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=compressed))
    with httpx.Client(transport=transport) as client:
        assert api.fetch_json(api.ESPN_SITE, "x", client=client)[0] == {"a": 1}


def test_follows_redirects(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NFL_NFLVERSE_URL", "https://example.test/releases")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "example.test":
            return httpx.Response(302, headers={"Location": "https://cdn.example.test/blob"})
        return httpx.Response(200, content=b"PAR1data")

    with _client(handler) as client:
        assert api.fetch(api.NFLVERSE, "pbp/x.parquet", client=client).body == b"PAR1data"


def test_retry_delay_parses_http_dates_and_bounds() -> None:
    response = httpx.Response(429, headers={"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"})
    assert api._retry_delay(response, 0) <= api.MAX_RETRY_DELAY
    assert api._retry_delay(httpx.Response(429, headers={"Retry-After": "9999"}), 0) == api.MAX_RETRY_DELAY
    assert 0 < api._retry_delay(httpx.Response(429, headers={"Retry-After": "soon"}), 1) <= 1


def test_cache_is_byte_bounded() -> None:
    cache = api._ResponseCache(max_bytes=10)
    cache.store("a", b"123456", 60)
    cache.store("b", b"123456", 60)
    assert cache.get("a") is None
    assert cache.get("b") is not None
    cache.store("c", b"x", 0)
    assert cache.get("c") is None


def test_pacing_spaces_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [100.0]
    sleeps: list[float] = []
    monkeypatch.setattr("vgi_nfl.api.time.monotonic", lambda: clock[0])
    monkeypatch.setattr("vgi_nfl.api.time.sleep", sleeps.append)
    monkeypatch.setattr(api, "_last_request", {})
    original_pace(api.ESPN_SITE)
    original_pace(api.ESPN_SITE)
    original_pace(api.NFLVERSE)
    assert sleeps == [pytest.approx(api.ESPN_SITE.min_interval)]
