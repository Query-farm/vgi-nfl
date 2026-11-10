"""Arrow schemas for the ESPN- and Sleeper-backed NFL tables."""

from __future__ import annotations

import pyarrow as pa

from vgi_nfl.meta import field

TIMESTAMP = pa.timestamp("us", tz="UTC")
PERCENTAGE = pa.decimal128(4, 3)
GAMES_BACK = pa.decimal128(4, 1)
RATE_1 = pa.decimal128(6, 1)
STAT_VALUE = pa.decimal128(12, 3)

_SEASON_TYPE = "ESPN season-type code (not a count): 1 preseason, 2 regular season, 3 postseason."

TEAMS_SCHEMA = pa.schema(
    [
        field(
            "team_id",
            pa.int32(),
            "Stable ESPN team identifier (integer code, not a count); joins teams.team_id.",
        ),
        field("team_abbreviation", pa.string(), "ESPN team abbreviation, for example KC or WSH."),
        field("team_name", pa.string(), "Full team name, for example Kansas City Chiefs."),
        field("short_name", pa.string(), "Short display name, normally the nickname."),
        field("location", pa.string(), "Team location or city name."),
        field("nickname", pa.string(), "Team nickname."),
        field("slug", pa.string(), "ESPN URL slug for the team."),
        field("color", pa.string(), "Primary team color as a hex RGB string without '#'."),
        field("alternate_color", pa.string(), "Alternate team color as a hex RGB string without '#'."),
        field("is_active", pa.bool_(), "Whether ESPN marks the franchise as active."),
    ]
)

STANDINGS_SCHEMA = pa.schema(
    [
        field("season", pa.int32(), "NFL season year (the year the season starts)."),
        field("season_type", pa.int32(), _SEASON_TYPE),
        field("conference", pa.string(), "Conference abbreviation, AFC or NFC."),
        field("conference_name", pa.string(), "Full conference name."),
        field("division", pa.string(), "Division name, for example AFC East."),
        field(
            "division_rank",
            pa.int32(),
            "Position number 1-4 within the division (1 = leader), from ESPN's tiebreak seed order.",
        ),
        field("playoff_seed", pa.int32(), "Conference seed 1-16 in ESPN's tiebreak order; 1-7 qualify."),
        field(
            "team_id",
            pa.int32(),
            "Stable ESPN team identifier (integer code, not a count); joins teams.team_id.",
        ),
        field("team_abbreviation", pa.string(), "ESPN code for the club, for example KC or WSH."),
        field("team_name", pa.string(), "Club display name, for example Kansas City Chiefs."),
        field("wins", pa.int32(), "Count of games won this season."),
        field("losses", pa.int32(), "Count of games lost this season."),
        field("ties", pa.int32(), "Count of games tied after overtime this season."),
        field("win_percentage", PERCENTAGE, "Fraction of games won (0-1), ties counted as half a win."),
        field("games_back", GAMES_BACK, "Games behind the division leader, in games; the leader is 0.0."),
        field("points_for", pa.int32(), "Count of points scored this season."),
        field("points_against", pa.int32(), "Count of points allowed this season."),
        field("point_differential", pa.int32(), "Points scored minus points allowed, in points."),
        field("streak", pa.string(), "Current streak label, for example W3 or L1."),
        field(
            "streak_length",
            pa.int32(),
            "Signed streak length in games: positive for wins, negative for losses.",
        ),
        field("home_record", pa.string(), "Home record as W-L or W-L-T."),
        field("road_record", pa.string(), "Road record as W-L or W-L-T."),
        field("division_record", pa.string(), "Record against division opponents."),
        field("conference_record", pa.string(), "Record against conference opponents."),
        field(
            "clincher",
            pa.string(),
            "ESPN clinch marker: * top seed and bye, z division, y wild card, x playoff berth, e eliminated.",
        ),
    ]
)

