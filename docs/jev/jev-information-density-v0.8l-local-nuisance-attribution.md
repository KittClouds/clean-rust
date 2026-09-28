# JEV v0.8L — Local Nuisance Attribution

## Phase-A disposition

Phase A is **sealed but not promotable**. The symbolic candidate pool and frozen LFM feature materialization passed their boundaries, but the declared representation-radius matching criterion failed even under the unconstrained nearest-candidate lower bound.

```text
PHASE_A0 candidate pool       PASS
PHASE_A1 frozen features      PASS, training-only
PHASE_A2 matching             COMPLETE, radius gate FAIL
NOVEL arm                     NOT MATERIALIZED
Phase B                        NOT AUTHORIZED
```

No head training, evaluation inference, NewTight access, protected evaluation-body access, or Phoenix access occurred.

## Frozen construction

The experiment used the sealed v0.8I F100 training bank, sealed v0.8K triplets, and the existing certified sham views. NOVEL candidates were restricted to training-only anchor rows from other certified training triplets and matched on:

- exact choice schema and candidate order;
- exact family fields;
- exact target vector within `1e-12` per component;
- different root and canonical state text;
- candidate reuse cap of one.

The feature point was the frozen LFM final-layer `mean_full` state representation. Matching used only the scalar radius:

```text
abs(||h_N - h_A||_2 - ||h_S - h_A||_2)
```

Displacement direction was not matched.

## Results

```text
eligible NOVEL edges             517,922
hard-match groups                48
per-anchor candidates             88–119
matched anchors                  5,000
unique NOVEL candidates          5,000
exact target matching            PASS
different root/state             PASS
```

Radius results:

| Quantity | Observed | Frozen gate |
|---|---:|---:|
| Matched mean absolute error | 1.3748 | ≤ 0.05 |
| Matched median error | 1.2949 | diagnostic |
| Matched p95 error | 2.6789 | ≤ 0.15 |
| Matched maximum error | 6.2432 | diagnostic |
| Unconstrained nearest mean lower bound | 1.0673 | diagnostic lower bound |
| Unconstrained nearest p95 lower bound | 2.0952 | diagnostic lower bound |

Because the unconstrained nearest-candidate lower bound already fails the frozen gate, this is not attributable to the one-to-one assignment heuristic.

## Interpretation

The failure is a **support-construction failure**, not evidence for or against local nuisance information. The current training universe does not contain a sufficiently close generic same-target control under the declared exact semantic matching constraints.

The result must not be repaired by silently widening target tolerance, changing the radius definition, matching displacement direction, using protected/evaluation material, or reinterpreting the current NOVEL pool.

Any future recovery requires a separately authorized semantic amendment, such as a new training-only source lane or a new predeclared control-support definition. v0.8L Phase B remains unauthorized.

## Artifact roots

Phase-A run:

`D:/codex-runs/jev-information-density-v08l/phase-a-v01-clean/`

Local failure seal:

`D:/codex-runs/jev-information-density-v08l/phase-a-v01-clean/seal-local/`

Key artifacts:

- `candidate-pool-summary.json`
- `feature-cache/extraction-receipt.json`
- `matching-summary.json`
- `matching-receipt.json`
- `phase-a-final-receipt.json`

No follow-on experiment is authorized by this disposition.
