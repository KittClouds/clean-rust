# Adaptive Authority Geometry v0.1

Primary source: **REACH-01** · REACH-01 live=False · outcomes01=6912

Engineering-only. Finite-difference channel probes, not a measured SVD of \(G_x=J_cB_x\).

## Authority triplet (native)

| quantity | value |
|---|---:|
| eta_D (cos u_N, g) | 0.0002997567483604066 |
| eta_S (L1 capture of g on native support) | 0.6486034376150066 |
| native support fraction | 0.37325493383675507 |
| eta_M (mean of per-step ratios) | 182.04641495674096 |
| eta_M (ratio of mean norms) | 182.04641495674096 |
| sign agreement | 0.3897530032232756 |
| magnitude Pearson | 0.013743952078926437 |
| bound clip fraction | 0.27610266026315844 |

## Nested authority channels (endpoint loss_large gain)

| channel | from | to | gain |
|---|---|---|---:|
| direction_on_native_support | native | reference_direction_native_support | 0.065137 |
| support_expansion_after_direction | reference_direction_native_support | reference_direction_full_support | 0.005365 |
| free_weight_beyond_reference | reference_direction_full_support | weight_oracle | 0.012091 |
| sign_swap_native_magnitude | native | sign_ref_native_mag | 0.062506 |
| magnitude_swap_native_sign | native | mag_ref_native_sign | -0.019398 |
| full_direction_vs_native | native | reference_direction_full_support | 0.070502 |
| oracle_vs_native | native | weight_oracle | 0.082593 |

## Incremental spectrum proxies

- |gains| sorted: [0.06513666223596645, 0.06250565140335651, 0.019397594310619215, 0.012091177481192122, 0.0053654423466435175]
- participation-ratio effective rank: 2.264697328344941
- condition-number proxy (max/min |gain|): 12.140035812091853
- nonpositive channels: 1 / 5

## Stage chain

- eligibility: 0.0027673448624058084
- modulation: 0.0027281627859879584
- aggregation: 0.0027281627859879584
- delivered: 0.0002997567483604066

## First-order (||g||=1)

- useful component eta_M*eta_D: 0.054570
- orthogonal component: 182.046407
- useful fraction of ||u||: 2.997567e-04

**Adaptive power != adaptive progress.**

## AR-04C cross-check

```json
{
  "final_measurement_loss": {
    "training_full96": 4.942043199539,
    "sentinel_fixed128": 3.208658061028,
    "sentinel_rotating128": 0.768007643223
  },
  "terminal_operational_loss_approx": {
    "fixed": 0.03,
    "rotating": 0.778007643223,
    "training": 0.0
  },
  "operational_minus_final": {
    "fixed": -3.1786580610280004,
    "rotating": 0.01,
    "training": -4.942043199539
  },
  "adaptive_overfitting_gap_ratio_fixed_vs_rotating": 317.86580610280004,
  "conditional_unbiasedness": {
    "claim": "E[grad J_St(xt) | xt] = grad J(xt) if St fresh independent of xt",
    "status": "holds by construction for rotating panels (disjoint seed namespaces, prospective panel schedule)",
    "does_not_imply": "checkpoint action-ranking alignment (AR-H56 not supported)"
  },
  "cell_wins": {
    "rotating_beats_training": "25/25",
    "rotating_beats_fixed": "25/25",
    "fixed_beats_training": "22/25"
  },
  "spearman_terminal_approx": {
    "fixed": -0.15,
    "rotating": 0.02,
    "training": -0.08
  }
}
```

