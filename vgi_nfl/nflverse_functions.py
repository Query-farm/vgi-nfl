"""VGI table functions over curated nflverse-data releases (CC-BY 4.0)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, ClassVar

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

from vgi_nfl import nflverse
from vgi_nfl.emit import emit_table
from vgi_nfl.meta import meta_class

SOURCE = "nflverse-data (CC-BY 4.0)"
_SEASON_DOC = "Season year (the year the season starts). NULL selects the most recent season."
_WEEK_DOC = "Optional week filter."
_TEAM_DOC = "Optional nflverse team abbreviation filter, for example KC, LA, or WAS (case-insensitive)."


def _season(default_doc: str = _SEASON_DOC, *, ge: int = 1999) -> Arg:
    return Arg("season", default=None, arrow_type=pa.int32(), ge=ge, le=2100, doc=default_doc)


_WEEK = Arg("week", default=None, arrow_type=pa.int32(), ge=0, le=30, doc=_WEEK_DOC)
_TEAM = Arg("team", default=None, arrow_type=pa.string(), pattern=r"^[A-Za-z]{2,3}$", doc=_TEAM_DOC)
_SEASON_TYPE = Arg(
    "season_type",
    default="REG",
    arrow_type=pa.string(),
    choices=tuple(nflverse.SEASON_TYPES),
    doc="REG regular season, POST postseason, or REGPOST combined.",
)


@dataclass(kw_only=True)
class SeasonWeekTeamArgs:
    """Season, optional week, and optional team filters."""

    season: Annotated[int | None, _season()]
    week: Annotated[int | None, _WEEK]
    team: Annotated[str | None, _TEAM]


@dataclass(kw_only=True)
class SnapArgs:
    """Snap-count filters; nflverse snap counts start in 2012."""

    season: Annotated[int | None, _season(ge=2012)]
    week: Annotated[int | None, _WEEK]
    team: Annotated[str | None, _TEAM]


@dataclass(kw_only=True)
class NgsArgs:
    """Next Gen Stats filters; NGS starts in 2016."""

    season: Annotated[
        int | None,
        _season("Season year. NULL returns every season since 2016.", ge=2016),
    ]
    week: Annotated[
        int | None,
        Arg(
            "week",
            default=None,
            arrow_type=pa.int32(),
            ge=0,
            le=30,
            doc=("Optional week filter; week 0 rows are full-season aggregates."),
        ),
    ]
    team: Annotated[str | None, _TEAM]


@dataclass(kw_only=True)
class SeasonTypeArgs:
    """Season, season type, and optional team filters."""

    season: Annotated[int | None, _season()]
    season_type: Annotated[str, _SEASON_TYPE]
    team: Annotated[str | None, _TEAM]


@dataclass(kw_only=True)
class ScheduleArgs:
    """Schedule filters; every argument is optional."""

    season: Annotated[
        int | None,
        _season("Season year. NULL returns every season since 1999."),
    ]
    week: Annotated[int | None, _WEEK]
    team: Annotated[str | None, _TEAM]


@dataclass(kw_only=True)
class DraftArgs:
    """Draft filters; every argument is optional."""

    season: Annotated[
        int | None,
        _season("Draft year. NULL returns every draft since 1980.", ge=1980),
    ]
    team: Annotated[str | None, _TEAM]


@dataclass(kw_only=True)
class CombineArgs:
    """Combine filters."""

    season: Annotated[
        int | None,
        _season("Combine year. NULL returns every combine since 2000.", ge=2000),
    ]


def _run(
    dataset: nflverse.Dataset,
    params: ProcessParams,
    out: OutputCollector,
    **filters: object,
) -> None:
    clean = {key: value for key, value in filters.items() if value is not None}
    table, ttl = nflverse.load(dataset, names=params.output_schema.names, **clean)  # type: ignore[arg-type]
    emit_table(out, table, params.output_schema, ttl)


@init_single_worker
@bind_fixed_schema
class ScheduleFunction(TableFunctionGenerator[ScheduleArgs]):
    """Every NFL game since 1999 with scores, betting lines, venue, weather, and coaches."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = nflverse.SCHEDULE.schema
    Meta = meta_class(
        name="schedule",
        description="NFL schedule and results since 1999 with lines, roof, surface, weather (nflverse)",
        category="scores",
        schema=nflverse.SCHEDULE.schema,
        source=SOURCE,
        doc_llm=(
            "One row per NFL game from nflverse's games file, 1999 to the current season, including "
            "unplayed games. Columns cover final scores, home margin (result), overtime, rest days, "
            "closing spread_line and total_line, roof, surface, temperature, wind, starting QBs, "
            "coaches, referee, and the espn_game_id that joins to game_summary() and box scores. "
            "Filter with season, week, and team (nflverse abbreviations such as KC, LA, WAS)."
        ),
        doc_md=(
            "The nflverse schedule. `game_type` is REG, WC, DIV, CON, or SB; postseason weeks "
            "continue numbering after the regular season. `spread_line` is from the home team's "
            "perspective (positive means the home team was favored)."
        ),
        examples=[
            (
                "Kansas City's 2025 results with the closing spread.",
                "SELECT week, away_team, away_score, home_team, home_score, spread_line "
                "FROM nfl.main.schedule(season := 2025, team := 'KC') ORDER BY week",
            ),
            (
                "Super Bowl results since 2015.",
                "SELECT season, away_team, away_score, home_team, home_score, stadium "
                "FROM nfl.main.schedule() WHERE game_type = 'SB' AND season >= 2015 ORDER BY season",
            ),
        ],
    )

    @classmethod
    def cardinality(cls, params: object) -> TableCardinality:
        """Roughly 285 games a season across 28 seasons."""
        return TableCardinality(estimate=285, max=10_000)

    @classmethod
    def process(cls, params: ProcessParams[ScheduleArgs], state: None, out: OutputCollector) -> None:
        """Load and filter the schedule."""
        args = params.args
        _run(nflverse.SCHEDULE, params, out, season=args.season, week=args.week, team=args.team)


