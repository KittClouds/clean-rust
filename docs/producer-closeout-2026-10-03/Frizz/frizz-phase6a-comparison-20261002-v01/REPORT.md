# Phase 6A — Is comparison accessible in the frozen state?

**NO_EXPOSED_SURFACE_CLEARS_FIXED_USEFUL_RANKING_THRESHOLD**. F is not earned by the frozen rule and was not run.

This audit changes no Qwen or graft weights. It measures TRAIN-fitted diagnostic recovery on DEV, not protected generalization or an information-theoretic ceiling.

## Representation localization

Each row is a fixed readout, not a best-of-panel capability score. c = candidate-local 256; cs = candidate + context 320; e = integrated state32.

| Model | State | Surface | Readout | Selected top1 | Selected MRR | Optimal top1 | Optimal MRR | Type accuracy | Goal control BA |
|---|---|---|---|---:|---:|---:|---:|---:|---:|
| bridge | init | c | linear | 0.0991 | 0.2506 | 0.0661 | 0.2369 | 0.7477 | 0.7040 |
| bridge | init | c | mlp | 0.0811 | 0.2414 | 0.0901 | 0.2465 | 0.7477 | 0.7077 |
| bridge | init | cs | linear | 0.0781 | 0.2410 | 0.0751 | 0.2387 | 0.7477 | 0.7016 |
| bridge | init | cs | mlp | 0.0601 | 0.2326 | 0.0661 | 0.2354 | 0.7477 | 0.7290 |
| bridge | init | e | linear | 0.0841 | 0.2371 | 0.0751 | 0.2288 | 0.7477 | 0.6750 |
| bridge | init | e | mlp | 0.0781 | 0.2347 | 0.0751 | 0.2336 | 0.7477 | 0.6748 |
| bridge | trained | c | linear | 0.0781 | 0.2291 | 0.0751 | 0.2316 | 0.7477 | 0.7195 |
| bridge | trained | c | mlp | 0.0751 | 0.2315 | 0.0781 | 0.2372 | 0.7477 | 0.7219 |
| bridge | trained | cs | linear | 0.0781 | 0.2310 | 0.0691 | 0.2279 | 0.7087 | 0.7530 |
| bridge | trained | cs | mlp | 0.0841 | 0.2292 | 0.0781 | 0.2285 | 0.7027 | 0.7468 |
| bridge | trained | e | linear | 0.0991 | 0.2448 | 0.0901 | 0.2413 | 0.7027 | 0.7487 |
| bridge | trained | e | mlp | 0.0841 | 0.2338 | 0.0871 | 0.2365 | 0.6817 | 0.7481 |
| E | init | c | linear | 0.0991 | 0.2506 | 0.0661 | 0.2369 | 0.7477 | 0.7040 |
| E | init | c | mlp | 0.0811 | 0.2414 | 0.0901 | 0.2465 | 0.7477 | 0.7077 |
| E | init | cs | linear | 0.0781 | 0.2410 | 0.0751 | 0.2387 | 0.7477 | 0.7016 |
| E | init | cs | mlp | 0.0601 | 0.2326 | 0.0661 | 0.2354 | 0.7477 | 0.7290 |
| E | init | e | linear | 0.0841 | 0.2371 | 0.0751 | 0.2288 | 0.7477 | 0.6750 |
| E | init | e | mlp | 0.0781 | 0.2347 | 0.0751 | 0.2336 | 0.7477 | 0.6748 |
| E | trained | c | linear | 0.0871 | 0.2414 | 0.0991 | 0.2522 | 0.7477 | 0.7155 |
| E | trained | c | mlp | 0.0721 | 0.2263 | 0.0871 | 0.2391 | 0.7477 | 0.7106 |
| E | trained | cs | linear | 0.0871 | 0.2430 | 0.0961 | 0.2551 | 0.7117 | 0.7446 |
| E | trained | cs | mlp | 0.0661 | 0.2090 | 0.0781 | 0.2215 | 0.6877 | 0.7321 |
| E | trained | e | linear | 0.0901 | 0.2407 | 0.0901 | 0.2396 | 0.7087 | 0.8134 |
| E | trained | e | mlp | 0.0871 | 0.2399 | 0.0931 | 0.2446 | 0.6456 | 0.8096 |

