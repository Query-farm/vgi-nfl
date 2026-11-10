"""Every table function's process() against the replay server, including projection."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pyarrow as pa
import pytest

from vgi_nfl import espn_functions as e
from vgi_nfl import nflverse_functions as n


class _Out:
    def __init__(self) -> None:
        self.batches: list[pa.RecordBatch] = []
        self.cache_controls: list[Any] = []
        self.finished = False

    def emit(self, batch: pa.RecordBatch, cache_control: Any = None) -> None:
        assert not self.finished
        self.batches.append(batch)
        self.cache_controls.append(cache_control)

    def finish(self) -> None:
        self.finished = True


def _run(function: type, args: Any, schema: pa.Schema | None = None) -> tuple[pa.RecordBatch, Any]:
    out = _Out()
    params = SimpleNamespace(args=args, output_schema=schema or function.FIXED_SCHEMA)
    function.process(params, None, out)
    assert out.finished
    assert len(out.batches) == 1
    return out.batches[0], out.cache_controls[0]


CASES = [
    (e.CurrentScoreboardFunction, None),
    (e.CurrentStandingsFunction, None),
    (e.CurrentInjuriesFunction, None),
    (e.CurrentWeekFunction, None),
    (e.TeamsFunction, None),
    (e.ScoreboardFunction, e.ScoreboardArgs(season=2025, week=1, season_type="regular")),
    (e.StandingsFunction, e.StandingsArgs(season=2025)),
    (e.TeamScheduleFunction, e.TeamScheduleArgs(team="KC", season=2025, season_type="regular")),
    (e.RosterFunction, e.TeamArgs(team="KC")),
    (e.DepthChartFunction, e.TeamArgs(team="KC")),
    (e.GameSummaryFunction, e.GameArgs(game_id="401772510")),
    (e.BoxScoreTeamFunction, e.GameArgs(game_id="401772510")),
    (e.BoxScorePlayerFunction, e.GameArgs(game_id="401772510")),
    (e.DrivesFunction, e.GameArgs(game_id="401772510")),
    (e.ScoringPlaysFunction, e.GameArgs(game_id="401772510")),
    (e.PlayByPlayGameFunction, e.GameArgs(game_id="401772510")),
    (e.PlayerGameLogFunction, e.GameLogArgs(athlete_id=3139477, season=2025)),
    (n.ScheduleFunction, n.ScheduleArgs(season=2025, week=None, team=None)),
    (n.PlayByPlayFunction, n.SeasonWeekTeamArgs(season=2025, week=1, team=None)),
    (n.PlayerStatsWeekFunction, n.SeasonWeekTeamArgs(season=2025, week=1, team="KC")),
    (n.PlayerStatsSeasonFunction, n.SeasonTypeArgs(season=2025, season_type="REG", team=None)),
    (n.TeamStatsFunction, n.SeasonTypeArgs(season=2025, season_type="REG", team=None)),
    (n.DraftFunction, n.DraftArgs(season=2025, team=None)),
    (n.CombineFunction, n.CombineArgs(season=2025)),
    (n.SnapCountsFunction, n.SnapArgs(season=2025, week=1, team="KC")),
    (n.NgsPassingFunction, n.NgsArgs(season=2025, week=0, team=None)),
    (n.NgsReceivingFunction, n.NgsArgs(season=None, week=None, team=None)),
    (n.NgsRushingFunction, n.NgsArgs(season=2025, week=None, team=None)),
    (n.PlayersFunction, None),
]


def test_cases_cover_every_function() -> None:
    assert {function for function, _ in CASES} == {*e.ESPN_FUNCTIONS, *n.NFLVERSE_FUNCTIONS}


@pytest.mark.parametrize(("function", "args"), CASES, ids=lambda value: getattr(value, "__name__", ""))
def test_process_emits_full_schema(replay: list[str], function: type, args: Any) -> None:
    batch, cache = _run(function, args)
    assert batch.schema == function.FIXED_SCHEMA
    assert batch.num_rows > 0
    assert cache is not None and cache.ttl > 0
    cardinality = function.cardinality(None)
    assert cardinality.max >= 1


@pytest.mark.parametrize(("function", "args"), CASES, ids=lambda value: getattr(value, "__name__", ""))
def test_process_honors_projection(replay: list[str], function: type, args: Any) -> None:
    schema = function.FIXED_SCHEMA
    projected = pa.schema([schema.field(schema.names[-1]), schema.field(schema.names[0])])
    batch, _cache = _run(function, args, projected)
    assert batch.schema == projected


def test_empty_result_keeps_schema(replay: list[str]) -> None:
    batch, _ = _run(n.DraftFunction, n.DraftArgs(season=2025, team="ZZZ"))
    assert batch.num_rows == 0
    assert batch.schema == n.DraftFunction.FIXED_SCHEMA
