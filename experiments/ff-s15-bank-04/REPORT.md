# BANK-v4 construction report — 2026-10-03

**Qualified construction curriculum.** The seven-lane factory is implemented,
generated, replayed, regenerated and registered in Kammi Library. This qualifies
the controlled curriculum's mechanics; it is not a learned-model result, an
independent human scientific review, or a claim of general benchmark competence.

```text
SEED_SOURCE_INTAKE_COMPLETE=true
TYPED_EPISODE_SCHEMA_READY=true
SEVEN_LANE_FACTORY_READY=true
FULL_CORPUS_BUILD_COMPLETE=true
ALL_SERIALIZED_ROOT_REPLAY=PASS
FULL_CLEAN_RECONSTRUCTION=PASS
UNIT_AND_MUTANT_QUALIFICATION=PASS
OBSERVER_MODEL_CONTACT=false
EXTERNAL_RELEASED_ROWS_IMPORTED=0
V1_V3_ROWS_IMPORTED=0
TRANSFER_CONSTRUCTION_TRUTH_INSPECTED=true
UNTOUCHED_CONFIRMATION_ELIGIBLE=false
OS_ESCROW_QUALIFIED=false
```

## Actual bank

| Split | Families per lane | Seven-lane families | Typed roots | Views |
|---|---:|---:|---:|---:|
| TRAIN | 1,024 | 7,168 | 28,672 | 57,344 |
| DEV | 128 | 896 | 3,584 | 7,168 |
| TRANSFER | 128 | 896 | 3,584 | 7,168 |
| Total | 1,280 | 8,960 | 35,840 | 71,680 |

Four roots per family: full original, partial original, full truth sibling, partial
truth sibling. Two lossless views per root: canonical JSON and typed line records.
Keep the entire family together in training/evaluation splits and uncertainty
estimates. These are not 71,680 independent trials.

The actual policy mix is **20,883 ACT / 9,502 ASK / 5,455 ABSTAIN**. ACT supervision
is set-valued; only singleton optima have a selected-action target.

## Source intake and provenance

Public sources supply archetypes and schema lessons. All released instances remain
on the construction-reference side. Canonical rows are fresh deterministic worlds
and are adjudicated by executable local mechanics, not external answer strings.

