# Jev-like Probability-Source Taxonomy v0.1

Status: proposed E02 adapter metadata for the mixed-corpus bridge. This
taxonomy does not silently change the frozen v1 gold contract and does not
authorize training.

Authority answers “who or what may be trusted for this target?” Probability
source answers “what does a probability-like value mean?” They are separate
axes. Two `externally_annotated` targets may have different probability
semantics, and a `synthetic_control` target may have a mathematically exact
posterior without being Phoenix-authoritative.

## Required values

| Probability source | Meaning | Canonical probability allowed? |
| --- | --- | --- |
| `exact_generative_posterior` | Probability calculated from a frozen synthetic world and visible evidence | Yes |
| `empirical_annotator_distribution` | Frequency distribution of retained human annotations for one item | Yes, as human-disagreement probability |
| `elicited_subjective_probability` | A probability directly reported by a person or source instrument | Yes, but not as world posterior |
| `adjudicated_distribution` | Distribution produced by a declared adjudication process | Yes, with process metadata |
| `hard_label` | A categorical label with no calibrated probability claim | No probability field may be inferred |
| `weak_score` | Heuristic, distant, programmatic, or model-assisted signal | Only as a typed weak score, never primary calibration gold |
| `no_probability` | Source supplies neither a probability nor an admissible score | No |

`hard_label` is not `probability = 1.0`. A training adapter may create a
one-hot optimization target, but that derived representation must remain
outside the canonical semantic record and retain a transformation link to the
hard source label.

## Metadata fields

When applicable, every probability-source record stores:

```text
probability_source
sample_count
annotator_count
raw_label_counts when the source exposes countable labels
aggregation_method
normalization_scope
distribution_interpretation
```

Recommended values include:

```text
aggregation_method:
  exact_factorization
  normalized_vote_counts
  majority_vote
  adjudicator_protocol
  elicitation_instrument
  distant_supervision
  heuristic_rule

normalization_scope:
  supplied_candidate_set
  declared_label_inventory
  annotator_label_inventory
  ordinal_scale
  none

distribution_interpretation:
  world_posterior
  human_opinion_frequency
  reported_subjective_belief
  adjudicated_belief
  not_applicable
```

## Mixing policy

Probability-source strata must remain visible in manifests, census reports,
calibration plots, and split manifests. The following are not interchangeable:

```text
P_world(y | evidence)
P_human(y | item)
P_subjective(y | reporter, item)
```

They may be sampled together for a mixed-corpus experiment, but each target
retains its source tag and every metric must declare which strata it covers.
No aggregate entropy histogram may silently pool these meanings.

## Authority interaction

The default bridge mapping is:

```text
synthetic_control + exact_generative_posterior
externally_annotated + empirical_annotator_distribution
externally_annotated + hard_label
adjudicated + adjudicated_distribution
weak + weak_score or no_probability
```

These are defaults, not inference rules. The source adapter must record the
actual source protocol and refuse a row when the mapping is ambiguous.

## Validation rules

The bridge verifier rejects:

- a probability vector with no declared source;
- an empirical distribution whose retained counts do not sum to its annotator count;
- a hard label carrying a fabricated probability;
- an annotator distribution whose counts do not reproduce its frequencies;
- an exact posterior whose normalization scope is absent;
- weak or distant supervision promoted to primary calibration gold;
- a mixed target whose source lineage is missing;
- a source adapter that changes a hard task into an applicability task without
  a declared derived-view transformation.
