# E012 task construction specification v1

Status: frozen before scored task fixtures under bank amendment A04. This specification authorizes construction, offline candidate checks, projection, and leakage auditing only. It does not authorize any observer/model contact.

## Inputs and custody

- Task skeletons and opaque IDs: `bank/construction-01/family-design-v1.1.json`.
- Selected candidate implementations and feasibility outcomes: the twelve selected directories in `bank/construction-01/feasibility/`, selected by `feasibility-audit-v2.json` and `family-design-lock-v1.3.json`.
- Immutable source revisions and archive digests: `bank/construction-01/repository-source-inventory.json` and `repository-source-audit-v1.json`.
- Frame projection contract: `observer-frame-projection-v0.md`, as clarified by A04.
- Presentation/authority integration: E011 producer-order runtime, copied to the E012 repair subtree. Cargo path edits only locate the same dependency source roots.

All labels, candidate pass sets, donor assignments, raw logs, task source, and projected frames stay in separate bank-side records. Observer frames contain only the existing E009 schema.

## Frame and channel schema

Each frame uses `rdc-real-coding-observation.v1` with the E010/E011 field names: `task_id`, `task_family`, `repository_id`, `task_variant`, `task_prompt`, `repository_revision`, `snapshot_sha256`, `evidence`, and `action_options`. Opaque IDs are assigned by the locked family design and do not encode gold roles. Evidence uses the same fixed order and typed slots for execution and context on every condition. The action-option array always has four entries with `action:{id,schema_id}`, `summary`, `diff_excerpt`, and `patch_sha256`.

`E_t` projects only into `task_prompt`. `E_c.identity` is invariant and comprises option IDs, option count/schema, and patch identity. `E_c.content` comprises summaries and diff excerpts. `E_x` projects a pre-action observation from the untouched base snapshot; it never contains candidate runs or gold outcomes. Joint execution projections expose one predeclared factor only. `E_r` projects typed language/toolchain/build/feature context and the corresponding opaque repository metadata fields. Hidden family names, repository names, truth labels, candidate roles, condition names, and donor identifiers never enter observer-visible text.

## Source task and candidate construction

Each task is a clean consumer-code overlay importing a pinned upstream Rust library. Patch application is limited to overlay files. Each of the four actions is built from the selected feasibility patch content, with stable opaque action IDs. Candidate descriptions describe the observable code change, not its hidden role or correctness. IDs are assigned independently of task correctness and are balanced within family/stratum. Candidate position schedules are separately seeded, exactly truth-balanced within each eligible family block, and sealed before projection.

Candidate checks run in clean copies of the base task overlay against the pinned dependency commit. For support families, the expected valid-action set is computed from the frozen task contract and selected candidate-case pass matrix. The `bounded-prefix-copy` scored contract additionally requires shared backing storage, so its clean candidate check asserts both prefix value and zero-copy identity; the earlier value-only feasibility check remains unchanged. Abstention-positive tasks retain their explicit task request in the full frame and have no offered patch that meets the whole contract.

For candidate-only task families, place the candidate-visible contract facts in code comments and patch evidence shared by the candidate options; vary the task-specific distinguishing code/content across paired worlds. For task/request families, `E_t` switches the requirement across the predeclared pair while options and other channels remain fixed. For execution families, `E_x` switches the measured cursor/offset fact while all other channels remain fixed. For context families, `E_r` alone carries the compatibility/feature fact. Joint families use the 2×2 factorial truth table; each single factor leaves exactly two candidates and the combined factors identify one.

## Condition compiler

Emit the following 26 frames per task in canonical order:

1. `full_frame`.
2. `leave_out_E_t`, `leave_out_E_c_content`, `leave_out_E_x`, `leave_out_E_r`.
3. Ten truth-channel content-presence cells, in this order: `E_c_only`, `E_t_only`, `E_x_only`, `E_r_only`, `E_t_plus_E_c`, `E_c_plus_E_x`, `E_c_plus_E_r`, `E_t_plus_E_x_diagnostic`, `E_t_plus_E_c_plus_E_x`, `E_t_plus_E_c_plus_E_r`.
4. `control_E_t`, `control_E_c_content`, `control_E_x`, `control_E_r`.
5. `swap_E_t`, `swap_E_c_content`, `swap_E_x`, `swap_E_r`.
6. `E_p_balanced_coordinate_control`, `E_p_isomorphic_donor_coordinate`.
7. `identity_only_diagnostic` (all four truth-bearing contents absent; candidate identity retained; separate from the ten content-presence cells).

All masks retain the same frame schema and fixed evidence-slot order. A noninformative control is a typed matched-size payload independent of the receiver's action truth. A swap uses a preassigned isomorphic donor within the same repository and family-compatible schema. Donor maps are generated before labels are joined to projection code. `E_p` coordinate control and donor mapping are prospective constructor schedules; options are passed to the copied E011 runtime, which restores producer ordinals before serialization and seals the exact resulting sequence. No post-receipt reordering is allowed.

## Joint projection rules

- `bytes/composite-frame-field`: case truth is `(target field, byte order)`. `E_t` emits only `target field: header|payload`; `E_x` emits only `observed byte order: big|little`. Do not include the exact expected or parsed integer in projected evidence.
- `serde-json/number-mode-plus-error-site`: case truth is `(numeric mode, failing path)`. `E_t` emits only `requested numeric mode: whole|ratio`; `E_x` emits only `observed failing path: /header|/payload`. Do not include exact number values or a raw assertion line that combines both factors.

The projector runs counterfactual checks that each factor alone maps two roles to the same visible value, while the pair maps all four roles distinctly. Raw Cargo output remains vault-side.

## Precontact audits

The bank audit must fail closed unless all of the following pass:

- 48 tasks, 12 families, 3 repositories, and exactly 1,248 frames (26 per task).
- Each of 192 task-candidate rows (384 individual case invocations) and 48 base-task rows (96 case invocations) was run in an isolated overlay. The eight request/execution/joint/context families use one case per task; the two candidate-action and two abstention families use the full four-case suite per task. Exit status and actual/expected result are retained. Any compiler failure is a construction failure, not an incorrect-action label.
- Exactly the declared channel changes between paired frames; IDs, schemas, option counts, pair IDs, and non-target content are invariant.
- Candidate IDs and positions are checked for balance and independence from gold action; family/repository/task codes, patch lengths, evidence lengths/counts, test status, and simple lexical baselines are checked with family-grouped splits.
- Absence, controls, and swaps preserve types and fixed slots; donor compatibility and all donor assignments are hashed.
- Candidate presentation receipts bind each task-condition digest and exact sequence; normal path, transport scramble restoration, post-receipt drift rejection, wrong-presentation replay rejection, and state replay identity pass using the copied E011 runtime.
- Source commits, archive hashes, feasibility selection, scripts, inputs, all outputs, and audit results are included in a precontact manifest.

If any audit fails, retain the failed artifact, repair in a numbered sibling attempt, update the manifest, and rerun the affected offline checks. Model contact remains prohibited until a separate `FROZEN_BEFORE_MODEL_CONTACT` lock covers the complete passing bank and exact frozen observer inputs.
