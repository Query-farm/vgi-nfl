"""VGI table functions backed by ESPN's undocumented NFL APIs and Sleeper's state API."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any, ClassVar

import pyarrow as pa
from vgi.arguments import Arg
from vgi.table_function import (
    ProcessParams,
    TableCardinality,
    TableFunctionGenerator,
    bind_fixed_schema,
    init_single_worker,
)
from vgi_rpc.rpc import OutputCollector

from vgi_nfl import espn
from vgi_nfl.emit import emit_rows
from vgi_nfl.espn_schemas import (
    BOX_PLAYER_SCHEMA,
    BOX_TEAM_SCHEMA,
    CURRENT_WEEK_SCHEMA,
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
from vgi_nfl.meta import meta_class

ESPN = "ESPN site/core/common API (undocumented; ESPN terms apply)"
SLEEPER = "Sleeper public API"
_TEAM_PATTERN = r"^[A-Za-z]{2,3}$"
_TEAM = Arg(
    0,
    arrow_type=pa.string(),
    pattern=_TEAM_PATTERN,
    doc="Team abbreviation such as KC, PHI, or WSH (nflverse LA and WAS are accepted).",
)
_GAME_ID = Arg(
    0,
    arrow_type=pa.string(),
    pattern=r"^\d{6,12}$",
    doc="ESPN event id as text, for example '401772510' (see scoreboard() or schedule().espn_game_id).",
)
_SEASON_TYPE = Arg(
    "season_type",
    default="regular",
    arrow_type=pa.string(),
    choices=tuple(espn.SEASON_TYPES),
    doc="preseason, regular, or postseason.",
)


@dataclass(kw_only=True)
class ScoreboardArgs:
    """Arguments for ``scoreboard``."""

    season: Annotated[int, Arg(0, arrow_type=pa.int32(), ge=2002, le=2100, doc="Season year.")]
    week: Annotated[
        int,
        Arg(
            1,
            arrow_type=pa.int32(),
            ge=1,
            le=23,
            doc="Week within the season type; postseason weeks are 1 wild card through 5 Super Bowl.",
        ),
    ]
    season_type: Annotated[str, _SEASON_TYPE]


@dataclass(kw_only=True)
class StandingsArgs:
    """Arguments for ``standings``."""

    season: Annotated[
        int | None,
        Arg(
            "season",
            default=None,
            arrow_type=pa.int32(),
            ge=2002,
            le=2100,
            doc="Season year. NULL asks ESPN for the current season.",
        ),
    ]


@dataclass(kw_only=True)
class TeamScheduleArgs:
    """Arguments for ``team_schedule``."""

    team: Annotated[str, _TEAM]
    season: Annotated[
        int | None,
        Arg(
            "season",
            default=None,
            arrow_type=pa.int32(),
            ge=2002,
            le=2100,
            doc="Season year. NULL asks ESPN for the current season.",
        ),
    ]
    season_type: Annotated[str, _SEASON_TYPE]


@dataclass(kw_only=True)
class TeamArgs:
    """A single team argument."""

    team: Annotated[str, _TEAM]


@dataclass(kw_only=True)
class GameArgs:
    """A single ESPN game id argument."""

    game_id: Annotated[str, _GAME_ID]


@dataclass(kw_only=True)
class GameLogArgs:
    """Arguments for ``player_game_log``."""

    athlete_id: Annotated[
        int,
        Arg(
            0,
            arrow_type=pa.int32(),
            ge=1,
            doc="ESPN athlete id (roster().athlete_id or players.espn_id), for example 3139477.",
        ),
    ]
    season: Annotated[
        int | None,
        Arg(
            "season",
            default=None,
            arrow_type=pa.int32(),
            ge=2002,
            le=2100,
            doc="Season year. NULL asks ESPN for the athlete's current season.",
        ),
    ]


def _emit(
    fetch: Callable[[], tuple[list[dict[str, Any]], int]], params: ProcessParams, out: OutputCollector
) -> None:
    rows, ttl = fetch()
    emit_rows(out, rows, params.output_schema, ttl)


def _emit_game(
    flatten: Callable[[Any, str], list[dict[str, Any]]], params: ProcessParams, out: OutputCollector
) -> None:
    game_id = params.args.game_id
    payload, ttl = espn.fetch_summary(game_id)
    emit_rows(out, flatten(payload, game_id), params.output_schema, ttl)


# ------------------------------------------------------------------ current scans


@init_single_worker
@bind_fixed_schema
class CurrentScoreboardFunction(TableFunctionGenerator[None]):
    """Scan behind ``current_scoreboard``."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = EVENT_SCHEMA
    Meta = meta_class(
        name="all_current_scoreboard",
        description="This week's NFL games and live scores (scan behind current_scoreboard)",
        category="scores",
        schema=EVENT_SCHEMA,
        source=ESPN,
        doc_llm="The scan behind current_scoreboard. Prefer the table; use scoreboard() for other weeks.",
        doc_md="Returns ESPN's current-week scoreboard; selecting `current_scoreboard` is clearer.",
        examples=[
            (
                "Read this week's games through the backing scan.",
                "SELECT short_name, status_detail, away_score, home_score "
                "FROM nfl.main.all_current_scoreboard() ORDER BY game_time",
            )
        ],
    )

    @classmethod
    def cardinality(cls, params: object) -> TableCardinality:
        """An NFL week has at most 16 games."""
        return TableCardinality(estimate=16, max=20)

    @classmethod
    def process(cls, params: ProcessParams[None], state: None, out: OutputCollector) -> None:
        """Fetch the current scoreboard."""
        _emit(espn.fetch_scoreboard, params, out)


