"""VGI worker exposing NFL scores, standings, box scores, and nflverse statistics as a SQL catalog."""

from __future__ import annotations

import json
import os
import sys

import pyarrow as pa
from vgi import Worker
from vgi.catalog import Catalog, ConstraintInfo, Schema, Table, constraint_record

from vgi_nfl import nflverse
from vgi_nfl.espn_functions import (
    ESPN_FUNCTIONS,
    CurrentInjuriesFunction,
    CurrentScoreboardFunction,
    CurrentStandingsFunction,
    CurrentWeekFunction,
    TeamsFunction,
)
from vgi_nfl.espn_schemas import (
    CURRENT_WEEK_SCHEMA,
    EVENT_SCHEMA,
    INJURY_SCHEMA,
    STANDINGS_SCHEMA,
    TEAMS_SCHEMA,
)
from vgi_nfl.examples import COMPOSED_EXAMPLES, OPENER_SCRIMMAGE_SHARE
from vgi_nfl.meta import column_comments
from vgi_nfl.nflverse_functions import NFLVERSE_FUNCTIONS, PlayersFunction

SOURCE_URL = "https://github.com/Query-farm/vgi-nfl"


def _table_tags(
    *,
    category: str,
    title: str,
    keywords: list[str],
    doc_llm: str,
    doc_md: str,
    examples: list[tuple[str, str]],
) -> dict[str, str]:
    return {
        "provider": "nfl",
        "vgi.category": category,
        "vgi.title": title,
        "vgi.keywords": json.dumps(keywords),
        "vgi.doc_llm": doc_llm,
        "vgi.doc_md": doc_md,
        "vgi.example_queries": json.dumps(
            [{"description": description, "sql": sql} for description, sql in examples]
        ),
    }


_SCOREBOARD_TAGS = _table_tags(
    category="scores",
    title="Current NFL Scoreboard",
    keywords=["scores", "scoreboard", "live", "this week", "results", "schedule"],
    doc_llm=(
        "This week's NFL games from ESPN, one row per game: kickoff, status (pre/in/post), live or "
        "final scores, records, winner, venue, and broadcast. Start here for 'what is the score' or "
        "'who plays this week'. For another week call scoreboard(season, week)."
    ),
    doc_md=(
        "The current NFL week's scoreboard as an ordinary table. Scores are NULL before kickoff. "
        "Use `game_id` with `game_summary()`, `box_score_player()`, and related functions."
    ),
    examples=[
        (
            "This week's games with live or final scores.",
            "SELECT short_name, status_detail, away_score, home_score "
            "FROM nfl.main.current_scoreboard ORDER BY game_time",
        )
    ],
)

_STANDINGS_TAGS = _table_tags(
    category="standings",
    title="Current NFL Standings",
    keywords=["standings", "division", "playoff seed", "wild card", "records", "games back"],
    doc_llm=(
        "Current NFL regular-season standings from ESPN, one row per team: conference, division, "
        "division_rank, playoff_seed (1-7 qualify), W-L-T, win percentage, games back, points "
        "for/against, streak, home/road/division/conference records, and clinch marker. For past "
        "seasons call standings(season := ...)."
    ),
    doc_md="Current division standings as an ordinary read-only table.",
    examples=[
        (
            "Division tables in rank order.",
            "SELECT division, division_rank, team_name, wins, losses, ties, games_back "
            "FROM nfl.main.current_standings ORDER BY division, division_rank",
        ),
        (
            "Current playoff field by conference seed.",
            "SELECT conference, playoff_seed, team_name, wins, losses "
            "FROM nfl.main.current_standings WHERE playoff_seed <= 7 ORDER BY conference, playoff_seed",
        ),
    ],
)

_INJURY_TAGS = _table_tags(
    category="injuries",
    title="Current NFL Injury Report",
    keywords=["injuries", "injury report", "questionable", "out", "injured reserve", "IR"],
    doc_llm=(
        "League-wide NFL injury report from ESPN, one row per report entry: team, player, position, "
        "status (Questionable, Doubtful, Out, Injured Reserve, Active), body part, estimated return "
        "date, and news blurb. Filter by team_abbreviation or status."
    ),
    doc_md=(
        "The current injury report. ESPN's payload is several megabytes, so it is cached in memory "
        "for at least a minute."
    ),
    examples=[
        (
            "Players ruled out or on injured reserve for Kansas City.",
            "SELECT athlete_name, position, status, injury_type, return_date "
            "FROM nfl.main.current_injuries WHERE team_abbreviation = 'KC' "
            "AND status IN ('Out', 'Injured Reserve') ORDER BY status, athlete_name",
        )
    ],
)