Named selected-candidate ranking and optimal-membership scoring have separate fits, targets and eligibility masks. First-action-type is a root-level masked-mean readout; it is not a named-candidate score. The goal-control readouts are existing sealed Phase5 results, copied by reference and exact hash—not refit or selected.

TRAIN-majority action type index 0; DEV majority accuracy 0.7477. Type accuracy alone can ride MOVE prevalence. Per-class support/F1 are retained in every metrics.json.

## Within-type versus full-set ranking

| Model | Surface | Readout | Unrestricted selected top1 | Gold-type top1 | Predicted-type top1 | Gold-type MRR | Predicted-type exclusions |
|---|---|---|---:|---:|---:|---:|---:|
| bridge | c | linear | 0.0781 | 0.1111 | 0.0781 | 0.3068 | 84 |
| bridge | c | mlp | 0.0751 | 0.1201 | 0.0781 | 0.3131 | 84 |
| bridge | cs | linear | 0.0781 | 0.1171 | 0.0691 | 0.3113 | 97 |
| bridge | cs | mlp | 0.0841 | 0.1261 | 0.0781 | 0.3183 | 99 |
| bridge | e | linear | 0.0991 | 0.1622 | 0.1081 | 0.3469 | 99 |
| bridge | e | mlp | 0.0841 | 0.1441 | 0.0931 | 0.3327 | 106 |
| E | c | linear | 0.0871 | 0.1201 | 0.0871 | 0.3161 | 84 |
| E | c | mlp | 0.0721 | 0.1051 | 0.0691 | 0.3026 | 84 |
| E | cs | linear | 0.0871 | 0.1201 | 0.0811 | 0.3182 | 96 |
| E | cs | mlp | 0.0661 | 0.1051 | 0.0691 | 0.2945 | 104 |
| E | e | linear | 0.0901 | 0.1532 | 0.0931 | 0.3391 | 97 |
| E | e | mlp | 0.0871 | 0.1502 | 0.0901 | 0.3381 | 118 |

Gold type is an oracle restriction, never a learned input or deployable result. Predicted type uses the matching surface/family TRAIN-fit type readout. Excluded positives score zero reciprocal rank/top-k; their censored rank is N+1. The optimal endpoint remains independent, including under type restriction.

Both endpoint families under the **selected-candidate scorer** (not the separately fitted optimal scorer):

| Model | Surface | Readout | Selected roots | Exact top1 | Optimal roots | Optimal hit top1 | Best-optimal MRR |
|---|---|---|---:|---:|---:|---:|---:|
| bridge | c | linear | 333 | 0.0781 | 333 | 0.0781 | 0.2291 |
| bridge | c | mlp | 333 | 0.0751 | 333 | 0.0751 | 0.2315 |
| bridge | cs | linear | 333 | 0.0781 | 333 | 0.0781 | 0.2310 |
| bridge | cs | mlp | 333 | 0.0841 | 333 | 0.0841 | 0.2292 |
| bridge | e | linear | 333 | 0.0991 | 333 | 0.0991 | 0.2448 |
| bridge | e | mlp | 333 | 0.0841 | 333 | 0.0841 | 0.2338 |
| E | c | linear | 333 | 0.0871 | 333 | 0.0871 | 0.2414 |
| E | c | mlp | 333 | 0.0721 | 333 | 0.0721 | 0.2263 |
| E | cs | linear | 333 | 0.0871 | 333 | 0.0871 | 0.2430 |
| E | cs | mlp | 333 | 0.0661 | 333 | 0.0661 | 0.2090 |
| E | e | linear | 333 | 0.0901 | 333 | 0.0901 | 0.2407 |
| E | e | mlp | 333 | 0.0871 | 333 | 0.0871 | 0.2399 |

The full selected-scorer best-optimal ranks/top3/top5 and all restricted results remain in metrics.json.

## Pairwise diagnostics

