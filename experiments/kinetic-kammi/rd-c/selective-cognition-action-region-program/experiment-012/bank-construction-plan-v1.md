# E012 bank construction plan v1

**State:** frozen for source selection and family construction. No E012 task frames, labels, observer outputs, or model calls exist.

This version implements the effective v0.3 channel matrix. It retains the bank size and audit gates from the original plan and assigns the 12 families before task creation.

## Repositories and family allocation

All repositories are Rust projects with immutable commits. The three selected repositories are absent as evaluation repositories from E009, E010, and E011. E009's frame sources identify `phoenix-native`; E010/E011 use `ripgrep` and `turbovec`.

| Repository | Family | Stratum | Effective truth support | Predeclared task focus |
| --- | --- | --- | --- | --- |
| bytes | `wire-endian-contract` | task/request dominant | `E_c.content + E_t` | Choose the offered byte-order repair from the requested wire contract. |
| bytes | `bounded-prefix-copy` | candidate/action dominant | `E_c.content` | Choose the patch that preserves the bounded-copy contract from candidate implementation evidence. |
| bytes | `cursor-advance-observation` | pre-action test/execution dominant | `E_c.content + E_x` | Select among cursor patches using the base-snapshot failure trace. |
| bytes | `composite-frame-field` | joint support | `E_c.content + E_t + E_x` | Combine the requested frame field with the observed failing offset/value; neither channel alone resolves the offered action. |
| clap | `repeated-option-policy` | task/request dominant | `E_c.content + E_t` | Choose replacement versus accumulation behavior from the caller's stated contract. |
| clap | `possible-value-validation` | candidate/action dominant | `E_c.content` | Select a candidate implementation whose parser admits the documented finite values and rejects other strings. |
| clap | `derive-feature-compatibility` | context sensitive | `E_c.content + E_r` | Choose an implementation compatible with the frozen workspace feature/toolchain context. |
| clap | `conflicting-alias-requirement` | abstention positive | full frame supports no offered action | All offered patches violate at least one explicit alias/compatibility requirement; correct direct behavior is abstain. |
| serde-json | `stream-byte-offset` | pre-action test/execution dominant | `E_c.content + E_x` | Select a stream cursor patch using the base-snapshot error/offset trace. |
| serde-json | `number-mode-plus-error-site` | joint support | `E_c.content + E_t + E_x` | Combine requested numeric policy with the observed parse failure location. |
| serde-json | `map-order-feature-contract` | context sensitive | `E_c.content + E_r` | Choose a map iteration/serialization strategy compatible with the frozen `preserve_order` feature state. |
| serde-json | `raw-number-lossless` | abstention positive | full frame supports no offered action | The request requires lossless source-number preservation while every offered patch rounds or normalizes it; correct direct behavior is abstain. |

Each family has four task instances. Candidate identity and action IDs are opaque, stable within paired worlds, and randomized independently from correctness. The four producer ordinals are balanced within each family. Truth-bearing pair worlds keep every non-target channel and all candidate identities fixed; a change in the designated support channel switches the valid action set. The joint families use paired truth tables where neither `E_t` nor `E_x` alone identifies the action, while their combination does.

The table is a construction target, not a claim that a family has already passed qualification. If source-level implementation cannot realize a row honestly, preserve the failed attempt, repair it before task-frame generation, and issue a versioned precontact amendment if the support contract itself must change.

## Construction details fixed in advance

- Bank seed: `20260925`.
- Task count: 48; family count: 12; four tasks per family; two families per stratum.
- Candidate count: four per task; at least two semantically plausible non-no-op options where the family permits; one no-op or clearly rejectable option. Abstention-positive tasks may have four plausible but incomplete choices.
- Conditions use the frozen v0.3 condition list. Candidate-only content cells retain `E_c.identity`; task/test/context singleton cells are diagnostic only.
- Tests run against isolated copies of the pinned source snapshots plus frozen task overlays. Candidate patches are applied in clean copies; test output from the unmodified task snapshot is the only execution evidence exposed in `E_x`.
- Build outputs go to the `D:` target directory, with a `C:` junction for test tooling. Source snapshots remain immutable.
- Task family names, truth, candidate roles, donor assignments, and condition names are excluded from observer-facing IDs and fields. The projector emits opaque task/family identifiers.
- No observer output is used for repository, family, task, candidate, test, or condition selection.
