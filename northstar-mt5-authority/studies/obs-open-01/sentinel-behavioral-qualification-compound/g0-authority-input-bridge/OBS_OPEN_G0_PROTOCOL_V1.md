# G0 — Authority / Input Bridge

G0 verifies the sealed OBS-OPEN-04A fossil without modifying it and separately
qualifies the proposed normalization from its historical M1 `f64`/epoch-second
input surface to integer price units and nanosecond storage.

The fossil question and bridge question are independent. Exact represented
values do not imply byte identity. Nanosecond storage does not imply
nanosecond source precision.

G0 consumes D_A only through the sealed 04A loader. It applies no future
outcome registry and reads no D_B, D_C, or D_D outcome-bearing values.

The canonical runtime is inspected as an immutable external candidate
substrate. Its current bar engine is not silently treated as the historical
M1 authority: it derives M4/M20/H2/H4 bars from committed index-value events.

G0 emits orthogonal `QUESTION_STATUS`, `RESULT`, and `DISPOSITION` fields and
stops. It earns no G1 semantic-kernel, prediction, mechanism, economic, or
trading authority.