| Model | State | Surface | Readout | Selected pair BA | Selected pairs / roots | Optimal pair BA | Optimal pairs / roots |
|---|---|---|---|---:|---:|---:|---:|
| bridge | init | c | linear | 0.8131 | 1332/333 | 0.8131 | 1332/333 |
| bridge | init | c | mlp | 0.8123 | 1332/333 | 0.8123 | 1332/333 |
| bridge | init | cs | linear | 0.8108 | 1332/333 | 0.8108 | 1332/333 |
| bridge | init | cs | mlp | 0.8153 | 1332/333 | 0.8153 | 1332/333 |
| bridge | init | e | linear | 0.7793 | 1332/333 | 0.7793 | 1332/333 |
| bridge | init | e | mlp | 0.7890 | 1332/333 | 0.7890 | 1332/333 |
| bridge | trained | c | linear | 0.8266 | 1332/333 | 0.8266 | 1332/333 |
| bridge | trained | c | mlp | 0.8116 | 1332/333 | 0.8116 | 1332/333 |
| bridge | trained | cs | linear | 0.8251 | 1332/333 | 0.8251 | 1332/333 |
| bridge | trained | cs | mlp | 0.7950 | 1332/333 | 0.7950 | 1332/333 |
| bridge | trained | e | linear | 0.8183 | 1332/333 | 0.8183 | 1332/333 |
| bridge | trained | e | mlp | 0.8221 | 1332/333 | 0.8221 | 1332/333 |
| E | init | c | linear | 0.8131 | 1332/333 | 0.8131 | 1332/333 |
| E | init | c | mlp | 0.8123 | 1332/333 | 0.8123 | 1332/333 |
| E | init | cs | linear | 0.8108 | 1332/333 | 0.8108 | 1332/333 |
| E | init | cs | mlp | 0.8153 | 1332/333 | 0.8153 | 1332/333 |
| E | init | e | linear | 0.7793 | 1332/333 | 0.7793 | 1332/333 |
| E | init | e | mlp | 0.7890 | 1332/333 | 0.7890 | 1332/333 |
| E | trained | c | linear | 0.8041 | 1332/333 | 0.8041 | 1332/333 |
| E | trained | c | mlp | 0.7935 | 1332/333 | 0.7935 | 1332/333 |
| E | trained | cs | linear | 0.8003 | 1332/333 | 0.8003 | 1332/333 |
| E | trained | cs | mlp | 0.7598 | 1332/333 | 0.7598 | 1332/333 |
| E | trained | e | linear | 0.8453 | 1332/333 | 0.8453 | 1332/333 |
| E | trained | e | mlp | 0.8483 | 1332/333 | 0.8483 | 1332/333 |

Pairs were constructed and sealed before DEV scoring. Up to four positive members crossed with four evenly spaced negatives, alternating orientation. IDs and labels never enter features. High pair accuracy on these label-constructed contrasts does not establish full-universe ranking. Linear shared context cancels under antisymmetry; the TinyMLP can condition comparisons on context.

## Candidate-count slices and top-k

