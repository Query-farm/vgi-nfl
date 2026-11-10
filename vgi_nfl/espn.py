"""Fetching and flattening ESPN's undocumented NFL site, core, and common APIs.

ESPN publishes no developer program for these endpoints. They are fetched on
demand, cached briefly in memory, and never rehosted. Every flattener is a pure
function from a decoded payload to row dictionaries so it can be tested from
recorded fixtures.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from vgi_nfl import api
from vgi_nfl.convert import (
    athlete_id_from_links,
    clock_seconds,
    mapping,
    sequence,
    split_pair,
    to_bool,
    to_date,
    to_decimal,
    to_int,
    to_text,
    to_timestamp,
)

SEASON_TYPES = {"preseason": 1, "regular": 2, "postseason": 3}
#: nflverse spellings that ESPN abbreviates differently.
TEAM_ALIASES = {"LA": "LAR", "WAS": "WSH", "OAK": "LV", "SD": "LAC", "STL": "LAR"}
_REF_ID = re.compile(r"/athletes/(\d+)")


class UnknownTeamError(ValueError):
    """Raised when a team argument does not match an NFL team."""


def _check_league(payload: Any) -> None:
    """Reject a payload that identifies another league, so it is never cached or served."""
    if not isinstance(payload, Mapping):
        raise ValueError("ESPN returned a non-object JSON document")
    leagues = sequence(payload.get("leagues"))
    if not leagues:
        sports = sequence(payload.get("sports"))
        leagues = sequence(mapping(sports[0]).get("leagues")) if sports else []
    if leagues:
        slug = mapping(leagues[0]).get("slug")
        if slug is not None and slug != "nfl":
            raise ValueError(f"ESPN returned data for league {slug!r} instead of the NFL; retry later")


# --------------------------------------------------------------------------- teams


def flatten_teams(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Flatten ``/teams`` into one row per franchise."""
    sports = sequence(payload.get("sports"))
    leagues = sequence(mapping(sports[0]).get("leagues")) if sports else []
    teams = sequence(mapping(leagues[0]).get("teams")) if leagues else []
    rows = []
    for entry in teams:
        team = mapping(mapping(entry).get("team"))
        rows.append(
            {
                "team_id": to_int(team.get("id")),
                "team_abbreviation": to_text(team.get("abbreviation")),
                "team_name": to_text(team.get("displayName")),
                "short_name": to_text(team.get("shortDisplayName")),
                "location": to_text(team.get("location")),
                "nickname": to_text(team.get("nickname") or team.get("name")),
                "slug": to_text(team.get("slug")),
                "color": to_text(team.get("color")),
                "alternate_color": to_text(team.get("alternateColor")),
                "is_active": to_bool(team.get("isActive")),
            }
        )
    return rows


def fetch_teams() -> tuple[list[dict[str, Any]], int]:
    """Fetch every NFL franchise."""
    payload, ttl = api.fetch_json(api.ESPN_SITE, "teams", {"limit": 50}, check=_check_league)
    rows = flatten_teams(payload)
    if not rows:
        raise ValueError("ESPN teams response contained no teams")
    return rows, ttl


def resolve_team(team: str) -> dict[str, Any]:
    """Resolve an ESPN or nflverse team abbreviation (case-insensitive) to its team row."""
    wanted = team.strip().upper()
    wanted = TEAM_ALIASES.get(wanted, wanted)
    rows, _ttl = fetch_teams()
    for row in rows:
        if (row["team_abbreviation"] or "").upper() == wanted:
            return row
    known = ", ".join(sorted(row["team_abbreviation"] for row in rows if row["team_abbreviation"]))
    raise UnknownTeamError(f"Unknown NFL team {team!r}; expected one of: {known}")


# ----------------------------------------------------------------------- standings


