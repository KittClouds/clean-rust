# FAS S05–S11 Observer Geometry Synthesis

**Disposition:** `OBSERVATIONAL_LINEAGE_CLOSED_FOR_CURRENT_SCOPE`  
**Evidence status:** S05–S10 descriptive on previously revealed populations; S11 confirmatory transport result on a fresh, uniqueness-conditioned population.  
**S12:** design proposal only; no activation intervention or new model execution is authorized by this document.

## Executive finding

The strongest repeated result is that a useful linear observer is a property of a **representation and its fitted readout together**. On the fresh S11 quartets, the fixed final-position (F) observer bank transported better on average to non-native layers than the fixed mean-full (M) bank, while transport declined with layer distance for both. This establishes transport behavior for the frozen observer bank and this generator population. It does not establish why the transport pattern occurs.

The broader S-series distinction is:

```text
native accessibility
≠ observer compatibility
≠ cross-depth transportability
≠ geometric identity
```

These quantities have different evidence ancestry. S11 freshly confirms predictive transport and its F-over-M off-diagonal advantage. The near-orthogonal terminal observer planes and earlier depth trajectories are exploratory measurements from the already revealed S01 grouped split.

## Evidence ledger

### S05 — representation and readout are matched systems

S05 replayed sealed feature arrays through four fixed combinations of representation and complete scaler-plus-probe pipelines. On the S01 controlled test population, the native diagonal cells scored M/M `0.7414 BA` and F/F `0.9814 BA`; the crossed cells were near chance (`0.3417` and `0.3428 BA`). On the original FAS-00 context slice, the matched mean-full pipeline scored `0.5654 BA`, and the matched final-position pipeline `0.6722 BA`; on the entity slice the values were `0.8119` and `0.6676 BA`. The surface effect was therefore factor-conditional, not a uniform improvement. Crossed cells are fixed-pipeline transport tests, not refits.

### S06 — compatibility is distributed across affine scaling and probe orientation

The fixed 16-cell representation × center × scale × probe replay showed that no single affine correction accounts for the S01 compatibility pattern. Swapping probe orientation after native normalization reduced BA by about `0.398` for M and `0.411` for F. Center-only transport reduced it by about `0.399` for M and `0.369` for F. Scale-only transport reduced M by about `0.095`, while F changed by about `+0.001`. These are descriptive fixed-pipeline contrasts on the bound populations; they do not identify a transformer mechanism.

### S07 — the tested SAE did not pass decision-fidelity qualification

All 24 reconstruction-gate checks failed the prospectively contracted behavioral-fidelity limits. On S01 mean-full, zero-baseline reconstruction R² was approximately `0.972–0.973`, yet the fixed observer’s decision behavior degraded beyond tolerance. This shows that this SAE recipe’s vector MSE/R² was insufficient to preserve the decision behavior under study. It does **not** show that sparse structure is absent or that other SAE methods cannot explain it. No feature interpretation or ablation was conducted after the gate failed.

### S08 — distinct, diffuse observer planes (exploratory)

On S01, both native decision subspaces had rank 2. Their principal angles were approximately `79.6°` and `86.8°`, with normalized projection overlap about `1.78%`. The coordinate contribution census was diffuse (`K50 ≈ 312`, `K80 ≈ 771`); selected coordinate interventions hurt the observer, but matched controls also caused material loss. These findings characterize the fixed linear observers in the revealed population. Coordinate groups are not semantic features or transformer circuits.

### S09 — accessibility and terminal geometry followed different depth trajectories (exploratory)

Fixed linear accessibility became strong before terminal-plane convergence. On the S01 split, F reached near-ceiling BA by layer 5 and remained high through layer 16; M rose later, peaked around layers 8–10, then declined toward `0.750` at layer 16. The M/F layer-16 plane comparison reproduces the S08 angles. The depth curves and convergence trajectory remain exploratory because the grouped split had already been exposed. A weak fixed probe does not establish information absence.

### S10 — local predictive transport despite large observer-plane rotation (exploratory)

