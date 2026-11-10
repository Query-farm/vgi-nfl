"""Typed, curated views over nflverse-data release assets (CC-BY 4.0).

nflverse publishes NFL play-by-play, player and team statistics, schedules,
draft, combine, snap counts, and Next Gen Stats as Parquet files attached to
GitHub releases. This module downloads the requested file on demand (cached in
memory, never written to disk or rehosted), reads only the curated columns,
converts them to stable SQL types, and filters rows with Arrow compute kernels.

Release tags and file names are hardcoded rather than listed through the
GitHub REST API, which allows only 60 unauthenticated calls per hour.
"""

from __future__ import annotations

import io
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from vgi_nfl import api
from vgi_nfl.meta import field

FIRST_PBP_SEASON = 1999
SEASON_TYPES = {"REG": "reg", "POST": "post", "REGPOST": "regpost"}


@dataclass(frozen=True, slots=True)
class Column:
    """One curated output column and the nflverse column it comes from."""

    name: str
    kind: pa.DataType
    comment: str
    source: str | None = None

    @property
    def source_name(self) -> str:
        """Return the upstream column name."""
        return self.source or self.name


def _schema(columns: Sequence[Column]) -> pa.Schema:
    return pa.schema([field(column.name, column.kind, column.comment) for column in columns])


def current_season(today: datetime | None = None) -> int:
    """Return the most recent NFL season that has started (seasons kick off in September)."""
    now = today or datetime.now(UTC)
    return now.year if now.month >= 9 else now.year - 1


def _convert(values: pa.ChunkedArray, kind: pa.DataType) -> pa.ChunkedArray:
    """Convert one nflverse column to its curated SQL type."""
    if values.type == kind:
        return values
    if pa.types.is_boolean(kind) and (pa.types.is_floating(values.type) or pa.types.is_integer(values.type)):
        return pc.not_equal(values, 0)
    if pa.types.is_date(kind) and pa.types.is_string(values.type):
        cleaned = pc.if_else(pc.equal(values, ""), pa.scalar(None, pa.string()), values)
        return pc.cast(pc.strptime(cleaned, format="%Y-%m-%d", unit="s", error_is_null=True), kind)
    if pa.types.is_integer(kind) and pa.types.is_floating(values.type):
        return pc.cast(values, kind, safe=False)
    if pa.types.is_string(kind) and pa.types.is_integer(values.type):
        return pc.cast(values, kind)
    if pa.types.is_integer(kind) and pa.types.is_string(values.type):
        digits = pc.match_substring_regex(values, r"^[0-9]+$")
        return pc.cast(pc.if_else(digits, values, pa.scalar(None, pa.string())), kind)
    return pc.cast(values, kind)


def read_columns(body: bytes, columns: Sequence[Column], names: Sequence[str]) -> pa.Table:
    """Read and type only the requested curated columns from a Parquet body."""
    wanted = [column for column in columns if column.name in set(names)]
    available = set(pq.read_schema(io.BytesIO(body)).names)
    sources = sorted({column.source_name for column in wanted if column.source_name in available})
    table = pq.read_table(io.BytesIO(body), columns=sources)
    arrays = []
    for column in wanted:
        if column.source_name in available:
            arrays.append(_convert(table.column(column.source_name), column.kind))
        else:
            arrays.append(pa.chunked_array([pa.nulls(table.num_rows, column.kind)], type=column.kind))
    return pa.Table.from_arrays(arrays, schema=_schema(wanted))


def fetch_parquet(path: str) -> tuple[bytes, int]:
    """Fetch one release asset, mapping a missing file to a clear error."""

    def validate(body: bytes) -> None:
        if body[:4] != b"PAR1":
            raise ValueError(f"nflverse asset {path} is not a Parquet file")

    try:
        fetched = api.fetch(api.NFLVERSE, path, accept="application/octet-stream", validate=validate)
    except api.NflApiError as error:
        if error.status == 404:
            raise LookupError(
                f"nflverse has not published {path}; the season may not have started or "
                "the dataset does not cover it"
            ) from error
        raise
    return fetched.body, fetched.ttl


def _equals_any(table: pa.Table, columns: Sequence[str], value: str) -> pa.ChunkedArray:
    mask = None
    for name in columns:
        current = pc.fill_null(pc.equal(pc.utf8_upper(table.column(name)), value.upper()), False)
        mask = current if mask is None else pc.or_(mask, current)
    assert mask is not None
    return mask


