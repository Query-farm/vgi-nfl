"""Hermetic end-to-end coverage through Haybarn and the VGI transport.

Every upstream source is pointed at a local server replaying recorded, trimmed
real responses, so this test needs no network access to ESPN, nflverse, or Sleeper.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from tests.fixture_server import serve


def test_haybarn_attaches_and_queries_every_table() -> None:
    project = Path(__file__).resolve().parent.parent
    location = f"uv run --project {project} vgi-nfl"
    sql = (
        f"INSTALL vgi FROM community; LOAD vgi; ATTACH 'nfl' (TYPE vgi, LOCATION '{location}'); "
        "SELECT "
        "(SELECT count(*) FROM nfl.main.current_scoreboard) AS scoreboard, "
        "(SELECT count(*) FROM nfl.main.current_standings) AS standings, "
        "(SELECT count(*) FROM nfl.main.current_injuries) AS injuries, "
        "(SELECT count(*) FROM nfl.main.current_week) AS week, "
        "(SELECT count(*) FROM nfl.main.teams) AS teams, "
        "(SELECT count(*) > 0 FROM nfl.main.players) AS players, "
        "(SELECT winner_abbreviation FROM nfl.main.scoreboard(2025, 1) "
        "WHERE game_id = '401772510') AS winner, "
        "(SELECT max(rush_yards) FROM nfl.main.box_score_player('401772510')) AS top_rush, "
        "(SELECT espn_game_id FROM nfl.main.schedule(season := 2025, week := 1) "
        "WHERE home_team = 'PHI') AS espn_id;"
    )
    with serve() as (environment, requests):
        result = subprocess.run(
            ["uvx", "haybarn-cli", ":memory:", "-no-agent", "-csv", "-c", sql],
            cwd=project,
            env={**os.environ, **environment},
            check=True,
            capture_output=True,
            text=True,
            timeout=180,
        )
    assert "scoreboard,standings,injuries,week,teams,players,winner,top_rush,espn_id" in result.stdout
    assert "3,32,6,1,32,true,PHI,62,401772510" in result.stdout, result.stdout + result.stderr
    assert requests, "the worker never reached the replay server"