| Source | Pinned revision | Card-declared license | Local archetype |
|---|---|---|---|
| [ACPBench](https://huggingface.co/datasets/ibm-research/acp_bench) | `05e5883d9afbcfa3bdc8f270cb345ef0b9526d4a` | CDLA permissive 2.0 | transport/key/door prerequisites |
| [Sokoban](https://huggingface.co/datasets/novastar111/s_v5_move_push) | `d3f025d852c0e4acc504906513e874467c7f58a5` | not declared | one-crate bounded move/push |
| [Sudoku](https://huggingface.co/datasets/yuruny/sudoku_state_transition_model_sft) | `e2fcf1abec68b2a9af5176338ff4f8c6dfde711e` | not declared | miniature 4x4 state transitions |
| [MATM](https://huggingface.co/datasets/toeunkim/matm-trajectories) | `d84d6454fc5fcc337e2527533f484b79cf6f0872` | Apache 2.0 | household state, timed heating |
| [tau trajectories](https://huggingface.co/datasets/AgentSuite/tau-bench-trajectories) | `382e57d1784b55c5155f4ef394ef48f1c747a287` | not declared | authenticated/eligible/consented refunds |
| [GraphOmni](https://huggingface.co/datasets/G-A-I/GraphOmni) | `e2cafbbf8df5ea37780bd88af288d7c23e3561cf` | MIT | weighted directed navigation |
| [ToolACE](https://huggingface.co/datasets/Team-ACE/ToolACE) | `6bda777c88d21e5a204703c1ee45597a8fa4f734` | Apache 2.0 | strict method and argument binding |

The dataset viewer's schema samples are **not revision-pinned** and are explicitly
marked as unpinned construction references. They do not enter any corpus rows.
Missing licenses fail closed for direct row redistribution/import. Cards, API
metadata and samples are retained in Library CAS, not published as training data.

v1/v3 contribute lessons, not legacy labels: preserve epistemic versus actual truth,
signed clauses, dense candidate contrasts, explicit masks and complete replay.
No generator model or frozen observer bundle was used.

## Teaching architecture

```text
finite world + typed operators
    -> causal single-slot truth intervention
    -> full / partial observable frames
    -> observed slots + dense clause / binding / legality / permission targets
    -> operator, actual, clock and timed effects
    -> goal delta + step distance + environmental cost + policy cost
    -> all justified optimal candidates / ASK / ABSTAIN
```

Each family reserves executable local alternatives and a causal missing-slot
witness. Near misses share supported clauses; producer order is frozen separately
from candidate identity. Operational cost variation is prospective, construction-
driven, and independent of model outcomes. Environmental legality and policy
permission are distinct coordinates. Search exhausts the bounded state space;
exceeding 4,096 states is a failure, never an unreachable label.

Partial canonical consequences, pairwise consequence coordinates and canonical
optimal membership are diagnostics, masked from ordinary supervised loading.
ASK requires different optima across admissible completions and no common justified
optimum. Full reveal resolves the requested slot; a latent plan can coexist with ASK.

The safe loader offers observation-to-grounding, gold-grounding-to-consequence,
gold-consequence-to-decision and integrated entry points. Future research must
register subset-fit, TRAIN growth/ceiling, saturation and gold-substitution controls
before retiring an architecture. The bank itself makes no such trial.

## Measured curriculum pressure

| Coordinate | Actual count |
|---|---:|
| Paired full-observation grounding changes | 8,960 families |
| Paired optimal action-set changes | 7,077 families |
| Roots with multiple optimal offered actions | 7,498 |
| Dense pairwise consequence records | 1,002,260 |
| Unresolved legality/permission candidate instances | 69,096 |
| Legal but forbidden candidate instances | 6,978 |
| Legal actions with unreachable successors | 22,526 |
| Roots offering WAIT | 35,840 |
| Roots where WAIT is optimal | 244 |

Partial pairwise records are explicitly masked. WAIT's timed effects are real in
household worlds; its legality alone never earns an optimal-action label.

## Executed qualification

- 11 unit/adversarial qualification tests PASS, including corrupt masks, targets,
  physical moves and Sudoku guards, safe-loader masking and timed WAIT.
- All 35,840 serialized roots replayed in a fresh process.
- Separate reference mechanics verified **914,352 transitions** over **234,216
  reachable-state instances**. Independent forward shortest paths matched reverse
  construction distances for **154,535 supervised/completion/successor queries**.
- Every renderer was round-tripped; full and partial public frames were compared
  to exact observation projections. Partial sibling frames and observable targets
  are identical despite changed latent truth.
- Candidate reversal recomputed the optimal sets and preserved them. All optimal
  candidates, singleton labels, grounding, permission, effects, costs and masks
  were checked.
- Clean regeneration reproduced all **84 corpus files plus BUILD.json**, byte for
  byte, from the frozen factory. Reproducibility is distinct from semantic review.
- Cross-split exact input overlap: **0**. Cross-split declared structural signature
  overlap: **0**. The signature includes cost/operator/state data; this is **not**
  a proof of zero graph-isomorphism or abstract task-template overlap.
- A separate serialized-text scan independently reproduced zero cross-split exact
  text overlap, 53,760 distinct texts and 17,920 intended duplicate occurrences.
- Within-split repeated input occurrences: **17,920**, exactly the intentionally
  identical partial sibling views. No additional literal repetition was detected.

The full initial build took approximately **126 seconds** on CPU, no GPU. Files
registered before the manifest were approximately **754.5 MB decimal**. No model
weights were produced or uploaded.

## Failures preserved and repaired

Early sacrificial checks rejected six Sudoku families because the verifier demanded
each guard's compared digit belong to that cell's restricted domain. A fixed cell
can legitimately be compared against another digit in a signed exclusion guard.
The verifier now checks the typed value universe and independently checks every
Sudoku peer. The failed smoke manifest remains at
`C:/phoenix-data/banks/BANK-v4-smoke-20261003-v03/BUILD.json`.

The completed production build has **zero exclusions/failures**; no task was replaced
after observer outcomes. The source contract's v01 is retained as history; v02 is
the effective, explicitly corrected contract.

## Identities and locations

- Release: `C:/phoenix-data/banks/BANK-v4-20261003-v01/`
- Frozen factory: `factory/` under that root; source and tools in
  `C:/code land/clean-rust/experiments/ff-s15-bank-04/`.
- Full regeneration: `C:/phoenix-data/banks/BANK-v4-reconstruction-20261003-v01/`.
- Evidence: `SOURCE-INTAKE.json`, `SOURCE-MANIFEST.json`, `BUILD.json`, `REPLAY.json`,
  `RECONSTRUCTION.json`, `CURRICULUM-AUDIT.json`, `QUALIFICATION.txt`, `RELEASE.json`
  `INDEPENDENT-SPLIT-AUDIT.json` and `LIBRARY-RECEIPT.json` in the release root.
- Release inventory root:
  `698413fe9d85684dc7c8466e056416a75ae7da112160ff5d5fe082e64ebe9f05`.
- Frozen factory root:
  `4a27b08c83b20d51432da844cc070eb194884574f7599e03cf406966e02f3c74`.
- Replay corpus-manifest root:
  `dc340da8fa9d23b59e35fdec6b1c9c4128298f0ef7feee8d186ba2cd01c773b3`.
- Library seal, **129 registered artifact members**:
  `sha256:66ed32b0e232a4aaf2a724864495d726d29ef6a4bba5d51970c526100c59aa6f`.
- Chief-owned workspace: `bank-v4-20261003-v01`.

## Claim boundaries

This is a finite typed curriculum for acquisition, consequences and decision seams.
It does not replicate full ACPBench, multi-crate Sokoban, 9x9 Sudoku, ALFWorld,
WebArena, customer APIs or every GraphOmni algorithm. The typed DSL and two clean
renderers do not demonstrate natural-language perception.

TRANSFER truth has been inspected during construction and replay. The bank is not
an untouched scientific confirmation bank, an E013 amendment, or an OS-qualified
truth escrow. Subsequent scientific confirmation needs a separately authorized fresh
bank and scoped Library access policy. Active Lexi/Frizz/Claudia/Lepori work was left
outside this construction. Model work remains a separate authorization.
