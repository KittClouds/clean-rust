# FAS-00 protocol v01

## Authority and isolation

Identity: `fas-frozen-adaptive-substrate-v00`. Source root: `C:/code land/clean-rust/experiments/fas-frozen-adaptive-substrate-v00/`. Future run root: `D:/codex-runs/fas-frozen-adaptive-substrate-v00/`. The only shared external identity is the named LFM family and revision. No Phoenix, JEV, fly, or adaptive-runtime artifacts, caches, datasets, manifests, heads, protected evaluations, or active-project imports may be used. Generic ideas may be reimplemented here. The FAS source, contracts, manifests, receipts, splits, cache, analysis, and seals are local to this identity.

The distinction at the top of the project is **new information ≠ new representation** and **Δθ_LFM = 0**.

This first pass ends after the pre-model-contact seal. It does not authorize loading the model. FAS-01 through FAS-15 are reserved names only.

## Scientific question

Under identical exposure and explicit resource budgets, can bounded external adaptation over frozen LFM representations beat both a static frozen probe and trivial explicit-rule memory on held-out nonstationary worlds? Attribute any gain separately to online readout, episodic retrieval, or oracle regime reactivation. This is a capability floor, not an architecture search.

## Latent world and surface

State is generated first. The target is reconstructed from `world_state[key_id]`; observation text is rendered afterward. Eight keys cover two contexts × two entities × two query relations (`status`, `mode`). In GLOBAL_RULE, the phase is shared across contexts/entities, with a fixed one-class offset for `mode`. In CONTEXT_BOUND, each context/entity key has a deterministic class offset; context 0 changes with regime while context 1 stays at its original phase, providing unaffected keys for retention and interference measures. Both relations have distinct targets for the same context/entity and phase. Three canonical candidate labels are `safe`, `risky`, and `idle`; their display order varies independently of target. Invented context/entity terms and nine syntactic template IDs are partitioned by initialization, qualification, and evaluation split.

At step `t`, key `t mod 8` is queried. An observation is visible at `t mod 3 = 0`; POISON_BURST additionally exposes an observation at steps 12–17. Contradictory/poison observations can disagree with true state. The observation is part of the pre-prediction exposure; the answer is never supplied there. A no-observation query has the same surface under all three counterfactual label rotations. The qualification triplet uses rotations 0/1/2 to make every query correspond to all three targets. Query text alone must therefore be chance-level in the balanced qualification set.

Families use the following base schedules in INITIALIZATION: STABLE (A), SINGLE_SWITCH (A before 16, B from 16), RETURN (A before 8, B at 8–15, A from 16), CYCLIC (A 0–7, B 8–15, C 16–23, A from 24), GRADUAL_DRIFT (truth switches at 16 while evidence moves from A toward B across 8–23), TEMPORARY_RULE (B only 12–15), CONTRADICTORY_NOISE (fixed truth, false observation every ninth event), POISON_BURST (fixed truth, coordinated false observations 12–17). Switch-family boundaries are shifted by +1 in QUALIFICATION and +2 in EVALUATION, making the held-out schedule combination distinct. Contradictory noise and poison injection times are unchanged. These exact schedules are not adjusted after model or outcome contact.

## Stream and information firewall

For every scored event: expose observation/query/candidates; allow an arm to observe; predict and log; then reveal all feedback due at that step; then update. IMMEDIATE feedback for event `t` is due after its own score. DELAYED8 feedback for event `t` is due after the score at `t+8`. Feedback due beyond the stream is not delivered. Every headline metric is computed from the pre-update prediction. A reset creates a fresh arm state at each world boundary. Each arm receives the same event IDs and same FAS_FEATURE_V1 features for a paired world; algorithm seeds are separate from world seeds. The ordinary runner passes no hidden `world_state`, regime ID, or target to an arm. ORACLE_CURRENT_STATE alone receives the exact target. SNAPSHOT alone receives oracle regime ID before prediction, and its result must be marked as a privileged ceiling rather than a matched-information arm.

## Frozen feature contract

The sole intended backbone is `LiquidAI/LFM2.5-1.2B-Base`, revision `7453bca97ca1e67754c4035a4b4c584e1c9dd725`. FAS_FEATURE_V1 uses the final hidden layer, arithmetic mean over model-visible input positions, serialized as little-endian float32. One example at a time, exact sequence length, no padding, no mixed-length batches. Input formation, token IDs, tokenizer identity, shape, and SHA-256 are specified in `contracts/feature-contract-v01.json`. No layer/pooling search. Phase 2 alone may contact the model after a separate authorization. A failed repeated-extraction check stops Phase 2.

