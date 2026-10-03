# Northstar G0–G8 Update Report

**Report date:** 2026-08-16  
**Scope:** sealed gate records G0 through G8, the frozen roadmap record, and the Northstar repository documentation inventory.  
**Current position:** G0–G8 sealed; work paused before G9.  
**Report mode:** raw evidence, receipt status, file inventory, provenance, repository state, and next documentation/data work only.

## 1. Scope guard

This report does not add a definition for thing 2. The label is retained only as a supplied reference. No characterization is supplied.

This report contains no interpretation or characterization of the underlying object. It records what is present in files, what was sealed, what was counted, what remains absent, and what is scheduled next.

The report does not open, summarize, or reproduce outcome-bearing rows, confirmation-window material, or real-pair contents. The receipt fields that record zero access are reported as counts only.

## 2. Authority and evidence locations

### 2.1 Gate compound root

Root directory:

studies/obs-open-01/sentinel-behavioral-qualification-compound

Observed gate directories:

| Gate | Directory | Seal file | Seal status |
|---|---|---|---|
| G0 | g0-authority-input-bridge | seal/G0_ROOT_RECEIPT.json | present |
| G1 | g1-semantic-kernel | seal/G1_ROOT_RECEIPT.json | present |
| G2 | g2-computational-role-census | seal/G2_ROOT_RECEIPT.json | present |
| G3 | g3-reachable-transition-semantics | seal/G3_ROOT_RECEIPT.json | present |
| G4 | g4-preservation-surface | seal/G4_ROOT_RECEIPT.json | present |
| G5 | g5-continuation-grammar | seal/G5_ROOT_RECEIPT.json | present |
| G6 | g6-behavioral-equivalence | seal/G6_ROOT_RECEIPT.json | present |
| G7 | g7-formal-analysis-boundary | seal/G7_ROOT_RECEIPT.json | present |
| G8 | g8-witness-laboratory-qualification | seal/G8_ROOT_RECEIPT.json | present |

No g9 directory or g9 seal was found during this audit.

### 2.2 Frozen roadmap record

File: CANONICAL_ROADMAP_ROOT_RECEIPT_V1.json

| Field | Recorded value |
|---|---|
| schema | OBS_OPEN_04A_DESCENDANT_CANONICAL_ROADMAP_ROOT_RECEIPT_V1 |
| status | FROZEN_CANONICAL_ROADMAP |
| program_id | 04A_DESCENDANT_BEHAVIORAL_QUALIFICATION_COMPOUND_V1 |
| ancestor root | 48102bd529abf01591842f85676b86eb66b0600dc8d702bd0dbb3d6b729b4c41 |
| artifact_count | 2 |
| roadmap root | bd5433521f24e17275583c1dc3869476d71376e3667d15019ec7b706d911a6f1 |
| root algorithm | SHA256_OF_CONTENT_MANIFEST_BYTES |
| authority | CANONICAL_PROGRAM_ROADMAP_ONLY |
| scientific-finding authority | false |
| roadmap g0_execution field | NOT_STARTED |

The roadmap record is a frozen planning artifact. The executed G0–G8 seal records listed below are the status records for the completed gate work. The roadmap field is not substituted for an executed gate receipt.

## 3. Gate status ledger