@init_single_worker
@bind_fixed_schema
class CurrentStandingsFunction(TableFunctionGenerator[None]):
    """Scan behind ``current_standings``."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = STANDINGS_SCHEMA
    Meta = meta_class(
        name="all_current_standings",
        description="Current NFL division standings (scan behind current_standings)",
        category="standings",
        schema=STANDINGS_SCHEMA,
        source=ESPN,
        doc_llm="The scan behind current_standings. Prefer the table; use standings() for past seasons.",
        doc_md="Returns ESPN's current division standings; selecting `current_standings` is clearer.",
        examples=[
            (
                "Division leaders through the backing scan.",
                "SELECT division, team_name, wins, losses FROM nfl.main.all_current_standings() "
                "WHERE division_rank = 1 ORDER BY division",
            )
        ],
    )

    @classmethod
    def cardinality(cls, params: object) -> TableCardinality:
        """Thirty-two teams."""
        return TableCardinality(estimate=32, max=40)

    @classmethod
    def process(cls, params: ProcessParams[None], state: None, out: OutputCollector) -> None:
        """Fetch current standings."""
        _emit(espn.fetch_standings, params, out)


@init_single_worker
@bind_fixed_schema
class CurrentInjuriesFunction(TableFunctionGenerator[None]):
    """Scan behind ``current_injuries``."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = INJURY_SCHEMA
    Meta = meta_class(
        name="all_current_injuries",
        description="League-wide NFL injury report (scan behind current_injuries)",
        category="injuries",
        schema=INJURY_SCHEMA,
        source=ESPN,
        doc_llm="The scan behind current_injuries. Prefer the table.",
        doc_md="Returns ESPN's league-wide injury report; selecting `current_injuries` is clearer.",
        examples=[
            (
                "Players ruled out through the backing scan.",
                "SELECT team_abbreviation, athlete_name, injury_type FROM nfl.main.all_current_injuries() "
                "WHERE status = 'Out' ORDER BY team_abbreviation",
            )
        ],
    )

    @classmethod
    def cardinality(cls, params: object) -> TableCardinality:
        """Several hundred report entries."""
        return TableCardinality(estimate=800, max=3_000)

    @classmethod
    def process(cls, params: ProcessParams[None], state: None, out: OutputCollector) -> None:
        """Fetch the injury report."""
        _emit(espn.fetch_injuries, params, out)


