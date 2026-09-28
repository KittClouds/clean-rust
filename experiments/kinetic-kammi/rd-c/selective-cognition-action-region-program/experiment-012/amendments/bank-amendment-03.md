# E012 bank amendment 03 — execution evidence repair

**State:** pretask fixture repair; no scored task frames or model contact authorized.

After freezing feasibility v1.2, a review of the actual test logs found that four families marked as execution- or joint-evidence dependent emitted only the generic assertion text `task contract failed`. Their candidate pass matrices were valid, but the baseline tool output did not contain the expected-versus-observed value needed for the declared `E_x` channel. This was a harness diagnostic defect, not a result about the observer.

The original outputs remain sealed. Four sibling harnesses change only the test assertion diagnostic from a boolean assertion to an equality assertion that prints both values:

| Family | Preserved earlier trial | Effective repaired trial | Diagnostic now exposed |
| --- | --- | --- | --- |
| bytes / cursor-advance-observation | `bytes-cursor` | `bytes-cursor-repair-01` | Actual byte at the base cursor versus expected byte. |
| bytes / composite-frame-field | `bytes-composite` | `bytes-composite-repair-01` | Actual selected field value versus expected value. |
| serde-json / stream-byte-offset | `serde-offset-repair-01` | `serde-offset-repair-02` | Actual reported byte offset versus expected offset. |
| serde-json / number-mode-plus-error-site | `serde-numeric-joint` | `serde-numeric-joint-repair-01` | Actual selected value versus expected value. |

The changed test diagnostics preserve each candidate pass matrix. The base snapshot still fails every case. The selected tests compile, and every selected failure reaches the equality assertion. The new logs are now suitable source material for `E_x`; no candidate-specific result is exposed in the pre-action frame.

All other family prototypes remain selected as recorded in amendment 02. This amendment changes neither task-family assignment nor truth support. The effective selected set, assertion-log audit, and hashes are recorded by bank plan v1.3 and `family-design-lock-v1.3.json`.

No scored tasks, channel projections, observer outputs, or model calls exist at this amendment's effective point. Construction may proceed; model contact still requires the separate completed-bank precontact lock.