| Gate | Root hash | Status | Question state | Disposition | Primary result |
|---|---|---|---|---|---|
| G0 | e317cabef33114edf47c50f4628a210ae8f1bd0b59feb436dc37e7df9cfe38bf | SEALED | CLOSED | ADVANCE_WITH_RESTRICTION | 04A_DA_OBSERVER_TRACE_PRESERVED_BY_INTEGER_TICK_AND_NANOSECOND_STORAGE_BRIDGE |
| G1 | 65cbe177fd5dc510ab9dc19e203a912a107ab8ac740b55a64926a1164edceafd | SEALED | CLOSED | ADVANCE | EXACT_SEMANTIC_KERNEL_EXTRACTED |
| G2 | bdb26248c750099e2a2aa64f09e75fc66a2c98893892e90e12c47ae9908c0fe6 | SEALED | CLOSED | ADVANCE | COMPUTATIONAL_ROLE_CENSUS_SEALED |
| G3 | c936eac1c37cbc70aa9d42bffdea096cdc1afb9269ad73c26f2ddf535eb54bef | SEALED | CLOSED | ADVANCE_WITH_RESTRICTION | SOUND_REACHABILITY_ENVELOPE_SEALED |
| G4 | 37ed98b4ebe447ef3c2152e550c99652d0157aea2c77b8a886379d1ba9e08e15 | SEALED | CLOSED | ADVANCE_WITH_RESTRICTION | PRESERVATION_SURFACE_SEALED_WITH_DECLARED_NOT_EVALUABLE_COMPONENTS |
| G5 | 808f4089ada22e7736460a90efd71b1dec0726dece460ca4dc1df8cbccac554c | SEALED | CLOSED | ADVANCE_WITH_RESTRICTION | SOUND_PARAMETRIC_CONTINUATION_GRAMMAR_ENVELOPE_SEALED |
| G6 | cf282d195f90e1ee970b7c5d57329c901848d7894f4ed8c5945755d3935633dd | SEALED | CLOSED | ADVANCE_WITH_RESTRICTION | FIBERWISE_BEHAVIORAL_EQUIVALENCE_CONTRACT_SEALED |
| G7 | 069a5294c37a6fbede436af2f57700964ce1e752643aeaa26b06de6581183bd5 | SEALED | CLOSED | ADVANCE_WITH_RESTRICTION | FORMAL_ANALYSIS_BOUNDARY_SEALED_WITH_RESTRICTIONS |
| G8 | 556cba86bf75a76d67c411db5a62229cb35ec84c92bd0bfbb6fd086971496ece | SEALED | CLOSED | ADVANCE_WITH_RESTRICTION | WITNESS_LABORATORY_QUALIFIED_WITH_RESTRICTIONS |

Summary of the ledger:

- 9 gate seal records are present from G0 through G8.
- 9 of 9 questions are marked CLOSED.
- 2 gates carry unrestricted ADVANCE disposition: G1 and G2.
- 7 gates carry ADVANCE_WITH_RESTRICTION disposition: G0 and G3 through G8.
- Each root receipt records zero access for the excluded downstream populations. The report preserves those receipt counts without opening the underlying material.

## 4. Gate-by-gate evidence

### G0 — authority input bridge

**Receipt:** g0-authority-input-bridge/seal/G0_ROOT_RECEIPT.json  
**Root:** e317cabef33114edf47c50f4628a210ae8f1bd0b59feb436dc37e7df9cfe38bf  
**Schema:** OBS_OPEN_G0_ROOT_RECEIPT_V1

Recorded facts:

- Status is SEALED.
- Question is CLOSED.
- Disposition is ADVANCE_WITH_RESTRICTION.
- Result string is 04A_DA_OBSERVER_TRACE_PRESERVED_BY_INTEGER_TICK_AND_NANOSECOND_STORAGE_BRIDGE.
- Fossil identity is EXACT_04A_ROOT_VERIFIED.
- Input bridge is marked SEMANTICS_PRESERVING_NORMALIZATION.
- Downstream authority flags are false.
- The typed qualification matrix is OBS_OPEN_G0_TYPED_QUALIFICATION_MATRIX_V1.
- The typed matrix contains 11 claims.
- The matrix records negative claims as typed results rather than gate failures.

Files inspected:

- OBS_OPEN_G0_PROTOCOL_V1.md
- seal/content_manifest.tsv
- seal/Gn_ROOT_RECEIPT.json
- typed qualification matrix JSON

Seal manifest record:

- Manifest byte count: 2175.
- SHA-256 of the seal manifest equals the G0 root hash.

Operational boundary recorded by the protocol:

- The prior fossil root is checked without mutation.
- The integer-unit and nanosecond storage bridge is checked as a separate input condition.
- The gate uses only the authorized source population.
- No downstream population is opened by this gate.

### G1 — semantic kernel

**Receipt:** g1-semantic-kernel/seal/G1_ROOT_RECEIPT.json  
**Root:** 65cbe177fd5dc510ab9dc19e203a912a107ab8ac740b55a64926a1164edceafd  
**Schema:** G1_ROOT_RECEIPT_V1

Recorded facts:

- Status is SEALED.
- Question is CLOSED.
- Disposition is ADVANCE.
- Result string is EXACT_SEMANTIC_KERNEL_EXTRACTED.
- Authorized population is D_A_154_SESSIONS_57500_COMPLETED_M1_BARS.
- Canonical bridge is CANONICAL_INTEGER_M1_BRIDGE_V1.
- Source-time resolution is one second.
- Storage resolution is one nanosecond.
- Kernel source SHA-256 is 8951dd29dc547d8ef9def2f356970c7398579da85f94521fff9de85f1740c2f0.
- Outcome access values are D_B=0, D_C=0, D_D=0.
- The typed qualification matrix is G1_TYPED_QUALIFICATION_MATRIX_V1 with 13 claims.

