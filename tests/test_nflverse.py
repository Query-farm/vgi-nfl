"""Curated nflverse reads from recorded (trimmed, real) release assets."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from vgi_nfl import nflverse

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "nflverse"


@pytest.mark.parametrize("dataset", nflverse.DATASETS, ids=lambda dataset: dataset.name)
def test_every_curated_column_exists_upstream(dataset: nflverse.Dataset) -> None:
    path = dataset.path.format(season=2025, kind="reg")
    upstream = set(pq.read_schema(FIXTURES / path).names)
    missing = [column.source_name for column in dataset.columns if column.source_name not in upstream]
    assert missing == []
    assert all(value.metadata and value.metadata[b"comment"] for value in dataset.schema)


@pytest.mark.parametrize("dataset", nflverse.DATASETS, ids=lambda dataset: dataset.name)
def test_read_columns_matches_schema(dataset: nflverse.Dataset) -> None:
    body = (FIXTURES / dataset.path.format(season=2025, kind="reg")).read_bytes()
    table = nflverse.read_columns(body, dataset.columns, dataset.schema.names)
    assert table.schema == dataset.schema
    assert table.num_rows > 0


def test_projection_and_missing_columns_are_null() -> None:
    body = (FIXTURES / "combine/combine.parquet").read_bytes()
    extra = nflverse.Column("not_upstream", pa.int32(), "Synthetic.")
    table = nflverse.read_columns(body, (*nflverse.COMBINE.columns, extra), ["player_name", "not_upstream"])
    assert table.column_names == ["player_name", "not_upstream"]
    assert table.column("not_upstream").null_count == table.num_rows


def test_current_season_rolls_over_in_september() -> None:
    assert nflverse.current_season(datetime(2026, 8, 31, tzinfo=UTC)) == 2025
    assert nflverse.current_season(datetime(2026, 9, 1, tzinfo=UTC)) == 2026
    assert nflverse.current_season(datetime(2027, 1, 15, tzinfo=UTC)) == 2026


def test_schedule_filters_and_types(replay: list[str]) -> None:
    table, ttl = nflverse.load(nflverse.SCHEDULE, names=nflverse.SCHEDULE.schema.names, season=2025, week=1)
    assert ttl >= nflverse.api.NFLVERSE.min_ttl
    opener = next(row for row in table.to_pylist() if row["home_team"] == "PHI")
    assert opener["espn_game_id"] == "401772510"
    assert opener["game_date"] == date(2025, 9, 4)
    assert (opener["away_score"], opener["home_score"]) == (20, 24)
    assert opener["overtime"] is False
    assert opener["division_game"] is True
    kc, _ = nflverse.load(nflverse.SCHEDULE, names=["week", "home_team", "away_team"], season=2025, team="kc")
    assert kc.num_rows == 2
    assert all("KC" in (row["home_team"], row["away_team"]) for row in kc.to_pylist())


def test_play_by_play_types(replay: list[str]) -> None:
    names = ["game_id", "play_id", "quarter", "down", "qb_dropback", "epa", "game_date"]
    table, _ = nflverse.load(nflverse.PLAY_BY_PLAY, names=names, season=2025, week=1, team="PHI")
    assert set(table.column("game_id").to_pylist()) == {"2025_01_DAL_PHI"}
    assert table.schema.field("play_id").type == pa.int64()
    assert table.schema.field("qb_dropback").type == pa.bool_()
    assert table.schema.field("game_date").type == pa.date32()
    assert any(table.column("qb_dropback").to_pylist())


def test_season_stats_select_file_by_season_type(replay: list[str]) -> None:
    table, _ = nflverse.load(
        nflverse.PLAYER_STATS_SEASON, names=["player_display_name", "passing_yards"], season=2025
    )
    stafford = next(row for row in table.to_pylist() if row["player_display_name"] == "Matthew Stafford")
    assert stafford["passing_yards"] == 4707
    assert any(path.endswith("stats_player_reg_2025.parquet") for path in replay)


def test_missing_release_asset_is_a_clear_error(replay: list[str]) -> None:
    with pytest.raises(LookupError, match="nflverse has not published pbp/play_by_play_2024.parquet"):
        nflverse.load(nflverse.PLAY_BY_PLAY, names=["game_id"], season=2024)


def test_seasons_before_coverage_are_rejected() -> None:
    with pytest.raises(ValueError, match="starts with the 2012 season"):
        nflverse.load(nflverse.SNAP_COUNTS, names=["player"], season=2010)


def test_non_parquet_body_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_fetch(*args, validate, **kwargs):
        validate(b"<html>")

    monkeypatch.setattr(nflverse.api, "fetch", fake_fetch)
    with pytest.raises(ValueError, match="not a Parquet file"):
        nflverse.fetch_parquet("schedules/games.parquet")


def test_team_abbreviations_are_normalized(replay: list[str]) -> None:
    draft, _ = nflverse.load(nflverse.DRAFT, names=["pick", "team"], season=2025, team="KC")
    assert draft.column("team").to_pylist() == ["KC"]
    assert (
        "NWE" not in nflverse.load(nflverse.DRAFT, names=["team"], season=2025)[0].column("team").to_pylist()
    )
    rams, _ = nflverse.load(nflverse.NGS_RUSHING, names=["team"], season=2025, team="LAR")
    assert set(rams.column("team").to_pylist()) <= {"LA"}
