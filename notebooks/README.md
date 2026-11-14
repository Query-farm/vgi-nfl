# NFL snap-share notebook

[01 · Snap shares have different denominators](01_snap_shares_have_different_denominators.ipynb) keeps offense, defense and special-teams participation separate, then compares exact player membership combinations at 50% and 80%. It uses Kansas City's 2025 week-1 game against the Chargers. Snap participation does not measure touches, quality, health or starter status.

## Install and execute

Requires Python 3.13–3.14, [uv](https://docs.astral.sh/uv/), Git, and internet for initial packages, Git worker and extension downloads. Replay serves a verified local Parquet asset on loopback.

```sh
cd notebooks
uv sync --locked
uv run --locked python execute.py
uv run --locked python -m ipykernel install --user --name vgi-nfl-notebooks --display-name 'Python (vgi-nfl notebooks)'
```

Select that kernel and Restart Kernel → Run All. The runner uses a fresh temporary kernel with this directory as cwd. Copy this whole directory to run without the worker checkout; no root source or binary discovery occurs.

The literal ATTACH pins Git tag **v0.2.0**, revision `d7d868c43ab7d22d1f46b72f3f7550ed4e6712ca`, plus SDK 0.51.0, RPC 0.53.1, httpx 0.28.1, httpx2 2.16.0 and Arrow 25.0.1. Haybarn is locked to **2.0.0rc11**. Revalidate all modes and the experiment before changing pins. This Git launch does not claim a published PyPI package.

## Experiment and live retrieval

```sh
uv run --locked python execute.py --parameters '{"MIN_UNIT_SHARE":0.80}' --output-dir validation/share-80
uv run --locked python execute.py --parameters '{"DATA_MODE":"live"}' --output-dir validation/live
```

Defaults are replay and 0.50. The finite threshold accepts 0.1–1.0 inclusive and applies to reported rounded fractions independently for each unit. Live requests the same historical season file, which may receive corrections; it has no fixture fallback. Source URL overrides are cleared before connection and restored during cleanup. A fresh execution starts a new worker process, so an old in-process cache is not reused.

Overrides require separate output destinations; unknown parameter names fail. The successful default is atomically replaced only after success. Experiments include branding, fixtures, helpers, documentation, runner and environment. Validation copies, extracted charts and request audits are ignored; the main notebook retains embedded outputs.

## Recorded data, attribution and request boundary

The fixture is the **complete unmodified 242,046-byte nflverse 2025 snap-count Parquet asset**, captured **2026-11-14 08:43:00 UTC**, containing **26,613 rows**. `fixtures/manifest.json` records source URL, exact retrieval interval, HTTP status, byte count and SHA-256. No rows or values are invented or projected away.

Data attribution: [nflverse-data snap counts](https://github.com/nflverse/nflverse-data/releases/tag/snap_counts), originating from [Pro Football Reference](https://www.pro-football-reference.com/), with [nflverse-data's CC BY 4.0 license](https://github.com/nflverse/nflverse-data/blob/main/LICENSE.md). The worker's source-code license is separate from upstream data. This example is not affiliated with the NFL or either data provider.

`replay_source.py` verifies the asset hash and serves only the exact `/snap_counts/snap_counts_2025.parquet` request. Unexpected requests fail without forwarding. The real worker downloads the full file, casts its curated columns and filters week/team; the notebook verifies every selected field against the recorded Parquet. **Week/team arguments and SQL LIMIT do not reduce the download size.** Explicit season avoids a current-season lookup. No ESPN or Sleeper call is needed. The recorded default serves exactly one file request; live HTTP attempts are not instrumented and can retry. Later calculations and display limits use only the materialized local table.

## Reading the result

Offense, defense and special teams use different team-unit denominators. Adding a player's unit shares does not produce a whole-game percentage; summing across players also counts simultaneous participants. The first chart separates units and labels snap counts. The second counts mutually exclusive combinations so each player appears once, while unit membership totals can count a player more than once.

Zero is an observed zero, not a replacement for missing values. Availability is shown; any missing share yields an unavailable exact-combination classification. Thresholds act on rounded reported shares, not reconstructed exact rates. No total team-snap denominator is inferred from a maximum player's count. The fixed one-game selection supports a transparent classification experiment, not general performance inference.

[Notebook standard](STANDARD.md) · [Query.Farm](https://query.farm/) · [VGI](https://query.farm/vgi/)