Files inspected:

- OBS_OPEN_G1_PROTOCOL_V1.md
- seal/content_manifest.tsv
- seal/Gn_ROOT_RECEIPT.json
- typed qualification matrix JSON

Seal manifest record:

- Manifest byte count: 3582.
- SHA-256 of the seal manifest equals the G1 root hash.

Operational boundary recorded by the protocol:

- All authorized distinctions are retained.
- A deterministic language-independent kernel is emitted.
- No extension beyond the authorized source population is admitted.

### G2 — computational role census

**Receipt:** g2-computational-role-census/seal/G2_ROOT_RECEIPT.json  
**Root:** bdb26248c750099e2a2aa64f09e75fc66a2c98893892e90e12c47ae9908c0fe6  
**Schema:** G2_ROOT_RECEIPT_V1

Recorded facts:

- Status is SEALED.
- Question is CLOSED.
- Disposition is ADVANCE.
- Result string is COMPUTATIONAL_ROLE_CENSUS_SEALED.
- Graph node count is 73.
- Graph edge count is 117.
- Role-census element count is 57.
- Multi-role collision count is 37.
- Grammar state/event is marked NOT_EVALUABLE.
- Outcome access values are D_A_market_rows=0, D_B=0, D_C=0, D_D=0.
- ROLE_AND_GRAPH_QUALIFICATION.json reports PASS.
- All 57 elements carry at least one role and a status.
- Dangling-edge count is 0.
- Required and present edge-kind lists each contain 9 entries.
- Importance/removability judgments are 0.

Files inspected:

- OBS_OPEN_G2_PROTOCOL_V1.md
- seal/content_manifest.tsv
- seal/Gn_ROOT_RECEIPT.json
- ROLE_AND_GRAPH_QUALIFICATION.json

Seal manifest record:

- Manifest byte count: 3307.
- SHA-256 of the seal manifest equals the G2 root hash.

Operational boundary recorded by the protocol:

- The census is exhaustive over the supplied graph artifact.
- No redesign is performed.
- The one NOT_EVALUABLE component is carried forward as a recorded status.

### G3 — reachable transition envelope

**Receipt:** g3-reachable-transition-semantics/seal/G3_ROOT_RECEIPT.json  
**Root:** c936eac1c37cbc70aa9d42bffdea096cdc1afb9269ad73c26f2ddf535eb54bef  
**Schema:** G3_ROOT_RECEIPT_V1

Recorded facts:

- Status is SEALED.
- Question is CLOSED.
- Disposition is ADVANCE_WITH_RESTRICTION.
- Result string is SOUND_REACHABILITY_ENVELOPE_SEALED.
- Exact global reachability is false.
- Constructive witness count is 16.
- Proven joint-constraint count is 22.
- Proven unreachability-claim count is 9.
- Outcome access values are all zero.
- The final seal root is c936eac1...54bef.
- Earlier intermediate roots 535a8721... and b4b214... are retained as build history, not as the final seal.

Recorded restriction:

LATER COUNTEREXAMPLES FROM T_PLUS REQUIRE CONSTRUCTIVE WITNESS; LOWER-BOUND ABSENCE CANNOT SUPPORT UNREACHABILITY.

Files inspected:

- OBS_OPEN_G3_PROTOCOL_V1.md
- seal/content_manifest.tsv
- seal/Gn_ROOT_RECEIPT.json
- final qualification receipt

Seal manifest record:

- Manifest byte count: 3514.
- SHA-256 of the seal manifest equals the G3 root hash.

Operational boundary recorded by the protocol:

- Context-indexed lower and upper records are retained.
- Search failure is not recorded as an absence result.
- Later counterexamples require a constructive witness record.

### G4 — preservation surface

**Receipt:** g4-preservation-surface/seal/G4_ROOT_RECEIPT.json  
**Root:** 37ed98b4ebe447ef3c2152e550c99652d0157aea2c77b8a886379d1ba9e08e15  
**Schema:** G4_ROOT_RECEIPT_V1

Recorded facts:

- Status is SEALED.
- Question is CLOSED.
- Disposition is ADVANCE_WITH_RESTRICTION.
- Result string is PRESERVATION_SURFACE_SEALED_WITH_DECLARED_NOT_EVALUABLE_COMPONENTS.
- Protected observable count is 23.
- G2 elements dispositioned count is 57.
- Blind-spot label is GrammarStateAndEvent.
- G4_CLOSURE_QUALIFICATION.json reports PASS.
- Named observable count is 23.
- In-authority element count is 54.
- Not-in-authority element count is 3.
- Not-evaluable blind-spot count is 1.
- Comparison semantics defined is false.
- Exclusions with affirmative basis is true.
- Surface is immutable is true.
- Six carried-not-next-read items are protected is true.

