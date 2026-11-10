"""Opt-in smoke tests against the real ESPN, nflverse, and Sleeper endpoints.

They pin historical facts (2025 week 1, game 401772510) so they stay stable
while live data moves.
"""

from __future__ import annotations

import pytest

from vgi_nfl import espn, nflverse

GAME = "401772510"


@pytest.mark.live
def test_current_standings_cover_the_league() -> None:
    rows, _ = espn.fetch_standings()
    assert len(rows) == 32
    assert len({row["division"] for row in rows}) == 8
    assert sum(row["wins"] for row in rows) == sum(row["losses"] for row in rows)


@pytest.mark.live
def test_2025_standings_balance() -> None:
    rows, _ = espn.fetch_standings(2025)
    games = sum(row["wins"] + row["losses"] + row["ties"] for row in rows)
    assert games == 32 * 17
    seahawks = next(row for row in rows if row["team_abbreviation"] == "SEA")
    assert seahawks["playoff_seed"] == 1


@pytest.mark.live
def test_2025_week_1_and_opener_box_score() -> None:
    games, _ = espn.fetch_scoreboard(2025, 1, 2)
    assert len(games) == 16
    opener = next(game for game in games if game["game_id"] == GAME)
    assert (opener["away_score"], opener["home_score"]) == (20, 24)
    payload, _ = espn.fetch_summary(GAME)
    players = espn.flatten_box_player(payload, GAME)
    prescott = next(row for row in players if row["athlete_name"] == "Dak Prescott")
    assert prescott["pass_yards"] == 188
    assert len(espn.flatten_scoring_plays(payload, GAME)) == 8


@pytest.mark.live
def test_current_tables() -> None:
    assert len(espn.fetch_teams()[0]) == 32
    assert espn.fetch_injuries()[0]
    assert espn.fetch_state()[0][0]["season"] >= 2026
    assert espn.fetch_scoreboard()[0]
    assert any(row["position"] == "QB" for row in espn.fetch_roster("KC")[0])
    assert any(row["depth"] == 1 for row in espn.fetch_depth_chart("KC")[0])


@pytest.mark.live
def test_mahomes_2025_game_log_totals() -> None:
    rows, _ = espn.fetch_game_log(3139477, 2025)
    yards = sum(row["value"] for row in rows if row["stat"] == "passingYards")
    assert yards == 3587


@pytest.mark.live
def test_nflverse_assets_resolve() -> None:
    schedule, _ = nflverse.load(nflverse.SCHEDULE, names=["espn_game_id", "home_team"], season=2025, week=1)
    assert "401772510" in schedule.column("espn_game_id").to_pylist()
    season, _ = nflverse.load(
        nflverse.PLAYER_STATS_SEASON, names=["player_display_name", "def_sacks"], season=2025
    )
    garrett = next(row for row in season.to_pylist() if row["player_display_name"] == "Myles Garrett")
    assert garrett["def_sacks"] == 23.0
    for dataset in (nflverse.DRAFT, nflverse.COMBINE, nflverse.NGS_PASSING, nflverse.PLAYERS):
        table, _ = nflverse.load(dataset, names=dataset.schema.names[:2], season=None)
        assert table.num_rows > 0
