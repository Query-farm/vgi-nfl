"""Serve the recorded ESPN, nflverse and Sleeper responses over HTTP for the SQL tests.

``ci/run-integration.sh`` starts this server, points every upstream source at it
(``tests/fixture_server.SOURCE_PREFIXES``), and runs ``test/sql`` through DuckDB,
so the suite needs no network access. Prints ``PORT:<n>`` once listening.
"""

from __future__ import annotations

import sys
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.fixture_server import _Handler  # noqa: E402


def main() -> None:
    """Serve until killed."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    print(f"PORT:{server.server_port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
