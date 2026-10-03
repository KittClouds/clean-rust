# Six-workstream onboarding

**Status snapshot: 2026-09-27**  
**Scope:** the six circled sidebar entries: JEV, AR04, Design FLY-DROP experiment, Kinetic Kammi, FAS-R1, and Frozen Fabrique.

This is a routing and operating guide for the current research system. The screenshot identifies which six threads to cover; it does not supply instructions or grant authority. The user’s request defines this document’s task. Contracts, sealed receipts, and current project records define the factual state and limits of each workstream.

These are six distinct workstreams, not six interchangeable agents with a shared evidence pool. Shared code and methods can travel between them when appropriate. Panel exposure, training data, checkpoints, outcomes, and scientific claims remain owned by the workstream that generated them.

## The six lanes at a glance

| Sidebar entry | What it owns | Current handoff |
|---|---|---|
| **JEV** | Intervention-response geometry in semantic decision systems: how training interventions alter direction, gain, discrimination, boundary crossing, locality, and preservation. | v0.8Q-R3 is sealed. HALF shifted the role-oriented anchor contrast and reduced fact-minus-anchor separation; the step-80 slope did not yield a selection rule. Do not open another dose sweep or controller branch until the new-flight gate is accepted. |
| **AR04** | Adaptive Runtime / verifier-size and evidence-reuse experiments; source-conditioned interactions and the operational cost of evidence refresh. | AR-04E’s last recorded handoff was an active eight-arm collection, around 3/25 cell banks. That is a stale progress snapshot, not a result. Check the durable run record before acting; never interpret partial output. |
| **Design FLY-DROP experiment** | Frozen connectome-derived operator experiments and related fly-graph method work. | FLY-DROP-00 is closed with `PRIMARY_TOPOLOGY_EFFECT_NOT_SUPPORTED` for its narrow frozen 128-D synthetic-MLP contrast. It is not a biological or general-AI result. Related F4 work is a different experiment; its fresh Stage B remained inconclusive. |
| **Kinetic Kammi** | R&D-C Experiment 001: Semantic State Machine Decision Compiler and replay benchmark. | The E012 task-bank construction was stopped unfinished; the last verified preflight was 20/80 packets, the positive control never ran, and there was no observer contact. Do not restart it by implication. |
| **FAS-R1** | Semantic-particle reachability and action/search experiments, with strict separation between public inference inputs and hidden validation truth. | The semantic sensor rung ended `R1_SENSOR_FAIL_SEMANTIC`; binding/action probes did not run. Later QΔ work is useful engineering evidence but does not reopen or pass the semantic qualification. |
| **Frozen Fabrique** | Frozen observer bundles, substrate/route engineering, and FAS E3 localization. | E4-1 is design-only. Its entry requires a terminal E4-0 disposition and Kammi Ledger acceptance; neither a plan nor a prototype seal opens the experiment. |

“Current” here means the latest status record available while this guide was prepared. For any live or long-running collection, the process/journal and terminal receipt outrank a sidebar summary or an old progress message.

## How to use the system

### Route to the owner

Open the existing task by its exact sidebar title and keep the request inside that lane. If a request crosses domains, identify the owner for each deliverable before work begins. Examples:

- JEV owns JEV intervention-response evidence; it does not own FAS-R1 semantic qualification.
- FAS-R1 owns its semantic sensor and reachability evidence; Frozen Fabrique owns FAS observer-bundle engineering and E3 localization.
- R&D-C owns E013 pair-localization work. Do not route E013 to Frozen Fabrique just because both touch FAS-adjacent infrastructure.
- Kinetic Kammi can build shared custody plumbing; the Ledger does not take ownership of a lab’s scientific evidence.
- FLY-DROP-00’s MaleCNS operator result is not evidence for JEV, FAS, or biological cognition.

If the destination is unclear, ask for an ownership/routing check first. Do not solve ambiguity by combining panels or results from multiple lanes.

### State the kind of work you want

At the top of a request, say whether it is:

1. **Read-only orientation or status** — inspect existing records; do not change files or start runs.
2. **Engineering repair** — trace a bug, fix the implementation, add a regression test, and preserve the scientific protocol. A technical repair is in scope when it does not alter data, outcomes, treatment definitions, metrics, thresholds, or what information has been exposed.
3. **Work under an already-sealed contract** — continue the authorized packet through its specified steps; do not stop at every routine receipt.
4. **New scientific flight** — requires its own accepted contract and any applicable program-level gate. A design document, roadmap, or successful build is not execution authorization.

Useful request shape:

