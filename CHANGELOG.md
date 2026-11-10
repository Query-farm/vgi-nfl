# Changelog

All notable changes to this project are documented here.

## [Unreleased]

## [0.1.0]

- Initial release: a read-only NFL catalog for VGI protocol 3.2 (vgi-python 0.50).
- Current tables: `current_scoreboard`, `current_standings`, `current_injuries`,
  `current_week`, `teams`, and `players`.
- ESPN functions for any week's scoreboard, historical standings, team schedules,
  rosters, depth charts, game summaries, team and player box scores, drives,
  scoring plays, game play-by-play, and athlete game logs.
- nflverse (CC-BY 4.0) functions for schedules with lines and weather, season
  play-by-play with EPA and win probability, weekly and season player stats,
  team stats, snap counts, draft, combine, and Next Gen Stats.
- One HTTP chokepoint with an honest User-Agent, retries with `Retry-After`,
  a total query deadline, per-source pacing, and an in-process response cache
  that honors upstream `Cache-Control`.