@init_single_worker
@bind_fixed_schema
class PlayByPlayFunction(TableFunctionGenerator[SeasonWeekTeamArgs]):
    """nflverse play-by-play with expected points and win probability."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = nflverse.PLAY_BY_PLAY.schema
    Meta = meta_class(
        name="play_by_play",
        description="Season play-by-play with EPA, win probability, and player ids (nflverse)",
        category="play-by-play",
        schema=nflverse.PLAY_BY_PLAY.schema,
        source=SOURCE,
        doc_llm=(
            "One row per play for an NFL season from nflverse (1999 onward), including expected "
            "points (ep, epa), win probability (wp, wpa), completion probability over expected "
            "(cpoe), success, down and distance, formation flags, and passer/rusher/receiver GSIS "
            "ids and names. Always pass season; add week and team (either side of the game) to "
            "limit the download-backed scan. Use play_by_play_game() for a live ESPN feed."
        ),
        doc_md=(
            "Curated nflverse play-by-play. The season file is downloaded once and cached in "
            "memory; filters apply before rows reach SQL. `posteam` is the offense. Join players "
            "to `players` on GSIS id."
        ),
        examples=[
            (
                "Passing EPA per dropback leaders for 2025 week 1.",
                "SELECT passer_player_name, count(*) AS dropbacks, round(avg(epa), 3) AS epa_per_play "
                "FROM nfl.main.play_by_play(season := 2025, week := 1) "
                "WHERE qb_dropback AND passer_player_name IS NOT NULL "
                "GROUP BY passer_player_name HAVING count(*) >= 20 ORDER BY epa_per_play DESC",
            ),
            (
                "Fourth-down attempts by Philadelphia in 2025.",
                "SELECT week, quarter, yards_to_go, play_type, first_down "
                "FROM nfl.main.play_by_play(season := 2025, team := 'PHI') "
                "WHERE down = 4 AND posteam = 'PHI' AND play_type IN ('run', 'pass') ORDER BY week",
            ),
        ],
    )

    @classmethod
    def cardinality(cls, params: object) -> TableCardinality:
        """A full season is roughly 48,000 plays; one week about 2,800."""
        return TableCardinality(estimate=48_000, max=60_000)

    @classmethod
    def process(cls, params: ProcessParams[SeasonWeekTeamArgs], state: None, out: OutputCollector) -> None:
        """Load and filter a season of play-by-play."""
        args = params.args
        _run(nflverse.PLAY_BY_PLAY, params, out, season=args.season, week=args.week, team=args.team)


@init_single_worker
@bind_fixed_schema
class PlayerStatsWeekFunction(TableFunctionGenerator[SeasonWeekTeamArgs]):
    """Per-game player statistics from nflverse."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = nflverse.PLAYER_STATS_WEEK.schema
    Meta = meta_class(
        name="player_stats_week",
        description="Per-game player passing, rushing, receiving, defense, kicking, and EPA (nflverse)",
        category="player-stats",
        schema=nflverse.PLAYER_STATS_WEEK.schema,
        source=SOURCE,
        doc_llm=(
            "One row per player per game for a season (regular and postseason) from nflverse "
            "stats_player: passing, rushing, receiving, EPA, target share, WOPR, defensive, "
            "kicking, and fantasy points, keyed by GSIS player_id and nflverse game_id. Filter "
            "with season, week, and team. Use player_stats_season() for season totals."
        ),
        doc_md="Weekly nflverse player statistics. `season_type` is REG or POST.",
        examples=[
            (
                "Top rushing games of 2025 week 1.",
                "SELECT player_display_name, team, opponent_team, carries, rushing_yards, rushing_tds "
                "FROM nfl.main.player_stats_week(season := 2025, week := 1) "
                "ORDER BY rushing_yards DESC LIMIT 10",
            )
        ],
    )

    @classmethod
    def cardinality(cls, params: object) -> TableCardinality:
        """Roughly 19,000 player-games a season."""
        return TableCardinality(estimate=19_000, max=30_000)

    @classmethod
    def process(cls, params: ProcessParams[SeasonWeekTeamArgs], state: None, out: OutputCollector) -> None:
        """Load and filter weekly player statistics."""
        args = params.args
        _run(nflverse.PLAYER_STATS_WEEK, params, out, season=args.season, week=args.week, team=args.team)


