"""The connector's single, read-only HTTP boundary.

Every upstream request (ESPN's undocumented site/core/common APIs, nflverse-data
GitHub release assets, and Sleeper's public API) goes through :func:`fetch`.
That function adds an honest User-Agent, follows redirects, decodes stray gzip
bodies, retries 429/5xx with bounded backoff, enforces a total query deadline,
paces requests politely per source, and keeps a small in-process response cache
whose lifetime honors the upstream ``Cache-Control`` policy.

Nothing is persisted to disk and nothing is rehosted: responses live only in
this process's memory for at most their freshness lifetime.
"""

from __future__ import annotations

import gzip
import json
import logging
import os
import random
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from vgi_nfl import __version__

USER_AGENT = f"vgi-nfl/{__version__} (+https://github.com/Query-farm/vgi-nfl)"
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_ATTEMPTS = 4
MAX_RETRY_DELAY = 30.0
QUERY_TIMEOUT = 120.0
MAX_CONCURRENT_REQUESTS = 4
CACHE_MAX_BYTES = 256 * 1024 * 1024
CACHE_MAX_ENTRY_BYTES = 64 * 1024 * 1024

logger = logging.getLogger(__name__)
_request_slots = threading.BoundedSemaphore(MAX_CONCURRENT_REQUESTS)

