"""A local HTTP server replaying recorded upstream responses for hermetic tests."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

FIXTURES = Path(__file__).resolve().parent / "fixtures"

#: Environment overrides pointing every upstream source at the replay server.
SOURCE_PREFIXES = {
    "NFL_ESPN_SITE_URL": "/site",
    "NFL_ESPN_STANDINGS_URL": "/standings",
    "NFL_ESPN_CORE_URL": "/core",
    "NFL_ESPN_COMMON_URL": "/common",
    "NFL_NFLVERSE_URL": "/nflverse",
    "NFL_SLEEPER_URL": "/sleeper",
}

_JSON_ROUTES = {
    "/site/teams": "espn_teams.json",
    "/site/injuries": "espn_injuries.json",
    "/site/teams/kc/roster": "espn_roster_kc.json",
    "/site/teams/kc/schedule": "espn_team_schedule_kc_2025.json",
    "/core/seasons/2026/teams/12/depthcharts": "espn_depth_chart_kc.json",
    "/common/athletes/3139477/gamelog": "espn_gamelog_3139477_2025.json",
    "/sleeper/state/nfl": "sleeper_state.json",
}


def route(path: str, query: dict[str, list[str]]) -> Path | None:
    """Map a request onto a recorded fixture, or None for 404."""
    if path in _JSON_ROUTES:
        return FIXTURES / _JSON_ROUTES[path]
    if path == "/site/scoreboard":
        name = (
            "espn_scoreboard_2025_week1.json"
            if query.get("dates") == ["2025"]
            else "espn_scoreboard_current.json"
        )
        return FIXTURES / name
    if path == "/standings/standings":
        season = query.get("season", [None])[0]
        return FIXTURES / ("espn_standings_2025.json" if season == "2025" else "espn_standings_current.json")
    if path == "/site/summary" and query.get("event") == ["401772510"]:
        return FIXTURES / "espn_summary_401772510.json"
    if path.startswith("/nflverse/"):
        candidate = FIXTURES / "nflverse" / path.removeprefix("/nflverse/")
        return candidate if candidate.is_file() else None
    return None


class _Handler(BaseHTTPRequestHandler):
    requests: list[str] = []

    def log_message(self, format: str, *args: object) -> None:
        pass

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        type(self).requests.append(self.path)
        target = route(parsed.path, parse_qs(parsed.query))
        if target is None:
            self.send_error(404, "no fixture")
            return
        body = target.read_bytes()
        self.send_response(200)
        content_type = "application/octet-stream" if target.suffix == ".parquet" else "application/json"
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "max-age=60")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@contextmanager
def serve() -> Iterator[tuple[dict[str, str], list[str]]]:
    """Run the replay server; yield environment overrides and the request log."""
    handler = type("Handler", (_Handler,), {"requests": []})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        yield {name: base + prefix for name, prefix in SOURCE_PREFIXES.items()}, handler.requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