@init_single_worker
@bind_fixed_schema
class PlayerStatsSeasonFunction(TableFunctionGenerator[SeasonTypeArgs]):
    """Season player statistics from nflverse."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = nflverse.PLAYER_STATS_SEASON.schema
    Meta = meta_class(
        name="player_stats_season",
        description="Season player totals: passing, rushing, receiving, defense, kicking, EPA (nflverse)",
        category="player-stats",
        schema=nflverse.PLAYER_STATS_SEASON.schema,
        source=SOURCE,
        doc_llm=(
            "One row per player for a season from nflverse stats_player: games, passing, rushing, "
            "receiving, EPA, target share, defensive, kicking, and fantasy points. season_type "
            "selects REG (default), POST, or REGPOST. Use it for season leaderboards, for example "
            "passing yards or sacks leaders. recent_team is the player's most recent team."
        ),
        doc_md="Season nflverse player statistics, keyed by GSIS `player_id`.",
        examples=[
            (
                "2025 regular-season passing yards leaders.",
                "SELECT player_display_name, recent_team, passing_yards, passing_tds, interceptions "
                "FROM nfl.main.player_stats_season(season := 2025) "
                "ORDER BY passing_yards DESC LIMIT 10",
            ),
            (
                "2025 sack leaders.",
                "SELECT player_display_name, recent_team, def_sacks "
                "FROM nfl.main.player_stats_season(season := 2025) "
                "ORDER BY def_sacks DESC NULLS LAST LIMIT 10",
            ),
        ],
    )

    @classmethod
    def cardinality(cls, params: object) -> TableCardinality:
        """Roughly 2,000 players appear in a season."""
        return TableCardinality(estimate=2_000, max=3_000)

    @classmethod
    def process(cls, params: ProcessParams[SeasonTypeArgs], state: None, out: OutputCollector) -> None:
        """Load and filter season player statistics."""
        args = params.args
        _run(
            nflverse.PLAYER_STATS_SEASON,
            params,
            out,
            season=args.season,
            season_type=args.season_type,
            team=args.team,
        )


@init_single_worker
@bind_fixed_schema
class TeamStatsFunction(TableFunctionGenerator[SeasonTypeArgs]):
    """Season team statistics from nflverse."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = nflverse.TEAM_STATS.schema
    Meta = meta_class(
        name="team_stats",
        description="Season team offense, defense, special teams, and EPA totals (nflverse)",
        category="team-stats",
        schema=nflverse.TEAM_STATS.schema,
        source=SOURCE,
        doc_llm=(
            "One row per team for a season from nflverse stats_team: passing, rushing, EPA, "
            "first downs, turnovers, penalties, defensive sacks and interceptions, kicking and "
            "punting. season_type selects REG (default), POST, or REGPOST."
        ),
        doc_md="Season nflverse team statistics. Points are in `schedule()` and standings.",
        examples=[
            (
                "2025 teams by rushing yards.",
                "SELECT team, carries, rushing_yards, rushing_tds "
                "FROM nfl.main.team_stats(season := 2025) ORDER BY rushing_yards DESC",
            )
        ],
    )

    @classmethod
    def cardinality(cls, params: object) -> TableCardinality:
        """One row per team."""
        return TableCardinality(estimate=32, max=40)

    @classmethod
    def process(cls, params: ProcessParams[SeasonTypeArgs], state: None, out: OutputCollector) -> None:
        """Load and filter season team statistics."""
        args = params.args
        _run(
            nflverse.TEAM_STATS,
            params,
            out,
            season=args.season,
            season_type=args.season_type,
            team=args.team,
        )


