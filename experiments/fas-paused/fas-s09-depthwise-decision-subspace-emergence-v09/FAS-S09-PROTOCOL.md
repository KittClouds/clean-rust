# FAS-S09 v09: Depthwise Decision-Subspace Emergence

## Objective and scope

Continue the previously authorized S09 fixed analysis using the sealed S09-v03 feature cache and the sealed S01/S08 artifacts. The S01 grouped split was already revealed, so all depthwise findings remain exploratory. No FAS-00 artifacts are in scope.

Versions 05 and 06 preserve two implementation-only stops: v05 caught a transcribed F-state hash before cache access, and v06 matched both terminal probes to S01 but exposed FP32-versus-FP64 scaler semantics in the S08 normal check. Version 09 carries the corrected scaler semantics and stable plane-equality gate forward. The v04 M-normal residual that exposed the original formula mismatch was `4.180381107943276e-07`; no earlier-layer fit ran in any failed attempt.

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

The terminal layer-16 observer must reproduce the S08 pair normals within `1e-12` and the S08 basis projector within Frobenius distance `1e-12` after the terminal probe-state, probability, and metric gates pass. Principal angles remain descriptive outputs; arccos-derived angles do not gate terminal equality. This gate must complete before any layer 1-15 fit.

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

The v04, v05, v06, and v07 project and run artifacts remain preserved in the v08 history tree. V08 is the authorized offline replay under the corrected geometry semantics; it does not overwrite any earlier failure.

## v05 parent-hash preflight failure

The preserved v05 packet failed its read-only audit because one extra hexadecimal `f` was transcribed into the expected F-terminal probe-state hash. The archived artifact hash was read directly and bound correctly in v06. No feature cache was read, no model was loaded, and no probe was fit during the failed v05 audit. The v05 project and run are preserved under the v06 history tree.

## v06 terminal-plane numerical gate correction

The preserved v06 run passed full cache verification and exact terminal probe reproduction, then stopped before intermediate-layer fitting. Pair-normal residual was 0.0 and the S08 plane projector residual independently recomputed as 0.0 for both surfaces, but the arccos of rounded near-unit principal cosines exceeded the 1e-6-degree check. V08 keeps the same principal-angle outputs as descriptive measurements and gates terminal plane identity using pair-normal residual and projector Frobenius distance, each at 1e-12.

## v07 parent-lineage preflight failure

The preserved v07 preflight used the immediate v06 protocol root while checking the older v05 project. It stopped before feature-cache access and probe fitting. V08 binds v04, v05, v06, and v07 artifacts through separate version-specific root fields and verifies the complete archived chain before creating a new protocol snapshot. The depthwise analysis, fit recipe, corrected scaler semantics, and stable projector gate are unchanged.

## v08 replay-helper failure

The preserved v08 run verified the complete feature cache, fitted all 32 contracted probes, and passed the terminal S01/S08 gates. It then stopped at the first replay cell because the replay helper expected a layer field absent from the probe state. V09 passes the current loop layer explicitly and repeats the fixed analysis so no fit diagnostics or replay metrics need to be reconstructed. The cache, labels, split, fit recipe, and projector gate are unchanged.

## v08 history path handling

The v09 run preserves both the complete v08 run copy, including its nested v04-v07 history directories, and the corresponding v04-v07 sibling archives. A preflight audit verified all 1,505 v08 preflight entries against the sibling archives and reproduced the original v08 preflight root exactly. The v09 scripts use the Windows extended-length path prefix for recursive reads so the deep historical paths remain intact; no sealed history files are moved or removed. The equivalence audit is recorded in `history-v08/sibling-history-equivalence-audit-v09.json` in the v09 run tree.
