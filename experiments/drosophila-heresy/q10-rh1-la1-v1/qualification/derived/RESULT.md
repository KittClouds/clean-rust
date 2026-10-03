# Q10-RH1-LA1 result

LA1 reconstructed `16` receipt-selected primary groups.

This is an engineering audit of exact f32 endpoint decomposition. It contains no biological, behavioral, or scientific promotion claim.

## Selection

A group entered the audit when `authority__h32.chosen.D` was strictly lexicographically better than `authority__h16.chosen.D` on `(mismatch_count, total_ulp_distance, residual_l2, maximum_absolute_residual)`.

| group | coordinates | authority h16 D | authority h32 D | morphology | mechanism class |
|---|---:|---|---|---|---|
| `seed9731-L-tau16.json:0:45` | 49 | [2, 2, 1.066240299940009e-06, 9.5367431640625e-07] | [0, 0, 0.0, 0.0] | `zero_support+zero_sign` | `LATE_INDEPENDENT` |
| `seed9731-L-tau16.json:1:43` | 44 | [3, 8, 1.5266237824995157e-06, 1.430511474609375e-06] | [2, 2, 5.331201499700045e-07, 4.76837158203125e-07] | `zero_support+zero_sign` | `GEOMETRY_BALANCING_DOMINANT` |
| `seed9731-L-tau16.json:2:40` | 53 | [7, 9, 3.0994415283203125e-06, 1.9073486328125e-06] | [4, 5, 2.900487198971853e-06, 1.9073486328125e-06] | `zero_support+zero_sign` | `LATE_INDEPENDENT` |
| `seed9731-L-tau16.json:3:44` | 45 | [3, 3, 7.152557373046875e-07, 4.76837158203125e-07] | [2, 2, 6.743495761743046e-07, 4.76837158203125e-07] | `zero_support+zero_sign` | `GEOMETRY_BALANCING_DOMINANT` |
| `seed9731-L-tau4.json:1:43` | 62 | [2, 2, 2.6973983046972182e-06, 1.9073486328125e-06] | [0, 0, 0.0, 0.0] | `localized_support+positive_only` | `EARLY_CONFIGURATION_IMPROVED` |
| `seed9731-L-tau4.json:3:48` | 58 | [2, 4, 1.966049969490843e-06, 1.9073486328125e-06] | [1, 1, 2.384185791015625e-07, 2.384185791015625e-07] | `localized_support+mixed_sign` | `GEOMETRY_BALANCING_DOMINANT` |
| `seed9731-R-tau16.json:1:44` | 46 | [1, 1, 4.76837158203125e-07, 4.76837158203125e-07] | [0, 0, 0.0, 0.0] | `localized_support+positive_only` | `GEOMETRY_BALANCING_DOMINANT` |
| `seed9732-L-tau16.json:0:43` | 59 | [3, 3, 1.3696104637475082e-06, 9.5367431640625e-07] | [0, 0, 0.0, 0.0] | `zero_support+zero_sign` | `EARLY_CONFIGURATION_IMPROVED` |
| `seed9732-L-tau4.json:1:41` | 55 | [4, 7, 2.1851423716334533e-06, 1.430511474609375e-06] | [1, 1, 9.5367431640625e-07, 9.5367431640625e-07] | `zero_support+zero_sign` | `EARLY_CONFIGURATION_IMPROVED` |
| `seed9732-R-tau16.json:0:44` | 76 | [3, 4, 4.046097457045827e-06, 3.814697265625e-06] | [2, 2, 2.132480599880018e-06, 1.9073486328125e-06] | `localized_support+positive_only` | `LATE_CONTEXTUAL` |
| `seed9732-R-tau16.json:2:39` | 72 | [6, 9, 3.3717478808715227e-06, 1.9073486328125e-06] | [5, 8, 3.2340669551493016e-06, 1.9073486328125e-06] | `zero_support+zero_sign` | `LATE_INDEPENDENT` |
| `seed9732-R-tau16.json:3:38` | 70 | [5, 5, 1.7357134555054946e-06, 9.5367431640625e-07] | [0, 0, 0.0, 0.0] | `localized_support+mixed_sign` | `GEOMETRY_BALANCING_DOMINANT` |
| `seed9732-R-tau4.json:0:43` | 69 | [2, 4, 3.015782985847835e-06, 2.86102294921875e-06] | [2, 2, 1.3486991523486091e-06, 9.5367431640625e-07] | `zero_support+zero_sign` | `GEOMETRY_BALANCING_DOMINANT` |
| `seed9732-R-tau4.json:1:42` | 69 | [5, 9, 4.498472753551771e-06, 3.814697265625e-06] | [5, 8, 3.724217260316207e-06, 2.86102294921875e-06] | `zero_support+zero_sign` | `EARLY_CONFIGURATION_IMPROVED` |
| `seed9732-R-tau4.json:2:42` | 61 | [6, 8, 3.8462318908933826e-06, 1.9073486328125e-06] | [2, 2, 2.6973983046972182e-06, 1.9073486328125e-06] | `zero_support+zero_sign` | `EARLY_CONFIGURATION_IMPROVED` |
| `seed9732-R-tau4.json:3:43` | 76 | [5, 8, 3.724217260316207e-06, 2.86102294921875e-06] | [5, 7, 3.0532475649990313e-06, 1.9073486328125e-06] | `localized_support+negative_only` | `GEOMETRY_BALANCING_DOMINANT` |

