"""Flattening recorded ESPN and Sleeper responses into typed rows."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from tests.conftest import load_fixture
from vgi_nfl import espn
from vgi_nfl.convert import batch_from_rows
from vgi_nfl.espn_schemas import (
    BOX_PLAYER_SCHEMA,
    BOX_TEAM_SCHEMA,
    DEPTH_CHART_SCHEMA,
    DRIVES_SCHEMA,
    EVENT_SCHEMA,
    GAME_LOG_SCHEMA,
    GAME_SUMMARY_SCHEMA,
    INJURY_SCHEMA,
    PLAYS_SCHEMA,
    ROSTER_SCHEMA,
    SCORING_PLAYS_SCHEMA,
    STANDINGS_SCHEMA,
    TEAMS_SCHEMA,
)

GAME = "401772510"


def test_teams() -> None:
    rows = espn.flatten_teams(load_fixture("espn_teams.json"))
    assert len(rows) == 32
    chiefs = next(row for row in rows if row["team_abbreviation"] == "KC")
    assert chiefs["team_id"] == 12
    assert chiefs["team_name"] == "Kansas City Chiefs"
    assert batch_from_rows(rows, TEAMS_SCHEMA).schema == TEAMS_SCHEMA


def test_standings_2025_ranks_and_records() -> None:
    rows = espn.flatten_standings(load_fixture("espn_standings_2025.json"))
    assert len(rows) == 32
    assert {row["division"] for row in rows} >= {"AFC East", "NFC West"}
    assert sum(row["wins"] for row in rows) == sum(row["losses"] for row in rows)
    patriots = next(row for row in rows if row["team_abbreviation"] == "NE")
    assert (patriots["wins"], patriots["losses"], patriots["ties"]) == (14, 3, 0)
    assert patriots["division_rank"] == 1
    assert patriots["games_back"] == Decimal("0.0")
    assert patriots["win_percentage"] == Decimal("0.824")
    assert patriots["home_record"] == "6-3"
    assert patriots["road_record"] == "8-0"
    assert patriots["clincher"] == "z"
    west = sorted(
        (row for row in rows if row["division"] == "AFC West"), key=lambda row: row["division_rank"]
    )
    assert west[0]["team_abbreviation"] == "DEN"
    assert [row["division_rank"] for row in west] == [1, 2, 3, 4]
    jets = next(row for row in rows if row["team_abbreviation"] == "NYJ")
    assert jets["streak"] == "L5"
    assert jets["streak_length"] == -5
    assert batch_from_rows(rows, STANDINGS_SCHEMA).num_rows == 32


def test_scoreboard_2025_week_1() -> None:
    rows = espn.flatten_scoreboard(load_fixture("espn_scoreboard_2025_week1.json"))
    opener = next(row for row in rows if row["game_id"] == GAME)
    assert opener["season"] == 2025
    assert opener["season_type"] == 2
    assert opener["week"] == 1
    assert opener["game_time"] == datetime(2025, 9, 5, 0, 20, tzinfo=UTC)
    assert (opener["away_team_abbreviation"], opener["away_score"]) == ("DAL", 20)
    assert (opener["home_team_abbreviation"], opener["home_score"]) == ("PHI", 24)
    assert opener["winner_abbreviation"] == "PHI"
    assert opener["completed"] is True
    assert opener["venue"] == "Lincoln Financial Field"
    assert opener["home_record"] == "1-0"
    assert batch_from_rows(rows, EVENT_SCHEMA).schema == EVENT_SCHEMA


def test_pregame_scores_are_null() -> None:
    event = {
        "id": "1",
        "competitions": [
            {
                "status": {"type": {"state": "pre", "name": "STATUS_SCHEDULED"}},
                "competitors": [
                    {"homeAway": "home", "score": "0", "team": {"abbreviation": "KC"}},
                    {"homeAway": "away", "score": "0", "team": {"abbreviation": "BUF"}},
                ],
                "broadcasts": [{"names": ["CBS"]}],
            }
        ],
    }
    row = espn.flatten_scoreboard({"events": [event]})[0]
    assert row["home_score"] is None and row["away_score"] is None
    assert row["broadcast"] == "CBS"
    assert row["winner_abbreviation"] is None


def test_team_schedule_scores_are_objects() -> None:
    rows = espn.flatten_team_schedule(load_fixture("espn_team_schedule_kc_2025.json"))
    first = rows[0]
    assert first["week"] == 1
    assert (first["away_team_abbreviation"], first["away_score"]) == ("KC", 21)
    assert (first["home_team_abbreviation"], first["home_score"]) == ("LAC", 27)
    assert first["neutral_site"] is True


def test_injuries() -> None:
    rows = espn.flatten_injuries(load_fixture("espn_injuries.json"))
    assert rows
    assert all(row["athlete_id"] for row in rows)
    assert {row["team_abbreviation"] for row in rows} <= {"KC", "PHI"}
    assert all(row["injury_side"] != "Not Specified" for row in rows)
    assert batch_from_rows(rows, INJURY_SCHEMA).num_rows == len(rows)


def test_roster() -> None:
    rows = espn.flatten_roster(load_fixture("espn_roster_kc.json"))
    mahomes = next(row for row in rows if row["athlete_id"] == 3139477)
    assert mahomes["athlete_name"] == "Patrick Mahomes"
    assert mahomes["position"] == "QB"
    assert mahomes["birth_date"] == date(1995, 9, 17)
    assert mahomes["college"] == "Texas Tech"
    assert mahomes["team_abbreviation"] == "KC"
    assert batch_from_rows(rows, ROSTER_SCHEMA).num_rows == len(rows)


def test_depth_chart_names_from_roster() -> None:
    roster = espn.flatten_roster(load_fixture("espn_roster_kc.json"))
    rows = espn.flatten_depth_chart(
        load_fixture("espn_depth_chart_kc.json"),
        team={"team_id": 12, "team_abbreviation": "KC"},
        season=2026,
        roster=roster,
    )
    assert {row["formation"] for row in rows} == {"3WR 1TE", "Base 4-3 D", "Special Teams"}
    assert all(row["athlete_id"] for row in rows)
    assert all(row["depth"] >= 1 for row in rows)
    assert batch_from_rows(rows, DEPTH_CHART_SCHEMA).num_rows == len(rows)


def test_game_summary_by_quarter() -> None:
    row = espn.flatten_game_summary(load_fixture(f"espn_summary_{GAME}.json"))[0]
    assert row["game_id"] == GAME
    assert row["short_name"] == "DAL @ PHI"
    assert [row[f"home_q{quarter}"] for quarter in range(1, 5)] == [7, 14, 3, 0]
    assert [row[f"away_q{quarter}"] for quarter in range(1, 5)] == [7, 13, 0, 0]
    assert row["home_ot"] is None
    assert row["period"] == 4
    assert row["referee"] == "Shawn Smith"
    assert row["grass"] is True
    assert row["attendance"] == 69879
    assert batch_from_rows([row], GAME_SUMMARY_SCHEMA).num_rows == 1


def test_box_score_team() -> None:
    rows = espn.flatten_box_team(load_fixture(f"espn_summary_{GAME}.json"), GAME)
    dallas = next(row for row in rows if row["team_abbreviation"] == "DAL")
    assert dallas["total_yards"] == 307
    assert (dallas["third_down_conversions"], dallas["third_down_attempts"]) == (7, 11)
    assert (dallas["pass_completions"], dallas["pass_attempts"]) == (21, 34)
    assert dallas["interceptions_thrown"] == 0
    assert dallas["possession_seconds"] == 25 * 60 + 8
    assert dallas["yards_per_play"] == Decimal("5.5")
    assert batch_from_rows(rows, BOX_TEAM_SCHEMA).num_rows == 2


def test_box_score_player_merges_categories() -> None:
    rows = espn.flatten_box_player(load_fixture(f"espn_summary_{GAME}.json"), GAME)
    prescott = next(row for row in rows if row["athlete_name"] == "Dak Prescott")
    assert (prescott["pass_completions"], prescott["pass_attempts"], prescott["pass_yards"]) == (21, 34, 188)
    assert prescott["passer_rating"] == Decimal("76.6")
    barkley = next(row for row in rows if row["athlete_name"] == "Saquon Barkley")
    assert (barkley["rush_attempts"], barkley["rush_yards"], barkley["receptions"]) == (18, 60, 4)
    assert len({(row["team_id"], row["athlete_id"]) for row in rows}) == len(rows)
    assert batch_from_rows(rows, BOX_PLAYER_SCHEMA).num_rows == len(rows)


def test_drives_plays_and_scoring() -> None:
    payload = load_fixture(f"espn_summary_{GAME}.json")
    drives = espn.flatten_drives(payload, GAME)
    assert drives[0]["team_abbreviation"] == "DAL"
    assert drives[0]["result"] == "Touchdown"
    assert drives[0]["duration_seconds"] == 191
    assert batch_from_rows(drives, DRIVES_SCHEMA).num_rows == len(drives)

    plays = espn.flatten_plays(payload, GAME)
    assert plays and plays[0]["play_type"] == "Kickoff"
    assert plays[0]["down"] is None
    assert any(play["down"] == 3 for play in plays)
    assert batch_from_rows(plays, PLAYS_SCHEMA).num_rows == len(plays)

    scores = espn.flatten_scoring_plays(payload, GAME)
    assert len(scores) == 8
    assert (scores[-1]["away_score"], scores[-1]["home_score"]) == (20, 24)
    assert batch_from_rows(scores, SCORING_PLAYS_SCHEMA).num_rows == 8


def test_game_log_is_long_format() -> None:
    rows = espn.flatten_game_log(load_fixture("espn_gamelog_3139477_2025.json"), 3139477)
    yards = [row for row in rows if row["stat"] == "passingYards"]
    assert yards and all(row["category"] == "passing" for row in yards)
    assert all(row["season"] == 2025 for row in rows)
    rushing = [row for row in rows if row["stat"] == "rushingYards"]
    assert rushing and rushing[0]["category"] == "rushing"
    assert batch_from_rows(rows, GAME_LOG_SCHEMA).num_rows == len(rows)


def test_state() -> None:
    row = espn.flatten_state(load_fixture("sleeper_state.json"))[0]
    assert row["season"] == 2026
    assert row["phase"] == "regular"
    assert row["season_start_date"] == date(2026, 9, 9)


def test_league_mismatch_is_rejected() -> None:
    with pytest.raises(ValueError, match="instead of the NFL"):
        espn._check_league({"sports": [{"leagues": [{"slug": "eng.1"}]}]})
    with pytest.raises(ValueError, match="non-object"):
        espn._check_league([])
    espn._check_league({"leagues": [{"slug": "nfl"}]})


def test_live_fetchers_through_replay(replay: list[str]) -> None:
    assert len(espn.fetch_teams()[0]) == 32
    assert espn.resolve_team("la")["team_abbreviation"] == "LAR"
    assert espn.resolve_team("WAS")["team_abbreviation"] == "WSH"
    with pytest.raises(espn.UnknownTeamError, match="Unknown NFL team 'XYZ'"):
        espn.resolve_team("XYZ")
    assert len(espn.fetch_standings(2025)[0]) == 32
    assert espn.fetch_scoreboard(2025, 1, 2)[0][0]["season"] == 2025
    assert espn.fetch_scoreboard()[0]
    assert espn.fetch_team_schedule("KC", 2025)[0][0]["week"] == 1
    assert espn.fetch_injuries()[0]
    depth, ttl = espn.fetch_depth_chart("kc")
    assert depth and ttl > 0
    assert espn.fetch_game_log(3139477, 2025)[0]
    assert espn.fetch_state()[0][0]["week"] == 10
    payload, _ttl = espn.fetch_summary(GAME)
    assert payload["header"]["id"] == GAME
    # The team list is fetched once and reused from the in-process cache.
    assert sum(1 for path in replay if path.startswith("/site/teams?")) == 1


def test_bad_identifiers_are_rejected() -> None:
    with pytest.raises(ValueError, match="numeric ESPN event id"):
        espn.fetch_summary("abc")
    with pytest.raises(ValueError, match="positive"):
        espn.fetch_game_log(0)
