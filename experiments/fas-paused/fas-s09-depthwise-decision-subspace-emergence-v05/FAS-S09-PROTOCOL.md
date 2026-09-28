# FAS-S09 v05: Depthwise Decision-Subspace Emergence

## Objective and scope

Continue the previously authorized S09 fixed analysis using the sealed S09-v03 feature cache and the sealed S01/S08 artifacts. The S01 grouped split was already revealed, so all depthwise findings remain exploratory. No FAS-00 artifacts are in scope.

Version 05 corrects one analytical reconstruction mismatch found after v04 fit the two terminal probes and reproduced their S01 states, probabilities, and condition metrics. The v04 runner compared effective pair normals made from stored FP64 scaler values with S08 normals made from the runtime FP32 scaler values. The M residual was `4.180381107943276e-07`; the run stopped before fitting layers 1-15.

## Frozen correction

Probe execution and fitting stay unchanged. For analytical geometry, convert weights, bias, scaler mean, and scaler scale to their runtime FP32 values, then promote those values to FP64 for the matrix calculations. In particular:

```text
mu = float64(float32(stored_scaler_mean))
sd = float64(float32(stored_scaler_scale))
w  = float64(float32(runtime_probe_weights))
b  = float64(float32(runtime_probe_bias))
n  = w / sd
beta = (b_a - b_b) - n_ab dot mu
delta_b = b_a - b_b
```

For every fitted observer, class pair, and held-out row, verify these equivalent identities to absolute tolerance `1e-12`:

```text
m_ab = n_ab dot h + beta
m_ab = n_ab dot (h - mu) + delta_b
beta = delta_b - n_ab dot mu
```

The terminal layer-16 observer must reproduce the S08 pair normals within `1e-12` and the S08 plane within `1e-6` degrees after the terminal probe-state, probability, and metric gates pass. This gate must complete before any layer 1-15 fit.

## Fixed analysis

Fit the same 32 fixed exact-target linear probes: layers 1-16, surfaces `M=mean_full` and `F=final_position`, the sealed S01-3 grouped train/test split and masks, class order, standardization, optimizer, regularization, iteration and evaluation limits, and metric implementation. Layer 16 M and F are fitted first. Only after exact terminal reproduction and the corrected S08 plane and affine identity gates pass may layers 1-15 be fitted.

At each layer evaluate the four frozen cells:

```text
M_NATIVE
F_NATIVE
M_REP_F_PIPELINE
F_REP_M_PIPELINE
```

Report the already contracted accuracy, balanced accuracy, per-class metrics, margins, paired prediction transitions, M/F observer-plane principal angles and overlap, and convergence to each sealed S08 terminal plane. Do not introduce a promotion threshold, significance test, layer selection, representation search, or new probe.

## Boundaries

```text
LFM loading or feature extraction     FORBIDDEN
FAS-00 access                         FORBIDDEN
new probe family or solver changes    FORBIDDEN
adaptive mechanisms / SAE / nonlinear FORBIDDEN
FAS00_PHASE4_AUTHORIZED               false
ADAPTIVE_MECHANISMS_AUTHORIZED        false
```

The S09-v04 project, run, failure, and terminal probe states remain preserved in the v05 history tree. V05 is a complete offline replay under the corrected geometry semantics; it does not reinterpret or overwrite the v04 failure.
