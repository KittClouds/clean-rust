# AR-04C Ranking Addendum

Read-only cross-scoring of sealed AR-04C checkpoint states. Rows: 900.

This addendum does not alter AR-04C artifacts or authorize a controller.
All three evidence sources were scored on every frozen AR-04C checkpoint state,
against the same final-measurement candidate utilities for that state.

| source | mean Spearman | mean candidate regret | terminal Spearman | terminal regret | terminal utility spread |
| --- | ---: | ---: | ---: | ---: | ---: |
| training | 0.2917 | 6.0951e-3 | 0.2263 | 1.3639e-2 | 3.2277e-2 |
| fixed | 0.1913 | 6.9964e-3 | 0.1223 | 1.5237e-2 | 2.1221e-2 |
| rotating | 0.3101 | 5.7133e-3 | 0.2830 | 1.2222e-2 | 3.4901e-2 |

The cross-scored terminal rotating ranking is not strong, but its terminal
utility spread is not collapsed relative to the other sources. This leaves
H56 as not supported for this addendum's common-state telemetry, without
using the addendum to reinterpret the sealed AR-04C disposition.
