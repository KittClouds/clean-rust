# FAS-00 Phase 3 execution v02

This sidecar implements only the sealed `FAS00_SENSOR_QUALIFICATION_V01` contract. It supersedes the v01 runner, which stopped at its source-seal sort check before opening the corpus or fitting a probe. The v01 source seal and source files remain unchanged.

The runner reads the Phase 1 v03 corpus and the sealed Phase 2A FULL and QUERY_ONLY cache. It does not load LFM or create new features.

The implementation uses the FAS-local SciPy 1.16.2 wheel and the existing NumPy 2.5.3 runtime. The source seal binds the exact implementation files, execution plan, numerical versions, and wheel hash before probe fitting. The `--self-test` command uses synthetic vectors only.

Run order:

1. `python phase3.py --self-test`
2. `pwsh -NoProfile -File scripts/seal-source.ps1`
3. `pwsh -NoProfile -File scripts/seal-source.ps1 -Verify`
4. `python phase3.py --run`
5. `python phase3.py --verify-result`

The run writes only to `D:/codex-runs/fas-frozen-adaptive-substrate-v00/phase3-v02/results-v01`. It refuses to overwrite an existing result identity. A failed gate is a terminal Phase 3 disposition under the frozen contract. No Phase 4 authorization follows from any Phase 3 result.
