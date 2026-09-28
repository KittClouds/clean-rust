# E011 Postrun Engineering Amendment 02

- Parent run: `e011-20260925-causal-evidence-01`
- Classification: downstream repair diagnostics; no upstream transfer and no edits to sealed E011, E011-R1, or E011-R2 artifacts.
- Amendment 01 records the R2 factorial and the first candidate-presentation receipt implementation. This amendment records the prompt-repair result and the producer-order repair.

## E011-R3: prompt repair result

The same E010 bank and already-opened labels were used for a posthoc repair diagnostic. E009 v5 weights, schema, normalization, runtime mode, and 850/150 thresholds stayed fixed. Only the small observer prompt changed; large fallback outputs were reused from sealed runs on identical frames.

| Condition | Repository | v5 small coverage / precision | Prompt repair coverage / precision | Repair wrong accepted | v5 hybrid | Repair hybrid | Always large |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Original order | ripgrep | 8/8 / 8/8 | 4/8 / 4/4 | 0 | 8/8 | 8/8 | 8/8 |
| Original order | turbovec | 5/8 / 5/5 | 2/8 / 2/2 | 0 | 8/8 | 5/8 | 5/8 |
| Permuted order | ripgrep | 8/8 / 7/8 | 7/8 / 6/7 | 1 | 7/8 | 7/8 | 8/8 |
| Permuted order | turbovec | 7/8 / 5/7 | 4/8 / 3/4 | 1 | 5/8 | 4/8 | 5/8 |

The prompt reduced accepted errors in the permuted lane from three to two, but still made wrong legal proposals and lowered pooled hybrid completion from 12/16 to 11/16 there. In original order it lowered hybrid completion from 16/16 to 13/16. It is rejected. No prompt or threshold tuning was performed after scoring.

Run: `repairs/order-robust-prompt-v1/artifacts/runs/e011-r3-20260925-order-robust-prompt-01`. Its 32 small-observer outputs were sealed before scoring. It contacted no large model and executed no action.

## Producer-order repair

The E010 candidate producer placed all 16 original lists in stable creation order; their IDs were `[11, 37, 68, 94]` in that order. E011-R2's order-only treatment preserved those IDs while shuffling each list. Restoring each candidate's original producer ordinal reconstructed the entire original frame, including all non-candidate fields, for **16/16 tasks**. The deterministic reconstruction is recorded in [the producer-order check](../../../repairs/producer-order-v1/artifacts/runs/e011-producer-order-restoration-01/frame-restoration-report.md).

The runtime contract now offers `SequencedCandidate<T>` and an in-place `order_by_producer_ordinal` helper. Candidate producers assign the ordinal when creating each option and carry it with the option; the runtime sorts by that field before serialization. Action IDs stay labels and patch hashes stay identities. This is the repair for ordering changes introduced after candidate creation. It does not make a different producer order behaviorally equivalent.

The versioned presentation receipt remains the second guard: it binds the chosen task, IDs, patch digests, and exact order. The authority-facing resolver checks that receipt before mapping the observer proposal. A changed order, remapping, reserved no-action ID, or unoffered proposal is rejected. The receipt prevents request/authorization/replay drift; it does not identify a semantically correct action.

## Verification

- `rdc-runtime-contracts-v1`: release suite passed, 14 integration tests total; strict Clippy passed.
- Candidate presentation test binary built under `D:\cargo-targets\rdc-runtime-contracts-v1`, copied to `C:\rd-c\rdc-runtime-contracts-v1\artifacts\linked-tests`, and rerun from there. SHA-256: `e5b6b2d8acdaf95124595291df2ca02ebfa6318c14527fdc598ef9045fcc86ea`.
- Criterion measured in-place receipt validation and producer-order restoration at 4, 16, 64, and 256 candidates. Results and host details are in `rdc-runtime-contracts-v1/benchmarks/candidate-presentation-validation.md`.
- Both local model processes were stopped after capture. All R3 inference remained shadow-only.

## Next integration step

Wire producer ordinals and the receipt through the actual observation-to-proposal-to-authority path. Assign ordinals at candidate creation, sort before model serialization, carry the receipt digest with the request and response, and validate it before action authorization and replay. Add a smoke case that mutates option order after receipt creation and checks deterministic rejection plus the runtime's configured fallback. Keep the E011 scientific and transfer claims unchanged.