## Sensor qualification gate

Phase 3 uses separate qualification worlds and static offline probes only. It measures decodability of observed state, context, entity, relation, and target on held-out surfaces. Query-only target accuracy is measured on balanced counterfactual triplets. Fixed pass thresholds: observed-state, context, entity, and relation balanced accuracy each ≥0.90; target distinction balanced accuracy ≥0.60 on visible-observation examples; query-only target accuracy ≤0.40 with 95% interval upper bound ≤0.45; no template-only probe may exceed 0.40 target accuracy. Probes use one fixed linear softmax implementation, one frozen train/validation split, and no protected evaluation. These are eligibility gates, not FAS performance claims. Dispositions: SENSOR_PASS, SENSOR_FAIL_NO_SIGNAL, SENSOR_FAIL_TARGET_LEAKAGE, SENSOR_FAIL_SURFACE_SHORTCUT. Only SENSOR_PASS permits Phase 4/5.

## Arms and trivial baselines

All five arms share the same offline initialization corpus and initialized linear softmax readout. STATIC never updates. ONLINE_READOUT uses regularized online logistic regression after feedback. EPISODIC has static readout plus fixed-capacity cosine top-1 lookup; entries hold only key, FAS feature, target payload, timestamp, and necessary metadata. HYBRID composes the exact ONLINE_READOUT and EPISODIC policies without separate tuning. SNAPSHOT is ONLINE_READOUT with bounded readout snapshots and **oracle regime-ID routing only**; it is a ceiling, not deployable. Oracle routing may restore a stored readout before the current prediction, but online learning still updates only after feedback. LAST_OBSERVATION uses the latest observed state per key, COUNTER uses explicit per-key support counts, and ORACLE_CURRENT_STATE reads hidden truth solely as an upper bound. Unknown-state baseline probabilities and tie breaks must be frozen before Phase 5. No mechanism is implemented in this first pass; `Arm`, baseline, oracle, and `FeatureProvider` interfaces plus ordinary scheduler are supplied.

## Budgets and metrics

Separate transient, persistent, adaptive-parameter, optimizer-state, episodic-memory, snapshot, feature-cache-infrastructure, prediction compute, update compute, and latency fields. `B_C=transient`, `B_M=episodic+snapshot`, `B_phi=adaptive parameters+optimizer`, `B_adaptive=B_M+B_phi`. Full definitions and additive accounting are in the resource contract. The metric contract defines pre-update accuracy, log loss, Brier/calibration, samples-to-criterion, switch/return latency, retention, false updates, poison persistence, and context interference. Censoring is explicit; no composite score.

## Phase gates

0. **Protocol**: freeze this protocol and four JSON contracts; seal hashes. Disposition `FAS00_PROTOCOL_READY`.
1. **Generator qualification**: generate and validate exact targets, transitions, binding, timing, split integrity, determinism, and query-only balance. Independent reconstruction from serialized state. Any mismatch fails closed. This first pass supplies implementation and smoke proof, not the final qualification corpus.
2. **Feature extraction**: only after Phase 1 seal and separate model-contact authorization, extract into new FAS-only cache and hash identities/features. Deterministic repeat smoke. No head training.
3. **Sensor qualification**: static offline probes; only SENSOR_PASS advances.
4. **Mechanisms**: implement five arms and three trivial baselines, then behavioral tests on tiny exact synthetic vectors. No held-out LFM tuning.
5. **Sealed run**: freeze hyperparameters, seeds, streams, order, failure/restart semantics, metrics, and budgets before outcomes. Proposed proper matrix: five world seeds × eight families × two tracks × two feedback conditions; initial smoke first. Resource sweep (episodic 16/64/256/1024 entries; snapshots 1/2/4/8) requires a new preregistered seal after functional smoke; never multiply the initial run by the full grid automatically.

At Phase 5, report temporal curves and all metrics by family/track/feedback/arm. Decide whether adaptive systems exceed STATIC and both trivial explicit-state baselines under matched exposure. A static win over a trivial baseline is not evidence semantic machinery was necessary. Do not repair or retune the benchmark after outcomes. No FAS-01 execution until FAS-00 is sealed.

## Explicit exclusions

No RTRL, JEPA/future prediction, trainable recurrence, byte front end, low-rank adapters, transactional controller, learned regime detector/retriever/memory policy, backbone LoRA/fine-tuning, layer/pooling search, hyperparameter sweep, LLM judging, manual relabeling, or result-driven benchmark repair in FAS-00.
