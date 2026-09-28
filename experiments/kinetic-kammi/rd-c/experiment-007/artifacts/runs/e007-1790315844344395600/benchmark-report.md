# R&D-C Experiment 007 — Query Value Transfer

## Frozen evaluation

- Development: 8 independently seeded worlds, 2048 episodes; all router fits were frozen before held-out source and label fixtures were scored.
- Held out: 16 worlds, 6144 episodes, four preregistered strata; each world has four familiar IDs and eight new IDs.
- Each router receives exactly 16, 32, or 64 paid calls per world. Query cost varies by world and episode and is reported separately in cost units.
- The feature router reuses E006's eight public features; query price is supplied separately to rank benefit per cost. It has no world ID, domain ID, source reply, label, or oracle value.
- The evaluation oracle ranks realized task-completion deltas after the ordinary route plans are frozen; it is a measurement ceiling with no route authority.

## Overall paired results

Values pool all 16 held-out worlds (6,144 episodes per lane and budget). `Gain` is completion change from the paired zero-call floor. `Capture` is pooled gain divided by the evaluation-only oracle gain under the same call budget.

| Lane | Calls/world | Complete | Floor | Gain | Wrong→right | Right→wrong | Unresolved | Marginal gain/call | Paid cost | Capture | Mean bank gain | Min…max bank gain | Receipt B/call | Replay failures |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| domain_table | 16 | 3666/6144 | 3712 | -46 | 44 | 54 | 73 | -0.1797 | 1513 | -0.180 | -2.88 | -10…3 | 2235.6 | 0 |
| domain_table | 32 | 3618/6144 | 3712 | -94 | 89 | 95 | 145 | -0.1836 | 3045 | -0.188 | -5.88 | -15…3 | 2235.5 | 0 |
| domain_table | 64 | 3501/6144 | 3712 | -211 | 153 | 172 | 312 | -0.2061 | 6159 | -0.268 | -13.19 | -30…5 | 2237.2 | 0 |
| smoothed_table | 16 | 3659/6144 | 3712 | -53 | 42 | 45 | 80 | -0.2070 | 1549 | -0.207 | -3.31 | -10…4 | 2234.7 | 0 |
| smoothed_table | 32 | 3625/6144 | 3712 | -87 | 88 | 84 | 145 | -0.1699 | 3015 | -0.174 | -5.44 | -16…4 | 2235.4 | 0 |
| smoothed_table | 64 | 3518/6144 | 3712 | -194 | 160 | 179 | 287 | -0.1895 | 6114 | -0.246 | -12.12 | -31…7 | 2236.9 | 0 |
| feature_router | 16 | 3646/6144 | 3712 | -66 | 30 | 50 | 68 | -0.2578 | 2304 | -0.258 | -4.12 | -10…3 | 2234.4 | 0 |
| feature_router | 32 | 3569/6144 | 3712 | -143 | 63 | 93 | 159 | -0.2793 | 4608 | -0.285 | -8.94 | -18…3 | 2235.1 | 0 |
| feature_router | 64 | 3450/6144 | 3712 | -262 | 130 | 171 | 325 | -0.2559 | 9214 | -0.332 | -16.38 | -35…8 | 2237.4 | 0 |
| matched_random | 16 | 3648/6144 | 3712 | -64 | 35 | 41 | 102 | -0.2500 | 1604 | -0.250 | -4.00 | -10…2 | 2236.0 | 0 |
| matched_random | 32 | 3611/6144 | 3712 | -101 | 79 | 88 | 169 | -0.1973 | 3070 | -0.202 | -6.31 | -19…2 | 2236.4 | 0 |
| matched_random | 64 | 3505/6144 | 3712 | -207 | 151 | 180 | 319 | -0.2021 | 6171 | -0.263 | -12.94 | -32…8 | 2237.4 | 0 |
| no_inspection | 0 | 3712/6144 | 3712 | 0 | 0 | 0 | 0 | 0.0000 | 0 | NA | 0.00 | 0…0 | 0.0 | 0 |
| evaluation_oracle | 16 | 3968/6144 | 3712 | 256 | 256 | 0 | 0 | 1.0000 | 939 | 1.000 | 16.00 | 16…16 | 2233.6 | 0 |
| evaluation_oracle | 32 | 4213/6144 | 3712 | 501 | 501 | 0 | 2 | 0.9785 | 2528 | 1.000 | 31.31 | 23…32 | 2234.4 | 0 |
| evaluation_oracle | 64 | 4500/6144 | 3712 | 788 | 788 | 0 | 61 | 0.7695 | 5191 | 1.000 | 49.25 | 23…64 | 2236.1 | 0 |

## New domain IDs at 64 calls/world

The slice includes all episodes whose domain IDs do not occur in development; per-world IDs are deliberately novel. See `new-id-summary.csv` for all budgets.