```text
Workstream / exact task:
Mode: read-only | engineering repair | continue sealed packet | propose new flight
Question or defect:
Authoritative contract / artifact identities:
Allowed work:
Explicitly out of scope:
What counts as completion:
Execution behavior: continue through specified steps; stop on a real invariant failure
```

For an already authorized phase-sized packet, say: **“Proceed automatically through all specified steps while invariants pass. Return at completion or a genuine fail-closed condition, not for routine substep authorization.”** This avoids paperwork pauses without expanding authority across a scientific boundary.

### How to handle bugs and failures

When a bug appears, the default should be productive engineering: reproduce it, trace the data/control path, identify the root cause, repair the systemic seam, add a regression test, and resume only within the original authorization. Do not discard or overwrite failed attempts. If the repair changes a sealed protocol, measurement, or information boundary, preserve the original and version the change; do not quietly patch history.

Use the right status words:

- **NOT_EVALUABLE** means the required predicate could not be computed; it is not a pass or a scientific failure.
- **FAILED_CLOSED** means an invariant stopped the process before the forbidden operation; it is not an outcome.
- **INCONCLUSIVE** means the frozen analysis ran but its decision rule was not met.
- **No effect supported** is bounded to the tested design; it is not proof of universal absence.
- **Engineering validation** (tests, parity, replay) is not semantic qualification or scientific confirmation.

### Shared administration and the gate that matters today

**Chief Kammi is the Lab Chief and Head Librarian, outside the six circled workstreams.** The assigned lab/agent owns its hypotheses, implementation, authorized runs, analysis, raw logs, and scientific claims. Chief owns central bookkeeping: artifact ingestion, identities, CAS, lineage, seals, authoritative heads, authorization records, exposure accounting, fenced resource leases, remote custody, and institutional-memory intake. Chief also owns the Library code, adapters, schemas, custody vocabulary, and qualification.

At a natural checkpoint, hand Chief ordinary-language pointers to the existing task/authority, changed work, artifact path or manifest/commit, run and log location, observed contacts/openings (or unknowns), failures/stops, next gated action, and any resource need. Do not make a parallel local custody system, invent a receipt format, manually operate the Ledger/SDK/MCP, edit Library schemas, or rehash sealed ancestors. Protected material is identified by classification and location only until access is authorized. Chief returns the custody disposition; bookkeeping does not promote a scientific result.

For a future gated run, resource acquisition, protected opening, model contact, remote dispatch, or promotion, send the intended action to Chief **before** crossing the gate when the existing protocol requires it. A request is not permission. Keep already-authorized running work intact; stopped, paused, and design-only work stays stopped, paused, or design-only.

Kammi Ledger architecture v1 is locked, but its acceptance record says `NOT_RUN` overall and `CLOSED_PENDING_ACCEPTANCE` for new flights. The prototype already demonstrates useful pieces—content-addressed storage, canonical serialization, journal replay, Merkle sealing, and a legacy-fixture import—but several enforcement and recovery gates remain pending or partial. Its current local token and filesystem permissions are development controls, not production isolation.

Therefore:

- Existing work that already has its own valid authorization may continue under that contract.
- Do not start a **new experimental flight** merely because its protocol is ready, the code compiles, or another lane has completed a result.
- Do not represent the prototype as accepted custody enforcement. Central custody implementation and operation are owned by Chief Kammi; lab agents send bookkeeping requests and existing artifact pointers to Chief.
- Before a new flight, check the current Ledger acceptance receipt and the owning lab’s contract. Both must support the action.

This is a real gate, not a reason to interrupt routine engineering with extra approvals. Finish the accepted infrastructure slice; then route new flights through the actual acceptance result.

## Workstream details

## 1. JEV

### Mission

JEV studies how an intervention applied during training changes a decision system’s response geometry. The useful state is a vector, not a scalar score:

```text
direction | gain | discrimination | boundary crossing | locality | preservation | calibration
```

The program’s central lesson is that these coordinates can move in opposite directions. A larger target-vs-competitor gap does not necessarily mean the target probability rose; preserved MAP does not guarantee posterior or calibration preservation; correct direction does not guarantee enough gain to cross a boundary.

### Latest sealed result

The current endpoint is **POST-REGISTERED v0.8Q-R3**, a fresh balanced-polarity successor study—not a retroactive rewrite of Q or R2. It used 192 balanced histories plus a 24-history high→low bridge, paired 1×/HALF late continuations from the common step-80 history, and a fresh fixed-family panel.

The fixed sequence was:

