# E012 bank amendment 02 — feasibility closure

**State:** pretask feasibility closure; no scored task frames or model contact authorized.

This amendment leaves the locked repository set, 12-family allocation, 48-task count, strata, candidate identity rules, conditions, scoring, and authority unchanged. It records feasibility repairs discovered while implementing the locked families. The failed trials remain byte-preserved beside their repaired siblings.

## Effective feasibility evidence

The selected offline checks cover all 12 planned families:

| Family | Selected feasibility record | Result used for construction |
| --- | --- | --- |
| bytes / wire-endian-contract | `bytes-endian` | Endian candidates pass only request-matched cases; base passes none. |
| bytes / bounded-prefix-copy | `bytes-prefix` | Prefix-copy candidates pass; suffix/full-input and base do not. |
| bytes / cursor-advance-observation | `bytes-cursor` | Candidate pass set changes only with the recorded pre-action cursor evidence. |
| bytes / composite-frame-field | `bytes-composite` | Four candidates separate on the preregistered request-by-execution truth table. |
| clap / repeated-option-policy | `clap-repeat-repair-01` | Append and last-value policies pass their corresponding paired cases. |
| clap / possible-value-validation | `clap-values` | Exact finite-value parser passes all cases; base rejects valid values and admits invalid ones. |
| clap / help-color-capability | `clap-color-repair-01` | Typed color policy changes with the ANSI-capability context. |
| clap / conflicting-alias-requirement | `clap-alias` | Each offered implementation misses at least one required spelling/precedence case; abstention is correct. |
| serde-json / stream-byte-offset | `serde-offset-repair-01` | Offset candidates pass only their paired trace cases; base passes none. |
| serde-json / number-mode-plus-error-site | `serde-numeric-joint` | Candidate validity follows the preregistered numeric-mode-by-error-site table. |
| serde-json / map-order-feature-contract | `serde-map-order-repair-02` | Feature-on insertion-order and feature-off lexical-order candidates separate by the real Cargo feature state. |
| serde-json / raw-number-lossless | `serde-raw-number` | No offered normalizer preserves all exact source-number tokens; abstention is correct. |

## Preserved failed trials and repairs

- The first Clap color test used `render_help().to_string()` as an ANSI-rendering check. That view did not preserve ANSI styling. The replacement uses Clap's typed `Command::get_color()` contract. Both attempts remain in `clap-color` and `clap-color-repair-01`.
- The first serde offset base accidentally passed one case. It remains in `serde-offset`; the corrected `base.saturating_add(2)` trial is `serde-offset-repair-01`.
- The original clap repeated-option feasibility trial contains a compile error in the `first_value_only` mutant. It is retained as `clap-repeat`; the one-token mutability repair and complete rerun are `clap-repeat-repair-01`.
- The first serde map-order trial used an untouched baseline that already passed the full feature-dependent output contract. It remains in `serde-map-order`. A canonical-sort base and feature-specific candidate repairs were tested in `serde-map-order-repair-01` and `serde-map-order-repair-02`; only repair 02 has the intended passing context-specific candidate matrix.
- The first proposed clap color family and first serde offset implementation are feasibility failures, not scored tasks. None of these traces were shown to an observer.

The selected set contains 240 candidate/base-case records: 192 candidate-case rows and 48 baseline rows. All failed selected candidate cases reached the test assertion; none failed to compile. The test fixtures exercise only feasibility behavior and do not count toward the 48 scored tasks.

The source audit reconfirmed all three pinned commits and clean source checkouts, verified each immutable archive and root manifest hash, and resolved all Cargo targets to `D:\rdc-e012-target` through the configured paths. The selected repositories remain absent from E009, E010, and E011 evaluation sets.

## No-contact boundary

This amendment authorizes the next construction stage only. It does not authorize observer calls. No task frames, condition projections, truth labels, model outputs, or E012 scores exist at this amendment's effective point. A separate precontact lock remains required after construction, candidate execution, support/leakage audit, receipt/replay checks, and input hashing.