_MAX_AGE = re.compile(r"(?:^|[,\s])max-age=(\d+)", re.IGNORECASE)
_NO_STORE = re.compile(r"(?:^|[,\s])no-store(?:$|[,\s])", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Source:
    """One upstream API root and its politeness policy."""

    key: str
    env_var: str
    default_url: str
    label: str
    #: Minimum seconds a successful response is reused, whatever the origin says.
    min_ttl: int
    #: Maximum seconds a response is reused, whatever the origin says.
    max_ttl: int
    #: Minimum spacing between request starts to this source, in seconds.
    min_interval: float

    def base_url(self) -> str:
        """Return the API root, optionally overridden for hermetic tests."""
        return os.environ.get(self.env_var, self.default_url).rstrip("/")


ESPN_SITE = Source(
    "espn_site",
    "NFL_ESPN_SITE_URL",
    "https://site.api.espn.com/apis/site/v2/sports/football/nfl",
    "ESPN site API",
    min_ttl=30,
    max_ttl=3_600,
    min_interval=0.25,
)
ESPN_STANDINGS = Source(
    "espn_standings",
    "NFL_ESPN_STANDINGS_URL",
    "https://site.api.espn.com/apis/v2/sports/football/nfl",
    "ESPN standings API",
    min_ttl=60,
    max_ttl=3_600,
    min_interval=0.25,
)
ESPN_CORE = Source(
    "espn_core",
    "NFL_ESPN_CORE_URL",
    "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl",
    "ESPN core API",
    min_ttl=300,
    max_ttl=3_600,
    min_interval=0.25,
)
ESPN_COMMON = Source(
    "espn_common",
    "NFL_ESPN_COMMON_URL",
    "https://site.web.api.espn.com/apis/common/v3/sports/football/nfl",
    "ESPN common API",
    min_ttl=60,
    max_ttl=3_600,
    min_interval=0.25,
)
NFLVERSE = Source(
    "nflverse",
    "NFL_NFLVERSE_URL",
    "https://github.com/nflverse/nflverse-data/releases/download",
    "nflverse-data releases",
    min_ttl=3_600,
    max_ttl=6 * 3_600,
    min_interval=0.0,
)
SLEEPER = Source(
    "sleeper",
    "NFL_SLEEPER_URL",
    "https://api.sleeper.app/v1",
    "Sleeper API",
    min_ttl=300,
    max_ttl=3_600,
    min_interval=0.1,
)
SOURCES = (ESPN_SITE, ESPN_STANDINGS, ESPN_CORE, ESPN_COMMON, NFLVERSE, SLEEPER)


class NflApiError(RuntimeError):
    """A failed response from an upstream NFL data source."""

    def __init__(self, source: Source, status: int, path: str, body: str) -> None:
        detail = " ".join(body.split())[:300]
        super().__init__(f"{source.label} returned HTTP {status} for {path}: {detail}")
        self.status = status
        self.source = source


@dataclass(frozen=True, slots=True)
class Fetched:
    """A response body plus the freshness lifetime it may be reused for."""

    body: bytes
    ttl: int

    def json(self) -> Any:
        """Decode the body as JSON."""
        return json.loads(self.body)


class _ResponseCache:
    """A byte-bounded LRU cache of fresh upstream responses."""

    def __init__(self, max_bytes: int) -> None:
        self._max_bytes = max_bytes
        self._entries: OrderedDict[str, tuple[float, bytes, int]] = OrderedDict()
        self._bytes = 0
        self._lock = threading.Lock()

    def get(self, key: str) -> Fetched | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            expires, body, _ttl = entry
            remaining = expires - time.monotonic()
            if remaining <= 0:
                self._drop(key)
                return None
            self._entries.move_to_end(key)
            return Fetched(body=body, ttl=max(1, int(remaining)))

    def store(self, key: str, body: bytes, ttl: int) -> None:
        if ttl <= 0 or len(body) > CACHE_MAX_ENTRY_BYTES:
            return
        with self._lock:
            if key in self._entries:
                self._drop(key)
            self._entries[key] = (time.monotonic() + ttl, body, ttl)
            self._bytes += len(body)
            while self._bytes > self._max_bytes and self._entries:
                self._drop(next(iter(self._entries)))

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._bytes = 0

    def _drop(self, key: str) -> None:
        _expires, body, _ttl = self._entries.pop(key)
        self._bytes -= len(body)


_cache = _ResponseCache(CACHE_MAX_BYTES)
_pacing_lock = threading.Lock()
_last_request: dict[str, float] = {}


def clear_cache() -> None:
    """Forget every cached response (used by tests and long-lived operators)."""
    _cache.clear()


def _cache_key(source: Source, path: str, params: Mapping[str, str | int]) -> str:
    query = "&".join(f"{key}={params[key]}" for key in sorted(params))
    return f"{source.base_url()}/{path.lstrip('/')}?{query}"


def ttl_for(source: Source, cache_control: str) -> int:
    """Return how long a response may be reused under the source's policy."""
    if _NO_STORE.search(cache_control):
        return source.min_ttl
    match = _MAX_AGE.search(cache_control)
    origin = int(match.group(1)) if match else 0
    return max(source.min_ttl, min(origin, source.max_ttl))


def _retry_delay(response: httpx.Response | None, attempt: int) -> float:
    """Return a bounded Retry-After delay or exponential backoff with jitter."""
    if response is not None:
        raw = response.headers.get("retry-after")
        if raw:
            try:
                delay = float(raw)
            except ValueError:
                try:
                    retry_at = parsedate_to_datetime(raw)
                    if retry_at.tzinfo is None:
                        retry_at = retry_at.replace(tzinfo=UTC)
                    delay = (retry_at - datetime.now(UTC)).total_seconds()
                except (TypeError, ValueError, OverflowError):
                    delay = -1.0
            if delay >= 0:
                return min(delay, MAX_RETRY_DELAY)
    base = min(0.25 * 2**attempt, MAX_RETRY_DELAY)
    return min(base + random.uniform(0, base * 0.25), MAX_RETRY_DELAY)


def _pace(source: Source) -> None:
    """Space request starts to one source by its minimum interval."""
    if source.min_interval <= 0:
        return
    with _pacing_lock:
        now = time.monotonic()
        wait = _last_request.get(source.key, 0.0) + source.min_interval - now
        _last_request[source.key] = max(now, now + wait)
    if wait > 0:
        time.sleep(wait)


def _decode(body: bytes) -> bytes:
    """ESPN occasionally gzips bodies without a Content-Encoding header."""
    if body[:2] == b"\x1f\x8b":
        try:
            return gzip.decompress(body)
        except (OSError, EOFError):
            return body
    return body


def _get(
    source: Source,
    path: str,
    params: Mapping[str, str | int],
    *,
    client: httpx.Client,
    deadline: float,
    accept: str,
) -> httpx.Response:
    """Issue one GET, retrying transient failures within the query deadline."""
    url = f"{source.base_url()}/{path.lstrip('/')}"
    for attempt in range(MAX_ATTEMPTS):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"{source.label} query exceeded {QUERY_TIMEOUT:g} seconds")
        started = time.monotonic()
        try:
            if not _request_slots.acquire(timeout=remaining):
                raise TimeoutError(f"{source.label} query exceeded {QUERY_TIMEOUT:g} seconds")
            try:
                _pace(source)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"{source.label} query exceeded {QUERY_TIMEOUT:g} seconds")
                response = client.get(
                    url,
                    params=dict(params),
                    headers={"Accept": accept, "User-Agent": USER_AGENT},
                    timeout=httpx.Timeout(min(30.0, remaining), connect=min(10.0, remaining)),
                    follow_redirects=True,
                )
            finally:
                _request_slots.release()
        except httpx.TransportError:
            logger.warning(
                "nfl_api_transport_error source=%s path=%s attempt=%d duration_ms=%d",
                source.key,
                path,
                attempt + 1,
                round((time.monotonic() - started) * 1_000),
            )
            if attempt + 1 == MAX_ATTEMPTS:
                raise
            time.sleep(min(_retry_delay(None, attempt), max(0.0, deadline - time.monotonic())))
            continue
        logger.debug(
            "nfl_api_response source=%s path=%s status=%d attempt=%d duration_ms=%d",
            source.key,
            path,
            response.status_code,
            attempt + 1,
            round((time.monotonic() - started) * 1_000),
        )
        if response.status_code not in RETRYABLE_STATUSES or attempt + 1 == MAX_ATTEMPTS:
            return response
        delay = min(_retry_delay(response, attempt), max(0.0, deadline - time.monotonic()))
        logger.warning(
            "nfl_api_retry source=%s path=%s status=%d attempt=%d delay_seconds=%.3f",
            source.key,
            path,
            response.status_code,
            attempt + 1,
            delay,
        )
        time.sleep(delay)
    raise AssertionError("retry loop exited without a response")