Recorded restriction:

GrammarStateAndEvent remains NOT_EVALUABLE; G3 mixed-reachability restrictions propagate unchanged.

Seal manifest record:

- Manifest byte count: 3311.
- SHA-256 of the seal manifest equals the G4 root hash.

Operational boundary recorded by the protocol:

- Protected observables are frozen.
- The declared blind spot is carried forward.
- Cross-history comparison is not performed by this gate.

### G5 — continuation grammar

**Receipt:** g5-continuation-grammar/seal/G5_ROOT_RECEIPT.json  
**Root:** 808f4089ada22e7736460a90efd71b1dec0726dece460ca4dc1df8cbccac554c  
**Schema:** G5_ROOT_RECEIPT_V1

Recorded facts:

- Status is SEALED.
- Question is CLOSED.
- Disposition is ADVANCE_WITH_RESTRICTION.
- Result string is SOUND_PARAMETRIC_CONTINUATION_GRAMMAR_ENVELOPE_SEALED.
- Fixture count is 24.
- Single-grammar exactness is SOUND_ENVELOPE.
- Pairwise exactness is SOUND_ENVELOPE.
- Rejection exactness is EXACT.
- Coupling-interface exactness is EXACT.
- G5_QUALIFICATION_RECEIPT_V1 reports PASS.
- Fixture failures are 0.
- Epsilon handling is true.
- Prefix closure is true.
- Layer separation is true.
- Non-diagonal coupling is true.
- Applied-rejected matrix is true.
- Comparison performed is false.
- Upper-start condition is true.

Recorded restriction:

Upper-envelope starts and candidate counterexamples require constructive reachability validation; GrammarStateAndEvent remains NOT_EVALUABLE.

Seal manifest record:

- Manifest byte count: 4170.
- SHA-256 of the seal manifest equals the G5 root hash.

Operational boundary recorded by the protocol:

- Future-test grammar is recorded as prefix-closed.
- The empty prefix is included.
- Rejection and coupling interfaces are exact at the fixture boundary.
- No comparison of real histories is performed.

### G6 — fiberwise equivalence contract

**Receipt:** g6-behavioral-equivalence/seal/G6_ROOT_RECEIPT.json  
**Root:** cf282d195f90e1ee970b7c5d57329c901848d7894f4ed8c5945755d3935633dd  
**Schema:** G6_ROOT_RECEIPT_V1

Recorded facts:

- Status is SEALED.
- Question is CLOSED.
- Disposition is ADVANCE_WITH_RESTRICTION.
- Result string is FIBERWISE_BEHAVIORAL_EQUIVALENCE_CONTRACT_SEALED.
- Observable rule count is 23.
- Relation scope is FIBERWISE.
- Reflexivity is PROVEN_WITHIN_FIBER.
- Symmetry is PROVEN_WITHIN_FIBER.
- Transitivity is PROVEN_WITHIN_FIBER.
- Real-pair claim count is 0.
- Outcome access values are all zero.
- G6_QUALIFICATION_RECEIPT_V1 reports PASS.
- Fixture count is 45.
- Fixture failures are 0.
- Relation-law derivation count is 7.
- Real-history-pairs-inspected count is 0.

Seal manifest record:

- Manifest byte count: 5659.
- SHA-256 of the seal manifest equals the G6 root hash.

Operational boundary recorded by the protocol:

- The comparison contract is frozen for the declared record set.
- The three relation-law checks are limited to the declared fiber scope.
- No real pair search is performed.

### G7 — formal analysis boundary

**Receipt:** g7-formal-analysis-boundary/seal/G7_ROOT_RECEIPT.json  
**Root:** 069a5294c37a6fbede436af2f57700964ce1e752643aeaa26b06de6581183bd5  
**Schema:** G7_ROOT_RECEIPT_V1

Recorded facts:

