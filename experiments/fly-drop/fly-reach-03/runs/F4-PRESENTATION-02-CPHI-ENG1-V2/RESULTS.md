# F4-PRESENTATION-02 Cphi engineering screen

Descriptive engineering comparison on the reused F4-INVARIANT-01 panel. The parent scientific disposition remains `NOT_EVALUABLE_SUPPORT` (7/12 class-complete blocks), and the parent analysis had previously opened held-out truth.

- New fits: 36 Cphi; parent D/S reruns: 0.
- Mean pooled balanced error: D=0.024123, S-sum=0.059352, Cphi=0.010234.
- Cphi minus D: -0.013888; Cphi minus S-sum: -0.049117.
- Block 306005 mean balanced errors: D=0.001863, S-sum=0.150514, Cphi=0.000040.
- Cphi training traces include epoch BCE, training balanced error, and per-layer gradient norm summaries. Parent D/S training traces were not retained, so no historical curve comparison is available without rerunning those arms.
- Role-separation and post-hoc sum-neighbor diagnostics use Cphi's learned shared phi. They do not reconstruct S-sum's own trained hidden state.
- No calibration promotion, measured REACH-03, controller, PHENO reopening, or biological promotion is authorized by this engineering screen.

## Replicate contrasts

| Replicate | Cphi − D error | Cphi − S error |
| ---: | ---: | ---: |
| 0 | +0.007618 | -0.054167 |
| 1 | -0.030103 | -0.051987 |
| 2 | -0.019181 | -0.041198 |

## Block 306005

| Arm | Replicate errors | Mean |
| --- | --- | ---: |
| D | 0.000000, 0.004098, 0.001490 | 0.001863 |
| S | 0.403984, 0.010060, 0.037498 | 0.150514 |
| Cphi | 0.000000, 0.000121, 0.000000 | 0.000040 |