1. Role-oriented anchor shift `M_C`: median `+0.03651`, interval `[+0.02626,+0.05671]` — passed.
2. Universal additive discrimination change `D`: median `−0.07270`, interval `[−0.11272,−0.05181]` — passed.
3. Proportional ratio `R`: eligible in 188/192; median `−0.32963`, interval `[−0.35582,−0.29845]` — passed. This corresponds to HALF retaining about 0.72 of the 1× fact-minus-anchor separation.
4. Linear step-80 moderation slope: `β=+0.14940`, 95% HC3 interval `[−0.21740,+0.51620]` — did not exclude zero.

Bounded reading: under this recipe, HALF shifted the role-oriented anchor contrast while reducing fact-minus-anchor separation. This did not produce a usable rule for choosing the intervention from step-80 state. Family endpoint rates were mixed; no family-specific training rule follows.

### Use JEV for

- Read-only interpretation or reporting of sealed JEV results.
- A concrete implementation repair inside an already authorized JEV packet.
- Prospective design work that keeps `M_C`, `P_C`, `D`, and `R` separate and makes role/polarity/identity contrasts identifiable.

### Do not use JEV to

- Reopen R2/X1/X2 to search for another favorable metric.
- Treat the failed moderation step as proof that all state dependence is absent.
- Fit a controller, choose a dose, or start a follow-on experiment under R3.
- Import FLY-DROP or FAS outcomes as if they were JEV replication data.

**How to brief it:** name the sealed JEV identity, specify read-only vs implementation work, and state which response coordinate is under discussion. Any new training/evaluation flight remains behind the Ledger acceptance gate.

Reference: [v0.8Q-R3 result](jev-v08q-r3-selectivity-v03-result.md).

## 2. AR04

### Mission

AR04 is the Adaptive Runtime line: it asks how a learner behaves when its update/search process depends on the evidence available to it, including verifier size, evidence reuse, refresh cadence, source-conditioned interactions, and path divergence. The key discipline is to distinguish evidence quantity from reuse structure and to report operational and population behavior together.

The source-path work already warns against overclaiming: path distance can track the magnitude of an interaction without giving a universal sign rule. Report unconditional interaction, divergence frequency, conditional effects, and seed-level signs separately; do not match on a downstream distance that the treatment itself changed.

### Current collection and handoff

AR-04D exposed an important labeling issue: its “K=16 pooled” condition repeatedly scored one fixed V2048 panel, so it is more accurately described as **fixed V2048**. AR-04E was redesigned as an eight-arm size × exposure comparison, with exact cadence accounting and a cached panel-generation optimization that preserves sample identity.

The last recorded task handoff said the fresh `run-20260926-ar04e-v4` collection was active and had reached roughly 3 of 25 cell banks. It had passed release tests, strict Clippy, formatting, and the identity-preserving prefix test before launch. No scientific result was interpreted at that handoff. This may have advanced since; check the process and durable completion journal before taking action. Partial files are not a result, and Windows may keep buffered outputs locked until clean exit.

### Use AR04 for

- Adaptive-runtime scientific questions about verifier size, exposure/reuse, path-conditioned effects, and cost/accuracy tradeoffs.
- Rust implementation and benchmark work in the isolated AR-04E branch.
- A bounded run-health check using process state, journaled cell completion, and terminal receipts.

### Do not use AR04 to

- Treat partial collection files as complete evidence.
- Explain a source-conditioned effect as a universal sign law or mechanism.
- Reuse a stopped v1 collection or alter the frozen cadence to save compute after seeing progress.
- Transfer AR-04 results into FAS-R1 or JEV without a separately designed bridge.

**How to brief it:** specify the AR protocol/run ID, whether you need a health check or post-run analysis, and require the agent to wait for clean exit before validating row counts or interpreting metrics.

## 3. Design FLY-DROP experiment

### Mission

The FLY-DROP lane tests whether a frozen connectivity-derived mixing operator has a reproducible computational effect inside a simple synthetic learner, relative to topology controls. Its source object is the full MaleCNS segment-connection table; the operator is not a neuron-only adjacency matrix. The experiment does not test fly cognition, biological function, or general AI performance.

The closed v0.1 protocol compared an identity path, dense mixer, random directed sparse graph, degree-preserving shuffled fly graph, and literal MaleCNS operator. Each was inserted into the same 128-dimensional synthetic teacher–student MLP setup, using frozen projections and paired training/evaluation structure.

### Closed result

`FLY-DROP-00-RUN1` is sealed and closed. Its integrity receipt verified 656 fits, 656 terminal evaluation events, and 839,680 optimizer updates with no infrastructure or numerical failures. The primary contrast was MaleCNS minus the degree/weight-context-preserving shuffle:

