# Q10-NA v2 preflight: hidden authority in no-helpful rows

The engineering preflight is valid and ready for replay. It verified the
current Q10-RMT parent hashes, the canonical receipt root, all eight sealed
source fixtures, the DA2 results hash, and the reconstructed endpoint state.

The preflight contains exactly 326 endpoint-row targets. Two targets have an
empty raw-support neighborhood; they are recorded as complete empty local
domains without making a global impossibility claim. The other 324 targets
have nonempty raw support. The reconstructed endpoint and target readouts
matched the sealed row bits for all 326 targets.

The RMT stream contains 8,515 serialized prefix keys for these neighborhoods.
Deterministic replay from the frozen endpoint fixtures exposes 25,940 legal
prefix keys; the 17,425 absent serialized keys are therefore metadata about
the RMT stream, not missing legal moves. No legal prefix was unavailable under
the frozen bounds and reserve rule, and the raw-support union had zero
mismatches.

The exact pair domain is 1,493,624 candidates and fits the 25,000,000 global
pair budget. The exact triple domain is 61,058,294 candidates and exceeds the
50,000,000 global triple budget, so a future replay must leave a declared
higher-order/untested tail rather than label that tail no-effect.

## Completed engineering replay

The exact pair sweep covered all 324 nonempty target domains with 1,493,624
replays. It found pair authority in 213 rows; 202 of those rows had a best
pair candidate whose readout reached the target bits exactly. The remaining
111 rows had complete pair domains with no improving pair.

The declared triple tail for those 111 rows was 15,868,182 candidates, below
the frozen global triple budget. All of it was replayed. Sixteen rows had
triple-only authority, and all 16 reached the target bits exactly. Ninety-five
rows remained no-effect after complete pair and triple domains. The two empty
raw-support rows remain the separate complete-empty-domain diagnostic from
preflight.

The resulting engineering partition of all 326 targets is therefore:

| Local result | Rows |
| --- | ---: |
| pair authority | 213 |
| triple-only authority | 16 |
| no effect after complete pair/triple domain | 95 |
| empty raw-support domain | 2 |

These are exact readout diagnostics for the declared local domains. They are
not behavioral findings, global impossibility claims, or evidence that a
canonical repair should be applied. No scientific seed bundle, behavioral
measurement, canonical repair, or DH08B authorization occurred.

Independent checks passed:

- `python -B scripts/audit_q10_na.py`
- `python -B scripts/test_q10_na.py` — 7 tests passed
- `python -B scripts/audit_q10_na_replay.py`
- parent Q10-RMT audit — 28 endpoints, 7,003 rows, 168,071 moves, 2,738 components