@init_single_worker
@bind_fixed_schema
class CurrentWeekFunction(TableFunctionGenerator[None]):
    """Scan behind ``current_week``."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = CURRENT_WEEK_SCHEMA
    Meta = meta_class(
        name="all_current_week",
        description="Current NFL season, phase, and week from Sleeper (scan behind current_week)",
        category="calendar",
        schema=CURRENT_WEEK_SCHEMA,
        source=SLEEPER,
        doc_llm="The scan behind current_week. Prefer the table.",
        doc_md="Returns Sleeper's NFL state; selecting `current_week` is clearer.",
        examples=[
            (
                "Current season and week through the backing scan.",
                "SELECT season, phase, week FROM nfl.main.all_current_week()",
            )
        ],
    )

    @classmethod
    def cardinality(cls, params: object) -> TableCardinality:
        """Exactly one row."""
        return TableCardinality(estimate=1, max=1)

    @classmethod
    def process(cls, params: ProcessParams[None], state: None, out: OutputCollector) -> None:
        """Fetch the current NFL state."""
        _emit(espn.fetch_state, params, out)


@init_single_worker
@bind_fixed_schema
class TeamsFunction(TableFunctionGenerator[None]):
    """Scan behind ``teams``."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = TEAMS_SCHEMA
    Meta = meta_class(
        name="all_teams",
        description="The 32 NFL franchises with ESPN ids and abbreviations (scan behind teams)",
        category="teams",
        schema=TEAMS_SCHEMA,
        source=ESPN,
        doc_llm="The scan behind the teams table. Prefer the table.",
        doc_md="Returns ESPN's NFL team list; selecting `teams` is clearer.",
        examples=[
            (
                "Team ids through the backing scan.",
                "SELECT team_id, team_abbreviation, team_name FROM nfl.main.all_teams() ORDER BY team_name",
            )
        ],
    )

    @classmethod
    def cardinality(cls, params: object) -> TableCardinality:
        """Thirty-two franchises."""
        return TableCardinality(estimate=32, max=40)

    @classmethod
    def process(cls, params: ProcessParams[None], state: None, out: OutputCollector) -> None:
        """Fetch the team list."""
        _emit(espn.fetch_teams, params, out)


# --------------------------------------------------------------- parameterized


@init_single_worker
@bind_fixed_schema
class ScoreboardFunction(TableFunctionGenerator[ScoreboardArgs]):
    """Scores for any NFL week."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = EVENT_SCHEMA
    Meta = meta_class(
        name="scoreboard",
        description="NFL games and scores for a season, week, and season type (ESPN)",
        category="scores",
        schema=EVENT_SCHEMA,
        source=ESPN,
        doc_llm=(
            "One row per game for a given season and week from ESPN's scoreboard: kickoff time, "
            "status, home/away teams, scores, records, winner, venue, attendance, and broadcast. "
            "season and week are positional; season_type => 'postseason' selects playoff weeks "
            "(1 wild card, 2 divisional, 3 conference, 5 Super Bowl). game_id feeds game_summary()."
        ),
        doc_md=(
            "ESPN scoreboard for one week. Scores are NULL before kickoff. Use `current_scoreboard` "
            "for this week."
        ),
        examples=[
            (
                "2025 week 1 results.",
                "SELECT short_name, away_score, home_score, winner_abbreviation "
                "FROM nfl.main.scoreboard(2025, 1) ORDER BY game_time",
            ),
            (
                "The Super Bowl that ended the 2025 season.",
                "SELECT name, away_score, home_score, venue "
                "FROM nfl.main.scoreboard(2025, 5, season_type := 'postseason')",
            ),
        ],
    )

    @classmethod
    def cardinality(cls, params: object) -> TableCardinality:
        """An NFL week has at most 16 games."""
        return TableCardinality(estimate=16, max=20)

    @classmethod
    def process(cls, params: ProcessParams[ScoreboardArgs], state: None, out: OutputCollector) -> None:
        """Fetch one week's scoreboard."""
        args = params.args
        _emit(
            lambda: espn.fetch_scoreboard(args.season, args.week, espn.SEASON_TYPES[args.season_type]),
            params,
            out,
        )