```text
delta = -7.65e-7 held-out BCE
95% bootstrap interval = [-1.289e-5, +1.046e-5]
disposition = PRIMARY_TOPOLOGY_EFFECT_NOT_SUPPORTED
```

This supports no reproducible held-out-loss difference for the tested **frozen 128-D algebraic projection** in this synthetic MLP host. It says nothing about nonlinear graph computation, recurrence, plasticity, alternate projections, other hosts, or biological function. Jev was explicitly out of scope.

Related fly work must retain its own identity. F4-BINDING-01’s exploratory Stage A showed assignment sensitivity, while its fresh Stage B had a positive mean pair-swap error change but too many non-evaluable bootstrap draws for the frozen interval rule; it remained inconclusive. Do not combine that with FLY-DROP-00 or call it confirmation.

### Use this lane for

- Reading the sealed FLY-DROP protocol, result, or operator construction.
- A separately named follow-up design that says exactly which untested operator/host property it addresses.
- Fly graph engineering with explicit boundaries between source-table structure and biological interpretation.

### Do not use it to

- Claim the fly connectome improves learning generally.
- Retrospectively change the graph control, host task, projection, or primary metric in FLY-DROP-00.
- Treat F4 binding, FAS-R1, and FLY-DROP as one dataset or one result.
- Use “fly-inspired” as a substitute for a specified operator and control.

**How to brief it:** name the fly experiment identity, separate design from execution, and state whether the requested output is source/operator engineering or a scientific claim.

References: [FLY-DROP protocol](../experiments/fly-drop-00/PROTOCOL.md), [terminal result receipt](../experiments/fly-drop-00/artifacts/run-FLY-DROP-00-RUN1/terminal-result-receipt.json).

## 4. Kinetic Kammi

### Mission

Kinetic Kammi is the R&D-C workstream currently assigned **Experiment 001: Semantic State Machine Decision Compiler replay benchmark**. It owns that assigned experiment’s task design, implementation, authorized construction/execution, raw logs, tests, and analysis. It is not the custody administrator or a central scientific judge.

### Gate and limitations

As of the status record, architecture v1 is locked for implementation; overall acceptance is `NOT_RUN`, and the new-flight gate is `CLOSED_PENDING_ACCEPTANCE`. Prototype passes exist for parts of tamper detection/rebuild; crash recovery is partial; GPU leases, exposure enforcement, adapters, failure-history projections, remote execution, and memory retrieval remain pending. The `/v1/authorize` denial only protects clients routed through that service; local tokens and filesystem permissions are development controls.

The recent E012 construction episode was stopped unfinished: the last verified preflight was 20/80 task/reserve packets, the positive control never ran, and there was no observer contact. Preserve that disposition; do not treat the build attempts as a completed bank or silently resume the old task.

E013 is an R&D-C-owned episode-factory / pair-localization program, not Frozen Fabrique work. Its earlier v0.2 plan was design-only; public datasets are seed sources, not a completed development/confirmation bank.

### Use Kinetic Kammi for

- R&D-C-owned decision-compiler, replay, and task-bank implementation within an explicitly authorized scope.
- Read-only status or engineering diagnosis of its own construction/build work.
- Preserving task-local tests, logs, and failed attempts while fixing ordinary software defects that do not change the experiment or expose protected information.

### Do not use it to

- Implement or operate the shared Ledger, Library schemas, or local custody wrappers; send those needs to Chief Kammi.
- Declare all experiments authorized because the Ledger architecture is locked.
- Conflate a prototype receipt with acceptance.
- Move another lab’s data, labels, or result into a shared “system” evidence pool.
- Restart E012 or begin E013 model contact merely from a roadmap or thread summary.

**How to brief it:** name R&D-C Experiment 001 or the exact owned task, and say whether the request is design, engineering repair, read-only status, or execution under an existing contract. For a new gated action, route the authorization/bookkeeping request to Chief Kammi; do not ask Kinetic Kammi to operate the Ledger.

References: [Ledger architecture](../program-infrastructure/kammi-ledger/ARCHITECTURE-v1.md), [acceptance status](../program-infrastructure/kammi-ledger/ACCEPTANCE-STATUS-v0.1.md), [architecture lock](../program-infrastructure/kammi-ledger/ARCHITECTURE-LOCK-v1.json).

## 5. FAS-R1

### Mission

FAS-R1 studies semantic particle reachability: can a system use a learned estimate of one-step reachability to propose actions/search paths while keeping proposal value (`V_reach`) separate from terminal solution selection (`Q_terminal`)? The inference-time agent receives only a public task projection. Private constraints, validators, solution sets, and hidden metadata remain offline/post-hoc.