On the same revealed S01 population, adjacent-layer transport averaged about `0.451` forward / `0.470` backward for M and `0.729` / `0.684` for F. At distance 2, the reported means were about `0.388` for M and `0.590` for F. Adjacent planes could remain highly rotated while a fixed observer still transported usefully. This supports an observer-level description of local predictive transport without local plane identity, but S10 was not an independent population confirmation.

### S11 — fresh-population transport confirmation

S11 used 5,318 whole quartets (21,272 event rows) from the fixed world families/templates, selected under the sealed deterministic collision-aware uniqueness rule. The 100 collision-rejected quartets remain construction metadata; the result is conditional on the final admitted panel.

The frozen 32-observer bank was replayed across all 512 surface × source-layer × target-layer cells. A shared 10,000-replicate, class-stratified whole-quartet bootstrap yielded simultaneous 95% intervals:

| Summary | Estimate | Simultaneous 95% interval | Frozen criterion |
|---|---:|---:|---|
| `D_off` (F minus M off-diagonal BA) | `+0.106489` | `[+0.105512, +0.107466]` | lower bound > 0: pass |
| M distance slope | `−0.005273` | `[−0.005375, −0.005171]` | upper bound < 0: pass |
| F distance slope | `−0.018614` | `[−0.018847, −0.018381]` | upper bound < 0: pass |

At distance 1, mean BA was about `0.465` for M and `0.710` for F; at distance 2, `0.388` and `0.593`; at distance 3, `0.360` and `0.489`. F’s overall off-diagonal transport envelope is larger, but its fitted raw distance slope is steeper. The claim is **not** that F decays more slowly. At larger distances both approach chance, and the F-minus-M difference shrinks.

The point estimates and intervals concern quartet sampling uncertainty conditional on this fixed observer bank and generator. They do not include observer-training, model-seed, or generator-family variation. S11 does not freshly estimate observer planes, native accessibility, or circuit structure.

## Established, exploratory, and failed claims

### Freshly confirmed by S11

- The frozen F observer bank has higher mean off-diagonal balanced-accuracy transport than the frozen M bank on the admitted fresh S11 quartets.
- Raw balanced-accuracy transport declines with layer distance for both banks.
- The result is based on a complete 512-cell replay and the frozen joint bootstrap rule.

### Exploratory evidence from S01 and its fixed observers

- Matched representation/scaler/probe systems can be highly capable while crossed systems fail.
- The fixed observers have distinct low-rank planes whose decision support is spread over many original coordinates.
- Accessibility, plane convergence, and transport have different depth trajectories.
- Nearby observers may transport predictions despite substantial plane rotation.

### Method qualification failure

- The one S07 SAE recipe was not behaviorally faithful enough for the planned sparse compatibility analysis. This closes that method branch as run; it is not evidence against sparse structure in general.

### Not established

- Semantic meaning of individual hidden coordinates, SAE features, neurons, or attention heads.
- A transformer circuit or mechanistic information-flow account.
- Causal necessity of a plane for native LFM behavior.
- Generalization across model seeds, model families, generator families, or newly fitted observers.
- A categorical “emergence layer,” or that a low probe score means the model lacks information.
- Any change to FAS-00’s `SENSOR_FAIL_NO_SIGNAL` disposition or authorization of adaptive mechanisms.

## Lineage closure and next question

The S05–S11 observational lineage is closed for the current question. No additional S11 metrics or subgroup promotions are part of this synthesis. The next proposed question is whether a fixed observer plane at a selected intermediate layer has **selective causal influence on the terminal decision of the observer-augmented FAS system**, compared with an equal-energy random-plane intervention. That is an activation intervention in a new S12 identity and requires separate execution authorization.

A causal effect on the external frozen probe would establish dependence of that **LFM-plus-observer system** under the specified intervention. It would not, by itself, establish that the same plane is necessary for the pretrained LFM’s native language-model behavior.

## Source bindings

The machine-readable source binding beside this document records the protocol/result roots used for S05–S11, including the authoritative S11 v02 final root. Sealed source artifacts remain immutable.
