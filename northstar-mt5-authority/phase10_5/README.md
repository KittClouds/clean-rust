# Phase 10.5 — Research Interface Lock

This package is the only supported Python entry point for Phase 11 analysis of
the sealed RG2 corpus. It verifies the Phase 10 corpus seal and every per-run
file receipt before loading data. Verification cannot be disabled.

Canonical views:

- `attempt_view()` — one row per attempt with one frozen feature snapshot and
  contributor identities aggregated without row multiplication.
- `attempt_chain_view()` — ordered attempts with prior/next receipts and
  episode-level event-presence flags.
- `episode_timeline_view()` — one row per deterministic event.
- `transit_view()` — one row per transit with source-attempt context.
- `node_context_view()` — explicit one-to-many contributor expansion.

Lifecycle contracts are executable: `NODE_RETIRED`, attempt/transit timeouts,
unresolved receipts, and right-censoring cannot become behavioral outcomes.
Episode resolution remains a terminal receipt, never a whole-episode label.

The default partition is `RG2_EXPLORATORY`. `RG2_REPLAY_QC` is available for
replay inspection. `FUTURE_HOLDOUT` always raises `HoldoutAccessError` because
the reserved calendar windows are intentionally absent from RG2.

Build and verify the interface receipt:

```powershell
$py = 'C:\Users\shuga\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $py .\phase10_5\phase10_5.py build
& $py .\phase10_5\phase10_5.py verify
```

Example:

```python
from pathlib import Path
from phase10_5 import QuerySpec, ResearchCorpus

corpus = ResearchCorpus(Path.cwd())
result = corpus.estimate(QuerySpec.create(
    "reclaim_given_break",
    group_by=("canonical_instrument", "start_region"),
))
result.write(Path("phase11/results"), Path.cwd())
```

Every result includes its corpus hash, code hash, query hash, filters,
eligibility rule, censoring treatment, counts, and artifact hash.
