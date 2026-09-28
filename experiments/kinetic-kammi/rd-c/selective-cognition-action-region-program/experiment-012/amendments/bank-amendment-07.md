# E012 bank amendment A07 — isolate Cargo overlay artifacts

**State:** runner repair frozen before retry. **Model contact remains prohibited.**

Candidate-check attempt 02 produced 192 candidate rows and 48 base rows, but it is not valid scoring evidence. A post-run consistency audit found 15 groups where identical source-overlay and test-overlay hashes under the same case ID had both pass and fail results. The full raw file is preserved at `bank/construction-01/scored-bank-v1/attempts/scored-check-results-attempt-02-quarantined.json`; the conflict audit is beside it. Every outcome from that run is excluded.

The runner used one Cargo target directory per family for different temporary source overlays. That shared build cache is the likely source of stale test binaries. Runner v1.2 keys `CARGO_TARGET_DIR` by the family, manifest hash, source-overlay hash, and test-overlay hash. `E012_CASE` remains a runtime input, so identical compiled overlays can safely share artifacts across case invocations. Incremental compilation is disabled. The executable test predicates, candidate overlays, and locked task-source fixture are unchanged for this retry.

The next check run must demonstrate that identical content-hash/case groups have a single outcome. This is a harness-integrity gate; attempt 02 is not used to set task labels or characterize the candidates.
