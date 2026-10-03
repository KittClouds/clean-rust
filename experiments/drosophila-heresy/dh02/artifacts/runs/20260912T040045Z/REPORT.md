# DH-02 measured results

**OPPOSITE_DIRECTION_TO_DISTRACTOR_IMPAIRMENT_HYPOTHESIS**

All reversal conditions began from identical acquired states within each seed, side, tau and learning arm.

Primary: right-slice uniform-learning final reversal probe, quiet minus distractor = **-8.171 percentage points**, paired 95% bootstrap interval **[-9.277, -7.080]**.

576 arm runs; 294,912 computed training trials; 192 distinct acquisition streams reused across three conditions; 24 new computational seed bundles; two taus; one specimen.

## Final reversal probe accuracy

| Soma slice | Arm | Immediate | Quiet delay | Distractor delay |
|---|---|---:|---:|---:|
| R | E | 56.53% | 31.27% | 39.44% |
| R | Z | 50.85% | 50.85% | 50.85% |
| L | E | 55.06% | 31.26% | 38.13% |
| L | Z | 50.20% | 50.20% | 50.20% |

E learns with uniform modulation; Z has fixed weights. Only the primary contrast is inferential; all other comparisons are descriptive.

## Primary sensitivity by eligibility tau

- tau=4.0: quiet minus distractor -8.545 percentage points.
- tau=16.0: quiet minus distractor -7.796 percentage points.

## Reversal diagnostics: right slice, uniform learning

| Condition | Cue L1 | Interval L1 | Cue share of component L1 | Cue output saturation | Proposed clipping | A/B relative routing RMS |
|---|---:|---:|---:|---:|---:|---:|
| immediate | 510.460 | 0.000 | 100.00% | 2.20% | 0.20% | 9.002% |
| quiet | 159.408 | 0.000 | 100.00% | 2.18% | 0.19% | 7.026% |
| distractor | 125.752 | 2437.551 | 4.09% | 2.09% | 1.10% | 13.815% |

These are observer-only summaries. L1 component shares describe pre-clipping eligibility, not fractions of measured learning or proof of erroneous credit. Counterfactual routing uses the same current DAN state and is never delivered to E/Z.

## Phase performance: right slice, uniform learning

| Condition | Acquisition probe | Online reversal | Late reversal | Final reversal probe |
|---|---:|---:|---:|---:|
| immediate | 76.66% | 40.69% | 54.43% | 56.53% |
| quiet | 76.66% | 26.20% | 30.57% | 31.27% |
| distractor | 76.66% | 32.58% | 38.90% | 39.44% |

## Integrity and resources

- Complete expected outcome grid, matching acquired-state hashes, no-learning action parity, zero quiet-interval eligibility, and routing-null invariants passed.
- Simulator execution including diagnostics and setup: 7.953 seconds on 4 workers. Downloads/build/analysis excluded.
- No hot-loop allocations. Observer CPU and arrays are additional experimental instrumentation costs.
- Learner float arrays: 195,656 bytes; observer float arrays: 96,756 bytes per right-slice simulator. Immutable graph/cache, blank pattern and initial-weight audit copy are additional.

## Limits

- Quiet versus distractor tests total sensory exposure during reversal at matched time steps. It does not separately identify baseline adaptation, eligibility contamination, clipping, or other internal mediators.
- Immediate versus quiet changes both elapsed time and internal-state updates.
- Same fixed local rule, arbitrary synthetic action mapping and model dynamics; no rule search or post-outcome tuning.
- One animal; left/right are related soma slices. No biological functional validation.
- DH-01 remains frozen. The archived DH-01 engine is used only for compatibility tests.

Source: MaleCNS v1.0, FlyEM/Janelia and collaborators, CC-BY. https://male-cns.janelia.org/download/