_WEEK_TAGS = _table_tags(
    category="calendar",
    title="Current NFL Week",
    keywords=["current week", "season", "calendar", "what week"],
    doc_llm=(
        "One row with the current NFL season, phase (pre/regular/post/off), week, and display week "
        "from Sleeper. Use it to parameterize scoreboard() or nflverse functions for 'this week'."
    ),
    doc_md="Sleeper's NFL state. `week` advances early in the week; `display_week` lags.",
    examples=[
        (
            "The current season and week.",
            "SELECT season, phase, week, display_week FROM nfl.main.current_week",
        )
    ],
)

_TEAMS_TAGS = _table_tags(
    category="teams",
    title="NFL Teams",
    keywords=["teams", "franchises", "abbreviations", "team ids"],
    doc_llm=(
        "The 32 NFL franchises from ESPN: ESPN team_id, abbreviation, full name, location, "
        "nickname, and colors. Use abbreviations with roster(), depth_chart(), and team_schedule(). "
        "nflverse uses LA and WAS where ESPN uses LAR and WSH."
    ),
    doc_md="ESPN's NFL team directory.",
    examples=[
        (
            "Every franchise and its ESPN abbreviation.",
            "SELECT team_abbreviation, team_name FROM nfl.main.teams ORDER BY team_name",
        )
    ],
)

_PLAYERS_TAGS = _table_tags(
    category="players",
    title="NFL Players",
    keywords=["players", "player ids", "gsis", "espn id", "crosswalk", "bio"],
    doc_llm=(
        "Every NFL player in nflverse's directory (about 25,000, historical and current): GSIS id, "
        "name, position, birth date, size, college, draft, latest team, status, and cross-ids for "
        "ESPN, PFR, PFF, NFL.com, and OverTheCap. Use it to find an espn_id for "
        "player_game_log() or to join nflverse stats by gsis_id."
    ),
    doc_md="nflverse player directory with identifier crosswalk (CC-BY 4.0).",
    examples=[
        (
            "Look up Patrick Mahomes's identifiers.",
            "SELECT gsis_id, espn_id, pfr_id, position, latest_team "
            "FROM nfl.main.players WHERE display_name = 'Patrick Mahomes'",
        )
    ],
)

# The schema-level list keeps the standings examples and adds every composed
# example (each is also listed on the function that drives it).
_SCHEMA_EXAMPLES = json.dumps(
    [
        *json.loads(_STANDINGS_TAGS["vgi.example_queries"]),
        *({"description": description, "sql": sql} for description, sql in COMPOSED_EXAMPLES),
    ]
)

_EXECUTABLE_EXAMPLES = json.dumps(
    [
        {
            "name": "thirty_two_teams",
            "description": "ESPN lists all 32 NFL franchises.",
            "sql": "SELECT count(*) AS teams FROM nfl.main.teams",
            "expected_result": [{"teams": 32}],
        },
        {
            "name": "current_standings_cover_every_team",
            "description": "Current standings contain one row for each of the 32 teams in 8 divisions.",
            "sql": (
                "SELECT count(*) = 32 AND count(DISTINCT division) = 8 AS complete "
                "FROM nfl.main.current_standings"
            ),
            "expected_result": [{"complete": True}],
        },
        {
            "name": "season_2025_week_1_scores",
            "description": "The 2025 season opened with Philadelphia beating Dallas 24-20.",
            "sql": (
                "SELECT away_score, home_score, winner_abbreviation FROM nfl.main.scoreboard(2025, 1) "
                "WHERE game_id = '401772510'"
            ),
            "expected_result": [{"away_score": 20, "home_score": 24, "winner_abbreviation": "PHI"}],
        },
        {
            "name": "schedule_has_espn_crosswalk",
            "description": "nflverse's schedule links the 2025 opener to its ESPN game id.",
            "sql": (
                "SELECT espn_game_id FROM nfl.main.schedule(season := 2025, week := 1) "
                "WHERE home_team = 'PHI'"
            ),
            "expected_result": [{"espn_game_id": "401772510"}],
        },
        {
            "name": "opener_top_scrimmage_share",
            "description": (
                "CeeDee Lamb's 110 scrimmage yards were the largest share (35.8%) of either team's "
                "offense in the 2025 opener."
            ),
            "sql": (
                "SELECT athlete_name, scrimmage_yards, pct_of_team_offense "
                f"FROM ({OPENER_SCRIMMAGE_SHARE[1]}) ORDER BY pct_of_team_offense DESC LIMIT 1"
            ),
            "expected_result": [
                {"athlete_name": "CeeDee Lamb", "scrimmage_yards": 110, "pct_of_team_offense": 35.8}
            ],
        },
        {
            "name": "current_week_is_one_row",
            "description": "Sleeper reports exactly one current NFL state.",
            "sql": "SELECT count(*) AS rows FROM nfl.main.current_week",
            "expected_result": [{"rows": 1}],
        },
    ]
)

