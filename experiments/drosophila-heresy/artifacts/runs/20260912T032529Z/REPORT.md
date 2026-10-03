# DH-01 measured results

**NOT_SUPPORTED_BY_PRESPECIFIED_GATE**

Primary A−B: **+0.079 percentage points**, paired seed-bundle bootstrap 95% interval **[-0.279, +0.452]**.

1,728 arm runs; 884,736 training trials; 24 computational seed bundles per suite; four frozen dynamics settings. One biological specimen.

## Online accuracy

| Suite | A anatomical | B route shuffle | C signal shuffle | D both | E uniform | Z no learning |
|---|---:|---:|---:|---:|---:|---:|
| primary | 51.47% | 51.39% | 51.39% | 51.47% | 51.29% | 49.92% |
| left_transfer | 51.84% | 51.74% | 51.70% | 51.64% | 51.86% | 50.11% |
| task_transfer | 49.52% | 49.82% | 50.23% | 50.32% | 49.59% | 49.28% |

## Prespecified routing comparisons

| Suite | A−B (percentage points) | Descriptive 95% interval |
|---|---:|---:|
| primary | +0.079 | [-0.279, +0.452] |
| left_transfer | +0.096 | [-0.151, +0.346] |
| task_transfer | -0.301 | [-0.657, +0.020] |

Only the right-slice primary comparison is the primary inferential endpoint. Transfer intervals and all other contrasts are descriptive.

### Primary sensitivity settings

- tau4_glut_inhibitory: +0.065 percentage points.
- tau4_glut_excitatory: +0.065 percentage points.
- tau16_glut_inhibitory: +0.374 percentage points.
- tau16_glut_excitatory: -0.187 percentage points.

## Anatomical diagnostics

Motif counts were defined before outcome execution; these are not selected discoveries.

- R: reciprocal pairs 311 versus null mean 141.1; feedforward triangles 127,841 versus 81,095.5.
- L: reciprocal pairs 314 versus null mean 142.6; feedforward triangles 142,815 versus 86,912.5.

## Engineering measurements

- Execution wall time including setup and all arms: 24.473 seconds; 4 workers.
- Sum of individual arm timers (concurrent; not wall time): 52.947 seconds.
- Hot-loop allocations across all scientific arm runs: 0.
- Online edge visits, including probes: 41,689,377,104; fixed feature-cache construction is outside this counter but inside execution wall time.
- Persistent mutable float-array storage per right-slice simulator: 195,460 bytes, excluding immutable graph, cue cache, and the audit copy of initial weights.
- Shuffled routing retains 21.3–27.9% of original pairs. Exact binary degrees and outgoing multiplicity sums passed for every null.

## Interpretation limits

- one specimen.
- coarse degree nulls do not preserve cell-type-pair structure.
- invented neuron dynamics, action partition, and cell-level broadcast.
- global gain normalization and top-k inhibition are modelling assumptions.
- no biological or architecture-family confirmation.
- persistent-array bytes exclude graph, cue cache, and temporary initial-weight audit copy.

The result concerns this fixed local rule and synthetic delayed-reward task. It neither establishes nor refutes biological dopamine function, general local-learning advantages, or a universal learning law.

Source attribution: MaleCNS v1.0, FlyEM/Janelia and collaborators, CC-BY. https://male-cns.janelia.org/download/

The source hashes, frozen config, executable hash and raw-output hashes are in the adjacent seal and completion receipts.