@init_single_worker
@bind_fixed_schema
class StandingsFunction(TableFunctionGenerator[StandingsArgs]):
    """Division standings for any season."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = STANDINGS_SCHEMA
    Meta = meta_class(
        name="standings",
        description="NFL division standings for a season with seeds, streaks, and splits (ESPN)",
        category="standings",
        schema=STANDINGS_SCHEMA,
        source=ESPN,
        doc_llm=(
            "One row per team with conference, division, division_rank, playoff_seed, W-L-T, "
            "win percentage, games back, points for/against, streak, home/road/division/"
            "conference records, and clinch marker for a regular season. Pass season for "
            "history (2002 onward); with no arguments it returns the current season."
        ),
        doc_md=(
            "ESPN regular-season standings. `playoff_seed` 1-7 make the playoffs; "
            "`division_rank` is derived from ESPN's tiebreak-aware seed order."
        ),
        examples=[
            (
                "Final 2025 AFC standings by seed.",
                "SELECT playoff_seed, team_name, wins, losses, ties, clincher "
                "FROM nfl.main.standings(season := 2025) WHERE conference = 'AFC' ORDER BY playoff_seed",
            )
        ],
    )

    @classmethod
    def cardinality(cls, params: object) -> TableCardinality:
        """Thirty-two teams."""
        return TableCardinality(estimate=32, max=40)

    @classmethod
    def process(cls, params: ProcessParams[StandingsArgs], state: None, out: OutputCollector) -> None:
        """Fetch standings for one season."""
        _emit(lambda: espn.fetch_standings(params.args.season), params, out)


@init_single_worker
@bind_fixed_schema
class TeamScheduleFunction(TableFunctionGenerator[TeamScheduleArgs]):
    """One team's games for a season."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = EVENT_SCHEMA
    Meta = meta_class(
        name="team_schedule",
        description="One NFL team's games and results for a season and season type (ESPN)",
        category="scores",
        schema=EVENT_SCHEMA,
        source=ESPN,
        doc_llm=(
            "One row per game on a team's schedule from ESPN, with scores and status. The team is "
            "positional (KC, PHI, ...); season defaults to ESPN's current season and season_type "
            "to regular. Use schedule() for every team at once with betting lines and weather."
        ),
        doc_md="ESPN team schedule. Bye weeks have no row.",
        examples=[
            (
                "Kansas City's 2025 regular season.",
                "SELECT week, short_name, away_score, home_score, winner_abbreviation "
                "FROM nfl.main.team_schedule('KC', season := 2025) ORDER BY week",
            )
        ],
    )

    @classmethod
    def cardinality(cls, params: object) -> TableCardinality:
        """Seventeen regular-season games."""
        return TableCardinality(estimate=17, max=25)

    @classmethod
    def process(cls, params: ProcessParams[TeamScheduleArgs], state: None, out: OutputCollector) -> None:
        """Fetch one team's schedule."""
        args = params.args
        _emit(
            lambda: espn.fetch_team_schedule(args.team, args.season, espn.SEASON_TYPES[args.season_type]),
            params,
            out,
        )


@init_single_worker
@bind_fixed_schema
class RosterFunction(TableFunctionGenerator[TeamArgs]):
    """One team's current roster."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = ROSTER_SCHEMA
    Meta = meta_class(
        name="roster",
        description="One NFL team's current roster with positions, bio, and status (ESPN)",
        category="rosters",
        schema=ROSTER_SCHEMA,
        source=ESPN,
        doc_llm=(
            "One row per player currently on a team's roster from ESPN, grouped as offense, "
            "defense, specialTeam, injuredReserveOrOut, suspended, or practiceSquad, with jersey, "
            "position, age, height, weight, experience, and college. athlete_id feeds "
            "player_game_log(). ESPN serves only the current roster; use players for history."
        ),
        doc_md="ESPN current team roster.",
        examples=[
            (
                "Kansas City's quarterbacks.",
                "SELECT athlete_name, jersey, age, experience_years FROM nfl.main.roster('KC') "
                "WHERE position = 'QB'",
            )
        ],
    )

    @classmethod
    def cardinality(cls, params: object) -> TableCardinality:
        """About 70 players including the practice squad."""
        return TableCardinality(estimate=70, max=120)

    @classmethod
    def process(cls, params: ProcessParams[TeamArgs], state: None, out: OutputCollector) -> None:
        """Fetch one team's roster."""
        _emit(lambda: espn.fetch_roster(params.args.team), params, out)