_AGENT_TEST_TASKS = json.dumps(
    [
        {
            "name": "bye_week_teams",
            "prompt": "What NFL season and week is it right now, and which teams are not playing this week?",
        },
        {
            "name": "division_leaders_vs_2025",
            "prompt": "Which team currently leads each NFL division, and what was each one's 2025 record?",
        },
        {
            "name": "chiefs_starters_injuries",
            "prompt": (
                "List the Kansas City Chiefs' current depth-chart starters with jersey numbers and "
                "ages, and flag any who appear on the injury report."
            ),
        },
        {
            "name": "opener_team_breakdown",
            "prompt": (
                "For the 2025 season opener (ESPN game 401772510, Dallas at Philadelphia), show "
                "each team's points, total yards, turnovers, and leading rusher."
            ),
        },
        {
            "name": "opener_scoring_drives",
            "prompt": (
                "In ESPN game 401772510, how many scoring drives did each team have, how many "
                "yards did those drives cover, and how many plays did each offense run?"
            ),
        },
        {
            "name": "week1_2025_against_the_spread",
            "prompt": (
                "For every week 1 game of the 2025 NFL season, show the final score, the closing "
                "spread, and whether the home team covered."
            ),
        },
        {
            "name": "passing_leaders_2025_efficiency",
            "prompt": (
                "Who were the top five passers by 2025 regular-season passing yards? Include each "
                "one's EPA per dropback, completion percentage over expected, and his team's "
                "most-targeted receiver."
            ),
        },
        {
            "name": "top_rushing_teams_2025",
            "prompt": (
                "Which three teams rushed for the most yards in 2025? For each, name its leading "
                "rusher with his season yards, week 1 yards, and rush yards over expected."
            ),
        },
        {
            "name": "first_round_2025_combine_snaps",
            "prompt": (
                "List the first round of the 2025 NFL draft with each player's combine 40-yard "
                "dash and how many snaps he played in week 1."
            ),
        },
        {
            "name": "chiefs_week1_2025_skill_snaps",
            "prompt": (
                "In week 1 of the 2025 season, which Kansas City Chiefs running backs, wide receivers, "
                "and tight ends played at least half of the offensive snaps? For each, give the player "
                "name, offensive snaps, touches (carries plus receptions), and yards from scrimmage "
                "(rushing plus receiving yards)."
            ),
        },
        {
            "name": "mahomes_2025_passing_by_week",
            "prompt": (
                "Show Patrick Mahomes's passing yards in each 2025 game alongside the matchup and the winner."
            ),
        },
    ]
)


def _key_constraints(table: str, key: tuple[str, ...]) -> tuple[ConstraintInfo, ...]:
    """Primary-key and NOT NULL records for a read-only table keyed by ``key``."""
    records = [
        constraint_record(
            ["main"],
            table,
            "pk",
            "PRIMARY_KEY",
            [[column] for column in key],
            enforcement="ENFORCED",
            validation="ALL_ROWS",
        )
    ]
    records += [
        constraint_record(
            ["main"],
            table,
            f"{column}_not_null",
            "NOT_NULL",
            [[column]],
            enforcement="ENFORCED",
            validation="ALL_ROWS",
        )
        for column in key
    ]
    return tuple(records)


def _table(
    name: str,
    function: type,
    comment: str,
    tags: dict[str, str],
    schema: pa.Schema,
    key: tuple[str, ...],
    estimate: int,
) -> Table:
    return Table(
        name=name,
        function=function,
        comment=comment,
        tags=tags,
        column_comments=column_comments(schema),
        constraints=_key_constraints(name, key),
        cardinality_estimate=estimate,
    )