EVENT_SCHEMA = pa.schema(
    [
        field("game_id", pa.string(), "ESPN event identifier; pass it to game_summary() and box scores."),
        field("season", pa.int32(), "NFL season year (the year the season starts)."),
        field("season_type", pa.int32(), _SEASON_TYPE),
        field("week", pa.int32(), "Ordinal week number (1-18 regular season) within the season type."),
        field("game_time", TIMESTAMP, "Scheduled kickoff time in UTC."),
        field("name", pa.string(), "Matchup name, for example Dallas Cowboys at Philadelphia Eagles."),
        field("short_name", pa.string(), "Short matchup name, for example DAL @ PHI."),
        field("status", pa.string(), "ESPN status code, for example STATUS_SCHEDULED or STATUS_FINAL."),
        field("status_state", pa.string(), "Game state: pre, in, or post."),
        field("status_detail", pa.string(), "Human-readable status, for example Final/OT or 2nd 4:12."),
        field("completed", pa.bool_(), "Whether the game is complete."),
        field("period", pa.int32(), "Quarter number, current or final; 5 or more means overtime."),
        field("clock", pa.string(), "Game clock display for live games."),
        field("home_team_id", pa.int32(), "ESPN team identifier (integer code) of the home club."),
        field("home_team_abbreviation", pa.string(), "ESPN code of the home club, for example PHI."),
        field("home_team_name", pa.string(), "Display name of the home club."),
        field("home_score", pa.int32(), "Home club's score, in points; NULL before kickoff."),
        field("home_record", pa.string(), "Home team's overall record after this game, as ESPN reports it."),
        field("away_team_id", pa.int32(), "ESPN team identifier (integer code) of the away club."),
        field("away_team_abbreviation", pa.string(), "ESPN code of the visiting club, for example DAL."),
        field("away_team_name", pa.string(), "Display name of the visiting club."),
        field("away_score", pa.int32(), "Visiting club's score, in points; NULL before kickoff."),
        field("away_record", pa.string(), "Away team's overall record after this game, as ESPN reports it."),
        field(
            "winner_abbreviation", pa.string(), "Winning team abbreviation; NULL until decided or for a tie."
        ),
        field("venue", pa.string(), "Stadium name."),
        field("venue_city", pa.string(), "Stadium city."),
        field("venue_state", pa.string(), "Stadium state or province, when applicable."),
        field("neutral_site", pa.bool_(), "Whether the game is played at a neutral site."),
        field("attendance", pa.int32(), "Reported crowd, in people; NULL or 0 before the game."),
        field("broadcast", pa.string(), "National broadcast network(s), when listed."),
    ]
)

GAME_SUMMARY_SCHEMA = pa.schema(
    [
        *[value for value in EVENT_SCHEMA if value.name not in {"broadcast", "home_record", "away_record"}],
        field("home_q1", pa.int32(), "Home points in the first quarter."),
        field("home_q2", pa.int32(), "Home points in the second quarter."),
        field("home_q3", pa.int32(), "Home points in the third quarter."),
        field("home_q4", pa.int32(), "Home points in the fourth quarter."),
        field("home_ot", pa.int32(), "Home points in overtime; NULL when the game had no overtime."),
        field("away_q1", pa.int32(), "Away points in the first quarter."),
        field("away_q2", pa.int32(), "Away points in the second quarter."),
        field("away_q3", pa.int32(), "Away points in the third quarter."),
        field("away_q4", pa.int32(), "Away points in the fourth quarter."),
        field("away_ot", pa.int32(), "Away points in overtime; NULL when the game had no overtime."),
        field("grass", pa.bool_(), "Whether ESPN lists a natural-grass surface."),
        field("referee", pa.string(), "Name of the referee (crew chief)."),
    ]
)

INJURY_SCHEMA = pa.schema(
    [
        field("injury_id", pa.string(), "ESPN injury report entry identifier."),
        field("team_id", pa.int32(), "ESPN team identifier (integer code) of the player's club."),
        field("team_abbreviation", pa.string(), "ESPN code of the player's club."),
        field("team_name", pa.string(), "Display name of the player's club."),
        field(
            "athlete_id",
            pa.int32(),
            "ESPN athlete identifier (integer code); joins roster and players.espn_id.",
        ),
        field("athlete_name", pa.string(), "Player name."),
        field("position", pa.string(), "Position abbreviation."),
        field("status", pa.string(), "Report status, for example Questionable, Out or Injured Reserve."),
        field("status_abbreviation", pa.string(), "Short status code such as Q, D, O or IR."),
        field("injury_type", pa.string(), "Injured body part or reason, for example Knee."),
        field("injury_location", pa.string(), "Broader body location, for example Leg."),
        field("injury_detail", pa.string(), "Injury detail such as Sprain, when reported."),
        field("injury_side", pa.string(), "Side of the body, when reported."),
        field("return_date", pa.date32(), "ESPN's estimated return date, when reported."),
        field("short_comment", pa.string(), "Short news blurb."),
        field("long_comment", pa.string(), "Longer news blurb."),
        field("reported_at", TIMESTAMP, "Time the entry was last updated, in UTC."),
    ]
)

