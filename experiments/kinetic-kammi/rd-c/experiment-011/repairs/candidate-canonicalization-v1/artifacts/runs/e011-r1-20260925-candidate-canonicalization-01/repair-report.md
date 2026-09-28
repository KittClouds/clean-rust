# E011-R1 — Candidate Canonicalization Repair

- Run: e011-r1-20260925-candidate-canonicalization-01
- Adapter: candidate-canonicalization-v1
- Same E009 v5 weights, prompt, schema, thresholds, and authority; input adapter has a new bundle identity.
- Same E010 task bank and already-opened labels; shadow-only repair validation.

## Repository-level outcomes

| Repository | Small coverage | Direct precision | Wrong small actions | Hybrid | Always large | Large calls avoided | Mapping failures |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| ripgrep | 8/8 | 8/8 | 0 | 8/8 | 8/8 | 8 | 0 |
| turbovec | 8/8 | 2/8 | 6 | 2/8 | 7/8 | 8 | 0 |

## Pooled descriptive totals

Small coverage 16/16; direct correct actions 10; wrong accepted small actions 6; hybrid 10/16; always large 15/16; large calls avoided 16; mapping failures 0; routed observer tokens 23172; routed observer time 4697.220 ms.

## Input invariance and authority mapping

The pre-model audit canonicalized each full E010 frame and its paired E011 candidate-permuted frame through the Rust adapter. All 16 model-visible frames were identical across the two source forms. Output choices were receipted back to original E010 action IDs and patch digests; mapping failures are reported per repository.

## Comparison with sealed E011

| Repository | E010 full-frame hybrid / errors | E011 permuted hybrid / errors | E011-R1 canonical hybrid / errors |
| --- | ---: | ---: | ---: |
| ripgrep | 8/8, 0 | 7/8, 1 | 8/8, 0 |
| turbovec | 8/8, 0 | 6/8, 1 | 2/8, 6 |

This comparison diagnoses one deterministic adapter on the reused bank. It is not a new transfer test or a mechanism claim. The adapter changes the observer-visible representation and therefore has a separate versioned bundle identity.