_CATEGORIES = [
    ("scores", "Scores", "Scoreboards, schedules, and results.", ["scores", "schedule", "results"]),
    ("standings", "Standings", "Division standings, seeds, and records.", ["standings", "seeds"]),
    ("game-detail", "Game Detail", "Box scores, drives, and scoring plays.", ["box score", "drives"]),
    ("play-by-play", "Play-by-Play", "Plays with EPA and win probability.", ["plays", "EPA", "WP"]),
    ("player-stats", "Player Statistics", "Weekly, season, and game-log stats.", ["players", "stats"]),
    ("team-stats", "Team Statistics", "Season team totals.", ["team stats"]),
    ("next-gen-stats", "Next Gen Stats", "NFL tracking metrics.", ["NGS", "tracking"]),
    ("rosters", "Rosters", "Current rosters and depth charts.", ["roster", "depth chart"]),
    ("injuries", "Injuries", "The league-wide injury report.", ["injuries"]),
    ("draft", "Draft and Combine", "Draft picks and combine results.", ["draft", "combine"]),
    ("players", "Players", "Player directory and identifier crosswalk.", ["players", "ids"]),
    ("teams", "Teams", "NFL franchises.", ["teams"]),
    ("calendar", "Calendar", "Current season and week.", ["week", "season"]),
]

NFL_CATALOG = Catalog(
    name="nfl",
    default_schema="main",
    source_url=SOURCE_URL,
    comment=(
        "Read-only NFL scores, standings, box scores, play-by-play, and statistics from ESPN, "
        "nflverse (CC-BY 4.0), and Sleeper"
    ),
    tags={
        "provider": "nfl",
        "domain": "sports",
        "vgi.title": "National Football League Data",
        "vgi.subtitle": "NFL scores, standings, box scores, play-by-play, and player statistics as SQL.",
        "vgi.source_url": SOURCE_URL,
        "vgi.author": "Query Farm LLC <hello@query.farm>",
        "vgi.copyright": (
            "Worker (c) 2026 Query Farm LLC. nflverse data is CC-BY 4.0 (nflverse contributors). "
            "ESPN and Sleeper data belong to their owners and are subject to their terms. "
            "Not affiliated with the NFL, ESPN, Disney, or Sleeper."
        ),
        "vgi.license": "MIT",
        "vgi.support_contact": "https://github.com/Query-farm/vgi-nfl/issues",
        "vgi.support_policy_url": "https://github.com/Query-farm/vgi-nfl/blob/main/README.md",
        "vgi.keywords": json.dumps(
            ["NFL", "football", "scores", "standings", "play-by-play", "EPA", "nflverse", "box score"]
        ),
        "vgi.executable_examples": _EXECUTABLE_EXAMPLES,
        "vgi.agent_test_tasks": _AGENT_TEST_TASKS,
        "vgi.doc_llm": (
            "Read-only National Football League data for answering questions about games, teams, "
            "and players, live or historical. Live state (this week's scores, standings, injuries, "
            "rosters, depth charts, and per-game box scores, drives, and play-by-play) comes from "
            "ESPN's public endpoints and is keyed by ESPN ids: a text game_id and an integer "
            "athlete_id. Historical analytics (schedules with closing lines and weather since 1999, "
            "play-by-play with expected points added and win probability, weekly and season player "
            "and team statistics, snap counts, draft, combine, and Next Gen Stats tracking metrics) "
            "come from nflverse (CC-BY 4.0) and are keyed by GSIS player ids and nflverse team "
            "abbreviations such as LA and WAS. The schedule's espn_game_id and the players "
            "directory's espn_id bridge the two id systems. Seasons are labelled by the year they "
            "start."
        ),
        "vgi.doc_md": (
            "# NFL scores, standings, and statistics\n\n"
            "Query live and historical National Football League data from SQL.\n\n"
            "## Data model\n\n"
            "* **Live (ESPN):** scoreboards, standings, injuries, rosters, depth charts, and per-game "
            "box scores, drives, scoring plays, and play-by-play.\n"
            "* **Analytics (nflverse, CC-BY 4.0):** schedules with lines and weather, play-by-play "
            "with EPA/WP, weekly and season player stats, team stats, snap counts, draft, combine, "
            "and Next Gen Stats.\n"
            "* **Calendar (Sleeper):** the current season and week.\n\n"
            "Data is fetched on demand, cached briefly in memory, and never rehosted. This worker is "
            "not affiliated with the NFL, ESPN, Disney, nflverse, or Sleeper."
        ),
    },
    schemas=[
        Schema(
            path=["main"],
            comment="NFL scores, standings, game detail, play-by-play, and statistics",
            tags={
                "provider": "nfl",
                "domain": "sports",
                "vgi.title": "NFL",
                "vgi.keywords": json.dumps(
                    ["NFL", "scores", "standings", "box score", "play-by-play", "player stats", "draft"]
                ),
                "vgi.categories": json.dumps(
                    [
                        {"name": name, "title": title, "description": description, "keywords": keywords}
                        for name, title, description, keywords in _CATEGORIES
                    ]
                ),
                "vgi.doc_llm": (
                    "Start with current_scoreboard, current_standings, current_injuries, current_week, "
                    "teams, or players. For a past week call scoreboard(season, week); for game detail "
                    "pass a game_id to game_summary(), box_score_team(), box_score_player(), drives(), "
                    "scoring_plays(), or play_by_play_game(). For analytics use nflverse functions: "
                    "schedule(), play_by_play(), player_stats_week(), player_stats_season(), "
                    "team_stats(), snap_counts(), draft(), combine(), and ngs_*()."
                ),
                "vgi.doc_md": (
                    "## NFL data\n\n"
                    "Current tables answer live questions about this week's games, standings, "
                    "injuries, the current week, teams, and players.\n\n"
                    "Parameterized ESPN functions take a season and week, a team abbreviation, or "
                    "a game id. nflverse functions take a season with optional week and team "
                    "filters and download one cached release file per call."
                ),
                "vgi.example_queries": _SCHEMA_EXAMPLES,
            },
            functions=[*ESPN_FUNCTIONS, *NFLVERSE_FUNCTIONS],
            tables=[
                _table(
                    "current_scoreboard",
                    CurrentScoreboardFunction,
                    "This week's NFL games with live or final scores, one row per game",
                    _SCOREBOARD_TAGS,
                    EVENT_SCHEMA,
                    ("game_id",),
                    16,
                ),
                _table(
                    "current_standings",
                    CurrentStandingsFunction,
                    "Current NFL regular-season standings, one row per team",
                    _STANDINGS_TAGS,
                    STANDINGS_SCHEMA,
                    ("team_id",),
                    32,
                ),
                _table(
                    "current_injuries",
                    CurrentInjuriesFunction,
                    "League-wide NFL injury report, one row per report entry",
                    _INJURY_TAGS,
                    INJURY_SCHEMA,
                    ("injury_id",),
                    800,
                ),
                _table(
                    "current_week",
                    CurrentWeekFunction,
                    "The current NFL season, phase, and week",
                    _WEEK_TAGS,
                    CURRENT_WEEK_SCHEMA,
                    ("season",),
                    1,
                ),
                _table(
                    "teams",
                    TeamsFunction,
                    "The 32 NFL franchises with ESPN ids and abbreviations",
                    _TEAMS_TAGS,
                    TEAMS_SCHEMA,
                    ("team_id",),
                    32,
                ),
                _table(
                    "players",
                    PlayersFunction,
                    "Every NFL player in nflverse's directory with cross-source ids",
                    _PLAYERS_TAGS,
                    nflverse.PLAYERS.schema,
                    ("gsis_id",),
                    25_000,
                ),
            ],
        )
    ],
)


