# E012 observer-frame projection v0

This mapping is part of the frozen E012 protocol. The canonical task/channel record is bank-side and never sent wholesale to a model. A single deterministic projector compiles each treatment into the existing E009 v5 input shape. The system prompt, output schema, normalizer, and serializer stay fixed.

| Canonical field | Frozen observer frame field | Channel / rule |
| --- | --- | --- |
| `E_t.request_text` | `task_prompt` | Task/request evidence only. No repository identity, patch solution, or test output. Absent uses one fixed sentinel string. |
| `E_c.options[]` | `action_options[]` | Candidate summary and diff excerpt. IDs remain attached to candidates across paired coordinate conditions, are randomized independently of correctness, and are the only model output choices. Absent uses fixed neutral summary/diff values while preserving options and IDs. |
| `E_x.observations[]` | `evidence[]` entries of kind `pre_action_execution` | Base-snapshot evidence only. Candidate-specific test results and hidden labels are forbidden. Absent uses the fixed sentinel for this evidence kind. |
| `E_r.metadata` | `repository_id`, `repository_revision`, `snapshot_sha256`, `task_family`, and `evidence[]` entries of kind `repository_context` | Use opaque stable IDs and typed compatibility/build metadata. Keep raw repository names, commits, and labels in the hidden source record. An absent or swapped Er changes only these fields and context evidence. |
| `E_p.mapping` | array order of `action_options[]` | Schedule is assigned by the producer at candidate construction. Ordinal is carried through transport and restored before serialization. Receipt binds each task-condition frame's exact ordered ID/patch-digest sequence. |

The frame projector keeps common schema keys and evidence-list structure stable. Each evidence entry has the same keys and type. Where a condition removes an evidence channel, a channel-specific sentinel occupies that channel's slot; it does not change other channel contents or item order. `task_id` and `task_variant` are opaque stable per-task codes shared across its paired conditions, generated independently of gold action, candidate ID, family semantics, and coordinate schedule. `task_family` is an opaque stable code for family-clustered analysis; repo/family/code fields are included in nuisance-leakage audits.

The observer is not given the treatment name, donor identity, hidden `D_i`, correct-action set, candidate role labels, completion-test result, or condition seed. The runtime/audit keeps them outside the request.