| Model | Surface | Readout | Count band | Roots | Selected rank | MRR | Top1 | Top3 | Top5 | Best optimal rank | Optimal MRR | Optimal top1/3/5 |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| bridge | c | linear | all | 333 | 11.12 | 0.2291 | 0.0781 | 0.2342 | 0.3544 | 10.80 | 0.2316 | 0.0751/0.2372/0.3874 |
| bridge | c | linear | 1-28 | 17 | 7.59 | 0.1767 | 0.0000 | 0.2353 | 0.3529 | 6.76 | 0.2207 | 0.0588/0.1765/0.4118 |
| bridge | c | linear | 29-64 | 187 | 9.96 | 0.2355 | 0.0749 | 0.2406 | 0.3743 | 9.52 | 0.2396 | 0.0695/0.2781/0.4278 |
| bridge | c | linear | 65-128 | 128 | 12.93 | 0.2284 | 0.0938 | 0.2266 | 0.3281 | 12.85 | 0.2231 | 0.0859/0.1875/0.3281 |
| bridge | c | linear | 129-171 | 1 | 57.00 | 0.0175 | 0.0000 | 0.0000 | 0.0000 | 57.00 | 0.0175 | 0.0000/0.0000/0.0000 |
| bridge | c | mlp | all | 333 | 11.51 | 0.2315 | 0.0751 | 0.2432 | 0.3784 | 11.02 | 0.2372 | 0.0781/0.2492/0.3934 |
| bridge | c | mlp | 1-28 | 17 | 7.88 | 0.1790 | 0.0000 | 0.1765 | 0.4118 | 7.47 | 0.1856 | 0.0000/0.2353/0.3529 |
| bridge | c | mlp | 29-64 | 187 | 10.18 | 0.2376 | 0.0695 | 0.2513 | 0.3957 | 9.78 | 0.2396 | 0.0749/0.2353/0.4225 |
| bridge | c | mlp | 65-128 | 128 | 13.61 | 0.2313 | 0.0938 | 0.2422 | 0.3516 | 12.97 | 0.2423 | 0.0938/0.2734/0.3594 |
| bridge | c | mlp | 129-171 | 1 | 52.00 | 0.0192 | 0.0000 | 0.0000 | 0.0000 | 55.00 | 0.0182 | 0.0000/0.0000/0.0000 |
| bridge | cs | linear | all | 333 | 11.13 | 0.2310 | 0.0781 | 0.2282 | 0.3574 | 10.79 | 0.2279 | 0.0691/0.2282/0.3964 |
| bridge | cs | linear | 1-28 | 17 | 7.71 | 0.1740 | 0.0000 | 0.2353 | 0.3529 | 6.47 | 0.2014 | 0.0000/0.1765/0.5294 |
| bridge | cs | linear | 29-64 | 187 | 9.90 | 0.2411 | 0.0802 | 0.2353 | 0.3904 | 9.55 | 0.2358 | 0.0695/0.2460/0.4278 |
| bridge | cs | linear | 65-128 | 128 | 13.01 | 0.2256 | 0.0859 | 0.2188 | 0.3125 | 12.84 | 0.2215 | 0.0781/0.2109/0.3359 |
| bridge | cs | linear | 129-171 | 1 | 58.00 | 0.0172 | 0.0000 | 0.0000 | 0.0000 | 53.00 | 0.0189 | 0.0000/0.0000/0.0000 |
| bridge | cs | mlp | all | 333 | 12.15 | 0.2292 | 0.0841 | 0.2312 | 0.3724 | 11.33 | 0.2285 | 0.0781/0.2132/0.3724 |
| bridge | cs | mlp | 1-28 | 17 | 7.71 | 0.2064 | 0.0588 | 0.1176 | 0.3529 | 8.12 | 0.2078 | 0.0588/0.1765/0.2353 |
| bridge | cs | mlp | 29-64 | 187 | 9.97 | 0.2387 | 0.0856 | 0.2406 | 0.3957 | 9.50 | 0.2295 | 0.0642/0.2193/0.4064 |
| bridge | cs | mlp | 65-128 | 128 | 15.91 | 0.2196 | 0.0859 | 0.2344 | 0.3438 | 14.45 | 0.2306 | 0.1016/0.2109/0.3438 |
| bridge | cs | mlp | 129-171 | 1 | 15.00 | 0.0667 | 0.0000 | 0.0000 | 0.0000 | 8.00 | 0.1250 | 0.0000/0.0000/0.0000 |
| bridge | e | linear | all | 333 | 11.01 | 0.2448 | 0.0991 | 0.2342 | 0.3574 | 10.94 | 0.2413 | 0.0901/0.2372/0.3874 |
| bridge | e | linear | 1-28 | 17 | 6.94 | 0.2100 | 0.0588 | 0.1176 | 0.2941 | 6.65 | 0.2201 | 0.0588/0.1176/0.4706 |
| bridge | e | linear | 29-64 | 187 | 9.30 | 0.2590 | 0.1016 | 0.2567 | 0.4011 | 9.40 | 0.2526 | 0.0909/0.2567/0.4171 |
| bridge | e | linear | 65-128 | 128 | 13.94 | 0.2302 | 0.1016 | 0.2188 | 0.3047 | 13.67 | 0.2292 | 0.0938/0.2266/0.3359 |
| bridge | e | linear | 129-171 | 1 | 23.00 | 0.0435 | 0.0000 | 0.0000 | 0.0000 | 23.00 | 0.0435 | 0.0000/0.0000/0.0000 |
| bridge | e | mlp | all | 333 | 11.39 | 0.2338 | 0.0841 | 0.2402 | 0.3694 | 11.62 | 0.2365 | 0.0871/0.2222/0.3814 |
| bridge | e | mlp | 1-28 | 17 | 7.24 | 0.2072 | 0.0588 | 0.1176 | 0.3529 | 6.82 | 0.2256 | 0.0588/0.1176/0.4706 |
| bridge | e | mlp | 29-64 | 187 | 9.52 | 0.2437 | 0.0749 | 0.2674 | 0.4225 | 9.78 | 0.2525 | 0.0909/0.2567/0.4171 |
| bridge | e | mlp | 65-128 | 128 | 14.60 | 0.2243 | 0.1016 | 0.2188 | 0.2969 | 14.85 | 0.2162 | 0.0859/0.1875/0.3203 |
| bridge | e | mlp | 129-171 | 1 | 20.00 | 0.0500 | 0.0000 | 0.0000 | 0.0000 | 26.00 | 0.0385 | 0.0000/0.0000/0.0000 |
| E | c | linear | all | 333 | 11.55 | 0.2414 | 0.0871 | 0.2402 | 0.3904 | 11.35 | 0.2522 | 0.0991/0.2673/0.3724 |
| E | c | linear | 1-28 | 17 | 7.59 | 0.1994 | 0.0000 | 0.2353 | 0.4118 | 7.59 | 0.2511 | 0.1176/0.2353/0.2941 |
| E | c | linear | 29-64 | 187 | 10.45 | 0.2415 | 0.0802 | 0.2406 | 0.4064 | 10.28 | 0.2586 | 0.0963/0.2834/0.3957 |
| E | c | linear | 65-128 | 128 | 13.15 | 0.2486 | 0.1094 | 0.2422 | 0.3672 | 12.91 | 0.2449 | 0.1016/0.2500/0.3516 |
| E | c | linear | 129-171 | 1 | 79.00 | 0.0127 | 0.0000 | 0.0000 | 0.0000 | 77.00 | 0.0130 | 0.0000/0.0000/0.0000 |
| E | c | mlp | all | 333 | 12.11 | 0.2263 | 0.0721 | 0.2372 | 0.3904 | 11.79 | 0.2391 | 0.0871/0.2432/0.3664 |
| E | c | mlp | 1-28 | 17 | 8.65 | 0.2147 | 0.0588 | 0.2353 | 0.3529 | 8.41 | 0.2122 | 0.0588/0.2353/0.2941 |
| E | c | mlp | 29-64 | 187 | 10.82 | 0.2188 | 0.0481 | 0.2460 | 0.4225 | 10.61 | 0.2374 | 0.0749/0.2513/0.3850 |
| E | c | mlp | 65-128 | 128 | 13.98 | 0.2406 | 0.1094 | 0.2266 | 0.3516 | 13.49 | 0.2468 | 0.1094/0.2344/0.3516 |
| E | c | mlp | 129-171 | 1 | 72.00 | 0.0139 | 0.0000 | 0.0000 | 0.0000 | 71.00 | 0.0141 | 0.0000/0.0000/0.0000 |
| E | cs | linear | all | 333 | 11.56 | 0.2430 | 0.0871 | 0.2523 | 0.3844 | 11.41 | 0.2551 | 0.0961/0.2613/0.4144 |
| E | cs | linear | 1-28 | 17 | 7.76 | 0.1986 | 0.0000 | 0.2353 | 0.3529 | 7.41 | 0.2480 | 0.0588/0.2941/0.4118 |
| E | cs | linear | 29-64 | 187 | 10.46 | 0.2398 | 0.0749 | 0.2460 | 0.4011 | 10.32 | 0.2654 | 0.1016/0.2781/0.4332 |
| E | cs | linear | 65-128 | 128 | 13.15 | 0.2555 | 0.1172 | 0.2656 | 0.3672 | 13.02 | 0.2429 | 0.0938/0.2344/0.3906 |
| E | cs | linear | 129-171 | 1 | 79.00 | 0.0127 | 0.0000 | 0.0000 | 0.0000 | 78.00 | 0.0128 | 0.0000/0.0000/0.0000 |
| E | cs | mlp | all | 333 | 13.31 | 0.2090 | 0.0661 | 0.1952 | 0.3514 | 12.28 | 0.2215 | 0.0781/0.2102/0.3453 |
| E | cs | mlp | 1-28 | 17 | 8.24 | 0.1602 | 0.0000 | 0.1176 | 0.3529 | 8.24 | 0.1440 | 0.0000/0.0588/0.2353 |
| E | cs | mlp | 29-64 | 187 | 11.21 | 0.2064 | 0.0481 | 0.2086 | 0.3850 | 10.57 | 0.2149 | 0.0588/0.2139/0.3636 |
| E | cs | mlp | 65-128 | 128 | 16.89 | 0.2206 | 0.1016 | 0.1875 | 0.3047 | 15.11 | 0.2431 | 0.1172/0.2266/0.3359 |
| E | cs | mlp | 129-171 | 1 | 33.00 | 0.0303 | 0.0000 | 0.0000 | 0.0000 | 39.00 | 0.0256 | 0.0000/0.0000/0.0000 |
| E | e | linear | all | 333 | 9.99 | 0.2407 | 0.0901 | 0.2282 | 0.3784 | 9.86 | 0.2396 | 0.0901/0.2222/0.3634 |
| E | e | linear | 1-28 | 17 | 6.59 | 0.2962 | 0.1765 | 0.1765 | 0.4118 | 6.94 | 0.2467 | 0.1176/0.1765/0.2353 |
| E | e | linear | 29-64 | 187 | 8.68 | 0.2505 | 0.0856 | 0.2406 | 0.4171 | 8.78 | 0.2503 | 0.0856/0.2353/0.4225 |
| E | e | linear | 65-128 | 128 | 12.16 | 0.2207 | 0.0859 | 0.2188 | 0.3203 | 11.63 | 0.2246 | 0.0938/0.2109/0.2969 |
| E | e | linear | 129-171 | 1 | 33.00 | 0.0303 | 0.0000 | 0.0000 | 0.0000 | 35.00 | 0.0286 | 0.0000/0.0000/0.0000 |
| E | e | mlp | all | 333 | 10.08 | 0.2399 | 0.0871 | 0.2492 | 0.3724 | 9.72 | 0.2446 | 0.0931/0.2192/0.3724 |
| E | e | mlp | 1-28 | 17 | 6.82 | 0.2263 | 0.0588 | 0.1765 | 0.3529 | 6.88 | 0.2484 | 0.1176/0.1765/0.2353 |
| E | e | mlp | 29-64 | 187 | 8.68 | 0.2530 | 0.0909 | 0.2620 | 0.4118 | 8.60 | 0.2582 | 0.0963/0.2353/0.4171 |
| E | e | mlp | 65-128 | 128 | 12.38 | 0.2243 | 0.0859 | 0.2422 | 0.3203 | 11.53 | 0.2258 | 0.0859/0.2031/0.3281 |
| E | e | mlp | 129-171 | 1 | 32.00 | 0.0312 | 0.0000 | 0.0000 | 0.0000 | 35.00 | 0.0286 | 0.0000/0.0000/0.0000 |

