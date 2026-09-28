# E011 Postrun Engineering Amendment 01

- Parent run: `e011-20260925-causal-evidence-01`
- Purpose: record the candidate-presentation autopsy and downstream repair attempts.
- Classification: postrun engineering diagnosis; no upstream science input and no changes to frozen E011 artifacts.
- Parent reports, inputs, labels, and observer output trees remain byte-for-byte unchanged.

## Candidate-presentation factorial

E011-R2 reused the already-opened E010 tasks and labels for a paired shadow diagnosis. E009 v5 weights, prompt, output schema, normalization, thresholds, and authority were unchanged. The two frozen conditions independently changed candidate IDs or candidate order.

| Condition | Repository | Small coverage | Direct precision | Wrong small actions | Hybrid | Always large | Large calls avoided |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| IDs only | ripgrep | 7/8 | 7/7 | 0 | 8/8 | 8/8 | 7 |
| IDs only | turbovec | 5/8 | 5/5 | 0 | 8/8 | 5/8 | 5 |
| Order only | ripgrep | 8/8 | 7/8 | 1 | 7/8 | 8/8 | 8 |
| Order only | turbovec | 7/8 | 5/7 | 2 | 5/8 | 5/8 | 7 |

Changing numeric IDs alone retained perfect direct precision in both repositories. Changing only the option order produced three wrong accepted actions: one in ripgrep and two in turbovec. On this bank, the observed fragility is attributable to candidate ordering, not the numeric ID reassignment. Pooled figures are descriptive: IDs-only hybrid completion was 16/16; order-only was 12/16, versus 13/16 for always-large in that condition.

This is an input-sensitivity result for these frozen models and tasks, not a claim about internal model mechanism or broad repository transfer. The E010 baseline candidate order remains part of the successful E010 execution contract.

## Repair attempts

### R1: sort by patch digest

The adapter made all 16 paired full/permuted frames byte-identical. This solved input invariance but imposed an arbitrary order. Its shadow result was unsafe on turbovec: the small observer acted on 8/8 tasks with only 2/8 correct, and the hybrid completed 2/8 versus 7/8 for always-large. The adapter is not promoted. Its input-invariance result and behavioral regression remain in [the R1 report](../../../repairs/candidate-canonicalization-v1/artifacts/runs/e011-r1-20260925-candidate-canonicalization-01/repair-report.md).

### R2: separate IDs from order

The factorial run localized the regression to option order. This rules out hash sorting as a general repair. The reusable downstream guard is now implemented in `rdc-runtime-contracts-v1`: a versioned candidate-presentation receipt binds task identity, action IDs, patch digests, and their exact sequence. Validation rejects reordered, remapped, or otherwise changed options before proposal-to-action authorization. Validation reads the encoded receipt in place, including from a read-only memory map.

The receipt prevents an unrecorded order change between observer request, authorization, and replay. The caller must mint it from the candidate producer's chosen order before model contact and validate it at the authority boundary. It does not make a newly chosen arbitrary order safe, nor does it validate task correctness.

## Verification

- E011-R2 used the same already-opened E010 labels solely for downstream engineering diagnosis.
- 64/64 R2 calls returned HTTP 200 and normalized outputs; outputs were sealed before scoring.
- The recorded small and large model processes were stopped after capture.
- `rdc-runtime-contracts-v1`: release test suite passed (12 integration tests); strict Clippy passed.
- Candidate-presentation test binary was copied from the `D:` Cargo target to `C:` and rerun there; all 7 contract tests passed. Binary SHA-256: `9eda9911528fece80813ffd0fd9413be2ddbdc29e544eb7d64e7157ee1a469c7`.
- Criterion central estimates for allocation-free receipt validation were 477 ns for 4 candidates, 1.48 μs for 16, 9.26 μs for 64, and 88.8 μs for the 256-candidate maximum (20 samples, two-second warmup and measurement per size). Full intervals and host details are in [the benchmark note](../../../../rdc-runtime-contracts-v1/benchmarks/candidate-presentation-validation.md). These are local microbenchmarks, not production latency claims.
- No observer was trained, no threshold was fitted, and no treatment proposal was executed.

## Program consequence

Keep the E010 frozen source order stable and receipt it before observer contact. Do not sort candidate actions by content hash. If a future candidate producer can produce variable ordering, its ordering policy needs to be deterministic and versioned at that producer boundary; the presentation receipt then makes the exact request replayable and rejects downstream drift. Further model optimization should follow integration of this guard and a smoke test at the real authority boundary.
