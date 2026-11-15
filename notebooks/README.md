# NFL scores, standings, and statistics notebooks — unfinished checkpoint

**Stopped at the user's request before publication.** This branch contains four executed drafts using the public worker release **v0.2.0** and shared notebook tools **v0.3.54**. It is a checkpoint, not an accepted fleet publication. The original checkout and its README edits are preserved.

| Draft | Question | Executed experiment |
| --- | --- | --- |
| [01 · Snap shares](01_snap_shares_have_different_denominators.ipynb) | How do offense, defense and special-teams denominators change participation interpretation? | `MIN_UNIT_SHARE=0.80`, from 0.50. |
| [02 · Player and team attribution](02_reconcile_players_before_assigning_teams.ipynb) | Do weekly counts reconcile, and why does assigning a whole season to a recent club move historical yards? | `COHORT="rookies"`, from `"all"`. |
| [03 · Expected metrics](03_expected_differences_need_named_units.ipynb) | Which expected-rate identities are supported by the exposed columns? | `EXPOSURE_MULTIPLIER=2`, from 1. |
| [04 · One game, several ledgers](04_follow_one_game_across_statistical_ledgers.ipynb) | How do scores, drives, events, gross player yards and net team offense reconcile? | `MIN_SCRIMMAGE_YARDS=75`, from 25; 150 tests an empty display. |

## Completed before stopping

All four defaults executed successfully: **66 code cells, eight SVG figures and 55 SQL invariants**. Four separate notebook-only parameter experiments and the 150-yard empty boundary also completed successfully. The exact replay request counts are **1 / 5 / 3 / 4**, with no forwarding or unexpected requests. Ruff, formatting, presentation and structure checks passed. All eight default figures received author review; final coordinator review and experiment-figure review are unfinished.

[coverage.json](coverage.json) maps **18 of 35** public SQL names to successful visible SQL, returned results and interpretations. Actual complete released/current function, table and view exports reconcile the denominator; the six differently named backing scans are retained. Analytical execution uses released `v0.2.0`, revision `d7d868c43ab7d22d1f46b72f3f7550ed4e6712ca`. Current catalog revision `79985312aea37d49ceba1a874bf901589dc1546f` was collected separately; this does not claim current analytical execution.

## Still pending

- Cross-run analytical and fixed-figure comparisons, including preservation of the original snap notebook's analytical outputs.
- Visual review of all experiment and empty-boundary outputs, plus coordinator acceptance.
- Fresh preloaded-kernel, base-only notebook bootstrap and supported live runs.
- Runner and parameter guards, complete final documentation and publication evidence.
- Final cleanup, commit to `main`, actual native GitHub rendering/SVG verification, and controlled original-notebook sync.

No worker source build, full source suite, source CI dispatch or container publication was initiated. The unchanged worker's [green source CI](https://github.com/Query-farm/vgi-nfl/actions/runs/43577789425) is reused.

## Resume locally

From this directory, with [uv](https://docs.astral.sh/uv/) and Git installed:

```bash
uv sync --frozen
uv run --frozen vgi-notebooks --timeout 600
```

The notebooks install the base shared package for Colab and use the local `[runner]` extra for publication. They retrieve hash-verified companions and attach the worker in a separate Python 3.13 environment:

```sql
INSTALL vgi FROM community;
LOAD vgi;
ATTACH 'nfl' (TYPE vgi, LOCATION 'uvx --python 3.13 --from git+https://github.com/Query-farm/vgi-nfl@v0.2.0 vgi-nfl');
```

Shared setup uses UTC, empty temporary SQL secrets and disabled persistence. Run each story in a fresh kernel. `DATA_MODE="live"` clears inherited upstream root overrides and has no replay fallback; these full live notebook runs remain pending at this checkpoint. Hosted Colab has not been manually executed.

## Data and interpretation boundaries

The original [snap-count fixture](fixtures/manifest.json) remains the complete unchanged nflverse season asset captured on **2026-11-14 UTC**, with 26,613 rows and 242,046 bytes. [Twelve new complete response bodies](recordings/provenance.json) were captured independently on **2026-11-15 UTC**: eight nflverse Parquet assets and four bounded ESPN responses for the 2025 opener and its schedule/team context. Exact URLs, acquisition intervals, byte counts and hashes are retained. No synthetic observations are presented as real, and independent captures are not an atomic snapshot.

Credit [nflverse contributors](https://github.com/nflverse/nflverse-data), with [CC BY 4.0 data terms](https://github.com/nflverse/nflverse-data/blob/main/LICENSE.md); snap counts originate with Pro Football Reference and tracking metrics with NFL Next Gen Stats. ESPN's unofficial endpoints and data are subject to ESPN/Disney terms. The worker code license does not license third-party data. There is no affiliation with the NFL or these providers.

Missing player IDs remain explicit and are excluded from player joins. Recent-team labels do not allocate historical events. Rushing expected-metric residuals are shown without inventing unavailable eligibility denominators. Event counts, drive plays and official offensive plays are distinct; player gross scrimmage yards differ from team net offense by sack losses in the selected game. Local thresholds are descriptive display rules, not measures of player quality, causal effects or statistical reliability.
