# RG2 Phase 9 dataset-geometry audit

This package audits the sealed RG2 MT5 research corpus without introducing
strategy labels, expectancy, feature selection, or predictive models.

Run from the workspace root with the bundled Codex Python runtime:

```powershell
$py = 'C:\Users\shuga\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $py phase9\run_phase9.py
```

The audit validates receipt row counts and schema identity, streams the terminal
node snapshots, reconstructs node lifecycles from structural events, and emits
all results under `phase9/output`.

Before Phase 10, run the focused lifecycle semantics audit:

```powershell
& $py phase9\run_lifecycle_audit.py
```

It traces `NODE_RETIRED` identity turnover, validates the 25-bar timeout boundary,
and reconstructs the full attempt chains behind administrative episode endings.
Outputs are written under `phase9/output/lifecycle_audit`.

Important semantics:

- Percentages retain their unit-specific count and censoring rate.
- A right-censored episode may retain its latest provisional resolution; it is
  excluded from completed behavioral-resolution evidence.
- Nodes still present at the deterministic cutoff are censored lifecycle
  observations (`PERSISTED_AT_CUTOFF`), not inferred retirements.
- Producer combinations come from the frozen attempt/episode context dataset.
- Session buckets use the encoded MT5 server-clock timestamp.