@init_single_worker
@bind_fixed_schema
class DepthChartFunction(TableFunctionGenerator[TeamArgs]):
    """One team's current depth chart."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = DEPTH_CHART_SCHEMA
    Meta = meta_class(
        name="depth_chart",
        description="One NFL team's current depth chart by formation and slot (ESPN)",
        category="rosters",
        schema=DEPTH_CHART_SCHEMA,
        source=ESPN,
        doc_llm=(
            "One row per player per depth-chart slot for a team's current offense, defense, and "
            "special-teams formations from ESPN. depth = 1 is the starter. Names come from the "
            "team's current roster."
        ),
        doc_md="ESPN current depth chart; `depth` 1 is the starter in each slot.",
        examples=[
            (
                "Kansas City's offensive starters.",
                "SELECT position, athlete_name FROM nfl.main.depth_chart('KC') "
                "WHERE depth = 1 AND formation NOT IN ('Special Teams') ORDER BY formation, position",
            )
        ],
    )

    @classmethod
    def cardinality(cls, params: object) -> TableCardinality:
        """About 28 slots with two to four players each."""
        return TableCardinality(estimate=80, max=200)

    @classmethod
    def process(cls, params: ProcessParams[TeamArgs], state: None, out: OutputCollector) -> None:
        """Fetch one team's depth chart."""
        _emit(lambda: espn.fetch_depth_chart(params.args.team), params, out)


def _game_meta(
    *, name: str, description: str, category: str, schema: pa.Schema, doc_llm: str, example: tuple[str, str]
) -> type:
    return meta_class(
        name=name,
        description=description,
        category=category,
        schema=schema,
        source=ESPN,
        doc_llm=(
            f"{doc_llm} The single positional argument is ESPN's game id as text (from "
            "scoreboard(), team_schedule(), or schedule().espn_game_id). Works for live and "
            "completed games."
        ),
        doc_md=f"{description}. Backed by one cached ESPN game-summary request.",
        examples=[example],
    )


@init_single_worker
@bind_fixed_schema
class GameSummaryFunction(TableFunctionGenerator[GameArgs]):
    """One game's header: teams, score by quarter, venue, and officials."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = GAME_SUMMARY_SCHEMA
    Meta = _game_meta(
        name="game_summary",
        description="One NFL game's status, score by quarter, venue, and referee (ESPN)",
        category="game-detail",
        schema=GAME_SUMMARY_SCHEMA,
        doc_llm="One row describing a game: teams, status, final score, quarter-by-quarter points.",
        example=(
            "Score by quarter of the 2025 season opener.",
            "SELECT away_team_abbreviation, away_q1, away_q2, away_q3, away_q4, away_score, "
            "home_team_abbreviation, home_q1, home_q2, home_q3, home_q4, home_score "
            "FROM nfl.main.game_summary('401772510')",
        ),
    )

    @classmethod
    def cardinality(cls, params: object) -> TableCardinality:
        """Exactly one game."""
        return TableCardinality(estimate=1, max=1)

    @classmethod
    def process(cls, params: ProcessParams[GameArgs], state: None, out: OutputCollector) -> None:
        """Fetch a game summary."""
        _emit_game(lambda payload, _game: espn.flatten_game_summary(payload), params, out)


@init_single_worker
@bind_fixed_schema
class BoxScoreTeamFunction(TableFunctionGenerator[GameArgs]):
    """Team box score for one game."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = BOX_TEAM_SCHEMA
    Meta = _game_meta(
        name="box_score_team",
        description="Team box score for one NFL game: yards, downs, turnovers, possession (ESPN)",
        category="game-detail",
        schema=BOX_TEAM_SCHEMA,
        doc_llm=(
            "Two rows, one per team: first downs, third/fourth-down conversions, total yards, "
            "passing and rushing splits, red zone, penalties, turnovers, and time of possession."
        ),
        example=(
            "Team totals from the 2025 season opener.",
            "SELECT team_abbreviation, total_yards, passing_yards, rushing_yards, turnovers, "
            "possession_seconds FROM nfl.main.box_score_team('401772510')",
        ),
    )

    @classmethod
    def cardinality(cls, params: object) -> TableCardinality:
        """Two teams."""
        return TableCardinality(estimate=2, max=2)

    @classmethod
    def process(cls, params: ProcessParams[GameArgs], state: None, out: OutputCollector) -> None:
        """Fetch a team box score."""
        _emit_game(espn.flatten_box_team, params, out)


