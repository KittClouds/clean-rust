# Order-frontier comparison

Read-only comparison of fresh order-1, order-2, and order-3 frontiers.

The order-1 source contains all 3,696 singleton attempts. The order-2 and order-3 sources are already-valid frontiers: 9,530 and 1,090,580 records respectively. Their displayed 100% geometry-valid rates are therefore source-scope properties, not structural-domain validity rates.

| Order | Source records represented | Geometry-valid source records | Better than V | Zero-mismatch | Distinct exact confirmed | Best valid score |
|---:|---:|---:|---:|---:|---:|---|
| 1 | 3696 | 57 | 49 | 0 | 0 | `[123.0, 162.0, 1.866006202952065e-05, 7.62939453125e-06]` |
| 2 | 9530 | 9530 | 6626 | 0 | 0 | `[123.0, 162.0, 1.866006202952065e-05, 7.62939453125e-06]` |
| 3 | 1090580 | 1090580 | 563649 | 0 | 0 | `[123.0, 162.0, 1.866006202952065e-05, 7.62939453125e-06]` |

Global best-score relation: order 2 vs order 1 = **SAME**; order 3 vs order 2 = **SAME**; order 3 vs order 1 = **SAME**. The best recorded score is `(123, 162, 1.866006202952065e-05, 7.62939453125e-06)`, with zero exact target endpoints at every order.

## Per-context best frontier

`BETTER` and `SAME` refer to the lexicographic score tuple; a missing lower-order frontier is reported as `UNAVAILABLE`.

| Context | Order 1 best | Order 2 best | Order 3 best | O2 vs O1 | O3 vs O2 | O3 vs O1 |
|---|---|---|---|---|---|---|
| seed9731-L-tau16.json / set 2 | `(164, 208, 1.44451e-05, 3.8147e-06)` | `(164, 208, 1.44451e-05, 3.8147e-06)` | `(164, 208, 1.44451e-05, 3.8147e-06)` | SAME | SAME | SAME |
| seed9731-L-tau4.json / set 3 | `—` | `(159, 200, 1.6137e-05, 5.72205e-06)` | `(157, 206, 1.69177e-05, 5.72205e-06)` | UNAVAILABLE | BETTER | UNAVAILABLE |
| seed9731-R-tau16.json / set 1 | `—` | `(144, 194, 2.11144e-05, 7.62939e-06)` | `(144, 193, 2.05025e-05, 7.62939e-06)` | UNAVAILABLE | BETTER | UNAVAILABLE |
| seed9731-R-tau16.json / set 3 | `—` | `—` | `(142, 199, 2.23292e-05, 1.14441e-05)` | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE |
| seed9731-R-tau4.json / set 0 | `—` | `—` | `—` | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE |
| seed9731-R-tau4.json / set 1 | `(146, 194, 1.81228e-05, 5.72205e-06)` | `(144, 191, 1.80914e-05, 5.72205e-06)` | `(143, 192, 1.86727e-05, 5.72205e-06)` | BETTER | BETTER | BETTER |
| seed9731-R-tau4.json / set 2 | `(144, 191, 1.95149e-05, 5.72205e-06)` | `(144, 191, 1.95149e-05, 5.72205e-06)` | `(144, 191, 1.95149e-05, 5.72205e-06)` | SAME | SAME | SAME |
| seed9731-R-tau4.json / set 3 | `(123, 162, 1.86601e-05, 7.62939e-06)` | `(123, 162, 1.86601e-05, 7.62939e-06)` | `(123, 162, 1.86601e-05, 7.62939e-06)` | SAME | SAME | SAME |

## Interpretation boundary

This artifact compares recorded valid frontiers and performs no replay. It does not establish monotonic improvement, because higher-order frontiers are not required to contain lower-order candidates. It does establish whether the best recorded score improved in the tested order-specific domains. The result is a plateau in the global best score, with order-3 improvements confined to several contexts.
