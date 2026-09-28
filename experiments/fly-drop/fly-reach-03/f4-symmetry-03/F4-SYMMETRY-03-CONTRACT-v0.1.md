# F4-SYMMETRY-03 — Fresh Crossed-Regime Replication

**Status:** qualification-only, prospective, no measured REACH-03 authorization  
**Parent evidence:** F4-SYMMETRY-01 RUN4 and F4-SYMMETRY-02 are closed as archaeology; no further slicing of those outcomes is permitted.  
**Purpose:** test whether the RUN4 canonical-ordering effect recurs across fresh blocks within predeclared cue-incidence regimes.

## 1. Question and scope

The primary question is whether frozen canonical ordering (D) changes held-out polarity extraction relative to the same frozen relational values in absolute cue-slot order (C), and whether that difference varies by the predeclared incidence patterns `0011`, `0101`, `0001`, and `0100`.

This is a qualification replication. It does not open measured REACH-03, change the native learner, install a controller, reopen PHENO, or promote a biological claim.

RUN4/SYMMETRY-02 supplies hypothesis-generation evidence only. Its RUN4-specific observations are not pooled with this replication, used for seed selection, or used to tune its implementation.

## 2. Frozen source contrast

C and D retain the exact tuple values, feature packing, normalization, estimator, optimizer, update order, and numerical conventions in:

- `F4-SYMMETRY-01-CONTRACT-v0.1.md`, SHA-256 `cfef638aaeac1dfc0b768d13cc95afe7724861f74e3d3111d91401925bed6379`;
- `F4-SYMMETRY-01-IMPLEMENTATION-SPEC-v0.1.md`, SHA-256 `9ef769a80e4e5e91cd9af8b26bf22f8d1b49a940fe89c1f24f571333541ce0a4`;
- implementation amendment v0.2, SHA-256 `cf4b1a83922a08ec45b7e812cd1c39e8681940ff18c479bc0856bc18a9fa35f3`.

C contains the four six-field cue tuples in absolute cue-slot order. D contains those identical four tuple values sorted by the frozen tuple comparator, with no cue-ID tie-break. The C/D multiset equality invariant remains mandatory. The 90D model, 128/64 hidden widths, 200 epochs, batch size 2048, Adam settings, and float32 operation order remain unchanged. Only C and D are fitted; A, B, and HIST are excluded from this replication.

The replication uses leave-one-block-out predictions. The same fold normalization and initial trainable tensors are shared bitwise by C and D. Existing code is treated as an immutable source reference; this branch has its own versioned implementation and hashes.

## 3. Fresh task bank

The frozen coordinate-sampling manifest is reused without change: nine substrates (`fly`, `g001`–`g008`), two sides (`L`, `R`), and the existing 64 selected coordinates in each substrate-side cell. Training uses four cues, 8,192 trials per block, and delay 12, following the existing qualification task and schedule generator semantics.

Candidate block IDs are evaluated in ascending batches of eight beginning at `304000`; the maximum candidate range is `304000` through `304255`. A candidate ID is the task-pattern seed and native simulator seed. Its task schedule and balanced label permutation use the existing deterministic schedule procedure with seed `block_id XOR 0x545241494E`.

For each candidate batch, the structure-only screen constructs the four cue patterns using the frozen task generator and counts the four-bit incidence masks over only the already-frozen 64-coordinate-per-cell sample. The screen may read graph inputs, task seeds, coordinate IDs, and cue incidence. It must not read, compute, or serialize reference values, target signs, native proposed updates, fitted predictions, or performance outcomes.

Accept the first ascending candidate batch in which each named pattern (`0011`, `0101`, `0001`, `0100`) occurs on at least one sampled coordinate in at least six of its eight blocks. Displayed bit strings use the frozen convention: bit 0 is cue slot 0, and the displayed string is most-significant bit first. The accepted blocks are therefore structurally selected; this conditioning is part of the qualification population and must be reported. Record every screened batch, all per-block pattern counts, and rejected batches. If no batch passes within the candidate range, stop without generating native trajectories or fitting C/D.

This gate guarantees only task-structural support. It does not guarantee any number of U* rows, nonzero targets, or scoreable examples in a block-pattern cell. Such empty or class-absent outcome cells remain visible and are reported as undefined where required; no task block is replaced based on them.

## 4. Collection and fit firewall

After the accepted task bank and structural-screen receipt are frozen and hashed, run new native-only trajectories on the 18 frozen substrate-side cells. Construct the common C/D scoring rows under the original U* rule and serialize predictor features separately from scoring truth. No arm-comparative metric is available during collection or fit.

Fit the exact frozen C/D estimator in eight leave-one-block-out folds, producing 16 fits. Within each fold, C and D receive the same training rows, fold-normalization procedure, training order, and bit-identical initial tensors. All 16 held-out prediction streams are written and hashed before held-out truth is joined. Integrity validation must pass before any scientific comparison is emitted.

## 5. Frozen outcomes

Report in this order:

1. pooled and blockwise IPW-balanced error for C and D, and paired `error_D - error_C`;
2. blockwise signed margins, preserving null balanced-error values for any class-absent cell;
3. pooled, blockwise, and pattern-conditioned capability-weighted polarity `Psi_C`, `Psi_D`, and paired `DeltaPsi_D-C`;
4. pattern-conditioned balanced error and signed margins for `0011`, `0101`, `0001`, and `0100`;
5. leverage concentration for every reported pooled/pattern Psi: effective sample size `(sum w)^2/sum(w^2)`, and shares held by the top 1%, 5%, and 20% of `w=q*m*abs(g)` rows;
6. the full block-by-pattern table, retaining empty cells and reporting counts, leverage mass, and all defined metrics.

The pattern interaction diagnostic is the paired per-block contrast `DeltaPsi_D-C(0011) - DeltaPsi_D-C(0101)`. Report each of the eight block values and the pooled IPW-weighted value. Also report `0001` and `0100` separately; do not combine or relabel patterns after outcomes.

The replication signal is classified prospectively as **cross-block 0011 support** only when `DeltaPsi_D-C(0011) > 0` in at least six of the eight structurally supported blocks. Pattern-specific row support and missingness are reported, not imputed. This is a qualification decision rule, not a confirmatory population-level test. The `0101` comparator and interaction diagnostic determine whether the observed effect is regime-specific; neither can be used to tune features.

If cross-block 0011 support is present, the next eligible work is a separately sealed representation branch testing a principled canonical or permutation-equivariant representation. If it is absent or is carried by one or two blocks, close the current canonicalization hypothesis and return to the broader representation question. Either outcome leaves measured REACH-03 closed until a learned F4 calibration independently passes its frozen gate.

## 6. Prohibited adaptations

No RUN4 outcome slicing; no changes to C/D; no estimator enlargement; no selection using `g`, `Y`, predictions, model metrics, or native outcomes; no replacing a block after task bank acceptance; no dropping weak blocks or empty pattern cells; no measured REACH-03 namespace; no controller; no PHENO change; no biological promotion.

## 7. Required receipts

The qualification package records the contract and implementation hashes, reused input-manifest and graph hashes, candidate batch IDs and structure-only counts, accepted task bank and schedule hashes, native collection hashes, complete C/D fit manifest and receipts, all prediction hashes, integrity receipt, analysis code hash, block-by-pattern result table, final results, and terminal disposition. Source, task bank, predictions, and truth remain separate artifacts. A gate failure is terminal for this run identity.