@init_single_worker
@bind_fixed_schema
class DraftFunction(TableFunctionGenerator[DraftArgs]):
    """NFL draft picks since 1980 with career outcomes."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = nflverse.DRAFT.schema
    Meta = meta_class(
        name="draft",
        description="NFL draft picks since 1980 with career value and honors (nflverse)",
        category="draft",
        schema=nflverse.DRAFT.schema,
        source=SOURCE,
        doc_llm=(
            "One row per NFL draft pick since 1980 from nflverse: round, overall pick, team, "
            "position, college, and career outcomes (games, Pro Bowls, All-Pro, Hall of Fame, "
            "approximate value, and career box-score totals). Filter by season (draft year) "
            "and team."
        ),
        doc_md="nflverse draft picks with Pro Football Reference career outcomes.",
        examples=[
            (
                "First round of the 2025 draft.",
                "SELECT pick, team, player_name, position, college "
                "FROM nfl.main.draft(season := 2025) WHERE draft_round = 1 ORDER BY pick",
            )
        ],
    )

    @classmethod
    def cardinality(cls, params: object) -> TableCardinality:
        """About 257 picks a draft across 47 drafts."""
        return TableCardinality(estimate=257, max=15_000)

    @classmethod
    def process(cls, params: ProcessParams[DraftArgs], state: None, out: OutputCollector) -> None:
        """Load and filter draft picks."""
        args = params.args
        _run(nflverse.DRAFT, params, out, season=args.season, team=args.team)


@init_single_worker
@bind_fixed_schema
class CombineFunction(TableFunctionGenerator[CombineArgs]):
    """NFL Scouting Combine measurements since 2000."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = nflverse.COMBINE.schema
    Meta = meta_class(
        name="combine",
        description="NFL Scouting Combine measurements and drills since 2000 (nflverse)",
        category="draft",
        schema=nflverse.COMBINE.schema,
        source=SOURCE,
        doc_llm=(
            "One row per Scouting Combine invitee since 2000 from nflverse: height, weight, 40-yard "
            "dash, bench press, vertical, broad jump, 3-cone and shuttle, plus draft outcome. "
            "Filter by season (combine year)."
        ),
        doc_md="nflverse combine results. Missing drills are NULL.",
        examples=[
            (
                "Fastest 40-yard dashes at the 2025 combine.",
                "SELECT player_name, position, school, forty "
                "FROM nfl.main.combine(season := 2025) WHERE forty IS NOT NULL ORDER BY forty LIMIT 10",
            )
        ],
    )

    @classmethod
    def cardinality(cls, params: object) -> TableCardinality:
        """About 330 invitees a year."""
        return TableCardinality(estimate=330, max=10_000)

    @classmethod
    def process(cls, params: ProcessParams[CombineArgs], state: None, out: OutputCollector) -> None:
        """Load and filter combine results."""
        _run(nflverse.COMBINE, params, out, season=params.args.season)


