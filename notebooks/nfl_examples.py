"""Strict public-response replay; analysis stays in the notebooks' visible SQL."""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import parse_qs, urlparse

SOURCE_PREFIXES = {
    "NFL_ESPN_SITE_URL": "/site",
    "NFL_ESPN_STANDINGS_URL": "/standings",
    "NFL_ESPN_CORE_URL": "/core",
    "NFL_ESPN_COMMON_URL": "/common",
    "NFL_NFLVERSE_URL": "/nflverse",
    "NFL_SLEEPER_URL": "/sleeper",
}


class NFLExample:
    """Own one scenario's HTTP boundary and restore inherited endpoint settings."""

    def __init__(self, mode: str, scenario: str):
        if mode not in {"replay", "live"}:
            raise ValueError("DATA_MODE must be replay or live")
        if scenario not in {"snaps", "totals", "expected", "game"}:
            raise ValueError("Unknown NFL notebook scenario")
        self.mode = mode
        self.root = Path(__file__).resolve().parent
        self.requests: list[str] = []
        self.unexpected: list[str] = []
        self.server = None
        self.thread = None
        manifest = json.loads((self.root / "recordings/provenance.json").read_text())
        items = [
            dict(item, folder="recordings") for item in manifest["files"] if item["scenario"] == scenario
        ]
        if scenario == "snaps":
            original = json.loads((self.root / "fixtures/manifest.json").read_text())
            items = [
                dict(
                    item,
                    folder="fixtures",
                    file=item["filename"],
                    request_path="/nflverse" + item["request_path"],
                    params={},
                    content_type="application/octet-stream",
                )
                for item in original["entries"]
            ]
        self.expected = [item["file"] for item in items]
        responses = {}
        for item in items:
            body = (self.root / item["folder"] / item["file"]).read_bytes()
            if hashlib.sha256(body).hexdigest() != item["sha256"]:
                raise ValueError("Recorded body hash mismatch: " + item["file"])
            key = (item["request_path"], tuple(sorted((k, str(v)) for k, v in item["params"].items())))
            if key in responses:
                raise ValueError("Duplicate recorded request")
            responses[key] = (item, body)
        self.previous = {key: os.environ.pop(key, None) for key in SOURCE_PREFIXES}
        if mode == "live":
            return
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def do_GET(self):
                route = urlparse(self.path)
                query = parse_qs(route.query, keep_blank_values=True)
                if any(len(values) != 1 for values in query.values()):
                    owner.unexpected.append("duplicate query values")
                    self.send_error(400)
                    return
                key = (route.path, tuple(sorted((k, v[0]) for k, v in query.items())))
                if key not in responses:
                    owner.unexpected.append(self.path)
                    self.send_error(404, "Outside recorded coverage; no forwarding")
                    return
                item, body = responses[key]
                owner.requests.append(item["file"])
                self.send_response(200)
                self.send_header("Content-Type", item.get("content_type") or "application/octet-stream")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", item.get("cache_control") or "max-age=60")
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        for key, prefix in SOURCE_PREFIXES.items():
            os.environ[key] = f"http://127.0.0.1:{self.server.server_port}" + prefix

    def audit(self) -> str:
        """Check exact-once replay requests, without claiming live instrumentation."""
        if self.mode == "live":
            return "Live public reads used the default endpoints with no replay fallback. Retry attempts are not instrumented."
        assert not self.unexpected, self.unexpected
        assert Counter(self.requests) == Counter(self.expected), (self.requests, self.expected)
        return f"Exactly {len(self.expected)} recorded responses requested once each; no unexpected requests."

    def close(self):
        """Stop the server and restore every inherited source URL."""
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(timeout=5)
        for key, value in self.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