- Status is SEALED.
- Question is CLOSED.
- Disposition is ADVANCE_WITH_RESTRICTION.
- Result string is FORMAL_ANALYSIS_BOUNDARY_SEALED_WITH_RESTRICTIONS.
- Required-property count is 6.
- Real-pair search count is 0.
- Production-judge authority is false.
- Outcome access values are all zero.
- G7_QUALIFICATION_RECEIPT_V1 reports PASS.
- Fixture count is 28.
- Fixture failures are 0.
- Machinery-permission-record count is 6.
- Production judges built count is 0.
- Real-history-pairs-inspected count is 0.
- Unique problem-signature count is 6.

Seal manifest record:

- Manifest byte count: 5405.
- SHA-256 of the seal manifest equals the G7 root hash.

Operational boundary recorded by the protocol:

- Six required properties have a sealed analysis boundary.
- Each required property has a unique recorded problem signature.
- No production judge is constructed.
- No real pair search is performed.

### G8 — witness laboratory qualification

**Receipt:** g8-witness-laboratory-qualification/seal/G8_ROOT_RECEIPT.json  
**Root:** 556cba86bf75a76d67c411db5a62229cb35ec84c92bd0bfbb6fd086971496ece  
**Schema:** G8_ROOT_RECEIPT_V1

Recorded facts:

- Status is SEALED.
- Question is CLOSED.
- Disposition is ADVANCE_WITH_RESTRICTION.
- Result string is WITNESS_LABORATORY_QUALIFIED_WITH_RESTRICTIONS.
- Global-equivalence-decider flag is false.
- Observer-quotient flag is false.
- Global-minimality flag is false.
- Real-04A-pair-claim count is 0.
- Real-04A-read count is 0.
- Outcome access values are all zero.
- G8_QUALIFICATION_RECEIPT_V1 reports PASS.
- Fixture count is 31.
- Fixture failures are 0.
- Independent build is required.
- Oracle imports verifier is false.
- Verifier imports explorer is false.

Seal manifest record:

- Manifest byte count: 6652.
- SHA-256 of the seal manifest equals the G8 root hash.

Operational boundary recorded by the protocol:

- The laboratory is qualified on supplied fixtures and formally bounded inputs.
- Explorer and verifier dependencies are separated in the receipt.
- No real 04A read or real-pair claim is present.
- No global claim is added by this gate.

## 5. Cross-gate integrity checks

The following checks were performed without opening outcome-bearing contents:

| Check | Result |
|---|---|
| G0–G8 seal receipts present | PASS |
| G0–G8 questions closed | PASS |
| Final seal manifest hashes equal recorded roots | PASS |
| G0–G8 gate directories present | PASS |
| G9 directory present | NOT FOUND |
| G6 real-history-pairs-inspected | 0 |
| G7 real-history-pairs-inspected | 0 |
| G8 real-04A-reads | 0 |
| G8 real-04A-pair-claims | 0 |
| G7 production judges built | 0 |
| G8 global-equivalence-decider | false |
| G8 global-minimality | false |
| G4 declared blind spots | 1 |
| G3 exact global reachability | false |
| G5 fixture failures | 0 |
| G6 fixture failures | 0 |
| G7 fixture failures | 0 |
| G8 fixture failures | 0 |

The final seal manifest file counts observed in the seal trees are:

| Gate | Seal-tree file count | Manifest bytes |
|---|---:|---:|
| G0 | 23 | 2175 |
| G1 | 36 | 3582 |
| G2 | 34 | 3307 |
| G3 | 35 | 3514 |
| G4 | 33 | 3311 |
| G5 | 40 | 4170 |
| G6 | 53 | 5659 |
| G7 | 51 | 5405 |
| G8 | 62 | 6652 |
| Total | 367 | — |

Protocol copies exist at each gate source, build-a, build-b, and seal location. The source protocol names are:

- OBS_OPEN_G0_PROTOCOL_V1.md
- OBS_OPEN_G1_PROTOCOL_V1.md
- OBS_OPEN_G2_PROTOCOL_V1.md
- OBS_OPEN_G3_PROTOCOL_V1.md
- OBS_OPEN_G4_PROTOCOL_V1.md
- OBS_OPEN_G5_PROTOCOL_V1.md
- OBS_OPEN_G6_PROTOCOL_V1.md
- OBS_OPEN_G7_PROTOCOL_V1.md
- OBS_OPEN_G8_PROTOCOL_V1.md

## 6. Central Northstar repository status

**Repository:** C:/code land/northstar-singular-authority  
**Remote authority:** KittClouds/northstar  
**Branch:** codex/northstar-singular-authority-v1  
**Observed branch relation:** ahead 5, behind 52  
**Observed local state:** modified documentation/code and untracked CSV implementation files; preserve as user work.

### 6.1 Authority records