All restriction/slice endpoint supports are retained in metrics.json. Fewer than 200 roots is descriptive. Stable canonical-ID tie breaking is frozen; no selected-ID tie preference. Uniform selected top1 expectation is mean(1/N); optimal expectation is mean(|A*|/N).

## The next branch

Frozen well-ranked rule: unrestricted selected top1≥.35, MRR≥.50, uniform top1 lift≥.20, ≥200 eligible roots. This is an operational continuation rule, not a definition of information content.

E e TinyMLP-minus-linear top1, paired canonical-root bootstrap: {'delta': -0.0030030030030030047, 'ci95': [-0.018018018018018014, 0.009009009009009014], 'bootstrap_roots': 333, 'repetitions': 2000, 'seed': 20261002}.

Declared pass map: {'bridge:c:linear': False, 'bridge:c:mlp': False, 'bridge:cs:linear': False, 'bridge:cs:mlp': False, 'bridge:e:linear': False, 'bridge:e:mlp': False, 'E:c:linear': False, 'E:c:mlp': False, 'E:cs:linear': False, 'E:cs:mlp': False, 'E:e:linear': False, 'E:e:mlp': False}.

The present exposed path does not deliver useful full-set comparison under this fixed diagnostic family/dose. This does not prove the frozen substrate contains no comparison information. Goal-relative accessibility can survive while named-candidate ranking remains weak. No automatic F is justified by this result.

