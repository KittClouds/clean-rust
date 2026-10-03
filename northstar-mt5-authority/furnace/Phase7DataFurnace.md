# MasterStructure Phase 7 data furnace

Status: **PASS / PILOT VALIDATED**

## Production contract

- Campaign: `RG2_SIX_INDEX_ENVIRONMENT_FRAME_V3`
- Manifest SHA-256: `5bf12767746b8499ad0edde2597df67b1928cc5941705a8391ae2585a0574092`
- Controller preset: `RG2_M5_SIX_INDEX_V1`
- Visual rendering: disabled
- Research logging: enabled
- Warmup: native history with fixed producer lookbacks
- Finalization: final observed M5 bar frozen per instrument-window
- Isolation: unique instance tag per attempt plus one exclusive campaign writer
- Admission: staging, invariant certificate, hashes, terminal receipt, immutable seal, atomic move
- Failure: quarantine with raw capture and failure receipt; no deletion

## Exit-gate evidence

| Gate | Result | Evidence |
|---|---|---|
| Unattended batches complete | PASS | Clean DE40 batch admitted in 40.4 seconds; three additional V3 pilots are sealed and reconciled |
| Concurrent rows cannot interleave | PASS | Unique file stems and exclusive `single_writer.lock`; second process exited 1 before launch |
| Failed runs are quarantined | PASS | Four incomplete MT5 attempts retained with ten raw files each; synthetic failure fixture also retained |
| Every admitted run has a receipt | PASS | Four unique corpus directories; terminal, admission, certificate, manifest-row, and seal receipts present |
| Relational invariants | PASS | Every terminal receipt is COMPLETE, balanced, contract-valid, and has zero violations |
| Corpus integrity | PASS | Four unique run keys/windows; every sealed file and payload hash reverified; files read-only |
| Resume safety | PASS | Re-requesting admitted windows skips without starting MT5 |
| Process cleanup | PASS | Zero `terminal64` and `metatester64` processes remain |

## Admitted pilot specimens

| Window | Events | Attempts | Episodes | Transits | Canonical SHA-256 |
|---|---:|---:|---:|---:|---|
| `DE40_20251215_PROLONGED_BALANCE` | 2596 | 508 | 77 | 43 | `4cdfffe50b84c2ea719c270348ca37d5430d1f2929c3b3512420ed914c2af6c8` |
| `FRA40_20260427_EVENT_HEAVY` | 965 | 200 | 57 | 8 | `0edfbd5ff1d4353ea148bce07e56f63558d28720637389a250ea683b485e5abc` |
| `JPN225_20260316_SHARP_REVERSAL` | 1554 | 313 | 66 | 25 | `381360514868216a9d8f184b07be7b14044744446728add58a496939bab20e53` |
| `US30_20260427_ORDINARY` | 3239 | 630 | 99 | 68 | `b5e4734e2cefb4ec739e00b39c119647da03e4529bbcb8c8137997a2fdb57385` |

The pilot corpus contains 480,686,009 bytes across 68 files. Four windows are admitted and 50 frozen production windows remain. The full campaign has not been launched automatically.

## Preserved corrections

The V2 frame is preserved as `campaign_execution_rejected_v2`: a Friday holiday made its fixed Friday cutoff unreachable. V3 preserves the selected weeks but freezes each cutoff to the final observed M5 bar.

The first A01 pilot revealed exclusive logger ownership and orphan tester-agent behavior after killing the parent terminal. Those incomplete attempts are quarantined. The furnace now treats file locks as in-flight state and explicitly owns both terminal and tester-agent lifecycles.

Three valid V3 runs were initially duplicated into quarantine after admission because sealer output used the host stream. Reconciliation receipts mark those copies as diagnostic duplicates; the sealed corpus is authoritative. The sealer now emits pipeline output and the orchestrator checks corpus authority before quarantine.