def load(
    dataset: Dataset,
    *,
    names: Sequence[str],
    season: int | None = None,
    season_type: str = "REG",
    week: int | None = None,
    team: str | None = None,
) -> tuple[pa.Table, int]:
    """Load a curated dataset, filtered by season, week, and team."""
    if dataset.per_season and season is None:
        season = current_season()
    if season is not None and season < dataset.first_season:
        raise ValueError(f"{dataset.name} starts with the {dataset.first_season} season")
    path = dataset.path.format(season=season, kind=SEASON_TYPES.get(season_type, "reg"))
    body, ttl = fetch_parquet(path)
    filter_columns = {name for name in (dataset.season_column, dataset.week_column) if name}
    filter_columns.update(dataset.team_columns)
    needed = list(dict.fromkeys([*names, *filter_columns]))
    table = read_columns(body, dataset.columns, needed)
    for name, aliases in dataset.value_aliases:
        if name in table.column_names:
            values = table.column(name)
            for alias, canonical in aliases:
                values = pc.if_else(pc.equal(values, alias), canonical, values)
            table = table.set_column(table.column_names.index(name), table.schema.field(name), values)
    if season is not None and not dataset.per_season and dataset.season_column:
        table = table.filter(pc.fill_null(pc.equal(table.column(dataset.season_column), season), False))
    if week is not None and dataset.week_column:
        table = table.filter(pc.fill_null(pc.equal(table.column(dataset.week_column), week), False))
    if team is not None and dataset.team_columns:
        wanted = team.strip().upper()
        for name, aliases in dataset.value_aliases:
            if name in dataset.team_columns:
                wanted = dict(aliases).get(wanted, wanted)
        table = table.filter(_equals_any(table, dataset.team_columns, wanted))
    return table.select(list(names)), ttl


@dataclass(frozen=True, slots=True)
class Dataset:
    """A curated nflverse release asset."""

    name: str
    path: str
    columns: tuple[Column, ...]
    per_season: bool = False
    first_season: int = FIRST_PBP_SEASON
    season_column: str | None = "season"
    week_column: str | None = None
    team_columns: tuple[str, ...] = ()
    #: Per-column value rewrites that align a file with nflverse's usual abbreviations.
    value_aliases: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = ()

    @property
    def schema(self) -> pa.Schema:
        """Return the curated Arrow schema."""
        return _schema(self.columns)


I32 = pa.int32()
F64 = pa.float64()
STR = pa.string()
BOOL = pa.bool_()
DATE = pa.date32()

_GAME_TYPE = "nflverse game type: REG, WC, DIV, CON, or SB."
_GSIS = "NFL GSIS player id, for example 00-0033873; joins nflverse tables."

SCHEDULE = Dataset(
    name="schedule",
    path="schedules/games.parquet",
    week_column="week",
    team_columns=("home_team", "away_team"),
    columns=(
        Column("game_id", STR, "nflverse game id, for example 2025_01_DAL_PHI."),
        Column("season", I32, "NFL season year."),
        Column("game_type", STR, _GAME_TYPE),
        Column("week", I32, "Week number; postseason weeks continue after the regular season."),
        Column("game_date", DATE, "Local game date.", "gameday"),
        Column("weekday", STR, "Day of the week."),
        Column("kickoff_et", STR, "Scheduled kickoff in US Eastern time as HH:MM.", "gametime"),
        Column("away_team", STR, "Away team nflverse abbreviation."),
        Column("away_score", I32, "Away points; NULL until played."),
        Column("home_team", STR, "Home team nflverse abbreviation."),
        Column("home_score", I32, "Home points; NULL until played."),
        Column("location", STR, "Home or Neutral."),
        Column("result", I32, "Home score minus away score."),
        Column("total", I32, "Combined points."),
        Column("overtime", BOOL, "Whether the game went to overtime."),
        Column("espn_game_id", STR, "ESPN event id; pass it to game_summary().", "espn"),
        Column("away_rest", I32, "Away team's days of rest."),
        Column("home_rest", I32, "Home team's days of rest."),
        Column("spread_line", F64, "Closing point spread from the home team's view (positive = favored)."),
        Column("total_line", F64, "Closing over/under total."),
        Column("division_game", BOOL, "Whether both teams share a division.", "div_game"),
        Column("roof", STR, "Roof type: outdoors, dome, closed, or open."),
        Column("surface", STR, "Playing surface, for example grass or fieldturf."),
        Column("temperature_f", I32, "Kickoff temperature in Fahrenheit for outdoor games.", "temp"),
        Column("wind_mph", I32, "Wind speed in mph for outdoor games.", "wind"),
        Column("away_qb_id", STR, "Away starting QB GSIS id."),
        Column("away_qb_name", STR, "Away starting quarterback."),
        Column("home_qb_id", STR, "Home starting QB GSIS id."),
        Column("home_qb_name", STR, "Home starting quarterback."),
        Column("away_coach", STR, "Away head coach."),
        Column("home_coach", STR, "Home head coach."),
        Column("referee", STR, "Referee."),
        Column("stadium", STR, "Stadium name."),
    ),
)

