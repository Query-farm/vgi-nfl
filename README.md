<p align="center">
  <a href="https://query.farm/vgi/">
    <img src="https://raw.githubusercontent.com/Query-farm/vgi-kalshi/main/docs/vgi-logo.png" alt="Vector Gateway Interface logo" width="320">
  </a>
</p>

<h1 align="center">vgi-nfl</h1>

<p align="center">
  NFL scores, standings, box scores, play-by-play, and player statistics as ordinary DuckDB tables.<br>
  A <strong>read-only</strong> <a href="https://query.farm/vgi/">VGI</a> worker, built by <a href="https://query.farm">🚜 Query.Farm</a>
</p>

<p align="center">
  <a href="https://github.com/Query-farm/vgi-nfl/actions/workflows/ci.yml"><img src="https://github.com/Query-farm/vgi-nfl/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="MIT license"></a>
  <img src="https://img.shields.io/badge/python-3.13%2B-3776AB.svg" alt="Python 3.13+">
  <a href="https://query.farm/vgi/"><img src="https://img.shields.io/badge/VGI-read--only-6f42c1.svg" alt="Read-only VGI worker"></a>
</p>

---

`vgi-nfl` fetches National Football League data on demand and returns it as
typed Arrow data for Haybarn SQL. It combines three public sources:

- **ESPN's public site, core, and common endpoints** for live scoreboards,
  standings, injuries, rosters, depth charts, and per-game box scores, drives,
  scoring plays, and play-by-play.