| Lane | Episodes | Complete | Floor | Gain | Wrong→right | Right→wrong | Paid calls |
|---|---:|---:|---:|---:|---:|---:|---:|
| domain_table | 4096 | 2284 | 2495 | -211 | 153 | 172 | 1024 |
| smoothed_table | 4096 | 2301 | 2495 | -194 | 160 | 179 | 1024 |
| feature_router | 4096 | 2304 | 2495 | -191 | 86 | 124 | 693 |
| matched_random | 4096 | 2368 | 2495 | -127 | 104 | 122 | 689 |
| no_inspection | 4096 | 2495 | 2495 | 0 | 0 | 0 | 0 |
| evaluation_oracle | 4096 | 3025 | 2495 | 530 | 530 | 0 | 695 |

## Transfer by preregistered stratum at 64 calls/world

| Stratum | Lane | Complete | Floor | Gain | Wrong→right | Right→wrong | Unresolved | Capture |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| familiar_ids | domain_table | 996 | 1020 | -24 | 53 | 32 | 64 | -0.104 |
| familiar_ids | smoothed_table | 1002 | 1020 | -18 | 50 | 29 | 63 | -0.078 |
| familiar_ids | feature_router | 997 | 1020 | -23 | 47 | 20 | 72 | -0.100 |
| familiar_ids | matched_random | 1013 | 1020 | -7 | 52 | 19 | 62 | -0.030 |
| familiar_ids | evaluation_oracle | 1250 | 1020 | 230 | 230 | 0 | 6 | 1.000 |
| new_ids | domain_table | 963 | 1007 | -44 | 38 | 24 | 92 | -0.216 |
| new_ids | smoothed_table | 967 | 1007 | -40 | 41 | 29 | 80 | -0.196 |
| new_ids | feature_router | 949 | 1007 | -58 | 25 | 21 | 91 | -0.284 |
| new_ids | matched_random | 953 | 1007 | -54 | 37 | 25 | 92 | -0.265 |
| new_ids | evaluation_oracle | 1211 | 1007 | 204 | 204 | 0 | 13 | 1.000 |
| reliability_shift | domain_table | 737 | 813 | -76 | 25 | 42 | 99 | -0.418 |
| reliability_shift | smoothed_table | 759 | 813 | -54 | 37 | 43 | 78 | -0.297 |
| reliability_shift | feature_router | 732 | 813 | -81 | 31 | 47 | 92 | -0.445 |
| reliability_shift | matched_random | 757 | 813 | -56 | 35 | 51 | 100 | -0.308 |
| reliability_shift | evaluation_oracle | 995 | 813 | 182 | 182 | 0 | 29 | 1.000 |
| stale_sources | domain_table | 805 | 872 | -67 | 37 | 74 | 57 | -0.390 |
| stale_sources | smoothed_table | 790 | 872 | -82 | 32 | 78 | 66 | -0.477 |
| stale_sources | feature_router | 772 | 872 | -100 | 27 | 83 | 70 | -0.581 |
| stale_sources | matched_random | 782 | 872 | -90 | 27 | 85 | 65 | -0.523 |
| stale_sources | evaluation_oracle | 1044 | 872 | 172 | 172 | 0 | 13 | 1.000 |

## Typed inspection outcomes

Across repeated router and budget runs: Confirmed 2852, Contradicted 3861, Unknown 1088, Failed 1159. Unknown and Failed reobserved without a task action; the authority lane has no fallback-to-active transition.

## Runtime and paid-action gates

- Ordinary benchmark: illegal commits 0; rejected proposals 0; duplicate endpoint effects 0; replay failures 0.
- Group journals: 240 router/budget groups; each routed group used exactly its call budget; every result receipt and query hash chain passed.
- Crash recovery:

| Boundary | Attempts | Retries | Charges | Result receipts | Duplicate effects | Replay |
|---|---:|---:|---:|---:|---:|---|
| after-durable-intent-before-call | 1 | 0 | 1 | 1 | 0 | PASS |
| after-paid-response-before-outcome-receipt | 2 | 1 | 1 | 1 | 0 | PASS |
| after-durable-outcome-receipt | 1 | 0 | 1 | 1 | 0 | PASS |

The crash harness keeps a simulated endpoint stable-ID cache alive across client-journal recovery. A real endpoint must durably retain and honor the request ID to provide the same retry behavior.

## Interpretation limits

All data, task worlds, and inspection endpoints are synthetic deterministic proxies. Each held-out world has 384 tasks and 12 domains; estimates are world-level engineering evidence, not a production inspector error model. The feature router is an eight-weight ridge model over the fixed public schema, trained only on development worlds. Value capture is a finite-bank oracle ratio under the exact call budget; it is not a causal or broad-generalization claim.
