# FAS-S05–S11 Observer Geometry Synthesis

**Purpose:** close the descriptive observer-geometry phase and record its causal follow-up, FAS-S12.

**Status:** synthesis of sealed S05–S11 artifacts. This document is interpretive context; it is not an input to S12 execution, observer selection, or analysis.

## Bounded synthesis

The FAS observer studies distinguish four properties:

```text
accessibility
    a fixed representation can support a useful native linear observer

compatibility
    a representation, scaler, and probe can be transported as a matched bundle

transportability
    a frozen observer can remain predictive on a different layer's representation

geometric identity
    independently fitted observer decision planes are the same or nearly the same
```

These properties are not interchangeable. S09 showed high native linear accessibility before terminal decision geometry stabilized. S10 observed useful transport between nearby layers despite substantial observer-plane rotation. S11 confirmed predictive transport on a fresh generated population with the observer bank held fixed.

## Evidence classes

### Confirmatory on the S11 fresh panel

S11 evaluated the frozen 32-observer bank on 5,318 fresh, uniqueness-conditioned quartets (21,272 event rows), drawn from the same fixed world-family and template distribution. Its three preregistered summaries had the required simultaneous signs:

```text
D_off = +0.10649; simultaneous interval entirely above zero
M distance slope = -0.00527; simultaneous interval entirely below zero
F distance slope = -0.01861; simultaneous interval entirely below zero
```

The bounded confirmed statement is:

> With the observer bank frozen, final-position readouts have greater mean off-diagonal predictive transport than mean-full readouts on the S11 fresh panel, and transport declines with layer separation for both surfaces.

The final-position curve has a broader useful transport envelope near the diagonal. Its fitted raw distance slope is steeper because its near-distance transport begins much higher; it is not accurate to call its decay rate slower. For example, at distance one the reported mean balanced accuracies were about 0.710 for F and 0.465 for M. At large distances both approach chance and the difference narrows.

The S11 panel is fresh relative to the S01 exploratory split, but it is uniqueness-conditioned by the fixed collision-aware admission rule and retains the same world families/templates. The result does not establish generalization to new families, templates, or an unconditional generator population.

### Exploratory geometry inherited from S01

The following results remain exploratory because their split had already been exposed before the corresponding analyses:

- **S05–S06:** the usable decision system depends jointly on representation, centering/scaling, and probe orientation. Native matched pipelines work; crossed pipelines can collapse. The evidence does not reduce the mismatch to one affine nuisance.
- **S07:** the tested shared SAE recipe failed behavioral-fidelity qualification across its seeds, surfaces, and populations. High vector reconstruction quality did not preserve the fixed observer's decision geometry. This is a method limitation for that recipe, not evidence that sparse structure is absent.
- **S08:** the two native terminal observers each define rank-2 decision planes with principal angles near 79.6° and 86.8° and low normalized overlap. Their coordinate contribution support is diffuse (reported K50 about 312 and K80 about 771); only one coordinate overlaps in the top-32 sets. Coordinate-removal effects exceeded matched controls modestly but do not identify semantic dimensions.
- **S09:** native linear accessibility, cross-surface compatibility, and convergence to terminal observer geometry follow distinct depth trajectories. Its 32 fitted observers are now frozen inputs to S11.
- **S10:** the full layer-by-layer transport matrix showed stronger local transport for F than M alongside pronounced adjacent-plane rotation. It was descriptive on the revealed S01 population.

These geometric and depthwise observations were not re-estimated by S11. In particular, S11 does not turn the earlier plane-angle or terminal-convergence measurements into fresh-population geometry evidence.

## Methods that did not qualify

S07 closed one sparse-reconstruction route before feature interpretation. The valid conclusion is that the tested dictionary, sparsity, and reconstruction objective were not sufficiently faithful for attribution of the S06 observer effect. No feature identity or causal statement follows from that failure.

## Claims not established before S12

The S05–S11 lineage does not establish:

- semantic identity of any hidden coordinate or sparse component;
- a transformer circuit or causal information-flow path;
- mathematical necessity of an observer plane;
- native LFM answer-generation behavior;
- adaptive learning or online capability;
- generalization outside the pinned model, observers, task, and stated populations.

## S12: observer-plane causal dependence

S12 intervened on each sealed rank-2 source observer plane at layers 4, 8, and 12, then evaluated the unchanged terminal frozen observer. Each target edit was compared with eight independently generated random rank-2 planes using event-matched summary displacement norm and the same site/operator. The endpoint was the frozen-observer probe-logit margin, not an LFM language-model logit.

The primary contrast was the mean random-control target margin minus the target-plane target margin at strength 1.0. The shared 10,000-replicate whole-quartet bootstrap used a simultaneous six-site interval. Every site's interval was above zero:

| Site | Random minus target margin | Simultaneous 95% interval |
| --- | ---: | ---: |
| L04-M | 0.00472 | [0.00291, 0.00653] |
| L04-F | 0.07230 | [0.06339, 0.08121] |
| L08-M | 0.16025 | [0.15717, 0.16332] |
| L08-F | 0.89493 | [0.86737, 0.92249] |
| L12-M | 0.99551 | [0.97873, 1.01228] |
| L12-F | 3.08212 | [3.05034, 3.11390] |

Under the frozen site rule, selective causal dependence is supported at all six sites. The L04-M estimate is positive but small in probe-logit units; there was no minimum-effect threshold. The contract has no aggregate all-sites gate. Raw M-versus-F intervention magnitudes are not comparable because the M operator broadcasts across visible positions while F edits only the final position.

The result is a mechanistic follow-up on the already revealed S11 panel, not an independent population confirmation. It supports **selective causal influence of the specified activation-plane edit on the fixed observer-augmented decision system**, relative to matched random-plane edits. It does not establish mathematical necessity, native language behavior, semantic feature identity, transformer circuit causality, or generalization outside this model, observer bank, panel, and intervention.

The initial independent replay stopped on a verifier arithmetic defect: its scalar margin helper subtracted FP32 values before conversion, while the analysis contract computes the subtraction in FP64. Versioned verifier v03 casts before subtraction and independently replayed all 432 prediction/margin/metric cells and the full bootstrap. The original verifier is preserved; the raw and analysis roots did not change. This correction did not alter data or analysis.

```text
S12 execution: COMPLETE
S12 raw and analysis: SEALED
S12 independent replay: PASS
S12 final result root: ea753bd876981aeba199d15e621aa140928af685e9c3080eac13dbf78801182c
FAS-00: SENSOR_FAIL_NO_SIGNAL, unchanged
```