PLAY_BY_PLAY = Dataset(
    name="play_by_play",
    path="pbp/play_by_play_{season}.parquet",
    per_season=True,
    week_column="week",
    team_columns=("home_team", "away_team"),
    columns=(
        Column("game_id", STR, "nflverse game id."),
        Column("play_id", pa.int64(), "Play id, unique within a game."),
        Column("season", I32, "Season."),
        Column("week", I32, "Week."),
        Column("season_type", STR, "REG or POST."),
        Column("game_date", DATE, "Game date."),
        Column("home_team", STR, "Home team."),
        Column("away_team", STR, "Away team."),
        Column("posteam", STR, "Offense (team in possession)."),
        Column("defteam", STR, "Defense."),
        Column("quarter", I32, "Quarter; 5 is overtime.", "qtr"),
        Column("down", I32, "Down; NULL on kicks."),
        Column("yards_to_go", I32, "Yards to a first down.", "ydstogo"),
        Column("yardline_100", I32, "Yards from the opponent's end zone."),
        Column("game_seconds_remaining", I32, "Seconds left in regulation."),
        Column("drive", I32, "Drive number."),
        Column("play_type", STR, "run, pass, punt, field_goal, kickoff, extra_point, no_play, ..."),
        Column("description", STR, "Play text.", "desc"),
        Column("yards_gained", I32, "Yards gained."),
        Column("shotgun", BOOL, "Shotgun formation."),
        Column("no_huddle", BOOL, "No-huddle."),
        Column("qb_dropback", BOOL, "QB dropped back."),
        Column("qb_scramble", BOOL, "QB scrambled."),
        Column("pass_length", STR, "short or deep."),
        Column("pass_location", STR, "left, middle, or right."),
        Column("air_yards", I32, "Air yards of the pass."),
        Column("yards_after_catch", I32, "Yards after catch."),
        Column("run_location", STR, "left, middle, or right."),
        Column("run_gap", STR, "end, tackle, or guard."),
        Column("passer_player_id", STR, "Passer GSIS id."),
        Column("passer_player_name", STR, "Passer."),
        Column("receiver_player_id", STR, "Targeted receiver GSIS id."),
        Column("receiver_player_name", STR, "Targeted receiver."),
        Column("rusher_player_id", STR, "Rusher GSIS id."),
        Column("rusher_player_name", STR, "Rusher."),
        Column("complete_pass", BOOL, "Completed pass."),
        Column("interception", BOOL, "Interception."),
        Column("sack", BOOL, "Sack."),
        Column("touchdown", BOOL, "Touchdown scored."),
        Column("first_down", BOOL, "First down gained."),
        Column("penalty", BOOL, "Penalty on the play."),
        Column("fumble_lost", BOOL, "Fumble lost."),
        Column("field_goal_result", STR, "made, missed, or blocked."),
        Column("kick_distance", I32, "Kick distance."),
        Column("ep", F64, "Expected points before the play."),
        Column("epa", F64, "Expected points added."),
        Column("wp", F64, "Offense win probability before the play."),
        Column("wpa", F64, "Win probability added."),
        Column("cpoe", F64, "Completion % over expected."),
        Column("success", BOOL, "EPA > 0."),
        Column("home_score", I32, "Home score after the play.", "total_home_score"),
        Column("away_score", I32, "Away score after the play.", "total_away_score"),
    ),
)

_PLAYER_COMMON = (
    Column("player_id", STR, _GSIS),
    Column("player_name", STR, "Short player name, for example P.Mahomes."),
    Column("player_display_name", STR, "Full player name."),
    Column("position", STR, "Position."),
    Column("position_group", STR, "Position group."),
    Column("season", I32, "Season."),
    Column("season_type", STR, "REG, POST, or REG+POST."),
)

