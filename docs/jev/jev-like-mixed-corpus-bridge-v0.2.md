# Jev-like Mixed Corpus Bridge v0.2

Status: research implementation specification. The v1 semantic contract remains
frozen. This bridge adds typed probability-source metadata, runtime candidate
definitions, controlled synthetic span/relation records, independently audited
real-data adapters, lineage, overlap reports, and provisional split manifests.

It does not train models, mutate Phoenix datasets, or convert synthetic-control
records into Phoenix authority.

## 1. Bridge invariant

The mixed corpus is a typed composition, not an undifferentiated table:

```text
exact synthetic posterior
hard external label
human disagreement distribution
OOS / abstention label
span/type annotation
relation/evidence annotation
        ↓ source-specific normalization
jev-like-decision-dataset/v1
        ↓ typed census and split manifest
mixed research corpus
```

Every normalized record retains both authority and probability-source metadata.
The bridge never turns a hard label into a probability, never treats absent
relation evidence as a negative relation without source authorization, and
never treats an aggregate wrapper as an independent upstream corpus.

## 2. Contract compatibility boundary

The existing v1 contract already has fields for runtime candidates, span/type
targets, relation targets, evidence links, authority records, and source
lineage. The bridge uses those fields without changing their semantics.

Two controlled extensions are proposed, not silently adopted:

* `E01`: `structured_state` for pre-render entity and relation records with
  explicit offset units. This is needed when a source exposes entity identity
  before rendering but v1 only retains the post-render span target.
* `E02`: typed `probability_source` metadata and optional raw label counts.
  v1 can carry numerical targets, but does not by itself say whether a number
  is a world posterior, human vote frequency, subjective report, hard label,
  weak score, or no probability. That distinction is required for mixed-corpus
  calibration claims.

Episodes carrying E01, E02, or both are marked with the corresponding proposed
status and are excluded from a strict v1-only manifest until the extension is
accepted. No source is coerced into v1-compatible semantics by dropping these
fields.

## 3. Runtime candidate definitions

Every adapter may emit candidate definitions with:

```text
candidate_id                    local ID exposed in this episode
candidate_semantic_id           stable meaning/alignment ID
human-readable name             optional surface name
description                    optional natural-language criterion
aliases                        optional equivalent names
opaque_id                      optional opaque surface ID
parent_candidate_semantic_id   optional hierarchy edge
order_rank                     optional ordinal rank
mutually_exclusive_group_id    optional exclusive group
independent_allowed            whether independent applicability is legal
```

Presentation profiles are explicit:

```text
semantic_name_only
name_plus_definition
opaque_id_plus_definition
opaque_id_only
```

Equivalent-definition rename, opaque-ID substitution, and candidate reorder
are semantic interventions with strict invariance after alignment. Description
removal is not invariant unless the source task supplies a self-identifying
label inventory or the query explicitly declares the candidates opaque.

## 4. Structured synthetic substrate

Synthetic structured episodes create entities and semantic facts before text:

```text
Entity(person_17, type=person, name=Mara)
Entity(credential_3, type=credential, name=audit key)
Entity(system_4, type=system, name=Orion)

possesses(person_17, credential_3)
belongs_to(credential_3, system_4)
```

Renderers then generate controlled text and canonical contiguous mention
offsets. v0.2 restricts these episodes to non-overlapping contiguous mentions,
with one or more mentions per entity and exact round-trip offsets.

Relations are semantic records before rendering:

```text
relation_instance_id
relation_semantic_id
head_entity_id
tail_entity_id
direction
polarity: holds | does_not_hold | unknown
```

The relation polarity is three-state. An unmentioned relation is `unknown`,
not `does_not_hold`, unless the source explicitly annotates a negative.
Syntactic voice or argument order may change across renderers while the
semantic relation direction remains aligned.

## 5. Source adapters

Each source has an independent parser and transformation chain:

```text
source row
  → source-specific parser
  → semantic normalization
  → canonical Episode
  → bridge verifier
```

Initial adapters:

| Source | First supported view | Probability source | Boundary |
| --- | --- | --- | --- |
| `sr5434/multitask-classification-dataset` | schema-conditioned hard choice | `hard_label` | conditional: missing license/provenance review |
| `tasksource/zero-shot-label-nli` | source-preserving NLI hard label | `hard_label` | audit-only aggregate; upstream overlap quarantine |
| ChaosNLI | NLI human distribution | `empirical_annotator_distribution` | external GitHub/Dropbox snapshot must be pinned |
| GoEmotions raw | independent applicability and human distribution | `empirical_annotator_distribution` | group rows by source item ID |
| CLINC OOS | hard intent and explicit OOS/abstention | `hard_label` | source license and label inventory require pinned audit |
| MASSIVE | hard intent plus span/type | `hard_label` | slot offsets derived from annotated utterance |
| DocRED | relation plus evidence | `hard_label` or `weak_score` | annotated and distant splits remain separate |

Unsupported or ambiguous source semantics remain quarantined. The adapter may
emit a source profile without emitting episodes.

## 6. Human disagreement

When individual annotations exist, the normalized record retains source-scoped
anonymous rater references when permitted, raw label counts, frequencies,
entropy, and annotator count. The empirical distribution is reproducible from
the counts. Annotator identity is not invented when the source does not expose
it.

The bridge reports human disagreement separately from synthetic posterior
uncertainty and elicited subjective probability.

## 7. Lineage and overlap

Every accepted row carries:

```text
source_dataset_id
source_revision
source_split
source_row_id
upstream_dataset_id
upstream_row_id when known
adapter_id
adapter_revision
transformation_chain
authority_record_id
```

The overlap audit computes exact-text hashes, normalized-text hashes, semantic
fingerprints where available, and lineage intersections. It reports conflicts
without automatically deleting them. Aggregate sources are not independent
from an upstream corpus merely because their repository IDs differ.

## 8. Provisional splits

No random row split is primary. Sibling perturbations and all known upstream
instances stay in one partition. The bridge emits named manifests for:

```text
in_distribution_validation
surface_ood
schema_ood
candidate_ood
world_ood
domain_ood
human_uncertainty_eval
synthetic_calibration_eval
abstention_eval
span_relation_eval
```

Rows with unresolved lineage are not eligible for a benchmark split.

## 9. Semantic census

The census stratifies at least:

```text
episode/query/view counts
authority classes
probability-source classes
candidate cardinality
state/schema lengths
hard/soft target proportions
entropy by probability source
OOS prevalence
multi-label density
span/relation/evidence-link density
renderer representation
domain family
```

The manifest stores mixture weights independently from physical files. Initial
weights are descriptive only; they are not training prescriptions.

## 10. Acceptance gates

Synthetic gates:

```text
10k+ v0 episodes still validate
candidate-alignment interventions verify
span offsets round-trip exactly
relation endpoint IDs survive renderer changes
world/evidence interventions recompute gold
```

External-source gates:

```text
100% of normalized rows pass validation
100% retain source lineage
hard labels remain hard labels
unknown relation status is not coerced to false
OOS is not silently normalized into a closed set
```

Mixed-corpus gates are report-based: semantic coverage, authority coverage,
probability-source coverage, overlap, leakage, cardinality, and entropy reports
must exist before training is considered.

## 11. First research question

The bridge is successful if exact synthetic decisions, hard external labels,
human disagreement, abstention, spans, and relations coexist under one
architecture-neutral contract while preserving their distinct meanings of truth
and probability. Similar numeric vectors are not evidence that the underlying
uncertainties are the same.