CURRENT_WEEK_SCHEMA = pa.schema(
    [
        field("season", pa.int32(), "Current NFL season year according to Sleeper."),
        field("phase", pa.string(), "Sleeper season phase: pre, regular, post, or off."),
        field("week", pa.int32(), "Ordinal current week, which advances early in the week."),
        field("display_week", pa.int32(), "Ordinal week Sleeper displays, normally the last week played."),
        field("previous_season", pa.int32(), "Previous NFL season year."),
        field("season_start_date", pa.date32(), "Date the regular season starts."),
    ]
)

ROSTER_SCHEMA = pa.schema(
    [
        field("team_id", pa.int32(), "ESPN team identifier."),
        field("team_abbreviation", pa.string(), "Team abbreviation."),
        field("season", pa.int32(), "Season the roster belongs to."),
        field(
            "roster_group",
            pa.string(),
            "ESPN group: offense, defense, specialTeam, injuredReserveOrOut, suspended, or practiceSquad.",
        ),
        field("athlete_id", pa.int32(), "ESPN athlete identifier."),
        field("athlete_name", pa.string(), "Player's full name."),
        field("first_name", pa.string(), "First name."),
        field("last_name", pa.string(), "Last name."),
        field("jersey", pa.string(), "Uniform number."),
        field("position", pa.string(), "Position abbreviation, for example QB or WR."),
        field("position_name", pa.string(), "Position name."),
        field("age", pa.int32(), "Age in years."),
        field("birth_date", pa.date32(), "Date of birth."),
        field("height_inches", pa.int32(), "Height in inches."),
        field("weight_lbs", pa.int32(), "Weight in pounds."),
        field("experience_years", pa.int32(), "Completed NFL seasons; 0 for rookies."),
        field("college", pa.string(), "College attended."),
        field("birth_place", pa.string(), "Birthplace as city, state or country."),
        field("status", pa.string(), "ESPN player status, for example Active."),
    ]
)

DEPTH_CHART_SCHEMA = pa.schema(
    [
        field("team_id", pa.int32(), "ESPN team identifier."),
        field("team_abbreviation", pa.string(), "Team abbreviation."),
        field("season", pa.int32(), "Season of the depth chart."),
        field("formation", pa.string(), "Formation name, for example 3WR 1TE, Base 4-3 D, or Special Teams."),
        field("position_key", pa.string(), "ESPN depth-chart slot key, for example qb, lt, or lcb."),
        field("position", pa.string(), "Position abbreviation for the slot."),
        field("position_name", pa.string(), "Position name for the slot."),
        field("depth", pa.int32(), "Depth order within the slot: 1 is the starter."),
        field("athlete_id", pa.int32(), "ESPN athlete identifier."),
        field("athlete_name", pa.string(), "Player name from the current team roster; NULL if not listed."),
        field("jersey", pa.string(), "Uniform number from the current team roster."),
    ]
)

BOX_TEAM_SCHEMA = pa.schema(
    [
        field("game_id", pa.string(), "ESPN event identifier."),
        field("team_id", pa.int32(), "ESPN team identifier."),
        field("team_abbreviation", pa.string(), "Team abbreviation."),
        field("team_name", pa.string(), "Team name."),
        field("home_away", pa.string(), "home or away."),
        field("first_downs", pa.int32(), "First downs."),
        field("first_downs_passing", pa.int32(), "First downs by pass."),
        field("first_downs_rushing", pa.int32(), "First downs by rush."),
        field("first_downs_penalty", pa.int32(), "First downs by penalty."),
        field("third_down_conversions", pa.int32(), "Third downs converted."),
        field("third_down_attempts", pa.int32(), "Third downs attempted."),
        field("fourth_down_conversions", pa.int32(), "Fourth downs converted."),
        field("fourth_down_attempts", pa.int32(), "Fourth downs attempted."),
        field("total_plays", pa.int32(), "Offensive plays."),
        field("total_yards", pa.int32(), "Total net yards."),
        field("yards_per_play", RATE_1, "Net yards per offensive play."),
        field("total_drives", pa.int32(), "Offensive drives."),
        field("passing_yards", pa.int32(), "Net passing yards (after sack yardage)."),
        field("pass_completions", pa.int32(), "Completed passes."),
        field("pass_attempts", pa.int32(), "Pass attempts."),
        field("yards_per_pass", RATE_1, "Net yards per pass play."),
        field("interceptions_thrown", pa.int32(), "Interceptions thrown."),
        field("sacks_allowed", pa.int32(), "Times sacked."),
        field("sack_yards_lost", pa.int32(), "Yards lost to sacks."),
        field("rushing_yards", pa.int32(), "Rushing yards."),
        field("rushing_attempts", pa.int32(), "Rushing attempts."),
        field("yards_per_rush", RATE_1, "Yards per rushing attempt."),
        field("red_zone_conversions", pa.int32(), "Red-zone trips ending in a touchdown."),
        field("red_zone_attempts", pa.int32(), "Red-zone trips."),
        field("penalties", pa.int32(), "Accepted penalties."),
        field("penalty_yards", pa.int32(), "Penalty yards."),
        field("turnovers", pa.int32(), "Turnovers committed."),
        field("fumbles_lost", pa.int32(), "Fumbles lost."),
        field("defensive_touchdowns", pa.int32(), "Defensive and return touchdowns."),
        field("possession_seconds", pa.int32(), "Time of possession in seconds."),
    ]
)