| Record | Value |
|---|---|
| scientific root | 48102bd529abf01591842f85676b86eb66b0600dc8d702bd0dbb3d6b729b4c41 |
| fossil commit | aa12e457667a496188852ae7b7ed8d37990b15b7 |
| fossil tag | northstar-obs-open-04a-48102bd529ab |
| repository authority document | docs/NORTHSTAR_SINGULAR_AUTHORITY.md |
| local changes | present; not cleaned or reverted |
| unrelated running application | left untouched |

### 6.2 Data-plane implementation records

The central repository contains the following recorded data path:

provider bytes → L0 receipt → decoder → L1 canonical batch → durable commit → live/replay batch → L2 deterministic processors → immutable GPUI snapshots

Recorded implementation details:

- Raw receipts retain payload hashes, CRC, and BLAKE3 values.
- The journal uses fixed-layout records and a single-writer publication path.
- Durable storage and memory-mapped read access are present in the documented foundation.
- Replay and snapshot surfaces are present in the documented foundation.
- The fixture-backed prototype remains separate from the fixture-free operating surface.
- Missing authorities are rendered as missing; no substitute values are silently inserted.

### 6.3 Ledger records

docs/DURABLE_LEDGER.md records Ledger V1 as an append-only local record with:

- 176-byte hot header.
- Checksummed cold body.
- One-writer publication.
- Durable commit and recovery.
- Memory-mapped read view.
- Bounded immutable LedgerSnapshot.
- Automatic entries and operator entries.
- Attachments listed as later work.

### 6.4 Official source documentation

docs/OFFICIAL_MACRO_RUNTIME.md records operating adapters for:

- BLS.
- BLS calendar.
- BEA.
- Census.
- FRED.
- CFTC.
- Eurostat.
- ECB.
- ONS.
- Bank of England.
- Bank of Japan.

The document records:

- Raw receipts.
- Decoders.
- Canonical journal publication.
- Deterministic MacroSnapshot generation.
- GPUI notification delivery.
- e-Stat as credential-gated and not configured until the application ID, table, and dimension contracts exist.

### 6.5 HeroFX and TradeLocker data boundary

docs/HERO_FX_VENUE_DATA_PLAN.md and docs/TRADELOCKER_HEROFX_ACTIVATION_AUDIT_2026-08-11.md record:

- Desktop account and schema verified.
- HeroFX LIVE desktop environment observed.
- REST capability verified at the contract level.
- REST payload capture remains open.
- Typed decoders remain open.
- Coherent publication remains open.
- Durable-retention rights review remains open.
- MT5 bridge remains deferred.
- The captured desktop observation was read-only.
- The account was empty during the observation; schema and navigation were the parts verified.
- Candidate index symbols were observed, but IDs, tick units, lot units, and session metadata were not frozen.

### 6.6 Massive data boundary

docs/MASSIVE_ENTITLEMENT_AUDIT_2026-08-10.md records a fail-closed entitlement result:

- Supplied credential was valid.
- Reference catalog and entitled historical aggregates were available.
- The indices snapshot endpoint was not entitled.
- Individual terms included display-only or rights restrictions.
- Bearer check passed.
- MCP call was available.
- Ticker checks passed.
- I:NDX daily and minute aggregates were available.
- I:BDE40P and I:BUK100P were not entitled.
- A rate limit was observed.
- Massive is not active authority under the recorded contract.
- Durable publication and retention remain gated by rights.

### 6.7 Structural data records

docs/STRUCTURAL_MARKET_STATE_RUNTIME.md records a Phase II-B warm surface with:

- Compact identifiers.
- Reference and venue price-unit records.
- Level and band records.
- LevelBook storage.
- Session high/low records.
- Five extreme records.
- Opening-range records.
- Rolling-range records.
- Node merge and genealogy records.
- Corridor records.
- Fast location lookup.
- Chart snapshots.
- BLAKE3 fingerprints.
- Explicit unavailable-volume states.

The document records that no venue feed has been admitted to this surface yet, REST is not admitted, and the MT5 bridge is deferred.

### 6.8 Chart and page documentation

docs/NATIVE_CHART_ENGINE.md records:

- Lumen study notes retained as reference material.
- A GPUI-specific canvas contract.
- Chart interaction records.
- Presentation-only rendering boundaries.
- Next chart milestones.

docs/NORTHSTAR_OFFICE_DESIGN_V2.md records:

- Calm dark graphite base.
- Precise mint for healthy/current data.
- Warning amber for attention states.
- Rare coral for material faults.
- Dense, quiet panels with explicit provenance.