## Cost, identity and verification

120 fixed target fits plus four solvable instrument controls; no substrate/graft training. Frozen Qwen BF16 revision dc7cdfe2ee4154fa7e30f5b51ca41bfa40174e68; exhaustive candidates, unchanged TRAIN-only normalization and BANK-v3-core population.

| Model | State | Surface | Readout | Probe parameters (five tasks) | Fit seconds | DEV prediction seconds | Peak CUDA bytes |
|---|---|---|---|---:|---:|---:|---:|
| bridge | init | c | linear | 3853 | 15.39 | 0.64 | 90667008 |
| bridge | init | c | mlp | 115853 | 17.67 | 0.64 | 90785792 |
| bridge | init | cs | linear | 4813 | 15.73 | 0.71 | 96963584 |
| bridge | init | cs | mlp | 144525 | 18.55 | 0.75 | 97110016 |
| bridge | init | e | linear | 493 | 13.82 | 0.25 | 97110016 |
| bridge | init | e | mlp | 15501 | 17.32 | 0.29 | 97110016 |
| bridge | trained | c | linear | 3853 | 14.51 | 0.63 | 97110016 |
| bridge | trained | c | mlp | 115853 | 17.99 | 0.67 | 97110016 |
| bridge | trained | cs | linear | 4813 | 15.82 | 0.65 | 97110016 |
| bridge | trained | cs | mlp | 144525 | 18.24 | 0.68 | 97110016 |
| bridge | trained | e | linear | 493 | 14.05 | 0.24 | 97110016 |
| bridge | trained | e | mlp | 15501 | 17.80 | 0.32 | 97110016 |
| E | init | c | linear | 3853 | 15.23 | 0.61 | 97110016 |
| E | init | c | mlp | 115853 | 18.16 | 0.67 | 97110016 |
| E | init | cs | linear | 4813 | 16.52 | 0.66 | 97110016 |
| E | init | cs | mlp | 144525 | 19.28 | 0.75 | 97110016 |
| E | init | e | linear | 493 | 14.68 | 0.28 | 97110016 |
| E | init | e | mlp | 15501 | 17.71 | 0.33 | 97110016 |
| E | trained | c | linear | 3853 | 14.45 | 0.60 | 97110016 |
| E | trained | c | mlp | 115853 | 17.36 | 0.73 | 97110016 |
| E | trained | cs | linear | 4813 | 14.88 | 0.61 | 97110016 |
| E | trained | cs | mlp | 144525 | 18.11 | 0.68 | 97110016 |
| E | trained | e | linear | 493 | 13.13 | 0.23 | 97110016 |
| E | trained | e | mlp | 15501 | 16.33 | 0.29 | 97110016 |

Prediction timings are cached-feature diagnostic throughput, not end-to-end Qwen serving latency. Eight state caches reconstructed exactly from sealed checkpoints; pair/target construction reproduced exactly; 120 persisted parameter/logit/metric replays and four control replays pass in fresh processes. This is frozen authored-code replay, not an independently authored semantic oracle.

Engineering lineage: initial stable-sort keyword mismatch and compact action-type dtype mismatch were repaired before diagnostic scoring. Failed preparation snapshots and logs remain intact. Four regression tests pass. Writing follows the supplied audit brief; no retrieved writing-style samples were available.

Protected evaluation remained unopened. Conflict is diagnostic-only. No recurrence, LoRA, internal-attention intervention or new organ ran. The sealed Phase5 bridge/E artifacts remain unchanged.