@init_single_worker
@bind_fixed_schema
class BoxScorePlayerFunction(TableFunctionGenerator[GameArgs]):
    """Player box score for one game."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = BOX_PLAYER_SCHEMA
    Meta = _game_meta(
        name="box_score_player",
        description="Player box score for one NFL game, one row per player (ESPN)",
        category="game-detail",
        schema=BOX_PLAYER_SCHEMA,
        doc_llm=(
            "One row per player who recorded a stat, merging ESPN's passing, rushing, receiving, "
            "fumbles, defense, interception, return, kicking, and punting tables. Columns for "
            "categories a player did not record are NULL."
        ),
        example=(
            "Leading rushers in the 2025 season opener.",
            "SELECT athlete_name, team_abbreviation, rush_attempts, rush_yards, rush_touchdowns "
            "FROM nfl.main.box_score_player('401772510') WHERE rush_attempts > 0 "
            "ORDER BY rush_yards DESC",
        ),
    )

    @classmethod
    def cardinality(cls, params: object) -> TableCardinality:
        """About 60 players record a stat."""
        return TableCardinality(estimate=60, max=120)

    @classmethod
    def process(cls, params: ProcessParams[GameArgs], state: None, out: OutputCollector) -> None:
        """Fetch a player box score."""
        _emit_game(espn.flatten_box_player, params, out)


@init_single_worker
@bind_fixed_schema
class DrivesFunction(TableFunctionGenerator[GameArgs]):
    """Drive chart for one game."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = DRIVES_SCHEMA
    Meta = _game_meta(
        name="drives",
        description="Drive chart for one NFL game: start, end, plays, yards, result (ESPN)",
        category="game-detail",
        schema=DRIVES_SCHEMA,
        doc_llm="One row per drive with the offense, field position, plays, yards, duration, and result.",
        example=(
            "Scoring drives in the 2025 season opener.",
            "SELECT drive_number, team_abbreviation, plays, yards, result "
            "FROM nfl.main.drives('401772510') WHERE is_score ORDER BY drive_number",
        ),
    )

    @classmethod
    def cardinality(cls, params: object) -> TableCardinality:
        """About 22 drives a game."""
        return TableCardinality(estimate=22, max=40)

    @classmethod
    def process(cls, params: ProcessParams[GameArgs], state: None, out: OutputCollector) -> None:
        """Fetch a drive chart."""
        _emit_game(espn.flatten_drives, params, out)


