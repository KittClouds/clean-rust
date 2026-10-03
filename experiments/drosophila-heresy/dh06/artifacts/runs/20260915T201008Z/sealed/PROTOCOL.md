# DH-06 protocol: causal geometry of eligibility-driven destabilization

DH-06 tests whether interval eligibility suppresses acquired-memory expression through acquisition-aligned erosion, off-axis reconfiguration, or both. It inherits MaleCNS v1.0 inputs and the DH-05 task, reward, neuron model, delay schedule, state restoration operation, probe schedule, and paired seed analysis.

The only new intervention is applied during reversal reward updates in the four causal cells. Immediate and quiet remain descriptive lineage anchors. All four causal cells receive the DH-05 interval neural-state restoration. The fixed-weight `Z` arm is carried through every condition.

## Causal update

For each reward event, calculate realized per-edge deltas from the same pre-update weight snapshot:

```text
retained_i  = clip(w_i + step * retained_eligibility_i, 0, 2) - w_i
suppressed_i = clip(w_i + step * cue_eligibility_i, 0, 2) - w_i
D_int = retained - suppressed
```

The acquisition vector is frozen at reversal start:

```text
A = W_A - W_0
S_t = {i : D_int[i] != 0}
A_t = A masked to S_t
D_parallel = ((D_int dot A_t) / (A_t dot A_t)) * A_t
D_perpendicular = D_int - D_parallel
```

If `A_t` has zero norm, the declared fallback is `D_parallel = 0` and `D_perpendicular = D_int`. Partial cells apply the suppressed realized update plus the selected components and clamp the final candidate to `[0, 2]`. The `both` cell applies the retained realized update directly and must reproduce it exactly. The `neither` cell applies the suppressed realized update directly.

No counterfactual path consumes RNG, advances eligibility, or advances neural state. The geometry transform is applied once after the two realized counterfactual deltas are calculated. Weight clipping is included before decomposition, and the reconstruction error is recorded.

## Conditions

| Condition | Parallel gate | Perpendicular gate | Role |
|---|---:|---:|---|
| `immediate` | n/a | n/a | successful-reversal reference |
| `quiet` | n/a | n/a | delayed reference |
| `neither` | 0 | 0 | eligibility-suppressed causal corner |
| `parallel_only` | 1 | 0 | acquisition-aligned erosion |
| `perpendicular_only` | 0 | 1 | off-axis reconfiguration |
| `both` | 1 | 1 | retained-eligibility causal corner |

All rows share acquisition streams, reversal examples, reward outcomes, probe RNG, route rewiring, and state-restoration semantics within each seed/tau/side/arm bundle. Fresh computational seed bundles are `6000..6031`; two trace time constants are used and averaged within bundle before inference. One specimen is used.

## Outcomes

The co-primary contrasts are paired factorial effects at reversal trial 256:

```text
perpendicular effect on old-map margin
  = 1/2 * [(M_01 - M_00) + (M_11 - M_10)]

parallel effect on acquisition-axis coordinate
  = 1/2 * [(C_10 - C_00) + (C_11 - C_01)]
```

The first contrast tests whether zero-instantaneous-axis off-axis remodeling changes old-map expression. The second tests whether the aligned component erodes acquired structure. Both use familywise 97.5% paired bootstrap intervals. Ordinary 95% intervals are descriptive for secondary contrasts and trajectories.

Secondary diagnostics include the two cross-effects, the parallel/perpendicular interaction, trajectory checkpoints `0,16,32,64,128,256`, realized component energy fractions, reconstruction error, support-zero events, and the sign of `q_t = D_int dot A` in windows `1..16`, `17..32`, `33..64`, `65..128`, and `129..256`.

## Predeclared interpretation gate

| Result | Interpretation |
|---|---|
| Parallel changes the acquisition coordinate and largely reproduces old-map loss; perpendicular is small | Direct erasure dominates |
| Perpendicular lowers old-map margin while acquisition coordinate changes little | Off-axis reconfiguration suppresses old-memory expression |
| Parallel erodes coordinate and perpendicular suppresses behavior with additive effects | Two-component destabilization |
| Neither isolated component works but both does | Synergistic or basin-transition mechanism |
| Perpendicular causes generic degradation across probes | Possible nonspecific perturbation |
| `both` fails to reproduce retained eligibility or `neither` fails to reproduce suppression | Intervention invalid; stop interpretation |

## Qualification and environment

The run is sealed before outcome inspection. The required sequence is release locked offline tests, release Clippy with warnings as errors, the zero-allocation benchmark, Python analysis tests, release build to `D:/drosophila-heresy/dh06-target`, lineage verification, sealed execution, analysis using the same frozen interpreter, and output verification. The analysis runtime is pinned to the project-local Python 3.13 interpreter and `numpy==2.3.3` in `requirements.lock`; the seal records the exact interpreter and NumPy version.

No shuffled-perpendicular control, four-class task, rule search, extra seed top-up, or post-outcome tuning is part of DH-06.