_PLAYER_STATS = (
    Column("completions", I32, "Completions."),
    Column("attempts", I32, "Pass attempts."),
    Column("passing_yards", I32, "Passing yards."),
    Column("passing_tds", I32, "Passing TDs."),
    Column("interceptions", I32, "Interceptions thrown.", "passing_interceptions"),
    Column("sacks_suffered", I32, "Times sacked."),
    Column("sack_yards_lost", I32, "Sack yards lost."),
    Column("passing_air_yards", I32, "Air yards on attempts."),
    Column("passing_epa", F64, "EPA on dropbacks."),
    Column("passing_cpoe", F64, "Completion % over expected."),
    Column("carries", I32, "Carries."),
    Column("rushing_yards", I32, "Rushing yards."),
    Column("rushing_tds", I32, "Rushing TDs."),
    Column("rushing_epa", F64, "EPA on carries."),
    Column("receptions", I32, "Receptions."),
    Column("targets", I32, "Targets."),
    Column("receiving_yards", I32, "Receiving yards."),
    Column("receiving_tds", I32, "Receiving TDs."),
    Column("receiving_air_yards", I32, "Air yards on targets."),
    Column("receiving_yards_after_catch", I32, "Yards after catch."),
    Column("receiving_epa", F64, "EPA on targets."),
    Column("target_share", F64, "Share of team targets."),
    Column("air_yards_share", F64, "Share of team air yards."),
    Column("wopr", F64, "Weighted opportunity rating."),
    Column("fumbles_lost", I32, "Fumbles lost.", "fumbles_lost_total"),
    Column("tackles_solo", I32, "Solo tackles.", "def_tackles_solo"),
    Column("tackle_assists", I32, "Tackle assists.", "def_tackle_assists"),
    Column("tackles_for_loss", I32, "Tackles for loss.", "def_tackles_for_loss"),
    Column("def_sacks", F64, "Sacks (half sacks allowed)."),
    Column("def_qb_hits", I32, "QB hits."),
    Column("def_interceptions", I32, "Interceptions made."),
    Column("def_pass_defended", I32, "Passes defended."),
    Column("def_tds", I32, "Defensive TDs."),
    Column("fg_made", I32, "Field goals made."),
    Column("fg_att", I32, "Field goals attempted."),
    Column("fg_long", I32, "Longest field goal."),
    Column("pat_made", I32, "Extra points made."),
    Column("pat_att", I32, "Extra points attempted."),
    Column("fantasy_points", F64, "Standard fantasy points."),
    Column("fantasy_points_ppr", F64, "PPR fantasy points."),
)

PLAYER_STATS_WEEK = Dataset(
    name="player_stats_week",
    path="stats_player/stats_player_week_{season}.parquet",
    per_season=True,
    week_column="week",
    team_columns=("team",),
    columns=(
        *_PLAYER_COMMON,
        Column("week", I32, "Week."),
        Column("game_id", STR, "nflverse game id."),
        Column("team", STR, "Player's team."),
        Column("opponent_team", STR, "Opponent."),
        *_PLAYER_STATS,
    ),
)

PLAYER_STATS_SEASON = Dataset(
    name="player_stats_season",
    path="stats_player/stats_player_{kind}_{season}.parquet",
    per_season=True,
    team_columns=("recent_team",),
    columns=(
        *_PLAYER_COMMON,
        Column("recent_team", STR, "Most recent team in the season."),
        Column("games", I32, "Games played."),
        *_PLAYER_STATS,
    ),
)