## Derived mechanism classification

`mechanism_class` is a descriptive-only derived label. It does not alter the sealed raw execution, describe behavior, or support a biological or scientific claim. The existing `morphology.label` remains the separate support/sign shape label for row-wise interaction.

Policy `LA1-DERIVED-MECHANISM-CLASS-V1` uses strict lexicographic D/P/G score relations, exact row interaction, and recorded geometry debt/pass flags. The policy digest is `E7F857A5536174D801753D9767392485FC0F3F0DB3F21E01329A56AC6EE7057C`.

| mechanism class | count |
|---|---:|
| `LATE_INDEPENDENT` | 3 |
| `LATE_CONTEXTUAL` | 1 |
| `EARLY_CONFIGURATION_IMPROVED` | 5 |
| `GEOMETRY_BALANCING_DOMINANT` | 7 |
| `MIXED` | 0 |
| `UNRESOLVED` | 0 |

The deterministic rules are:
- `LATE_INDEPENDENT`: full beats early in at least 2 of D/P/G, late-only beats W0 in at least 2 of D/P/G, and exact interaction support is zero
- `LATE_CONTEXTUAL`: full beats early in at least 2 of D/P/G, late-only beats W0 in zero domains, and exact interaction support is at least 1 row
- `EARLY_CONFIGURATION_IMPROVED`: early beats historical h16 in at least 2 of D/P/G, full beats early in at most 1 domain, and late-only beats W0 in at most 1 domain
- `GEOMETRY_BALANCING_DOMINANT`: actual full passes, both early and late-only diagnostic geometry flags fail, full geometry error is at most 0.5 times each counterfactual error, and no stronger score rule applies
- `MIXED`: two or more strong rules apply, or no strong rule applies and one comparison has both better and worse domains
- `UNRESOLVED`: no strong rule or declared mixed pattern is defensible from the receipts

Each group record preserves the three requested D/P/G comparisons, exact interaction support and hash, and all endpoint geometry debt. A class is `UNRESOLVED` when these receipt metrics do not provide a defensible rule match.

## D/P/G score aggregates

Means are across selected groups. D is the declared group-row search domain; P is physical support; G is the whole endpoint. The exact per-group scores are in `SUMMARY.json` and the group receipts.

| endpoint | domain | mean mismatches | mean ULP | mean residual L2 | mean max residual |
|---|---|---:|---:|---:|---:|
| `W0` | `D` | 7.3125 | 9.8125 | 4.25729e-06 | 2.83122e-06 |
| `W0` | `P` | 7.3125 | 9.8125 | 4.25729e-06 | 2.83122e-06 |
| `W0` | `G` | 255.125 | 348 | 2.49849e-05 | 7.80821e-06 |
| `historical_authority_h16` | `D` | 3.6875 | 5.375 | 2.4588e-06 | 1.84774e-06 |
| `historical_authority_h16` | `P` | 4.875 | 6.6875 | 2.66356e-06 | 1.84774e-06 |
| `historical_authority_h16` | `G` | 252.688 | 344.875 | 2.46902e-05 | 7.80821e-06 |
| `authority_h32_early_ranks_1_16` | `D` | 2.625 | 3.4375 | 1.8558e-06 | 1.43051e-06 |
| `authority_h32_early_ranks_1_16` | `P` | 4.75 | 6 | 2.34205e-06 | 1.54972e-06 |
| `authority_h32_early_ranks_1_16` | `G` | 252.562 | 344.188 | 2.46611e-05 | 7.80821e-06 |
| `authority_h32_late_only_ranks_17_32` | `D` | 6.5625 | 8.9375 | 4.11152e-06 | 2.77162e-06 |
| `authority_h32_late_only_ranks_17_32` | `P` | 7.6875 | 10.1875 | 4.38275e-06 | 2.77162e-06 |
| `authority_h32_late_only_ranks_17_32` | `G` | 255.5 | 348.375 | 2.50031e-05 | 7.80821e-06 |
| `authority_h32_full` | `D` | 1.9375 | 2.5 | 1.34313e-06 | 9.68575e-07 |
| `authority_h32_full` | `P` | 4.625 | 5.75 | 2.43938e-06 | 1.60933e-06 |
| `authority_h32_full` | `G` | 252.438 | 343.938 | 2.46684e-05 | 7.80821e-06 |

## Geometry and interaction

Inherited/actual endpoints W0, historical authority h16, and full authority h32 passed their hard geometry gate for all 16 groups: `True`.
Counterfactual early diagnostic pass count: `0/16`; late-only diagnostic pass count: `0/16`. Counterfactual failures are recorded and are non-blocking by contract.

For every endpoint row, the receipt records exact f32 bits and values and computes `I = (full-base)-(early-base)-(late-base)`. Morphology labels describe support and sign shape of I only; they are marked descriptive-only in the receipts.

The exact committed prefix maps are canonical coordinate-to-prefix lists sorted by coordinate id. Geometry metrics, signed normalized debt, endpoint hashes, row interactions, and per-group D/P/G scores are preserved in the JSON receipts.