- **[nflverse](https://github.com/nflverse/nflverse-data)** release files
  (CC-BY 4.0) for historical analytics: schedules with closing lines and
  weather since 1999, play-by-play with expected points added (EPA) and win
  probability, weekly and season player and team statistics, snap counts, the
  draft, the combine, and Next Gen Stats.
- **[Sleeper](https://docs.sleeper.com/)** for the current season and week.

It needs no credentials and does not rehost or persist any dataset. Read
[Data sources, licences, and affiliation](#data-sources-licences-and-affiliation)
before you deploy it.

## Quick start

Install the released worker with `uv`:

```bash
uv tool install vgi-nfl
vgi-nfl
```

Launch Haybarn with the catalog attached:

```bash
uvx haybarn-cli \
  -cmd "INSTALL vgi FROM community; LOAD vgi; ATTACH 'nfl' (TYPE vgi, LOCATION 'vgi-nfl');" \
  :memory:
```

Or attach it in an existing Haybarn session:

```sql
INSTALL vgi FROM community;
LOAD vgi;
ATTACH 'nfl' (
  TYPE vgi,
  LOCATION 'vgi-nfl'
);
```

For source development, run `uv lock --check --no-sources`, then
`uv sync --no-sources` and `uv run --no-sources vgi-nfl`.
The lockfile resolves every dependency from package registries and needs no
sibling checkout.

## Catalog surface

The catalog has six tables and twenty-three parameterized table functions. Each
table reads from a parameterless `all_*` function of the same shape.

| Kind | Objects | Source |
| --- | --- | --- |
| Current tables | `current_scoreboard`, `current_standings`, `current_injuries`, `current_week`, `teams`, `players` | ESPN, Sleeper, nflverse |
| Scores and standings | `scoreboard(season, week)`, `standings()`, `team_schedule(team)`, `schedule()` | ESPN, nflverse |
| Game detail | `game_summary(game_id)`, `box_score_team(game_id)`, `box_score_player(game_id)`, `drives(game_id)`, `scoring_plays(game_id)`, `play_by_play_game(game_id)` | ESPN |
| Rosters | `roster(team)`, `depth_chart(team)` | ESPN |
| Play-by-play analytics | `play_by_play()` | nflverse |
| Player and team statistics | `player_stats_week()`, `player_stats_season()`, `team_stats()`, `snap_counts()`, `player_game_log(athlete_id)` | nflverse, ESPN |
| Next Gen Stats | `ngs_passing()`, `ngs_receiving()`, `ngs_rushing()` | nflverse |
| Draft | `draft()`, `combine()` | nflverse |

**Identifiers.** ESPN objects use a text `game_id` (for example `'401772510'`),
an integer `athlete_id`, and ESPN team codes (`KC`, `LAR`, `WSH`). nflverse
objects use GSIS player ids (`00-0033873`) and nflverse team codes (`KC`, `LA`,
`WAS`). Two columns bridge the systems: `schedule().espn_game_id` and
`players.espn_id`. ESPN team arguments accept the nflverse spellings too. Seasons
are labelled by the year they start, so the season that ends with the February
2026 Super Bowl is `2025`.

## Usage

### This week

```sql
-- What week is it, and what are the scores?
SELECT season, phase, week, display_week FROM nfl.main.current_week;

SELECT short_name, status_detail, away_score, home_score
FROM nfl.main.current_scoreboard
ORDER BY game_time;

-- Teams on a bye this week
SELECT team_abbreviation, team_name
FROM nfl.main.teams
WHERE team_abbreviation NOT IN (
  SELECT home_team_abbreviation FROM nfl.main.current_scoreboard
  UNION ALL
  SELECT away_team_abbreviation FROM nfl.main.current_scoreboard
);
```

Scores are `NULL` before kickoff. `status_state` is `pre`, `in`, or `post`.

Sleeper's `week` advances early in the week, while ESPN's
`current_scoreboard` keeps showing the last week played until the new week's
slate is posted. Between Monday night and midweek, `current_scoreboard.week`
matches `current_week.display_week` rather than `current_week.week`.

### Standings

```sql
SELECT division, division_rank, team_name, wins, losses, ties, games_back, streak
FROM nfl.main.current_standings
ORDER BY division, division_rank;

-- Final 2025 AFC seeds
SELECT playoff_seed, team_name, wins, losses, clincher
FROM nfl.main.standings(season := 2025)
WHERE conference = 'AFC'
ORDER BY playoff_seed;
```

`playoff_seed` follows ESPN's tiebreak order; seeds 1-7 make the playoffs.
`division_rank` is derived from that seed order within each division.
`clincher` uses ESPN's markers: `*` clinched the top seed and the only
first-round bye, `z` clinched the division, `y` clinched a wild card, `x`
clinched a playoff berth, and `e` eliminated. It is `NULL` until a team clinches
or is eliminated.

### Past weeks and team schedules

```sql
-- 2025 week 1
SELECT short_name, away_score, home_score, winner_abbreviation
FROM nfl.main.scoreboard(2025, 1)
ORDER BY game_time;

-- The Super Bowl that ended the 2025 season
SELECT name, away_score, home_score, venue
FROM nfl.main.scoreboard(2025, 5, season_type := 'postseason');

SELECT week, short_name, away_score, home_score, winner_abbreviation
FROM nfl.main.team_schedule('KC', season := 2025)
ORDER BY week;
```

`season_type` is `preseason`, `regular` (the default), or `postseason`.
Postseason weeks are 1 wild card, 2 divisional, 3 conference championship, and
5 Super Bowl.

### One game in detail

Every game function takes the ESPN game id and is served from one cached ESPN
summary request:

```sql
SELECT away_team_abbreviation, away_q1, away_q2, away_q3, away_q4, away_score,
       home_team_abbreviation, home_q1, home_q2, home_q3, home_q4, home_score, referee
FROM nfl.main.game_summary('401772510');

SELECT team_abbreviation, total_yards, passing_yards, rushing_yards,
       third_down_conversions, third_down_attempts, turnovers, possession_seconds
FROM nfl.main.box_score_team('401772510');

SELECT athlete_name, team_abbreviation, rush_attempts, rush_yards, rush_touchdowns
FROM nfl.main.box_score_player('401772510')
WHERE rush_attempts > 0
ORDER BY rush_yards DESC;

SELECT drive_number, team_abbreviation, plays, yards, result
FROM nfl.main.drives('401772510')
WHERE is_score;

SELECT period, clock, team_abbreviation, description, away_score, home_score
FROM nfl.main.scoring_plays('401772510');

SELECT clock, offense_abbreviation, down_distance_text, play_type, yards
FROM nfl.main.play_by_play_game('401772510')
WHERE period = 4
ORDER BY sequence;
```

`box_score_player` merges ESPN's passing, rushing, receiving, fumbles,
defensive, interception, return, kicking, and punting tables into one row per
player. Columns for categories a player did not record are `NULL`.

### Rosters, depth charts, and injuries

```sql
SELECT athlete_name, jersey, age, experience_years, college
FROM nfl.main.roster('KC')
WHERE position = 'QB';

SELECT formation, position, depth, athlete_name
FROM nfl.main.depth_chart('KC')
WHERE depth = 1
ORDER BY formation, position;

SELECT athlete_name, position, status, injury_type, return_date
FROM nfl.main.current_injuries
WHERE team_abbreviation = 'KC' AND status IN ('Out', 'Injured Reserve');
```

ESPN serves only the current roster and depth chart. Use `players` for
historical player information.

### Play-by-play analytics (nflverse)

```sql
-- EPA per dropback, 2025 regular season
SELECT passer_player_name,
       count(*) AS dropbacks,
       round(avg(epa), 3) AS epa_per_dropback
FROM nfl.main.play_by_play(season := 2025)
WHERE qb_dropback AND season_type = 'REG' AND passer_player_name IS NOT NULL
GROUP BY passer_player_name
HAVING count(*) >= 300
ORDER BY epa_per_dropback DESC;

-- Philadelphia's fourth-down attempts
SELECT week, quarter, yards_to_go, play_type, first_down
FROM nfl.main.play_by_play(season := 2025, team := 'PHI')
WHERE down = 4 AND posteam = 'PHI' AND play_type IN ('run', 'pass');
```

`play_by_play()` downloads one season file (about 20 MB, 1999 onward) and keeps
it in memory for at least an hour. The optional `week` and `team` filters run
before rows reach SQL. `team` matches either side of the game, and `posteam` is
the offense.

### Player and team statistics

```sql
SELECT player_display_name, recent_team, passing_yards, passing_tds, interceptions
FROM nfl.main.player_stats_season(season := 2025)
ORDER BY passing_yards DESC
LIMIT 10;

SELECT player_display_name, team, opponent_team, carries, rushing_yards
FROM nfl.main.player_stats_week(season := 2025, week := 1)
ORDER BY rushing_yards DESC
LIMIT 10;

SELECT team, rushing_yards, passing_epa, def_sacks
FROM nfl.main.team_stats(season := 2025)
ORDER BY rushing_yards DESC;

SELECT player, position, offense_snaps, offense_pct
FROM nfl.main.snap_counts(season := 2025, week := 1, team := 'KC')
ORDER BY offense_snaps DESC;

-- ESPN game log, long format: one row per game and stat
SELECT week, opponent_abbreviation, result, value AS passing_yards
FROM nfl.main.player_game_log(3139477, season := 2025)
WHERE stat = 'passingYards'
ORDER BY week;
```

`player_stats_season()` and `team_stats()` take `season_type` `REG` (the
default), `POST`, or `REGPOST`.

### Next Gen Stats, draft, and combine

```sql
SELECT player_display_name, team, attempts, completion_percentage_above_expectation
FROM nfl.main.ngs_passing(season := 2025, week := 0)
WHERE season_type = 'REG'
ORDER BY completion_percentage_above_expectation DESC;

SELECT pick, team, player_name, position, college
FROM nfl.main.draft(season := 2025)
WHERE draft_round = 1
ORDER BY pick;

SELECT player_name, position, school, forty
FROM nfl.main.combine(season := 2025)
WHERE forty IS NOT NULL
ORDER BY forty
LIMIT 10;
```

In the Next Gen Stats functions, week `0` rows are full-season aggregates. The
worker changes Next Gen Stats' `LAR` and the draft file's Pro Football Reference
codes (`KAN`, `NWE`, ...) to the usual nflverse codes, so every nflverse team
filter accepts the same spellings.

## Data sources, licences, and affiliation

**This project is not affiliated with, endorsed by, or sponsored by the
National Football League, its member clubs, ESPN, The Walt Disney Company,
nflverse, or Sleeper.** "NFL" and team names are trademarks of their owners.
They are used here only to describe the data.

- **ESPN.** The site, core, and common APIs that ESPN's own apps use are
  **undocumented and unofficial**. ESPN publishes no developer program for them,
  and they can change or disappear without notice. ESPN's data and these
  endpoints are subject to ESPN's and Disney's terms of use, and those terms
  restrict automated access. The worker fetches only what a query asks for,
  identifies itself with an honest `User-Agent`, paces and caches requests, and
  never redistributes ESPN data or logos. **You are responsible for making sure
  your use complies with ESPN's terms.**
- **nflverse** data is published under
  [CC-BY 4.0](https://github.com/nflverse/nflverse-data/blob/master/LICENSE.md).
  If you publish results derived from the `schedule`, `play_by_play`,
  `player_stats_*`, `team_stats`, `snap_counts`, `draft`, `combine`, `ngs_*`, or
  `players` objects, credit "nflverse" and link to the dataset. Some nflverse
  sub-datasets carry their own attribution terms. Next Gen Stats metrics
  originate with the NFL, and snap counts and draft outcomes with Pro Football
  Reference.
- **Sleeper**'s read-only API is documented and free to use. The worker calls
  only `/state/nfl`, at most once every five minutes per process.

The worker is a client that runs on your machine. It does not host, mirror, or
resell any of this data. Responses live only in process memory until their
cache lifetime expires.

## Production HTTP deployment

Stdio is the recommended transport when Haybarn can launch the worker locally.
Use HTTP when several hosts must share the worker. The production HTTP entry
point refuses to start unless it has a stable signing key and either
authentication or an explicit anonymous-access decision:

```bash
export VGI_SIGNING_KEY='a-long-random-secret-shared-by-every-replica'
export VGI_BEARER_TOKENS='replace-with-a-random-token=haybarn'

vgi-nfl-http \
  --host 0.0.0.0 \
  --port 8000 \
  --cors-origins 'https://sql.example.com' \
  --log-format json
```

`vgi-nfl-http` disables the description pages and cross-origin access unless
you configure them. Terminate TLS at a trusted proxy or load balancer. Give every
replica the same `VGI_SIGNING_KEY`. Rotate the key in a coordinated deployment,
because outstanding state tokens are signed with it.

Supported authentication options are:

- `VGI_BEARER_TOKENS`: comma-separated `token=principal` pairs.
- `VGI_JWT_ISSUER` and `VGI_JWT_AUDIENCE`: JWT/JWKS authentication.
- `VGI_PROXY_PROOF_MODE=require` with the matching VGI proxy-proof settings,
  when a trusted proxy authenticates users.

A deliberately public service can set `VGI_ALLOW_ANONYMOUS=1`. Put it behind
gateway rate limits so it cannot be used to hammer the upstream sources. The
health probe is `GET /health`.

### Container

```bash
docker build -t vgi-nfl .
docker run --rm -p 8000:8000 \
  -e VGI_SIGNING_KEY='replace-with-a-stable-random-secret' \
  -e VGI_BEARER_TOKENS='replace-with-a-random-token=haybarn' \
  vgi-nfl
```

The image runs as an unprivileged user, writes JSON logs, disables interactive
description pages, and includes a health check.

## Reliability and operations

All upstream traffic goes through one module (`vgi_nfl/api.py`):

- **Timeouts and retries.** Each request has a 30-second timeout (10 seconds to
  connect), and each query has a 120-second total deadline. A request is tried
  at most four times. HTTP 429 and transient 5xx responses are retried with
  jittered exponential backoff. `Retry-After` is honored, capped at 30 seconds.
- **Concurrency and pacing.** At most four upstream requests run at once per
  process. ESPN requests start at least 250 ms apart.
- **Redirects and encoding.** Redirects are followed (nflverse assets redirect
  to GitHub's CDN). ESPN bodies that arrive gzipped without a
  `Content-Encoding` header are decompressed.
- **Caching.** Responses are cached in memory, up to 256 MB with
  least-recently-used eviction. A response stays cached for its upstream
  `Cache-Control` `max-age`, clamped per source: ESPN for 30 seconds to 1 hour
  (5 minutes minimum for core-API depth charts), nflverse for 1 to 6 hours,
  Sleeper for 5 minutes to 1 hour. The remaining lifetime is passed to VGI
  clients as the result's cache policy. Error responses and payloads that fail
  validation, such as a non-Parquet body or a response for a league other than
  the NFL, are never cached.
- **No release listing.** nflverse file names are hardcoded, so the worker never
  calls GitHub's rate-limited REST API.

Retries and transport failures are logged as warnings. Per-request timings are
logged at debug level.

Each upstream root can be overridden for hermetic tests: `NFL_ESPN_SITE_URL`,
`NFL_ESPN_STANDINGS_URL`, `NFL_ESPN_CORE_URL`, `NFL_ESPN_COMMON_URL`,
`NFL_NFLVERSE_URL`, and `NFL_SLEEPER_URL`. Never set them from untrusted input.

## Development and release checks

```bash
uv lock --check --no-sources
uv sync --no-sources
uv run --no-sources ruff check .
uv run --no-sources ruff format --check .
uv run --no-sources pytest
uv build
uvx twine check dist/*
uvx --no-sources --from vgi-lint-check==2.2.0 vgi-lint lint \
  'uv run --no-sources nfl_worker.py' \
  --no-execute --no-check-links --audit-waivers --fail-on warning
```

The offline suite replays trimmed real responses from `tests/fixtures/`: ESPN
and Sleeper JSON, plus row-filtered nflverse Parquet files with their original
columns. The Haybarn end-to-end test points every source at a local replay
server, attaches the worker with `INSTALL vgi FROM community; LOAD vgi;`, and
queries every table.

Live smoke tests are opt-in with `uv run pytest -m live`. They are pinned to
the finished 2025 season (week 1 and ESPN game `401772510`). A serialized
scheduled workflow runs them, followed by the executing vgi-lint pass over every
catalog example. Agent-simulation graders live in `vgi-agent-tests.yaml`. Tasks
over moving data grade through `check_sql`, and tasks pinned to 2025 grade
against a reference solution.

Releases are driven by GitHub releases. Create a release named `vX.Y.Z` that
matches the version in `pyproject.toml`. CI then builds, attests, validates,
and publishes the distributions through PyPI trusted publishing, and publishes
a multi-platform container image to GHCR.

---

Copyright 2026 Query Farm LLC - https://query.farm. Released under the [MIT License](LICENSE).
