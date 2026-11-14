"""Example queries that combine several of the catalog's objects.

Each example is defined once here and referenced from the function that drives
the query and from the schema-level ``vgi.example_queries`` list.
"""

from __future__ import annotations

OPENER_SCRIMMAGE_SHARE = (
    "Each ball carrier's and receiver's yards from scrimmage in the 2025 season opener as a share "
    "of his team's total offense, joining the player box score to the team box score.",
    "SELECT p.team_abbreviation, p.athlete_name, "
    "coalesce(p.rush_yards, 0) + coalesce(p.receiving_yards, 0) AS scrimmage_yards, "
    "t.total_yards AS team_total_yards, "
    "round(100.0 * (coalesce(p.rush_yards, 0) + coalesce(p.receiving_yards, 0)) / t.total_yards, 1) "
    "AS pct_of_team_offense "
    "FROM nfl.main.box_score_player('401772510') p "
    "JOIN nfl.main.box_score_team('401772510') t USING (team_id) "
    "WHERE p.rush_attempts > 0 OR p.receptions > 0 "
    "ORDER BY pct_of_team_offense DESC, p.athlete_name",
)

POINTS_PER_GAME_VS_EPA = (
    "2025 regular-season scoring leaders: points per game from the schedule's final scores beside "
    "each team's passing and rushing EPA and giveaways from team_stats.",
    "WITH games AS ("
    "SELECT home_team, away_team, home_score, away_score "
    "FROM nfl.main.schedule(season := 2025) WHERE game_type = 'REG' AND home_score IS NOT NULL), "
    "points AS ("
    "SELECT team, count(*) AS games, avg(points) AS points_per_game FROM ("
    "SELECT home_team AS team, home_score AS points FROM games "
    "UNION ALL SELECT away_team, away_score FROM games) GROUP BY team) "
    "SELECT t.team, points.games, round(points.points_per_game, 1) AS points_per_game, "
    "round(t.passing_epa, 1) AS passing_epa, round(t.rushing_epa, 1) AS rushing_epa, "
    "t.interceptions + t.fumbles_lost AS giveaways "
    "FROM nfl.main.team_stats(season := 2025) t JOIN points USING (team) "
    "ORDER BY points_per_game DESC, t.team LIMIT 10",
)

FIRST_ROUND_WR_SPEED_CAREERS = (
    "First-round wide receivers drafted 2015-2020 who ran the combine 40-yard dash, fastest first, "
    "with career receiving yards and Pro Bowls, joining draft to combine on the Pro Football "
    "Reference id.",
    "SELECT d.season, d.pick, d.player_name, d.team, c.forty, d.rec_yards, d.pro_bowls "
    "FROM nfl.main.draft() d JOIN nfl.main.combine() c ON c.pfr_id = d.pfr_player_id "
    "WHERE d.position = 'WR' AND d.draft_round = 1 AND d.season BETWEEN 2015 AND 2020 "
    "AND c.forty IS NOT NULL "
    "ORDER BY c.forty, d.pick",
)

ROOKIE_SCRIMMAGE_LEADERS = (
    "2025 rookies with the most yards from scrimmage and where each was drafted, joining season "
    "stats to the players directory on the GSIS id (undrafted rookies show NULL draft columns).",
    "SELECT s.player_display_name, s.position, s.recent_team, p.draft_round, p.draft_pick, "
    "coalesce(s.rushing_yards, 0) + coalesce(s.receiving_yards, 0) AS scrimmage_yards "
    "FROM nfl.main.player_stats_season(season := 2025) s "
    "JOIN nfl.main.players p ON p.gsis_id = s.player_id "
    "WHERE p.rookie_season = 2025 "
    "ORDER BY scrimmage_yards DESC, s.player_display_name LIMIT 10",
)

COMPOSED_EXAMPLES = [
    OPENER_SCRIMMAGE_SHARE,
    POINTS_PER_GAME_VS_EPA,
    FIRST_ROUND_WR_SPEED_CAREERS,
    ROOKIE_SCRIMMAGE_LEADERS,
]