def fetch(
    source: Source,
    path: str,
    params: Mapping[str, str | int] | None = None,
    *,
    accept: str = "application/json",
    validate: Callable[[bytes], None] | None = None,
    client: httpx.Client | None = None,
) -> Fetched:
    """Return a fresh response body, from the in-process cache when possible.

    ``validate`` runs before a response is cached, so a malformed or
    mismatched payload is reported and never served to later queries.
    """
    query = dict(params or {})
    key = _cache_key(source, path, query)
    cached = _cache.get(key)
    if cached is not None:
        return cached
    deadline = time.monotonic() + QUERY_TIMEOUT
    if client is None:
        with httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0)) as owned:
            response = _get(source, path, query, client=owned, deadline=deadline, accept=accept)
            body = _decode(response.content)
    else:
        response = _get(source, path, query, client=client, deadline=deadline, accept=accept)
        body = _decode(response.content)
    if not response.is_success:
        raise NflApiError(source, response.status_code, path, body.decode("utf-8", "replace"))
    if validate is not None:
        validate(body)
    ttl = ttl_for(source, response.headers.get("cache-control", ""))
    _cache.store(key, body, ttl)
    return Fetched(body=body, ttl=ttl)


def fetch_json(
    source: Source,
    path: str,
    params: Mapping[str, str | int] | None = None,
    *,
    check: Callable[[Any], None] | None = None,
    client: httpx.Client | None = None,
) -> tuple[Any, int]:
    """Fetch and decode a JSON document, returning it with its freshness lifetime."""
    decoded: list[Any] = []

    def validate(body: bytes) -> None:
        try:
            payload = json.loads(body)
        except ValueError as error:
            raise ValueError(f"{source.label} returned a non-JSON body for {path}") from error
        if check is not None:
            check(payload)
        decoded.append(payload)

    fetched = fetch(source, path, params, validate=validate, client=client)
    return (decoded[0] if decoded else fetched.json()), fetched.ttl