TEAM_STATS = Dataset(
    name="team_stats",
    path="stats_team/stats_team_{kind}_{season}.parquet",
    per_season=True,
    team_columns=("team",),
    columns=(
        Column("season", I32, "Season."),
        Column("team", STR, "nflverse team abbreviation."),
        Column("season_type", STR, "REG, POST, or REG+POST."),
        Column("games", I32, "Games played."),
        Column("completions", I32, "Completions."),
        Column("attempts", I32, "Pass attempts."),
        Column("passing_yards", I32, "Gross passing yards."),
        Column("passing_tds", I32, "Passing TDs."),
        Column("interceptions", I32, "Interceptions thrown.", "passing_interceptions"),
        Column("sacks_suffered", I32, "Times sacked."),
        Column("sack_yards_lost", I32, "Sack yards lost."),
        Column("passing_epa", F64, "Total EPA on dropbacks."),
        Column("passing_cpoe", F64, "Completion % over expected."),
        Column("carries", I32, "Carries."),
        Column("rushing_yards", I32, "Rushing yards."),
        Column("rushing_tds", I32, "Rushing TDs."),
        Column("rushing_epa", F64, "Total EPA on carries."),
        Column("receiving_yards_after_catch", I32, "Yards after catch."),
        Column("passing_first_downs", I32, "First downs by pass."),
        Column("rushing_first_downs", I32, "First downs by rush."),
        Column("fumbles_lost", I32, "Fumbles lost.", "fumbles_lost_total"),
        Column("penalties", I32, "Penalties."),
        Column("penalty_yards", I32, "Penalty yards."),
        Column("def_tackles_for_loss", I32, "Defensive tackles for loss."),
        Column("def_sacks", F64, "Defensive sacks."),
        Column("def_qb_hits", I32, "Defensive QB hits."),
        Column("def_interceptions", I32, "Defensive interceptions."),
        Column("def_pass_defended", I32, "Passes defended."),
        Column("def_fumbles_forced", I32, "Fumbles forced."),
        Column("def_tds", I32, "Defensive TDs."),
        Column("def_safeties", I32, "Safeties."),
        Column("special_teams_tds", I32, "Special-teams TDs."),
        Column("fg_made", I32, "Field goals made."),
        Column("fg_att", I32, "Field goals attempted."),
        Column("pat_made", I32, "Extra points made."),
        Column("pat_att", I32, "Extra points attempted."),
        Column("punts", I32, "Punts.", "pt_att"),
        Column("punt_net_yards", I32, "Net punt yards.", "pt_net_yards"),
    ),
)

_PFR_TEAMS = (
    ("KAN", "KC"),
    ("NWE", "NE"),
    ("NOR", "NO"),
    ("SFO", "SF"),
    ("GNB", "GB"),
    ("TAM", "TB"),
    ("LVR", "LV"),
    ("LAR", "LA"),
    ("SDG", "SD"),
)

DRAFT = Dataset(
    name="draft",
    path="draft_picks/draft_picks.parquet",
    first_season=1980,
    team_columns=("team",),
    value_aliases=(("team", _PFR_TEAMS),),
    columns=(
        Column("season", I32, "Draft year."),
        Column("draft_round", I32, "Round.", "round"),
        Column("pick", I32, "Overall pick number."),
        Column("team", STR, "Drafting team (nflverse abbreviation; older picks keep era codes like OAK)."),
        Column("gsis_id", STR, "GSIS id once the player reached the NFL."),
        Column("pfr_player_id", STR, "Pro Football Reference player id."),
        Column("player_name", STR, "Player name.", "pfr_player_name"),
        Column("position", STR, "Position."),
        Column("category", STR, "Position category, for example OL or DB."),
        Column("side", STR, "O, D, or S (special teams)."),
        Column("college", STR, "College."),
        Column("age", I32, "Age at the draft."),
        Column("last_season", I32, "Last season played.", "to"),
        Column("hall_of_fame", BOOL, "Hall of Fame inductee.", "hof"),
        Column("all_pro", I32, "First-team All-Pro selections.", "allpro"),
        Column("pro_bowls", I32, "Pro Bowl selections.", "probowls"),
        Column("seasons_started", I32, "Seasons as a primary starter."),
        Column("weighted_av", I32, "PFR weighted career approximate value.", "w_av"),
        Column("drafting_team_av", I32, "Approximate value for the drafting team.", "dr_av"),
        Column("games", I32, "Career games."),
        Column("pass_yards", I32, "Career passing yards."),
        Column("pass_tds", I32, "Career passing TDs."),
        Column("rush_yards", I32, "Career rushing yards."),
        Column("rush_tds", I32, "Career rushing TDs."),
        Column("receptions", I32, "Career receptions."),
        Column("rec_yards", I32, "Career receiving yards."),
        Column("rec_tds", I32, "Career receiving TDs."),
        Column("def_solo_tackles", I32, "Career solo tackles."),
        Column("def_ints", I32, "Career interceptions."),
        Column("def_sacks", F64, "Career sacks."),
    ),
)

