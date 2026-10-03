# Phase 6F — legality observability and identifiability

OBSERVABILITY_GAP_LOCALIZED

No models trained, no bank rows modified, protected evaluation unopened.
Canonical legality is positive/negative simulator preconditions, not permission.

| Population | Roots | Candidates | Directly witnessed ambiguous roots | Strict fully certified roots |
|---|---:|---:|---:|---:|
| DEV | 333 | 20789 | 140 (42.04%) | 1 |
| TRAIN | 1333 | 84636 | 598 (44.86%) | 3 |

## Interpretation

Byte-identical permitted-interface counterfactuals are direct non-identifiability witnesses within the pinned semantic/world domain. Each preserves conditional EXECUTE and is checked in both renderer families. They are private diagnostic alternatives, not newly sealed corpus rows, and do not establish their probability under the original seed generator.
The empirical bank ceilings and balanced counterfactual audit ceilings are reported separately. A 100% empirical ceiling in a unique-world sample does not establish observability. Conversely, the fraction with a witness is not an original-bank Bayesian accuracy ceiling.
Partition roots as VERIFIED_AMBIGUOUS, OBSERVABLE_RULE_CERTIFIED, and UNRESOLVED_NOT_CERTIFIED. Absence of a witness does not certify the third group. No Qwen capacity ceiling is inferred.

## Oracle and source tracing

The strict three-valued oracle uses active direct records plus pinned functional location/attribute semantics. Reports remain claims, never certainty. Missing predicates remain unknown; absent negative predicates are not silently false. The separately reported closed-graph oracle adds a recipe-level assumption only when the full population census finds no hidden graph facts or unrendered slot markers. That is an assumption-qualified reference, not additional text given to Qwen.
Semantic signatures retain full observable root context and candidate coordinates; entity names/bindings, direct records, report claims, emitted gates/policies/costs/query questions, goal prose/mentions, and public requests are traced to actual renderer consumption. Private relation registry IDs are excluded; emitted relation synonym pools are normalized, inverse wording remains distinct, and goal prose remains lexical where inversion is ambiguous. Semantic renderer differences are not automatically leaks or impossibility proofs. Exact interface witnesses retain raw full text, binding/goal information and deterministic type/argument coordinates.

## Detailed recorder

### DEV

Strict candidate coverage: 86.91%; certain-legal precision: 1.0; certain-illegal precision: 1.0.
Empirical exact-input full-set ceiling: 1.000000; gold-type-conditioned same-type ceiling: 1.000000.
Counterfactual augmented-sample full-set ceiling (NOT original bank): 0.704017; equal-root balanced-pair bound: 0.789790.
Counterfactual augmented-sample same-type ceiling (NOT original bank): 0.987315; same-type sets changed in 6 roots. First witness per root is not an exhaustive same-type ambiguity search.
Hidden predicates producing witnesses: {"AT":128,"HOLDS":6,"STATE":6}; selected labels flipped: 0.
Renderer recorder: {"changed_observable_sections":{"direct":26},"hidden_fact_policy_ordering_source":"fact-ID sorting; exact witness test rejects any changed text","no_legality_clause_truth_inferred_from_renderer_metadata":true,"non_REL_semantic_changes":0,"oracle_status_changes":0,"raw_input_changes":333,"relation_phrase_source_private_id_and_family":true,"semantic_class_changes":26}; failed paired proofs: 0.
Closed-graph qualification valid: True; qualified root count: 49.

### TRAIN

Strict candidate coverage: 87.48%; certain-legal precision: 1.0; certain-illegal precision: 1.0.
Empirical exact-input full-set ceiling: 1.000000; gold-type-conditioned same-type ceiling: 1.000000.
Counterfactual augmented-sample full-set ceiling (NOT original bank): 0.690316; equal-root balanced-pair bound: 0.775694.
Counterfactual augmented-sample same-type ceiling (NOT original bank): 0.980839; same-type sets changed in 37 roots. First witness per root is not an exhaustive same-type ambiguity search.
Hidden predicates producing witnesses: {"AT":533,"HOLDS":13,"STATE":52}; selected labels flipped: 0.
Renderer recorder: {"changed_observable_sections":{"direct":118},"hidden_fact_policy_ordering_source":"fact-ID sorting; exact witness test rejects any changed text","no_legality_clause_truth_inferred_from_renderer_metadata":true,"non_REL_semantic_changes":0,"oracle_status_changes":0,"raw_input_changes":1333,"relation_phrase_source_private_id_and_family":true,"semantic_class_changes":118}; failed paired proofs: 0.
Closed-graph qualification valid: True; qualified root count: 213.

Unknown-clause attribution (both renderings; clauses, not mutually exclusive candidate counts):

```json
{
  "DEV:multiple_unknown_clauses": 2986,
  "DEV:negative:BLOCKED": 2348,
  "DEV:positive:AT": 4914,
  "DEV:positive:CONTAINS": 90,
  "DEV:positive:HOLDS": 840,
  "DEV:positive:STATE": 554,
  "TRAIN:multiple_unknown_clauses": 12134,
  "TRAIN:negative:BLOCKED": 8900,
  "TRAIN:positive:AT": 19556,
  "TRAIN:positive:CONTAINS": 398,
  "TRAIN:positive:HOLDS": 3376,
  "TRAIN:positive:STATE": 2804
}
```

## Verification and limitations

Nine unit/positive-control tests include direct truth, unresolved absence, functional-slot contradiction, inactive schedules, candidate/root modal ceilings, real TRAIN renderer replay, a canonical hidden-only legality flip, metadata-key remapping and observable synonym normalization. Full fresh-process replay reconstructs every clause, signature, collision class, oracle status, partition and witness and compares canonical content.
The initial v01 pass is preserved. v02 repairs fact-ID dictionary-key remapping in private counterfactual acquisition-cost metadata, which previously caused censored KeyError attempts; successful v01 witnesses remain valid. The repair broadens search coverage, not corpus contents or scientific criteria. Instrument KeyError/ValueError now abort instead of silently censoring. See ENGINEERING-REPAIR-v02.json and source-v01/REPAIR-v02.md.
Renderer source audit finds relation wording depends on private relation ID and family, and query ordering sorts hidden fact IDs. These are observation-channel artifact/cue risks, not model capability. The recorder distinguishes remaining inverse relation wording from legality-relevant evidence changes. Byte-identical witnesses reject any ordering/text change.
This is a conservative bounded witness search, not exhaustive possible-world enumeration. Full-world signatures avoid falsely attributing omitted root context to the model. Root ceilings use whole legal vectors rather than multiplying candidate-level ceilings. Same-type ceilings condition on gold action type as a diagnostic only. No learned oracle or optional neural fit was performed.
All machine-readable denominators, source/input pins and output hashes accompany this report. Existing bridge/E, consequence, legality and LoRA artifacts remain unchanged.
