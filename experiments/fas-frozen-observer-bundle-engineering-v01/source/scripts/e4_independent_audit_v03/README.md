# E4-0 Independent Auditor v03

This package audits the sealed E4-0 v07 engineering amendment, source closure, stage authorizations, inherited population/parity-panel artifacts, new runtime stages, and terminal replay. It does not import the E4 scorer or read original terminal-label files.

## Contract lineage

E4-0 v07 leaves the scientific predecessor roots and population/scoring gates unchanged. The already sealed population and tokenizer-only parity-panel artifacts remain inherited v06 outputs and must retain their exact stage seal bytes and roots:

- `POPULATION_GENERATION` and `PARITY_PANEL_MATERIALIZATION` bind the frozen v06 contract SHA and seal root.
- `ONLINE_CACHE_PARITY`, `FRESH_FEATURE_EXTRACTION`, and `FRESH_SCORING` bind the v07 contract SHA and seal root.

The v03 auditor revalidates the exact v06 contract/seal lineage before population, parity, or score audits. For parity it verifies the panel seal against v06 and the parity seal against v07 in the same audit. It verifies the v07 contract and source map before audits of v07 runtime stages.

Population-stage and scoring audits require the inherited v06 population seal at
the authorized run-root path `stage-seal-v01.json`. Scoring also requires its
independent audit receipt at
`experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-execution/population-independent-audit-receipt-v01.json`.
The CLI rejects legacy alias paths that are not bound by the v06 source map and
stage authorization.

## Model-free source tests

Run from the experiment root:

```powershell
python -m unittest discover -s source\scripts\e4_independent_audit_v03\tests -v
python -m compileall -q source\scripts\e4_independent_audit_v03
$taskPythonPath = Join-Path (Get-Location) 'source\scripts'
$env:PYTHONPATH = $taskPythonPath
python -m e4_independent_audit_v03 --help
Remove-Item Env:\PYTHONPATH
```

Tests create synthetic temporary fixtures only. They exercise the inherited-v06/new-v07 binding split, contract supersession, authorization, integrity checks, and scorer-independent replay logic. The suite must not open E4 labels or load a tokenizer/model, initialize CUDA, or read real E4 runtime artifacts.