COMBINE = Dataset(
    name="combine",
    path="combine/combine.parquet",
    first_season=2000,
    columns=(
        Column("season", I32, "Combine year."),
        Column("player_name", STR, "Player name."),
        Column("position", STR, "Position.", "pos"),
        Column("school", STR, "College."),
        Column("height", STR, "Height as feet-inches, for example 6-3.", "ht"),
        Column("weight_lbs", I32, "Weight in pounds.", "wt"),
        Column("forty", F64, "40-yard dash in seconds."),
        Column("bench", I32, "225-lb bench press repetitions."),
        Column("vertical", F64, "Vertical jump in inches."),
        Column("broad_jump", I32, "Broad jump in inches."),
        Column("cone", F64, "3-cone drill in seconds."),
        Column("shuttle", F64, "20-yard shuttle in seconds."),
        Column("draft_year", I32, "Draft year, if drafted."),
        Column("draft_team", STR, "Drafting team, if drafted."),
        Column("draft_round", I32, "Draft round, if drafted."),
        Column("draft_pick", I32, "Overall pick, if drafted.", "draft_ovr"),
        Column("pfr_id", STR, "Pro Football Reference player id."),
        Column("cfb_id", STR, "Sports Reference college football id."),
    ),
)

SNAP_COUNTS = Dataset(
    name="snap_counts",
    path="snap_counts/snap_counts_{season}.parquet",
    per_season=True,
    first_season=2012,
    week_column="week",
    team_columns=("team",),
    columns=(
        Column("game_id", STR, "nflverse game id."),
        Column("season", I32, "Season."),
        Column("game_type", STR, _GAME_TYPE),
        Column("week", I32, "Week."),
        Column("player", STR, "Player name."),
        Column("pfr_player_id", STR, "Pro Football Reference player id."),
        Column("position", STR, "Position."),
        Column("team", STR, "Team."),
        Column("opponent", STR, "Opponent."),
        Column("offense_snaps", I32, "Offensive snaps played."),
        Column("offense_pct", F64, "Share of team offensive snaps (0-1)."),
        Column("defense_snaps", I32, "Defensive snaps played."),
        Column("defense_pct", F64, "Share of team defensive snaps (0-1)."),
        Column("st_snaps", I32, "Special-teams snaps played."),
        Column("st_pct", F64, "Share of team special-teams snaps (0-1)."),
    ),
)

_NGS_COMMON = (
    Column("season", I32, "Season."),
    Column("season_type", STR, "REG or POST."),
    Column("week", I32, "Week; 0 is the full-season aggregate row."),
    Column("player_gsis_id", STR, _GSIS),
    Column("player_display_name", STR, "Player name."),
    Column("player_position", STR, "Position."),
    Column("team", STR, "nflverse team abbreviation (NGS's LAR is normalized to LA).", "team_abbr"),
)

_NGS_ALIASES = (("team", (("LAR", "LA"),)),)

NGS_PASSING = Dataset(
    name="ngs_passing",
    path="nextgen_stats/ngs_passing.parquet",
    first_season=2016,
    week_column="week",
    team_columns=("team",),
    value_aliases=_NGS_ALIASES,
    columns=(
        *_NGS_COMMON,
        Column("attempts", I32, "Pass attempts."),
        Column("completions", I32, "Completions."),
        Column("pass_yards", I32, "Passing yards."),
        Column("pass_touchdowns", I32, "Passing TDs."),
        Column("interceptions", I32, "Interceptions."),
        Column("passer_rating", F64, "Passer rating."),
        Column("completion_percentage", F64, "Completion %."),
        Column("expected_completion_percentage", F64, "Expected completion %."),
        Column("completion_percentage_above_expectation", F64, "CPOE."),
        Column("avg_time_to_throw", F64, "Average seconds from snap to throw."),
        Column("avg_completed_air_yards", F64, "Average air yards on completions."),
        Column("avg_intended_air_yards", F64, "Average air yards on attempts."),
        Column("avg_air_yards_differential", F64, "Completed minus intended air yards."),
        Column("avg_air_yards_to_sticks", F64, "Average air yards past the first-down marker."),
        Column("aggressiveness", F64, "% of attempts into tight coverage."),
        Column("max_completed_air_distance", F64, "Longest completed air distance."),
    ),
)