@init_single_worker
@bind_fixed_schema
class SnapCountsFunction(TableFunctionGenerator[SnapArgs]):
    """Per-game offensive, defensive, and special-teams snap counts."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = nflverse.SNAP_COUNTS.schema
    Meta = meta_class(
        name="snap_counts",
        description="Per-game player snap counts and snap shares since 2012 (nflverse)",
        category="player-stats",
        schema=nflverse.SNAP_COUNTS.schema,
        source=SOURCE,
        doc_llm=(
            "One row per player per game since 2012 from nflverse (sourced from Pro Football "
            "Reference): offensive, defensive, and special-teams snaps with share of team snaps "
            "(0-1). Filter by season, week, and team."
        ),
        doc_md="nflverse snap counts. Percentages are fractions between 0 and 1.",
        examples=[
            (
                "Kansas City's offensive snap shares in 2025 week 1.",
                "SELECT player, position, offense_snaps, offense_pct "
                "FROM nfl.main.snap_counts(season := 2025, week := 1, team := 'KC') "
                "WHERE offense_snaps > 0 ORDER BY offense_snaps DESC",
            )
        ],
    )

    @classmethod
    def cardinality(cls, params: object) -> TableCardinality:
        """About 26,000 player-games a season."""
        return TableCardinality(estimate=26_000, max=35_000)

    @classmethod
    def process(cls, params: ProcessParams[SnapArgs], state: None, out: OutputCollector) -> None:
        """Load and filter snap counts."""
        args = params.args
        _run(nflverse.SNAP_COUNTS, params, out, season=args.season, week=args.week, team=args.team)


def _ngs_meta(dataset: nflverse.Dataset, what: str, doc: str, example: tuple[str, str]) -> type:
    return meta_class(
        name=dataset.name,
        description=f"NFL Next Gen Stats {what} metrics by week and season since 2016 (nflverse)",
        category="next-gen-stats",
        schema=dataset.schema,
        source=SOURCE,
        doc_llm=(
            f"NFL Next Gen Stats {what} tracking metrics from nflverse, one row per qualifying "
            f"player per week since 2016. {doc} Week 0 rows are full-season aggregates, so "
            "filter week := 0 for season leaderboards. Filter by season, week, and team."
        ),
        doc_md=f"Next Gen Stats {what} data. Only qualifying players appear each week.",
        examples=[example],
    )


@init_single_worker
@bind_fixed_schema
class NgsPassingFunction(TableFunctionGenerator[NgsArgs]):
    """Next Gen Stats passing metrics."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = nflverse.NGS_PASSING.schema
    Meta = _ngs_meta(
        nflverse.NGS_PASSING,
        "passing",
        "Includes time to throw, air yards, aggressiveness, and completion percentage above expectation.",
        (
            "2025 season leaders in completion percentage above expectation.",
            "SELECT player_display_name, team, attempts, completion_percentage_above_expectation "
            "FROM nfl.main.ngs_passing(season := 2025, week := 0) WHERE season_type = 'REG' "
            "ORDER BY completion_percentage_above_expectation DESC LIMIT 10",
        ),
    )

    @classmethod
    def cardinality(cls, params: object) -> TableCardinality:
        """About 600 passer-weeks a season."""
        return TableCardinality(estimate=600, max=10_000)

    @classmethod
    def process(cls, params: ProcessParams[NgsArgs], state: None, out: OutputCollector) -> None:
        """Load and filter NGS passing."""
        args = params.args
        _run(nflverse.NGS_PASSING, params, out, season=args.season, week=args.week, team=args.team)