@init_single_worker
@bind_fixed_schema
class ScoringPlaysFunction(TableFunctionGenerator[GameArgs]):
    """Scoring summary for one game."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = SCORING_PLAYS_SCHEMA
    Meta = _game_meta(
        name="scoring_plays",
        description="Scoring summary for one NFL game with the running score (ESPN)",
        category="game-detail",
        schema=SCORING_PLAYS_SCHEMA,
        doc_llm="One row per score with quarter, clock, team, scoring type, description, and score after.",
        example=(
            "Scoring summary of the 2025 season opener.",
            "SELECT period, clock, team_abbreviation, description, away_score, home_score "
            "FROM nfl.main.scoring_plays('401772510')",
        ),
    )

    @classmethod
    def cardinality(cls, params: object) -> TableCardinality:
        """About nine scores a game."""
        return TableCardinality(estimate=9, max=30)

    @classmethod
    def process(cls, params: ProcessParams[GameArgs], state: None, out: OutputCollector) -> None:
        """Fetch a scoring summary."""
        _emit_game(espn.flatten_scoring_plays, params, out)


@init_single_worker
@bind_fixed_schema
class PlayByPlayGameFunction(TableFunctionGenerator[GameArgs]):
    """ESPN play-by-play for one game."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = PLAYS_SCHEMA
    Meta = _game_meta(
        name="play_by_play_game",
        description="Play-by-play for one NFL game, live or final (ESPN)",
        category="play-by-play",
        schema=PLAYS_SCHEMA,
        doc_llm=(
            "One row per play in ESPN's drive chart: offense, quarter, clock, down and distance, "
            "play type, text, yards, scoring/penalty/turnover flags, and the running score. "
            "Updates during live games; use play_by_play() for nflverse EPA and win probability."
        ),
        example=(
            "Fourth-quarter plays of the 2025 season opener.",
            "SELECT clock, offense_abbreviation, down_distance_text, play_type, yards "
            "FROM nfl.main.play_by_play_game('401772510') WHERE period = 4 ORDER BY sequence",
        ),
    )

    @classmethod
    def cardinality(cls, params: object) -> TableCardinality:
        """About 180 plays a game."""
        return TableCardinality(estimate=180, max=400)

    @classmethod
    def process(cls, params: ProcessParams[GameArgs], state: None, out: OutputCollector) -> None:
        """Fetch a game's plays."""
        _emit_game(espn.flatten_plays, params, out)


@init_single_worker
@bind_fixed_schema
class PlayerGameLogFunction(TableFunctionGenerator[GameLogArgs]):
    """One player's per-game statistics."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = GAME_LOG_SCHEMA
    Meta = meta_class(
        name="player_game_log",
        description="One NFL player's per-game statistics for a season, one row per game and stat (ESPN)",
        category="player-stats",
        schema=GAME_LOG_SCHEMA,
        source=ESPN,
        doc_llm=(
            "Long-format game log from ESPN: one row per game per stat for an athlete and season, "
            "with week, opponent, home/away, result, category (passing, rushing, receiving, "
            "defensive, ...), stat key such as passingYards, and exact numeric value. Pivot or "
            "filter on stat. The athlete id is ESPN's (roster().athlete_id or players.espn_id)."
        ),
        doc_md="ESPN athlete game log. Stats offered depend on the player's position.",
        examples=[
            (
                "Patrick Mahomes's 2025 passing yards by week.",
                "SELECT week, opponent_abbreviation, result, value AS passing_yards "
                "FROM nfl.main.player_game_log(3139477, season := 2025) "
                "WHERE stat = 'passingYards' ORDER BY week",
            )
        ],
    )

    @classmethod
    def cardinality(cls, params: object) -> TableCardinality:
        """Seventeen games times about fifteen stats."""
        return TableCardinality(estimate=270, max=1_000)

    @classmethod
    def process(cls, params: ProcessParams[GameLogArgs], state: None, out: OutputCollector) -> None:
        """Fetch one athlete's game log."""
        args = params.args
        _emit(lambda: espn.fetch_game_log(args.athlete_id, args.season), params, out)


ESPN_FUNCTIONS = [
    CurrentScoreboardFunction,
    CurrentStandingsFunction,
    CurrentInjuriesFunction,
    CurrentWeekFunction,
    TeamsFunction,
    ScoreboardFunction,
    StandingsFunction,
    TeamScheduleFunction,
    RosterFunction,
    DepthChartFunction,
    GameSummaryFunction,
    BoxScoreTeamFunction,
    BoxScorePlayerFunction,
    DrivesFunction,
    ScoringPlaysFunction,
    PlayByPlayGameFunction,
    PlayerGameLogFunction,
]
