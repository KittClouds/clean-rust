# F4-PRESENTATION-03 raw q weight diagnostics

This companion attaches the unmodified inverse-inclusion diagnostics to each weighted score scope. It does not recompute or change any score.

Rule: `q = 1/p_inclusion`. No trimming, capping, normalization, or winsorization was applied. ESS is descriptive only.

Fields: min q, max q, mean q, sum q, ESS, and sampled count. Class-specific values are shown because balanced errors weight classes separately.

## Assignment scopes

| Assignment | Rows | min q | max q | mean q | sum q | ESS | Positive ESS | Negative ESS |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 4478 | 376.421875 | 380.546875 | 378.28356 | 1693953.78 | 4477.87 | 495 | 3982.88 |
| 1 | 4914 | 376.421875 | 380.546875 | 378.963694 | 1862227.59 | 4913.86 | 2452.99 | 2460.94 |
| 2 | 6289 | 376.421875 | 380.546875 | 379.407564 | 2386094.17 | 6288.85 | 4623.99 | 1665 |
| 3 | 7287 | 376.421875 | 380.546875 | 379.732291 | 2767109.2 | 7286.86 | 1782.99 | 5503.88 |
| 4 | 2195 | 376.421875 | 380.546875 | 377.421647 | 828440.516 | 2194.95 | 403 | 1791.96 |
| 5 | 4112 | 376.421875 | 380.546875 | 379.97407 | 1562453.38 | 4111.94 | 3065.95 | 1046 |

## Block scopes

| Block | Assignment | Rows | min q | max q | mean q | sum q | ESS | Positive ESS | Negative ESS |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 309000 | see support table | 2564 | 380.546875 | 380.546875 | 380.546875 | 975722.188 | 2564 | 0 | 2564 |
| 309001 | see support table | 4723 | 376.421875 | 380.546875 | 379.290073 | 1791387.02 | 4722.88 | 1782.99 | 2939.91 |
| 309002 | see support table | 1771 | 376.421875 | 380.546875 | 379.216906 | 671593.141 | 1770.95 | 1751.95 | 19 |
| 309003 | see support table | 3157 | 376.421875 | 380.546875 | 378.639209 | 1195363.98 | 3156.91 | 1121.99 | 2034.94 |
| 309004 | see support table | 4398 | 376.421875 | 380.546875 | 378.24239 | 1663510.03 | 4397.87 | 495 | 3902.88 |
| 309005 | see support table | 4149 | 376.421875 | 380.546875 | 379.347851 | 1573914.23 | 4148.9 | 3014.99 | 1134 |
| 309006 | see support table | 2341 | 380.546875 | 380.546875 | 380.546875 | 890860.234 | 2341 | 1314 | 1027 |
| 309007 | see support table | 1757 | 376.421875 | 380.546875 | 379.546733 | 666863.609 | 1756.96 | 1331 | 426 |
| 309008 | see support table | 2140 | 376.421875 | 380.546875 | 379.523335 | 812179.938 | 2139.95 | 1609 | 531 |
| 309009 | see support table | 403 | 376.421875 | 376.421875 | 376.421875 | 151698.016 | 403 | 403 | 0 |
| 309010 | see support table | 1792 | 376.421875 | 380.546875 | 377.646484 | 676742.5 | 1791.96 | 0 | 1791.96 |
| 309011 | see support table | 80 | 380.546875 | 380.546875 | 380.546875 | 30443.75 | 80 | 0 | 80 |

## Pooled scope

Rows: 29275; min q: 376.421875; max q: 380.546875; mean q: 379.172626; sum q: 11100278.6; ESS: 29274.2; positive ESS: 12823.8; negative ESS: 16450.5.

The machine-readable scope map attaches diagnostics to 465 weighted output paths. Equal-weight six-assignment aggregates reference all six assignment-specific q summaries; no pooled reweighting of assignments is implied.
