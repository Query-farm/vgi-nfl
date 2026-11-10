"""Shared fixtures: an isolated response cache and a recorded-upstream replay server."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.fixture_server import serve
from vgi_nfl import api

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load_fixture(name: str) -> Any:
    """Decode one recorded JSON response."""
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture(autouse=True)
def _isolated_cache(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Give every test an empty response cache and no politeness delays."""
    api.clear_cache()
    monkeypatch.setattr(api, "_pace", lambda source: None)
    yield
    api.clear_cache()


@pytest.fixture(scope="session")
def _replay_server() -> Iterator[tuple[dict[str, str], list[str]]]:
    with serve() as running:
        yield running


@pytest.fixture
def replay(monkeypatch: pytest.MonkeyPatch, _replay_server: tuple[dict[str, str], list[str]]) -> list[str]:
    """Point every upstream source at the local replay server; return its request log."""
    environment, requests = _replay_server
    requests.clear()
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    return requests