# Compact comments keep the wide box-score discovery record readable.
BOX_PLAYER_SCHEMA = pa.schema(
    [
        field("game_id", pa.string(), "ESPN event id."),
        field("team_id", pa.int32(), "ESPN team id."),
        field("team_abbreviation", pa.string(), "Team abbreviation."),
        field("athlete_id", pa.int32(), "ESPN athlete id."),
        field("athlete_name", pa.string(), "Player name."),
        field("jersey", pa.string(), "Uniform number."),
        field("pass_completions", pa.int32(), "Completions."),
        field("pass_attempts", pa.int32(), "Pass attempts."),
        field("pass_yards", pa.int32(), "Passing yards."),
        field("pass_touchdowns", pa.int32(), "Passing TDs."),
        field("interceptions_thrown", pa.int32(), "Interceptions thrown."),
        field("sacks_taken", pa.int32(), "Times sacked."),
        field("sack_yards_lost", pa.int32(), "Sack yards lost."),
        field("passer_rating", RATE_1, "NFL passer rating."),
        field("qbr", RATE_1, "ESPN adjusted QBR."),
        field("rush_attempts", pa.int32(), "Carries."),
        field("rush_yards", pa.int32(), "Rushing yards."),
        field("rush_touchdowns", pa.int32(), "Rushing TDs."),
        field("rush_long", pa.int32(), "Longest rush."),
        field("receptions", pa.int32(), "Receptions."),
        field("targets", pa.int32(), "Targets."),
        field("receiving_yards", pa.int32(), "Receiving yards."),
        field("receiving_touchdowns", pa.int32(), "Receiving TDs."),
        field("receiving_long", pa.int32(), "Longest reception."),
        field("fumbles", pa.int32(), "Fumbles."),
        field("fumbles_lost", pa.int32(), "Fumbles lost."),
        field("tackles", pa.int32(), "Total tackles."),
        field("solo_tackles", pa.int32(), "Solo tackles."),
        field("sacks", RATE_1, "Sacks; half sacks allowed."),
        field("tackles_for_loss", pa.int32(), "Tackles for loss."),
        field("passes_defended", pa.int32(), "Passes defended."),
        field("qb_hits", pa.int32(), "QB hits."),
        field("defensive_touchdowns", pa.int32(), "Defensive TDs."),
        field("interceptions", pa.int32(), "Interceptions made."),
        field("interception_yards", pa.int32(), "Interception return yards."),
        field("kick_returns", pa.int32(), "Kick returns."),
        field("kick_return_yards", pa.int32(), "Kick return yards."),
        field("kick_return_touchdowns", pa.int32(), "Kick return TDs."),
        field("punt_returns", pa.int32(), "Punt returns."),
        field("punt_return_yards", pa.int32(), "Punt return yards."),
        field("punt_return_touchdowns", pa.int32(), "Punt return TDs."),
        field("field_goals_made", pa.int32(), "Field goals made."),
        field("field_goals_attempted", pa.int32(), "Field goals attempted."),
        field("field_goal_long", pa.int32(), "Longest field goal."),
        field("extra_points_made", pa.int32(), "Extra points made."),
        field("extra_points_attempted", pa.int32(), "Extra points attempted."),
        field("kicking_points", pa.int32(), "Kicking points."),
        field("punts", pa.int32(), "Punts."),
        field("punt_yards", pa.int32(), "Gross punt yards."),
        field("punts_inside_20", pa.int32(), "Punts inside the 20."),
    ]
)

