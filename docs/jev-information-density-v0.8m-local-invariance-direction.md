# JEV v0.8M — Local Invariance Direction Attribution

## Phase-A disposition

`phase-a-v01-clean` is sealed as:

```text
PHASE_A_NOT_PROMOTABLE_RADIUS_GATE_FAIL
```

The semantic construction passed. The independent exact-world validator passed
all 12,000 training and 2,000 held-out neighborhoods. Frozen features were
extracted only for the selected 5,000 training neighborhoods (20,000 A/F/S/N
episodes). No head training, evaluation inference, protected evaluation-body
access, NewTight access, or Phoenix access occurred.

The predeclared geometry gate failed without replacement selection or threshold
relaxation:

| Quantity | Observed | Limit |
| --- | ---: | ---: |
| Mean relative sham/neutral radius error | 0.223267 | 0.10 |
| P95 absolute radius error | 0.479528 | 0.25 |
| Maximum family mean relative error | 0.261049 | 0.15 |

The gate failure means the independently generated `local_neutral` axis did
not land in a sufficiently comparable LFM local-radius regime to the certified
sham axis. This is a construction/geometric comparability failure, not a model
result and not evidence for or against direction-specific teaching.

## Construction evidence

- 12 training families, 1,000 neighborhoods per family.
- 4 held-out families, 500 neighborhoods per family.
- Four exact-world roles per neighborhood: anchor, fact flip, certified sham,
  and local neutral.
- Exact target preservation and independent nuisance-axis checks passed.
- Fact-flip MAP changes passed.
- One-field/one-character surface-edit checks passed.
- Feature-free selection produced 5,000 neighborhoods with fixed 416/417
  family quotas.
- The neutral intervention was assigned before feature extraction; features
  were used only for the post-construction gate.

## Boundary

Phase B remains unauthorized. The sealed artifact is permanently non-promotable
as a training parent unless a future protocol explicitly authorizes a new
design. This identity must not be repaired by widening the gate, selecting
replacement neutral variants after feature inspection, or reusing the failed
material under the same identity.

Canonical external receipt:

`D:/codex-runs/jev-information-density-v08m/phase-a-v01-clean/phase-a-failure-seal-final.json`

The earlier local receipt with the same disposition is retained as a
superseded preliminary seal after the independent validator was strengthened
to explicitly check train/evaluation family and template disjointness.