This separation matters: the reachability sensor, action proposal policy, search trajectory, and terminal judge answer different questions. A successful search trace cannot be substituted for semantic transfer qualification, and a strong terminal selector cannot fix a proposal/search topology failure.

### Current scientific boundary

The formal Stage 1 semantic sensor qualification is terminally `R1_SENSOR_FAIL_SEMANTIC`: all three seeds failed template-OOD and joint-OOD qualification despite passing ID-seen and vocabulary-OOD checks. Binding/action-relevance rungs did not run. Proposal training beyond the allowed engineering work, protected evaluation, and biological promotion are not authorized by that result.

Separate QΔ runtime engineering did make progress: the Rust proposal scorer passed 66 tests and declared Python/Rust parity; sharper sampling improved train/validation reachability in the engineering roster. The same diagnostics found assignment-only canonical merging destructive when latent state or depth differed. These are engineering findings, not a semantic sensor pass. Any harder-roster/state-aware merge flight remains behind the Ledger gate.

### Use FAS-R1 for

- Engineering and diagnostics on the already-built reachability/search runtime.
- Read-only review of the sealed semantic qualification and train/validation traces.
- Maintaining public-inference/hidden-validator separation and full dynamic state identity.

### Do not use it to

- Reopen protected/test evaluation or infer semantic transfer from ID-seen success.
- Collapse `V_reach` and `Q_terminal` into a single score.
- Merge search states solely because assignments match; latent/depth/RNG continuation state can differ.
- Treat QΔ engineering results as passing `R1_SENSOR_FAIL_SEMANTIC`.

**How to brief it:** identify whether you mean the formal semantic R1 branch or the QΔ engineering branch; state the roster boundary and whether truth/validator access is allowed. Do not say “continue R1” without naming the rung.

## 6. Frozen Fabrique

### Mission

Frozen Fabrique is the representation/observer engineering lane around frozen backbones and narrow observers. It asks which representation surface, observer, or implementation path is useful and robust enough to carry forward. Its engineering selection evidence is not automatically mechanistic evidence. Roadmap ownership assigns FAS E3 localization to Frozen Fabrique; it does not assign E013 to it.

The E4-1 plan combines two engineering questions: does the machine survive useful template/surface variation, and does the pretrained substrate earn its cost relative to lexical, embedding, random-weight, and from-scratch alternatives? The intended output is a route choice (keep, boundary, replace, or kill), not an explanation of why the route works.

### Current state and gate

E4-1 remains **design-only**. Its latest plan explicitly requires a terminal E4-0 disposition and Kammi Ledger acceptance before entry. The Ledger status still reports the frozen E4 legacy fixture’s independent closure as pending and the new-flight gate as closed. A sealed plan, successful smoke test, or imported legacy artifact is not the missing acceptance receipt.

Frozen Fabrique can continue authorized engineering and documentation within the current scope. It should not start E4-1 collection, model contact, or a new flight until its entry conditions are actually satisfied.

### Use Frozen Fabrique for

- Frozen observer-bundle, feature-surface, and implementation-route work.
- Engineering comparisons that preserve frozen inputs and separate route selection from mechanism claims.
- FAS E3 localization under its own accepted contract.

### Do not use it to

- Take ownership of E013 or another lab’s evaluation panel.
- Promote reconstruction fidelity or observer fit as proof of decision-level behavior.
- Treat design readiness or the E4-1 plan as execution permission.
- Modify sealed E4 artifacts to make the entry gate appear complete.

**How to brief it:** name the E4 stage and ask for either engineering route selection or a specific FAS localization question. State whether the request is design-only, implementation, or authorized execution.

## A good handoff from any lane

Ask for a compact final report that answers:

1. What changed or was measured?
2. Which exact run/contract/result identity governs it?
3. Which checks passed, failed, or remain incomplete?
4. What is the bounded interpretation—and what does it not establish?
5. What is the next useful action that is already authorized?
6. If the next step is gated, what concrete acceptance artifact is missing?

For ongoing work, request durable progress only at useful boundaries: completed unit/cell/history counts, process health, errors, and the authoritative journal. Do not ask the agent to interpret partial artifacts. When a handoff says “active,” verify the process and run receipt before deciding it is still running.

The system should make it easier to do the science and engineering, not turn every file read into a new permission ceremony. Keep authorization aligned to genuine boundaries: changing the experiment, touching protected information, crossing from engineering into model contact, or starting a new flight. Within a valid packet, fix ordinary bugs and keep moving.