@init_single_worker
@bind_fixed_schema
class NgsReceivingFunction(TableFunctionGenerator[NgsArgs]):
    """Next Gen Stats receiving metrics."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = nflverse.NGS_RECEIVING.schema
    Meta = _ngs_meta(
        nflverse.NGS_RECEIVING,
        "receiving",
        "Includes cushion, separation, intended air yards, and yards after catch over expected.",
        (
            "2025 receivers with the most average separation.",
            "SELECT player_display_name, team, targets, avg_separation "
            "FROM nfl.main.ngs_receiving(season := 2025, week := 0) WHERE season_type = 'REG' "
            "ORDER BY avg_separation DESC LIMIT 10",
        ),
    )

    @classmethod
    def cardinality(cls, params: object) -> TableCardinality:
        """About 1,500 receiver-weeks a season."""
        return TableCardinality(estimate=1_500, max=20_000)

    @classmethod
    def process(cls, params: ProcessParams[NgsArgs], state: None, out: OutputCollector) -> None:
        """Load and filter NGS receiving."""
        args = params.args
        _run(nflverse.NGS_RECEIVING, params, out, season=args.season, week=args.week, team=args.team)


@init_single_worker
@bind_fixed_schema
class NgsRushingFunction(TableFunctionGenerator[NgsArgs]):
    """Next Gen Stats rushing metrics."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = nflverse.NGS_RUSHING.schema
    Meta = _ngs_meta(
        nflverse.NGS_RUSHING,
        "rushing",
        "Includes rush yards over expected, box counts, efficiency, and time behind the line.",
        (
            "2025 rush yards over expected per carry leaders.",
            "SELECT player_display_name, team, rush_attempts, rush_yards_over_expected_per_att "
            "FROM nfl.main.ngs_rushing(season := 2025, week := 0) WHERE season_type = 'REG' "
            "ORDER BY rush_yards_over_expected_per_att DESC LIMIT 10",
        ),
    )

    @classmethod
    def cardinality(cls, params: object) -> TableCardinality:
        """About 600 rusher-weeks a season."""
        return TableCardinality(estimate=600, max=10_000)

    @classmethod
    def process(cls, params: ProcessParams[NgsArgs], state: None, out: OutputCollector) -> None:
        """Load and filter NGS rushing."""
        args = params.args
        _run(nflverse.NGS_RUSHING, params, out, season=args.season, week=args.week, team=args.team)


@init_single_worker
@bind_fixed_schema
class PlayersFunction(TableFunctionGenerator[None]):
    """Scan behind the ``players`` table."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = nflverse.PLAYERS.schema
    Meta = meta_class(
        name="all_players",
        description="Every NFL player nflverse knows with cross-ids (scan behind players)",
        category="players",
        schema=nflverse.PLAYERS.schema,
        source=SOURCE,
        doc_llm="The scan behind the players table. Prefer selecting from the players table itself.",
        doc_md="Returns the nflverse player directory; selecting `players` is normally clearer.",
        examples=[
            (
                "Find a player's ids through the backing scan.",
                "SELECT gsis_id, espn_id, display_name FROM nfl.main.all_players() "
                "WHERE display_name = 'Patrick Mahomes'",
            )
        ],
    )

    @classmethod
    def cardinality(cls, params: object) -> TableCardinality:
        """About 25,000 players."""
        return TableCardinality(estimate=25_000, max=40_000)

    @classmethod
    def process(cls, params: ProcessParams[None], state: None, out: OutputCollector) -> None:
        """Load the player directory."""
        _run(nflverse.PLAYERS, params, out)


NFLVERSE_FUNCTIONS = [
    ScheduleFunction,
    PlayByPlayFunction,
    PlayerStatsWeekFunction,
    PlayerStatsSeasonFunction,
    TeamStatsFunction,
    DraftFunction,
    CombineFunction,
    SnapCountsFunction,
    NgsPassingFunction,
    NgsReceivingFunction,
    NgsRushingFunction,
    PlayersFunction,
]