def _stats(entry: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    """Index a standings entry's stats by name, falling back to type for record summaries."""
    result: dict[str, Mapping[str, Any]] = {}
    for raw in sequence(entry.get("stats")):
        stat = mapping(raw)
        key = stat.get("name") or stat.get("type")
        if isinstance(key, str):
            result.setdefault(key, stat)
        kind = stat.get("type")
        if isinstance(kind, str):
            result.setdefault(f"type:{kind}", stat)
    return result


def flatten_standings(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Flatten the ``level=3`` standings tree into one row per team."""
    rows: list[dict[str, Any]] = []
    for conference in sequence(payload.get("children")):
        conference = mapping(conference)
        for division in sequence(conference.get("children")):
            division = mapping(division)
            standings = mapping(division.get("standings"))
            division_rows = []
            for raw_entry in sequence(standings.get("entries")):
                entry = mapping(raw_entry)
                team = mapping(entry.get("team"))
                stats = _stats(entry)

                def value(name: str, stats: dict[str, Mapping[str, Any]] = stats) -> Any:
                    return stats.get(name, {}).get("value")

                def display(name: str, stats: dict[str, Mapping[str, Any]] = stats) -> Any:
                    stat = stats.get(name, {})
                    return stat.get("displayValue", stat.get("summary"))

                games_back = display("gamesBehind")
                division_rows.append(
                    {
                        "season": to_int(standings.get("season")),
                        "season_type": to_int(standings.get("seasonType")),
                        "conference": to_text(conference.get("abbreviation")),
                        "conference_name": to_text(conference.get("name")),
                        "division": to_text(division.get("name")),
                        "playoff_seed": to_int(value("playoffSeed")),
                        "team_id": to_int(team.get("id")),
                        "team_abbreviation": to_text(team.get("abbreviation")),
                        "team_name": to_text(team.get("displayName")),
                        "wins": to_int(value("wins")),
                        "losses": to_int(value("losses")),
                        "ties": to_int(value("ties")),
                        "win_percentage": to_decimal(value("winPercent"), 3),
                        "games_back": to_decimal("0" if games_back == "-" else value("gamesBehind"), 1),
                        "points_for": to_int(value("pointsFor")),
                        "points_against": to_int(value("pointsAgainst")),
                        "point_differential": to_int(value("pointDifferential")),
                        "streak": to_text(display("streak")),
                        "streak_length": to_int(value("streak")),
                        "home_record": to_text(display("type:home")),
                        "road_record": to_text(display("type:road")),
                        "division_record": to_text(display("type:vsdiv")),
                        "conference_record": to_text(display("type:vsconf")),
                        "clincher": to_text(display("clincher")),
                    }
                )
            division_rows.sort(
                key=lambda row: (
                    row["playoff_seed"] is None,
                    row["playoff_seed"] or 0,
                    row["team_abbreviation"] or "",
                )
            )
            for rank, row in enumerate(division_rows, start=1):
                row["division_rank"] = rank
            rows.extend(division_rows)
    return rows


def fetch_standings(season: int | None = None, season_type: int = 2) -> tuple[list[dict[str, Any]], int]:
    """Fetch division standings for a season; NULL season means ESPN's current season."""
    params: dict[str, str | int] = {"level": 3, "seasontype": season_type}
    if season is not None:
        params["season"] = season
    payload, ttl = api.fetch_json(api.ESPN_STANDINGS, "standings", params, check=_check_league)
    return flatten_standings(payload), ttl


# -------------------------------------------------------------------- scoreboards


def _score(value: Any) -> int | None:
    if isinstance(value, Mapping):
        return to_int(value.get("value", value.get("displayValue")))
    return to_int(value)


def _record(competitor: Mapping[str, Any]) -> str | None:
    for raw in sequence(competitor.get("records")) or sequence(competitor.get("record")):
        record = mapping(raw)
        if record.get("type") == "total" or record.get("name") == "overall":
            return to_text(record.get("summary") or record.get("displayValue"))
    return None


def _broadcast(competition: Mapping[str, Any]) -> str | None:
    text = to_text(competition.get("broadcast"))
    if text:
        return text
    names: list[str] = []
    for raw in sequence(competition.get("broadcasts")):
        broadcast = mapping(raw)
        names.extend(str(name) for name in sequence(broadcast.get("names")) if name)
        short = mapping(broadcast.get("media")).get("shortName")
        if short:
            names.append(str(short))
    return "/".join(dict.fromkeys(names)) or None


def _competitors(competition: Mapping[str, Any]) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    home: Mapping[str, Any] = {}
    away: Mapping[str, Any] = {}
    for raw in sequence(competition.get("competitors")):
        competitor = mapping(raw)
        if competitor.get("homeAway") == "home":
            home = competitor
        elif competitor.get("homeAway") == "away":
            away = competitor
    return home, away


def flatten_event(event: Mapping[str, Any], season_type: int | None = None) -> dict[str, Any]:
    """Flatten one scoreboard or team-schedule event into a game row."""
    competition = mapping(sequence(event.get("competitions"))[0]) if event.get("competitions") else {}
    status = mapping(competition.get("status") or event.get("status"))
    status_type = mapping(status.get("type"))
    home, away = _competitors(competition)
    home_team = mapping(home.get("team"))
    away_team = mapping(away.get("team"))
    venue = mapping(competition.get("venue"))
    address = mapping(venue.get("address"))
    season = mapping(event.get("season"))
    event_season_type = to_int(season.get("type")) or to_int(mapping(event.get("seasonType")).get("type"))
    winner = None
    if home.get("winner") is True:
        winner = home_team.get("abbreviation")
    elif away.get("winner") is True:
        winner = away_team.get("abbreviation")
    return {
        "game_id": to_text(event.get("id")),
        "season": to_int(season.get("year")),
        "season_type": event_season_type or season_type,
        "week": to_int(mapping(event.get("week")).get("number")),
        "game_time": to_timestamp(event.get("date") or competition.get("date")),
        "name": to_text(event.get("name")),
        "short_name": to_text(event.get("shortName")),
        "status": to_text(status_type.get("name")),
        "status_state": to_text(status_type.get("state")),
        "status_detail": to_text(status_type.get("detail") or status_type.get("description")),
        "completed": to_bool(status_type.get("completed")),
        "period": to_int(status.get("period")),
        "clock": to_text(status.get("displayClock")),
        "home_team_id": to_int(home_team.get("id")),
        "home_team_abbreviation": to_text(home_team.get("abbreviation")),
        "home_team_name": to_text(home_team.get("displayName")),
        "home_score": _score(home.get("score")),
        "home_record": _record(home),
        "away_team_id": to_int(away_team.get("id")),
        "away_team_abbreviation": to_text(away_team.get("abbreviation")),
        "away_team_name": to_text(away_team.get("displayName")),
        "away_score": _score(away.get("score")),
        "away_record": _record(away),
        "winner_abbreviation": to_text(winner),
        "venue": to_text(venue.get("fullName")),
        "venue_city": to_text(address.get("city")),
        "venue_state": to_text(address.get("state")),
        "neutral_site": to_bool(competition.get("neutralSite")),
        "attendance": to_int(competition.get("attendance")),
        "broadcast": _broadcast(competition),
    }


def _pregame_scores(row: dict[str, Any]) -> dict[str, Any]:
    """ESPN reports 0-0 before kickoff; expose unknown scores as NULL."""
    if row["status_state"] == "pre":
        row["home_score"] = None
        row["away_score"] = None
    return row


def flatten_scoreboard(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Flatten a ``/scoreboard`` response into one row per game."""
    season_type = to_int(mapping(payload.get("season")).get("type"))
    return [
        _pregame_scores(flatten_event(mapping(event), season_type))
        for event in sequence(payload.get("events"))
    ]


def fetch_scoreboard(
    season: int | None = None, week: int | None = None, season_type: int | None = None
) -> tuple[list[dict[str, Any]], int]:
    """Fetch a week of games; with no arguments ESPN returns the current week."""
    params: dict[str, str | int] = {}
    if season is not None:
        params["dates"] = season
    if week is not None:
        params["week"] = week
    if season_type is not None:
        params["seasontype"] = season_type
    if params:
        params["limit"] = 100
    payload, ttl = api.fetch_json(api.ESPN_SITE, "scoreboard", params, check=_check_league)
    return flatten_scoreboard(payload), ttl


def flatten_team_schedule(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Flatten a team ``/schedule`` response into one row per game."""
    return [_pregame_scores(flatten_event(mapping(event))) for event in sequence(payload.get("events"))]


def fetch_team_schedule(
    team: str, season: int | None = None, season_type: int = 2
) -> tuple[list[dict[str, Any]], int]:
    """Fetch one team's games for a season and season type."""
    abbreviation = str(resolve_team(team)["team_abbreviation"]).lower()
    params: dict[str, str | int] = {"seasontype": season_type}
    if season is not None:
        params["season"] = season
    payload, ttl = api.fetch_json(api.ESPN_SITE, f"teams/{abbreviation}/schedule", params)
    return flatten_team_schedule(payload), ttl


# ------------------------------------------------------------------------ injuries


def flatten_injuries(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Flatten league-wide ``/injuries`` into one row per report entry."""
    rows = []
    for raw_team in sequence(payload.get("injuries")):
        team_block = mapping(raw_team)
        for raw in sequence(team_block.get("injuries")):
            injury = mapping(raw)
            athlete = mapping(injury.get("athlete"))
            team = mapping(athlete.get("team"))
            details = mapping(injury.get("details"))
            kind = mapping(injury.get("type"))
            rows.append(
                {
                    "injury_id": to_text(injury.get("id")),
                    "team_id": to_int(team.get("id") or team_block.get("id")),
                    "team_abbreviation": to_text(team.get("abbreviation")),
                    "team_name": to_text(team.get("displayName") or team_block.get("displayName")),
                    "athlete_id": to_int(athlete.get("id")) or athlete_id_from_links(athlete.get("links")),
                    "athlete_name": to_text(athlete.get("displayName")),
                    "position": to_text(mapping(athlete.get("position")).get("abbreviation")),
                    "status": to_text(injury.get("status")),
                    "status_abbreviation": to_text(kind.get("abbreviation")),
                    "injury_type": to_text(details.get("type")),
                    "injury_location": to_text(details.get("location")),
                    "injury_detail": _specified(details.get("detail")),
                    "injury_side": _specified(details.get("side")),
                    "return_date": to_date(details.get("returnDate")),
                    "short_comment": to_text(injury.get("shortComment")),
                    "long_comment": to_text(injury.get("longComment")),
                    "reported_at": to_timestamp(injury.get("date")),
                }
            )
    return rows


def _specified(value: Any) -> str | None:
    text = to_text(value)
    return None if text == "Not Specified" else text


def fetch_injuries() -> tuple[list[dict[str, Any]], int]:
    """Fetch the league-wide injury report (several MB, so it is cached)."""
    payload, ttl = api.fetch_json(api.ESPN_SITE, "injuries")
    return flatten_injuries(payload), ttl


# --------------------------------------------------------------------- roster/depth


def _birth_place(value: Any) -> str | None:
    place = mapping(value)
    parts = [place.get("city"), place.get("state") or place.get("country")]
    return ", ".join(str(part) for part in parts if part) or None


def flatten_roster(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Flatten a team ``/roster`` response into one row per player."""
    team = mapping(payload.get("team"))
    season = to_int(mapping(payload.get("season")).get("year"))
    rows = []
    for raw_group in sequence(payload.get("athletes")):
        group = mapping(raw_group)
        for raw in sequence(group.get("items")):
            athlete = mapping(raw)
            position = mapping(athlete.get("position"))
            rows.append(
                {
                    "team_id": to_int(team.get("id")),
                    "team_abbreviation": to_text(team.get("abbreviation")),
                    "season": season,
                    "roster_group": to_text(group.get("position")),
                    "athlete_id": to_int(athlete.get("id")),
                    "athlete_name": to_text(athlete.get("fullName") or athlete.get("displayName")),
                    "first_name": to_text(athlete.get("firstName")),
                    "last_name": to_text(athlete.get("lastName")),
                    "jersey": to_text(athlete.get("jersey")),
                    "position": to_text(position.get("abbreviation")),
                    "position_name": to_text(position.get("displayName") or position.get("name")),
                    "age": to_int(athlete.get("age")),
                    "birth_date": to_date(athlete.get("dateOfBirth")),
                    "height_inches": to_int(athlete.get("height")),
                    "weight_lbs": to_int(athlete.get("weight")),
                    "experience_years": to_int(mapping(athlete.get("experience")).get("years")),
                    "college": to_text(mapping(athlete.get("college")).get("name")),
                    "birth_place": _birth_place(athlete.get("birthPlace")),
                    "status": to_text(mapping(athlete.get("status")).get("name")),
                }
            )
    return rows


def fetch_roster(team: str) -> tuple[list[dict[str, Any]], int]:
    """Fetch a team's current roster."""
    abbreviation = str(resolve_team(team)["team_abbreviation"]).lower()
    payload, ttl = api.fetch_json(api.ESPN_SITE, f"teams/{abbreviation}/roster")
    return flatten_roster(payload), ttl


def flatten_depth_chart(
    payload: Mapping[str, Any],
    *,
    team: Mapping[str, Any],
    season: int | None,
    roster: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Flatten core-API depth charts, naming athletes from the team roster."""
    names = {row["athlete_id"]: row for row in roster if row.get("athlete_id") is not None}
    rows = []
    for raw_formation in sequence(payload.get("items")):
        formation = mapping(raw_formation)
        for key, raw_slot in mapping(formation.get("positions")).items():
            slot = mapping(raw_slot)
            position = mapping(slot.get("position"))
            for raw_athlete in sequence(slot.get("athletes")):
                entry = mapping(raw_athlete)
                match = _REF_ID.search(str(mapping(entry.get("athlete")).get("$ref", "")))
                athlete_id = int(match.group(1)) if match else None
                known = names.get(athlete_id, {})
                rows.append(
                    {
                        "team_id": team.get("team_id"),
                        "team_abbreviation": team.get("team_abbreviation"),
                        "season": season,
                        "formation": to_text(formation.get("name")),
                        "position_key": to_text(key),
                        "position": to_text(position.get("abbreviation")),
                        "position_name": to_text(position.get("displayName") or position.get("name")),
                        "depth": to_int(entry.get("rank")),
                        "athlete_id": athlete_id,
                        "athlete_name": known.get("athlete_name"),
                        "jersey": known.get("jersey"),
                    }
                )
    return rows


def fetch_depth_chart(team: str) -> tuple[list[dict[str, Any]], int]:
    """Fetch a team's current depth chart (one core request plus the roster for names)."""
    resolved = resolve_team(team)
    roster, roster_ttl = fetch_roster(str(resolved["team_abbreviation"]))
    season = next((row["season"] for row in roster if row.get("season") is not None), None)
    if season is None:
        raise ValueError("ESPN roster response did not identify the current season")
    payload, ttl = api.fetch_json(
        api.ESPN_CORE,
        f"seasons/{season}/teams/{resolved['team_id']}/depthcharts",
        {"limit": 50},
    )
    rows = flatten_depth_chart(payload, team=resolved, season=season, roster=roster)
    return rows, min(ttl, roster_ttl)


# -------------------------------------------------------------------- game summary


def fetch_summary(game_id: str) -> tuple[Mapping[str, Any], int]:
    """Fetch ESPN's full game summary (box score, drives, scoring plays)."""
    if not game_id.isdigit():
        raise ValueError("game_id must be a numeric ESPN event id, for example '401772510'")
    payload, ttl = api.fetch_json(api.ESPN_SITE, "summary", {"event": game_id})
    if not isinstance(payload, Mapping) or not isinstance(payload.get("header"), Mapping):
        raise ValueError(f"ESPN has no game summary for event {game_id}")
    return payload, ttl


def _linescores(competitor: Mapping[str, Any]) -> list[int | None]:
    return [to_int(mapping(score).get("displayValue")) for score in sequence(competitor.get("linescores"))]


def flatten_game_summary(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Flatten the summary header and game info into one game row."""
    header = mapping(payload.get("header"))
    event = {
        "id": header.get("id"),
        "season": header.get("season"),
        "week": {"number": header.get("week")},
        "competitions": header.get("competitions"),
        "name": None,
        "shortName": None,
    }
    competition = mapping(sequence(header.get("competitions"))[0]) if header.get("competitions") else {}
    home, away = _competitors(competition)
    game_info = mapping(payload.get("gameInfo"))
    venue = mapping(game_info.get("venue"))
    address = mapping(venue.get("address"))
    row = flatten_event(event)
    home_team = mapping(home.get("team"))
    away_team = mapping(away.get("team"))
    row["name"] = (
        f"{away_team['displayName']} at {home_team['displayName']}"
        if away_team.get("displayName") and home_team.get("displayName")
        else None
    )
    row["short_name"] = (
        f"{away_team['abbreviation']} @ {home_team['abbreviation']}"
        if away_team.get("abbreviation") and home_team.get("abbreviation")
        else None
    )
    row["venue"] = to_text(venue.get("fullName")) or row["venue"]
    row["venue_city"] = to_text(address.get("city")) or row["venue_city"]
    row["venue_state"] = to_text(address.get("state")) or row["venue_state"]
    row["attendance"] = to_int(game_info.get("attendance")) or row["attendance"]
    row["grass"] = to_bool(venue.get("grass"))
    row["referee"] = next(
        (
            to_text(mapping(official).get("displayName"))
            for official in sequence(game_info.get("officials"))
            if mapping(mapping(official).get("position")).get("name") == "Referee"
        ),
        None,
    )
    if row["period"] is None:
        row["period"] = max((len(_linescores(side)) for side in (home, away)), default=0) or None
    for side, competitor in (("home", home), ("away", away)):
        scores = _linescores(competitor)
        for quarter in range(4):
            row[f"{side}_q{quarter + 1}"] = scores[quarter] if quarter < len(scores) else None
        extra = [score for score in scores[4:] if score is not None]
        row[f"{side}_ot"] = sum(extra) if len(scores) > 4 else None
    return [_pregame_scores(row)]


_TEAM_STATS: dict[str, tuple[str, ...]] = {
    "firstDowns": ("first_downs",),
    "firstDownsPassing": ("first_downs_passing",),
    "firstDownsRushing": ("first_downs_rushing",),
    "firstDownsPenalty": ("first_downs_penalty",),
    "thirdDownEff": ("third_down_conversions", "third_down_attempts"),
    "fourthDownEff": ("fourth_down_conversions", "fourth_down_attempts"),
    "totalOffensivePlays": ("total_plays",),
    "totalYards": ("total_yards",),
    "yardsPerPlay": ("yards_per_play",),
    "totalDrives": ("total_drives",),
    "netPassingYards": ("passing_yards",),
    "completionAttempts": ("pass_completions", "pass_attempts"),
    "yardsPerPass": ("yards_per_pass",),
    "interceptions": ("interceptions_thrown",),
    "sacksYardsLost": ("sacks_allowed", "sack_yards_lost"),
    "rushingYards": ("rushing_yards",),
    "rushingAttempts": ("rushing_attempts",),
    "yardsPerRushAttempt": ("yards_per_rush",),
    "redZoneAttempts": ("red_zone_conversions", "red_zone_attempts"),
    "totalPenaltiesYards": ("penalties", "penalty_yards"),
    "turnovers": ("turnovers",),
    "fumblesLost": ("fumbles_lost",),
    "defensiveTouchdowns": ("defensive_touchdowns",),
}
_DECIMAL_TEAM_STATS = {"yards_per_play", "yards_per_pass", "yards_per_rush"}


def flatten_box_team(payload: Mapping[str, Any], game_id: str) -> list[dict[str, Any]]:
    """Flatten the team box score into one row per team."""
    rows = []
    for raw in sequence(mapping(payload.get("boxscore")).get("teams")):
        block = mapping(raw)
        team = mapping(block.get("team"))
        row: dict[str, Any] = {
            "game_id": game_id,
            "team_id": to_int(team.get("id")),
            "team_abbreviation": to_text(team.get("abbreviation")),
            "team_name": to_text(team.get("displayName")),
            "home_away": to_text(block.get("homeAway")),
        }
        for raw_stat in sequence(block.get("statistics")):
            stat = mapping(raw_stat)
            columns = _TEAM_STATS.get(str(stat.get("name")))
            if not columns or columns[0] in row:
                continue  # ESPN repeats "interceptions"; the first is the offense's.
            shown = stat.get("displayValue")
            if len(columns) == 2:
                separator = "/" if "/" in str(shown) else "-"
                row[columns[0]], row[columns[1]] = split_pair(shown, separator)
            elif columns[0] in _DECIMAL_TEAM_STATS:
                row[columns[0]] = to_decimal(shown, 1)
            else:
                row[columns[0]] = to_int(shown)
        possession = next(
            (
                mapping(stat).get("displayValue")
                for stat in sequence(block.get("statistics"))
                if mapping(stat).get("name") == "possessionTime"
            ),
            None,
        )
        row["possession_seconds"] = clock_seconds(possession)
        rows.append(row)
    return rows


#: (ESPN category, ESPN stat key) -> (column, kind) where kind is int, dec, or a pair half.
_PLAYER_STATS: dict[tuple[str, str], tuple[tuple[str, ...], str]] = {
    ("passing", "completions/passingAttempts"): (("pass_completions", "pass_attempts"), "/"),
    ("passing", "passingYards"): (("pass_yards",), "int"),
    ("passing", "passingTouchdowns"): (("pass_touchdowns",), "int"),
    ("passing", "interceptions"): (("interceptions_thrown",), "int"),
    ("passing", "sacks-sackYardsLost"): (("sacks_taken", "sack_yards_lost"), "-"),
    ("passing", "QBRating"): (("passer_rating",), "dec"),
    ("passing", "adjQBR"): (("qbr",), "dec"),
    ("rushing", "rushingAttempts"): (("rush_attempts",), "int"),
    ("rushing", "rushingYards"): (("rush_yards",), "int"),
    ("rushing", "rushingTouchdowns"): (("rush_touchdowns",), "int"),
    ("rushing", "longRushing"): (("rush_long",), "int"),
    ("receiving", "receptions"): (("receptions",), "int"),
    ("receiving", "receivingTargets"): (("targets",), "int"),
    ("receiving", "receivingYards"): (("receiving_yards",), "int"),
    ("receiving", "receivingTouchdowns"): (("receiving_touchdowns",), "int"),
    ("receiving", "longReception"): (("receiving_long",), "int"),
    ("fumbles", "fumbles"): (("fumbles",), "int"),
    ("fumbles", "fumblesLost"): (("fumbles_lost",), "int"),
    ("defensive", "totalTackles"): (("tackles",), "int"),
    ("defensive", "soloTackles"): (("solo_tackles",), "int"),
    ("defensive", "sacks"): (("sacks",), "dec"),
    ("defensive", "tacklesForLoss"): (("tackles_for_loss",), "int"),
    ("defensive", "passesDefended"): (("passes_defended",), "int"),
    ("defensive", "QBHits"): (("qb_hits",), "int"),
    ("defensive", "defensiveTouchdowns"): (("defensive_touchdowns",), "int"),
    ("interceptions", "interceptions"): (("interceptions",), "int"),
    ("interceptions", "interceptionYards"): (("interception_yards",), "int"),
    ("kickReturns", "kickReturns"): (("kick_returns",), "int"),
    ("kickReturns", "kickReturnYards"): (("kick_return_yards",), "int"),
    ("kickReturns", "kickReturnTouchdowns"): (("kick_return_touchdowns",), "int"),
    ("puntReturns", "puntReturns"): (("punt_returns",), "int"),
    ("puntReturns", "puntReturnYards"): (("punt_return_yards",), "int"),
    ("puntReturns", "puntReturnTouchdowns"): (("punt_return_touchdowns",), "int"),
    ("kicking", "fieldGoalsMade/fieldGoalAttempts"): (("field_goals_made", "field_goals_attempted"), "/"),
    ("kicking", "longFieldGoalMade"): (("field_goal_long",), "int"),
    ("kicking", "extraPointsMade/extraPointAttempts"): (("extra_points_made", "extra_points_attempted"), "/"),
    ("kicking", "totalKickingPoints"): (("kicking_points",), "int"),
    ("punting", "punts"): (("punts",), "int"),
    ("punting", "puntYards"): (("punt_yards",), "int"),
    ("punting", "puntsInside20"): (("punts_inside_20",), "int"),
}


def flatten_box_player(payload: Mapping[str, Any], game_id: str) -> list[dict[str, Any]]:
    """Merge every per-category player box score into one row per player."""
    rows: dict[tuple[int | None, int | None], dict[str, Any]] = {}
    for raw_team in sequence(mapping(payload.get("boxscore")).get("players")):
        team_block = mapping(raw_team)
        team = mapping(team_block.get("team"))
        team_id = to_int(team.get("id"))
        for raw_category in sequence(team_block.get("statistics")):
            category = mapping(raw_category)
            name = str(category.get("name"))
            keys = [str(key) for key in sequence(category.get("keys"))]
            for raw_athlete in sequence(category.get("athletes")):
                entry = mapping(raw_athlete)
                athlete = mapping(entry.get("athlete"))
                athlete_id = to_int(athlete.get("id"))
                row = rows.setdefault(
                    (team_id, athlete_id),
                    {
                        "game_id": game_id,
                        "team_id": team_id,
                        "team_abbreviation": to_text(team.get("abbreviation")),
                        "athlete_id": athlete_id,
                        "athlete_name": to_text(athlete.get("displayName")),
                        "jersey": to_text(athlete.get("jersey")),
                    },
                )
                for key, shown in zip(keys, sequence(entry.get("stats")), strict=False):
                    target = _PLAYER_STATS.get((name, key))
                    if target is None:
                        continue
                    columns, kind = target
                    if kind in {"/", "-"}:
                        row[columns[0]], row[columns[1]] = split_pair(shown, kind)
                    elif kind == "dec":
                        row[columns[0]] = to_decimal(shown, 1)
                    else:
                        row[columns[0]] = to_int(shown)
    return list(rows.values())


def _drive_list(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    drives = mapping(payload.get("drives"))
    result = [mapping(drive) for drive in sequence(drives.get("previous"))]
    current = mapping(drives.get("current"))
    if current and all(drive.get("id") != current.get("id") for drive in result):
        result.append(current)
    return result


def flatten_drives(payload: Mapping[str, Any], game_id: str) -> list[dict[str, Any]]:
    """Flatten the drive chart into one row per drive."""
    rows = []
    for number, drive in enumerate(_drive_list(payload), start=1):
        team = mapping(drive.get("team"))
        start = mapping(drive.get("start"))
        end = mapping(drive.get("end"))
        rows.append(
            {
                "game_id": game_id,
                "drive_number": number,
                "drive_id": to_text(drive.get("id")),
                "team_id": to_int(team.get("id")),
                "team_abbreviation": to_text(team.get("abbreviation")),
                "start_period": to_int(mapping(start.get("period")).get("number")),
                "start_clock": to_text(mapping(start.get("clock")).get("displayValue")),
                "start_field_position": to_text(start.get("text")),
                "end_period": to_int(mapping(end.get("period")).get("number")),
                "end_clock": to_text(mapping(end.get("clock")).get("displayValue")),
                "end_field_position": to_text(end.get("text")),
                "plays": to_int(drive.get("offensivePlays")),
                "yards": to_int(drive.get("yards")),
                "duration_seconds": clock_seconds(mapping(drive.get("timeElapsed")).get("displayValue")),
                "result": to_text(drive.get("displayResult") or drive.get("result")),
                "is_score": to_bool(drive.get("isScore")),
                "description": to_text(drive.get("description")),
            }
        )
    return rows


def flatten_plays(payload: Mapping[str, Any], game_id: str) -> list[dict[str, Any]]:
    """Flatten every play inside the drive chart, in game order."""
    abbreviations = {
        to_int(mapping(mapping(block).get("team")).get("id")): mapping(mapping(block).get("team")).get(
            "abbreviation"
        )
        for block in sequence(mapping(payload.get("boxscore")).get("teams"))
    }
    rows = []
    for number, drive in enumerate(_drive_list(payload), start=1):
        for raw_play in sequence(drive.get("plays")):
            play = mapping(raw_play)
            start = mapping(play.get("start"))
            offense = to_int(mapping(start.get("team")).get("id")) or to_int(
                mapping(drive.get("team")).get("id")
            )
            down = to_int(start.get("down"))
            rows.append(
                {
                    "game_id": game_id,
                    "play_id": to_text(play.get("id")),
                    "sequence": to_int(play.get("sequenceNumber")),
                    "drive_number": number,
                    "offense_team_id": offense,
                    "offense_abbreviation": to_text(abbreviations.get(offense)),
                    "period": to_int(mapping(play.get("period")).get("number")),
                    "clock": to_text(mapping(play.get("clock")).get("displayValue")),
                    "play_type": to_text(mapping(play.get("type")).get("text")),
                    "description": to_text(play.get("text")),
                    "down": down or None,
                    "distance": to_int(start.get("distance")) if down else None,
                    "yards_to_endzone": to_int(start.get("yardsToEndzone")),
                    "down_distance_text": to_text(start.get("downDistanceText")),
                    "yards": to_int(play.get("statYardage")),
                    "scoring_play": to_bool(play.get("scoringPlay")),
                    "penalty": to_bool(play.get("isPenalty")),
                    "turnover": to_bool(play.get("isTurnover")),
                    "away_score": to_int(play.get("awayScore")),
                    "home_score": to_int(play.get("homeScore")),
                    "wallclock": to_timestamp(play.get("wallclock")),
                }
            )
    return rows


def flatten_scoring_plays(payload: Mapping[str, Any], game_id: str) -> list[dict[str, Any]]:
    """Flatten the scoring summary into one row per score."""
    rows = []
    for raw in sequence(payload.get("scoringPlays")):
        play = mapping(raw)
        team = mapping(play.get("team"))
        rows.append(
            {
                "game_id": game_id,
                "play_id": to_text(play.get("id")),
                "period": to_int(mapping(play.get("period")).get("number")),
                "clock": to_text(mapping(play.get("clock")).get("displayValue")),
                "team_id": to_int(team.get("id")),
                "team_abbreviation": to_text(team.get("abbreviation")),
                "scoring_type": to_text(mapping(play.get("scoringType")).get("displayName")),
                "play_type": to_text(mapping(play.get("type")).get("text")),
                "description": to_text(play.get("text")),
                "away_score": to_int(play.get("awayScore")),
                "home_score": to_int(play.get("homeScore")),
            }
        )
    return rows


# ------------------------------------------------------------------------ game log


def flatten_game_log(payload: Mapping[str, Any], athlete_id: int) -> list[dict[str, Any]]:
    """Flatten a common-API athlete game log into one row per game and stat."""
    names = [str(name) for name in sequence(payload.get("names"))]
    labels = [str(label) for label in sequence(payload.get("labels"))]
    categories: list[str] = []
    for raw in sequence(payload.get("categories")):
        category = mapping(raw)
        categories.extend([str(category.get("name"))] * (to_int(category.get("count")) or 0))
    events = mapping(payload.get("events"))
    rows = []
    for raw_season in sequence(payload.get("seasonTypes")):
        season_block = mapping(raw_season)
        label = to_text(season_block.get("displayName"))
        season = to_int(label[:4]) if label and label[:4].isdigit() else None
        for raw_category in sequence(season_block.get("categories")):
            for raw_event in sequence(mapping(raw_category).get("events")):
                entry = mapping(raw_event)
                game_id = to_text(entry.get("eventId"))
                event = mapping(events.get(game_id or ""))
                team = mapping(event.get("team"))
                home_team = to_text(event.get("homeTeamId"))
                if home_team and team.get("id"):
                    home_away = "home" if str(team.get("id")) == home_team else "away"
                else:
                    at_vs = event.get("atVs")
                    home_away = "away" if at_vs == "@" else "home" if at_vs == "vs" else None
                for index, shown in enumerate(sequence(entry.get("stats"))):
                    rows.append(
                        {
                            "athlete_id": athlete_id,
                            "season": season,
                            "season_label": label,
                            "game_id": game_id,
                            "game_time": to_timestamp(event.get("gameDate")),
                            "week": to_int(event.get("week")),
                            "team_abbreviation": to_text(team.get("abbreviation")),
                            "opponent_abbreviation": to_text(
                                mapping(event.get("opponent")).get("abbreviation")
                            ),
                            "home_away": home_away,
                            "result": to_text(event.get("gameResult")),
                            "score": to_text(event.get("score")),
                            "category": categories[index] if index < len(categories) else None,
                            "stat": names[index] if index < len(names) else None,
                            "label": labels[index] if index < len(labels) else None,
                            "value": to_decimal(shown, 3),
                            "display_value": to_text(shown),
                        }
                    )
    return rows


def fetch_game_log(athlete_id: int, season: int | None = None) -> tuple[list[dict[str, Any]], int]:
    """Fetch one athlete's per-game statistics for a season."""
    if athlete_id <= 0:
        raise ValueError("athlete_id must be a positive ESPN athlete id")
    params: dict[str, str | int] = {}
    if season is not None:
        params["season"] = season
    payload, ttl = api.fetch_json(api.ESPN_COMMON, f"athletes/{athlete_id}/gamelog", params)
    return flatten_game_log(payload, athlete_id), ttl


# ------------------------------------------------------------------------- sleeper


def flatten_state(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Flatten Sleeper's ``/state/nfl`` into the single current-week row."""
    return [
        {
            "season": to_int(payload.get("season")),
            "phase": to_text(payload.get("season_type")),
            "week": to_int(payload.get("week")),
            "display_week": to_int(payload.get("display_week")),
            "previous_season": to_int(payload.get("previous_season")),
            "season_start_date": to_date(payload.get("season_start_date")),
        }
    ]


def fetch_state() -> tuple[list[dict[str, Any]], int]:
    """Fetch the current NFL season and week from Sleeper."""

    def check(payload: Any) -> None:
        if not isinstance(payload, Mapping) or "season" not in payload:
            raise ValueError("Sleeper state response has no season")

    payload, ttl = api.fetch_json(api.SLEEPER, "state/nfl", check=check)
    return flatten_state(payload), ttl
