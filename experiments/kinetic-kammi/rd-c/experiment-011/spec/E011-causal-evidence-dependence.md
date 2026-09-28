# R&D-C / Experiment 011 — Causal Evidence Dependence

## Question

Under the frozen E009 v5 observer bundles and E010 switchboard contract, do proposal, applicability, and abstention respond to task evidence, repository identity, and candidate presentation?

This is a diagnostic intervention on the already-scored E010 bank. It does not establish broad transfer, a causal mechanism inside either model, or a new task-completion estimate on independent tasks.

## Frozen items

- Small and large model bundle IDs, runtimes, chat templates, output schema, system prompt, and normalization are inherited unchanged from E010.
- Routing thresholds remain minimum applicability 850/1000 and maximum abstention 150/1000.
- Routing remains small first; the large observer is used only when the small proposal does not pass the frozen contract.
- The same E010 task frames, candidate patches, completion labels, authority definition, and paired repository split are used.
- No fitting, threshold adjustment, prompt editing, or model calls to select transformations.
- E010 labels and observer outputs were already opened. E011 is a same-bank explanatory diagnostic, not an independent held-out evaluation.
- All E011 model calls are shadow-only. No action is executed. E010's authority and replay result remains the execution control.

## Paired conditions

The E010 full frame is the reference condition. For each of its 16 tasks, both observers receive each of these four single-factor interventions:

1. **Evidence masked:** retain evidence item count and kind, replace source identities and evidence bodies with neutral values. Keep the task prompt, repository context, candidates, and formatting.
2. **Evidence swapped:** retain the task prompt, repository context, and candidates, but replace evidence with evidence from the next task family in the same repository and prompt variant. Donors are assigned by sorted family order and a cyclic shift, fixed before model contact.
3. **Repository neutralized:** retain task wording, evidence content, and candidates; neutralize repository/task IDs, revision/hash metadata, and exact repository-name strings. Task-family IDs are renamed to stable anonymous family labels. This removes direct identity tokens while preserving code, failures, and candidate diffs.
4. **Candidate permuted:** preserve every candidate's content and patch digest, but reorder the candidates and replace all numeric action IDs with deterministic fresh IDs. Score outputs by the option's patch digest, not by displayed position or ID.

The interventions are separate. They do not combine masking, swapping, identity removal, or candidate permutation.

## Analysis

For each observer, condition, and repository, report:

- Direct-action coverage under frozen 850/150 thresholds.
- Direct-action precision against the existing candidate completion labels.
- Applicability and abstention score changes from the paired full-frame result.
- Proposal change rate, abstention change rate, and whether changes follow the intervention.
- Hybrid completion, always-large completion, small direct completions, and large calls displaced, computed as shadow counterfactuals only.
- E010 full-frame complementarity: P(small correct | large wrong), P(large correct | small abstains or is wrong), reported per repository and pooled.
- Exact paired counts alongside percentages.

Keep repository-level tables separate. Pooled totals are descriptive. Do not characterize counterfactual label scoring as executed task success.

## Interpretation boundary

A change after evidence masking or swapping shows sensitivity to the edited input surface on this bank. No change does not prove the model ignored evidence: the task prompt and candidate diffs can carry overlapping information. Repository-neutralization is limited to the stated metadata and direct name substitutions. Candidate permutation tests order and numeric-ID sensitivity under this frame serializer. Any observed pattern is an engineering diagnostic for the frozen switchboard, not mechanistic evidence.

## Run identity

Run ID: `e011-20260925-causal-evidence-01`.

A pre-model lock records exact input, prompt, schema, bundle, threshold, transformation, and E010 baseline output hashes. The bank and labels are copied byte-for-byte from E010 and remain traceable to its original locks.