class NflWorker(Worker):
    """Worker process hosting the read-only NFL catalog."""

    catalog = NFL_CATALOG


def main() -> None:
    """Run over stdio by default, or HTTP when VGI's ``--http`` flag is supplied."""
    NflWorker.main()


def main_http() -> None:
    """Run HTTP with production-safe configuration requirements."""
    if not os.environ.get("VGI_SIGNING_KEY"):
        raise SystemExit(
            "VGI_SIGNING_KEY is required for HTTP mode so state remains valid across restarts and replicas"
        )
    auth_configured = bool(os.environ.get("VGI_BEARER_TOKENS") or os.environ.get("VGI_JWT_ISSUER"))
    auth_configured = auth_configured or os.environ.get("VGI_PROXY_PROOF_MODE", "").lower() == "require"
    if not auth_configured and os.environ.get("VGI_ALLOW_ANONYMOUS") != "1":
        raise SystemExit(
            "HTTP authentication is required; configure bearer/JWT/proxy proof, or explicitly set "
            "VGI_ALLOW_ANONYMOUS=1 for an intentionally public deployment"
        )
    argv = sys.argv[1:]
    if "--http" not in argv:
        argv = ["--http", *argv]
    if "--describe" not in argv and "--no-describe" not in argv:
        argv = ["--no-describe", *argv]
    if not any(value == "--cors-origins" or value.startswith("--cors-origins=") for value in argv):
        argv = ["--cors-origins", "", *argv]
    sys.argv = [sys.argv[0], *argv]
    NflWorker.main()