DRIVES_SCHEMA = pa.schema(
    [
        field("game_id", pa.string(), "ESPN event identifier."),
        field("drive_number", pa.int32(), "Drive order within the game, starting at 1."),
        field("drive_id", pa.string(), "ESPN drive identifier."),
        field("team_id", pa.int32(), "ESPN identifier of the offense."),
        field("team_abbreviation", pa.string(), "Abbreviation of the offense."),
        field("start_period", pa.int32(), "Quarter the drive started in."),
        field("start_clock", pa.string(), "Game clock when the drive started."),
        field("start_field_position", pa.string(), "Starting field position, for example DAL 25."),
        field("end_period", pa.int32(), "Quarter the drive ended in."),
        field("end_clock", pa.string(), "Game clock when the drive ended."),
        field("end_field_position", pa.string(), "Ending field position."),
        field("plays", pa.int32(), "Offensive plays in the drive."),
        field("yards", pa.int32(), "Net yards gained."),
        field("duration_seconds", pa.int32(), "Time of possession for the drive in seconds."),
        field("result", pa.string(), "Drive result, for example Touchdown, Punt, or Field Goal."),
        field("is_score", pa.bool_(), "Whether the drive produced points."),
        field("description", pa.string(), "ESPN summary, for example 6 plays, 53 yards, 3:11."),
    ]
)

SCORING_PLAYS_SCHEMA = pa.schema(
    [
        field("game_id", pa.string(), "ESPN event identifier."),
        field("play_id", pa.string(), "ESPN play identifier."),
        field("period", pa.int32(), "Quarter of the score; 5 or more is overtime."),
        field("clock", pa.string(), "Game clock at the score."),
        field("team_id", pa.int32(), "ESPN identifier of the scoring team."),
        field("team_abbreviation", pa.string(), "Abbreviation of the scoring team."),
        field("scoring_type", pa.string(), "Scoring type, for example Touchdown, Field Goal, or Safety."),
        field("play_type", pa.string(), "Play type, for example Passing Touchdown."),
        field("description", pa.string(), "Play description including the try."),
        field("away_score", pa.int32(), "Away team score after the play."),
        field("home_score", pa.int32(), "Home team score after the play."),
    ]
)

PLAYS_SCHEMA = pa.schema(
    [
        field("game_id", pa.string(), "ESPN event identifier."),
        field("play_id", pa.string(), "ESPN play identifier."),
        field("sequence", pa.int64(), "ESPN sequence number; orders plays within the game."),
        field("drive_number", pa.int32(), "Drive order within the game, starting at 1."),
        field("offense_team_id", pa.int32(), "ESPN team id of the offense at the snap."),
        field("offense_abbreviation", pa.string(), "Abbreviation of the offense at the snap."),
        field("period", pa.int32(), "Quarter; 5 or more is overtime."),
        field("clock", pa.string(), "Game clock at the snap."),
        field("play_type", pa.string(), "Play type, for example Rush, Pass Reception, or Punt."),
        field("description", pa.string(), "Play-by-play text."),
        field("down", pa.int32(), "Down before the play; NULL or 0 on kicks."),
        field("distance", pa.int32(), "Yards to go before the play."),
        field("yards_to_endzone", pa.int32(), "Yards from the line of scrimmage to the opponent's end zone."),
        field("down_distance_text", pa.string(), "Situation text, for example 3rd & 4 at KC 31."),
        field("yards", pa.int32(), "Yards gained on the play as ESPN credits it."),
        field("scoring_play", pa.bool_(), "Whether the play scored."),
        field("penalty", pa.bool_(), "Whether a penalty was called on the play."),
        field("turnover", pa.bool_(), "Whether the play was a turnover."),
        field("away_score", pa.int32(), "Away team score after the play."),
        field("home_score", pa.int32(), "Home team score after the play."),
        field("wallclock", TIMESTAMP, "Real-world UTC time of the play, when recorded."),
    ]
)

GAME_LOG_SCHEMA = pa.schema(
    [
        field("athlete_id", pa.int32(), "ESPN athlete identifier."),
        field("season", pa.int32(), "Season of the game log."),
        field("season_label", pa.string(), "ESPN season label, for example 2025 Regular Season."),
        field("game_id", pa.string(), "ESPN event identifier."),
        field("game_time", TIMESTAMP, "Kickoff time in UTC."),
        field("week", pa.int32(), "Week number."),
        field("team_abbreviation", pa.string(), "The player's team in this game."),
        field("opponent_abbreviation", pa.string(), "Opponent abbreviation."),
        field("home_away", pa.string(), "home or away from the player's perspective."),
        field("result", pa.string(), "W, L, or T from the player's perspective."),
        field("score", pa.string(), "Final score display, winner first, for example 23-20 OT."),
        field("category", pa.string(), "Stat category, for example passing, rushing, or receiving."),
        field("stat", pa.string(), "ESPN stat key, for example passingYards."),
        field("label", pa.string(), "Short stat label, for example YDS."),
        field("value", STAT_VALUE, "Numeric value of the stat; NULL when ESPN shows a marker."),
        field("display_value", pa.string(), "ESPN's original display value."),
    ]
)
