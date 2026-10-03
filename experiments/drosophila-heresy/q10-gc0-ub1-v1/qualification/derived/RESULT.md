# Q10-GC0-UB1 result

This sealed audit used the actual RH1-F2/PF5 runtime loader and `support_counts` for every raw group in the fixed Q10-GC0 sample.

Status: `UB1_ENGINEERING_COMPLETE_COMPLETE_SUPPORT`.
Raw-group upper bound: `COMPLETE_SUPPORT`; mismatch rows 3386, covered 3386, uncovered 0, coverage 1.000000.
Loaded states: 14; raw groups: 801; RH1 sample projection: 27 of 55 groups.

Per endpoint/set:

| endpoint/set | raw groups | union support | mismatches | covered | uncovered | fraction | RH1 covered/fraction |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `seed9731-L-tau16.json|set0` | 59 | 631 | 243 | 243 | 0 | 1.000000 | 13/0.053498 |
| `seed9731-L-tau16.json|set1` | 57 | 631 | 244 | 244 | 0 | 1.000000 | 9/0.036885 |
| `seed9731-L-tau16.json|set2` | 55 | 647 | 251 | 251 | 0 | 1.000000 | 12/0.047809 |
| `seed9731-L-tau16.json|set3` | 58 | 641 | 249 | 249 | 0 | 1.000000 | 14/0.056225 |
| `seed9731-L-tau4.json|set0` | 54 | 620 | 259 | 259 | 0 | 1.000000 | 12/0.046332 |
| `seed9731-L-tau4.json|set1` | 56 | 609 | 251 | 251 | 0 | 1.000000 | 8/0.031873 |
| `seed9731-L-tau4.json|set2` | 55 | 624 | 247 | 247 | 0 | 1.000000 | 11/0.044534 |
| `seed9731-L-tau4.json|set3` | 62 | 625 | 245 | 245 | 0 | 1.000000 | 12/0.048980 |
| `seed9731-R-tau16.json|set1` | 59 | 598 | 247 | 247 | 0 | 1.000000 | 8/0.032389 |
| `seed9731-R-tau16.json|set3` | 54 | 588 | 234 | 234 | 0 | 1.000000 | 10/0.042735 |
| `seed9731-R-tau4.json|set0` | 59 | 588 | 222 | 222 | 0 | 1.000000 | 14/0.063063 |
| `seed9731-R-tau4.json|set1` | 55 | 600 | 241 | 241 | 0 | 1.000000 | 10/0.041494 |
| `seed9731-R-tau4.json|set2` | 59 | 584 | 238 | 238 | 0 | 1.000000 | 8/0.033613 |
| `seed9731-R-tau4.json|set3` | 59 | 568 | 215 | 215 | 0 | 1.000000 | 9/0.041860 |

The raw-group result is a physical-support upper bound. It does not establish a candidate palette, behavioral effect, scientific finding, or GC1 authorization.

Exact row and bit identities, group inventories, size-stratum coverage, and RH1 comparison rows are in `qualification/execution.json` and `qualification/derived/SUMMARY.json`.
