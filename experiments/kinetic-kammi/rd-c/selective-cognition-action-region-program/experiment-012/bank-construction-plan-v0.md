# E012 bank construction plan v0

This is a construction contract, not a task bank. No task fixtures or model outputs are included here.

## Required bank shape

- At least 48 tasks, 12 independently constructed task families, and 3 repositories not used as evaluation repositories in E009, E010, or E011.
- At least two families for each preregistered support stratum and at least four tasks per family.
- Prefer three repositories with pinned immutable commits and Rust tasks, holding language constant while decomposition is measured. If a stratum cannot be created honestly in the available repositories, log the limit and version the protocol before task construction; do not pad it with paraphrases.
- Each task offers at least three candidates: at least two plausible alternatives when practical, plus at least one clearly rejectable or unchanged choice. The abstention-positive stratum contains tasks where no offered candidate is authorized by full-frame evidence.
- Each family has a hidden generator rule, a distinct behavior/regression, executable task check(s), a declared truth-support set, and paired worlds that verify which channels are necessary.

## Separated source fixtures

Store these under distinct directories with different reader permissions where practical:

```text
source/repositories/       immutable repository archives and build metadata
source/tasks/              hidden family construction records and source-channel payloads
source/candidates/         patch bytes, candidate IDs/roles, and application logs
source/outcomes/           completion checks and correct-action sets
frames/                    projected observer frames by preregistered condition
audit/                     leakage, dependency, and frame-diff reports
```

Candidate test fixtures must be computed before observer contact. `E_x` may contain only tests/logs produced on the unmodified base snapshot. Record patch-specific candidate test outcomes outside the model-visible frame.

## Deterministic assignment and audit

Freeze a bank-generation seed before assigning task IDs, candidate IDs, and producer coordinates. Candidate ID, candidate role, correctness, candidate length, position, repository code, family code, test count, and evidence-item count must be separately audited. Candidate position schedules are exactly balanced within dependency stratum and family; if a design block cannot balance, redesign the block. The coordinate control and donor map are generated at candidate construction, before ordinal assignment.

Before model contact, run and seal:

1. repository archive/revision and all source fixture hashes;
2. exact candidate test outcomes and task labels;
3. generator-derived `D_i` verification using paired counterfactuals;
4. channel-isolation check comparing full and treatment source records;
5. nuisance-only probes and a simple lexical baseline with family-grouped held-out splits;
6. producer-order restoration plus receipt/replay checks for every frame condition;
7. a manual audit that task wording, patches, logs, and metadata do not duplicate a hidden channel's truth cue.

Any failed audit blocks model contact. Repair occurs before freezing, and each failed attempt is preserved in its own sibling directory. No observer output, threshold response, or model preference may be used to choose families, edits, candidate ordering, or task inclusion.

## Reproducibility fields

The eventual precontact lock will include the exact protocol and projector hashes; bank-builder source and seed; repository commit and archive hashes; task/family manifest; channel source-tree hash; candidate patch hashes; completion-check source, commands, and logs; labels hash; every treatment-frame hash; presentation receipt/request IDs; model bundle/prompt/schema/runtime hashes; thresholds; and audit-script/output hashes. The precontact lock is created only after all audits pass.
