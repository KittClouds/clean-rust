# Claudia

Home for Claudia-lane experiments. It exists to keep surfaces clean: Claudia work no longer shares a namespace with the Frizz lineage.

## Rules

1. **New Claudia experiments live here**, one self-contained directory each: `experiments/Claudia/<name>-<YYYYMMDD>-vNN/` with `source/`, a frozen `SPECIFICATION`, receipts, `REPORT.md`, and the seal.
2. **Nothing Claudia writes into a `frizz-*` directory.** Those (`C:\phoenix-target-overgraph\frizz-*`, `bank-v3-core-*`) are sealed upstream: read-only, consumed by path **and hash** (see the `verify_inputs.py` pattern in the Phase 7 experiments), never extended.
3. **Reference, don't overlap.** An experiment names its upstream seals and file hashes; it does not copy or edit their files, and it does not take a `frizz-` name.
4. **Heavy artifacts** (`*.pt` checkpoints, score tensors, caches) are git-ignored here by default (`.gitignore`); the sealed manifest still records their hashes.
5. Smoke/rehearsal output goes to a scratch directory via the experiment's `*_SMOKE_OUT` switch, never into the experiment directory.

## Experiments in this directory

| experiment | status |
|---|---|
| `partitioned-pl-20261003-v01/` | sealed (402 artifacts, seal verified, replay PASS): partitioned Plackett-Luce vs CE vs vanilla PL on the frozen trained-E states; does not survive the frozen rule. A fresh re-run of the earlier Phase 7B experiment, **bit-identical** to it (`REPRODUCTION-CHECK.json`), no frizz naming, no dependency on the 7A/7B directories. Start with `REPORT.md`. |

## Index of earlier Claudia-lane work (created before this directory existed)

These were built under the Frizz namespace and are **left in place** (sealed; their receipts and cross-references use those paths). Nothing has been moved.

| experiment | current location | status |
|---|---|---|
| Phase 7A SetRank vs matched pointwise | `C:\phoenix-target-overgraph\frizz-phase7a-setrank-20261003-v01` | sealed, below survival rule |
| Phase 7B partitioned Plackett-Luce vs CE | `C:\phoenix-target-overgraph\frizz-phase7b-partitioned-pl-20261003-v01` | sealed, does not survive; superseded by `partitioned-pl-20261003-v01/` above |
| Looped Qwen3.5-0.8B (LoopUS/LoopCD) | `experiments/loopus-qwen35-08b` (branch `loopus-qwen35-08b-2026-10-02`) | shelved |