NGS_RECEIVING = Dataset(
    name="ngs_receiving",
    path="nextgen_stats/ngs_receiving.parquet",
    first_season=2016,
    week_column="week",
    team_columns=("team",),
    value_aliases=_NGS_ALIASES,
    columns=(
        *_NGS_COMMON,
        Column("targets", I32, "Targets."),
        Column("receptions", I32, "Receptions."),
        Column("yards", I32, "Receiving yards."),
        Column("rec_touchdowns", I32, "Receiving TDs."),
        Column("catch_percentage", F64, "Catch %."),
        Column("avg_cushion", F64, "Average yards of cushion at the snap."),
        Column("avg_separation", F64, "Average yards of separation at the catch or incompletion."),
        Column("avg_intended_air_yards", F64, "Average air yards per target."),
        Column("percent_share_of_intended_air_yards", F64, "% share of team intended air yards."),
        Column("avg_yac", F64, "Average yards after catch."),
        Column("avg_expected_yac", F64, "Average expected yards after catch."),
        Column("avg_yac_above_expectation", F64, "YAC over expected per reception."),
    ),
)

NGS_RUSHING = Dataset(
    name="ngs_rushing",
    path="nextgen_stats/ngs_rushing.parquet",
    first_season=2016,
    week_column="week",
    team_columns=("team",),
    value_aliases=_NGS_ALIASES,
    columns=(
        *_NGS_COMMON,
        Column("rush_attempts", I32, "Rush attempts."),
        Column("rush_yards", I32, "Rushing yards."),
        Column("rush_touchdowns", I32, "Rushing TDs."),
        Column("avg_rush_yards", F64, "Yards per carry."),
        Column("efficiency", F64, "Distance travelled per rushing yard gained."),
        Column("percent_attempts_gte_eight_defenders", F64, "% of carries against 8+ box defenders."),
        Column("avg_time_to_los", F64, "Average seconds behind the line of scrimmage."),
        Column("expected_rush_yards", F64, "Expected rushing yards."),
        Column("rush_yards_over_expected", F64, "Rushing yards over expected."),
        Column("rush_yards_over_expected_per_att", F64, "RYOE per carry."),
        Column("rush_pct_over_expected", F64, "% of carries beating expectation."),
    ),
)

PLAYERS = Dataset(
    name="players",
    path="players/players.parquet",
    season_column=None,
    team_columns=("latest_team",),
    columns=(
        Column("gsis_id", STR, _GSIS),
        Column("display_name", STR, "Full player name."),
        Column("first_name", STR, "Legal first name."),
        Column("last_name", STR, "Family name."),
        Column("position", STR, "Primary position code, for example QB or CB."),
        Column("position_group", STR, "Position group, for example QB, WR, OL, or DB."),
        Column("birth_date", DATE, "Date of birth."),
        Column("height_inches", I32, "Height in inches.", "height"),
        Column("weight_lbs", I32, "Weight in pounds.", "weight"),
        Column("college", STR, "School attended before the NFL.", "college_name"),
        Column("jersey_number", STR, "Most recent uniform number."),
        Column("rookie_season", I32, "Year of the first NFL season played."),
        Column("last_season", I32, "Year of the most recent NFL season played."),
        Column("latest_team", STR, "Most recent team (nflverse abbreviation)."),
        Column("status", STR, "Roster status, for example ACT, RES, CUT, or RET."),
        Column("years_of_experience", I32, "Count of accrued NFL seasons."),
        Column("draft_year", I32, "Draft year; NULL if undrafted."),
        Column("draft_round", I32, "Ordinal round (1-7) the player was selected in."),
        Column("draft_pick", I32, "Ordinal overall selection number in the draft."),
        Column("draft_team", STR, "Drafting team."),
        Column("espn_id", I32, "ESPN athlete id (integer code); joins athlete_id, feeds player_game_log()."),
        Column("pfr_id", STR, "Pro Football Reference id."),
        Column("pff_id", STR, "Pro Football Focus player identifier."),
        Column("nfl_id", STR, "NFL.com id."),
        Column("esb_id", STR, "NFL Elias (ESB) id."),
        Column("otc_id", STR, "OverTheCap id."),
    ),
)

DATASETS = (
    SCHEDULE,
    PLAY_BY_PLAY,
    PLAYER_STATS_WEEK,
    PLAYER_STATS_SEASON,
    TEAM_STATS,
    DRAFT,
    COMBINE,
    SNAP_COUNTS,
    NGS_PASSING,
    NGS_RECEIVING,
    NGS_RUSHING,
    PLAYERS,
)