docs/PAGE_BLUEPRINTS_V2.md records page ownership for Desk, Macro, Fund, Systems, and Ledger, with acceptance contracts and an implementation roadmap.

docs/REAL_DATA_FRONTEND_AND_LEDGER_PLAN.md records:

- The seam audit from source adapters to page snapshots.
- Authority tables.
- Snapshot contracts.
- Placeholder replacement work.
- Automatic and operator ledger entries.
- Append-only record rules.
- A seven-slice implementation sequence.
- Verification gates for the point at which pages are fed by real records.

## 7. Markdown report inventory

The central repository currently contains 18 Markdown files under docs. The relevant records are:

| File | Recorded subject | Current use in this report |
|---|---|---|
| CANONICAL_DATA_PLANE.md | canonical source-to-snapshot path | data path and storage status |
| CORE_ARCHITECTURE.md | frozen boundaries and later integration seam | authority split |
| DURABLE_LEDGER.md | append-only durable Ledger V1 | ledger state |
| GLOBAL_MACRO_SYSTEM_PLAN.md | global source coverage and provenance plan | source inventory |
| HERO_FX_VENUE_DATA_PLAN.md | HeroFX source boundary | venue data status |
| MACRO_DATA_SPINE.md | regional source spine | official source coverage |
| MASSIVE_ENTITLEMENT_AUDIT_2026-08-10.md | entitlement evidence | current Massive boundary |
| MASSIVE_REAL_DATA_RUNTIME.md | runtime capture and retention boundary | data-runtime follow-up |
| NATIVE_CHART_ENGINE.md | GPUI chart surface | presentation record |
| NORTHSTAR_OFFICE_DESIGN_V2.md | page visual system | UI record |
| NORTHSTAR_SINGULAR_AUTHORITY.md | repository authority and lineage | repository record |
| OFFICIAL_MACRO_RUNTIME.md | official adapters and publication | source runtime status |
| PAGE_BLUEPRINTS_V2.md | page ownership and contracts | page inventory |
| PROTOTYPE_CONTRACT.md | mode and acceptance records | prototype boundary |
| REAL_DATA_FRONTEND_AND_LEDGER_PLAN.md | source-to-frontend and ledger work | active implementation plan |
| STRUCTURAL_MARKET_STATE_RUNTIME.md | warm structural data surface | structural data status |
| TRADELOCKER_HEROFX_ACTIVATION_AUDIT_2026-08-11.md | read-only desktop audit | venue status |
| TRADELOCKER_READ_ONLY_ACTIVATION.md | authenticated read-only REST contract | next venue data work |

## 8. Completed work

The following work is evidenced by the sealed receipts and repository files:

1. The G0 input bridge was sealed with fossil-root verification and integer-unit/nanosecond storage evidence.
2. The G1 deterministic kernel was extracted from the authorized 154-session, 57,500-bar population.
3. The G2 graph and role census was sealed with 73 nodes, 117 edges, 57 elements, and zero dangling edges.
4. The G3 reachable-envelope record was sealed with 16 constructive witnesses, 22 joint constraints, and 9 recorded absence claims, with restrictions retained.
5. The G4 protected-observable surface was sealed with 23 protected observables and one declared blind spot.
6. The G5 fixture grammar was sealed with 24 fixtures and zero fixture failures.
7. The G6 comparison contract was sealed with 23 observable rules, 45 fixtures, zero fixture failures, and no real-pair reads.
8. The G7 analysis boundary was sealed with six required properties, 28 fixtures, zero fixture failures, and no production judge.
9. The G8 laboratory was qualified with 31 fixtures, zero fixture failures, independent-build separation, and zero real-04A reads.
10. The central Northstar repository has a documented singular-authority record, fossil record, data-plane record, ledger record, official-source record, venue boundary record, and UI/page record.
11. The central data plane has raw receipts, canonical batches, durable publication, replay/snapshot surfaces, and immutable GPUI snapshot records in the documented foundation.
12. The official-source runtime has provider adapters recorded for the US, Europe, UK, and Japan source families listed in the repository documentation.
13. The HeroFX desktop data boundary has been observed read-only, while REST capture and typed decoding remain open.
14. The Massive entitlement boundary has been recorded fail-closed.

## 9. Current gaps and open records

These are present-tense gaps recorded by the receipts or repository documents:

- G9 has no directory, protocol, build, qualification receipt, or seal.
- G10 through G12 have no gate artifacts in this compound root.
- G3 does not record exact global reachability.
- G4 carries one declared NOT_EVALUABLE blind spot.
- G5 keeps upper starts conditional on constructive reachability validation.
- G6 has no real-history pair search.
- G7 has no production judge and no real-history pair search.
- G8 has no global decider, no quotient record, no global minimality record, no real-04A read, and no real-04A pair claim.
- e-Stat requires an application ID, exact table contract, and dimension contract.
- HeroFX REST payload capture remains open.
- HeroFX typed decoders remain open.
- HeroFX coherent publication remains open.
- Durable-retention rights remain open for the venue payload path.
- MT5 bridge work is deferred.
- Massive rights and entitlement restrictions prevent it from being active authority under the recorded contract.
- Two index families named in the Massive audit are not entitled under the observed account contract.
- Structural data has no admitted venue feed.
- Ledger attachments are later work.
- Central branch synchronization requires an audit because the local branch is ahead 5 and behind 52.
- Central CSV implementation files are present as local work and must be preserved.

## 10. Paused point

The verified stopping point is:

G8 seal present → G8 restrictions retained → no G9 artifact → work paused before G9.

No G9 result, count, root, or disposition is inferred.

## 11. Next work sequence

The next sequence is documentation/data preparation only:

### 11.1 G9 preflight

1. Create a G9 preflight directory beside g0 through g8.
2. Record the exact G8 root as the parent input.
3. Record an input manifest with file names, byte counts, and hashes.
4. Record source exclusions before any read beyond the declared receipt fields.
5. Record output file names and receipt schema before generation.
6. Record the stop conditions and the absence-result policy.
7. Do not create a G9 seal until the preflight record is reviewed.

### 11.2 Northstar data plane

1. Keep source bytes, receipt records, decoded batches, durable commits, and published snapshots as separate file classes.
2. Complete the canonical CSV source-contract path with explicit columns, timestamp fields, unit fields, ordering rules, duplicate rules, and stable admission results.
3. Keep event time and knowledge time as separate fields in every admitted record.
4. Preserve raw CSV bytes and source-contract hashes beside compiled canonical records.
5. Keep rejected and quarantined records separate from admitted records.
6. Add Rust and Python decode fixtures for exact integer units and nanosecond timestamps.
7. Add replay fixtures that compare decoded tuples and publication roots.

### 11.3 Official-source data

1. Finish the remaining official release/document provenance records.
2. Add the missing e-Stat credential and table/dimension contracts when available.
3. Keep source receipts, revisions, release times, and publication sequence values visible on the Macro page.
4. Publish replay-safe MacroSnapshot records into the Desk page.
5. Keep missing or late families explicitly marked; do not fill them with substitute values.

### 11.4 HeroFX and TradeLocker data

1. Capture one sanitized authenticated REST read-only epoch after rights review.
2. Store the raw response hash and account-scope metadata without retaining credentials.
3. Freeze endpoint-to-record mappings in typed decoder receipts.
4. Publish a coherent read-only snapshot only after all required records share one epoch.
5. Preserve prior published data if a new capture is partial, stale, malformed, or unauthorized.
6. Leave MT5 bridge work deferred until its separate boundary is approved.

### 11.5 Frontend and ledger

1. Replace fixture-only page records with immutable snapshot subscriptions.
2. Show source, receipt time, publication sequence, freshness, and missingness on every data panel.
3. Connect the Ledger page to the append-only record stream.
4. Keep automatic entries and operator entries distinct but queryable in one read view.
5. Add durable ledger body attachments only after the current header/body contract is tested.
6. Re-run UI snapshots against real canonical records, not duplicated page-local values.

## 12. Exit conditions for the next report

The next update should not be called complete until it can show:

- A G9 preflight receipt with a declared parent root.
- A complete G9 input manifest.
- A binary G9 status or an explicit blocked status.
- No unrecorded reads of excluded material.
- Canonical data records reaching the frontend through the documented snapshot path.
- Official-source provenance visible in the published records.
- Venue data status separated into verified, pending, deferred, and rights-gated fields.
- Ledger records showing durable automatic and operator entries.
- A clean distinction between fixture-backed values and admitted source values.

## 13. Final state statement

As of 2026-08-16, the compound contains sealed G0–G8 artifacts with closed questions, root hashes, content manifests, qualification receipts, and retained restrictions. The next gate has not started. Northstar’s central repository contains the documented canonical data plane, official-source runtime, venue boundary records, ledger records, chart records, and page records, with the open items listed above. No additional result is claimed by this report.
