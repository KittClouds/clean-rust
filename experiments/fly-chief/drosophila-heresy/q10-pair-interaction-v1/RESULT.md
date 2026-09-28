# Q10-PI1 engineering result

Q10-PI1 completed all 8 declared engineering events: seeds 9721 and 9722,
sides R/L, taus 4/16, trial 128. No scientific seed bundle was opened and
DH08B remains unauthorized.

The independent Python replay verified all 76,800 signed pair endpoint
combinations. The disjoint controls had exactly zero interaction in all 25,600
candidates. Shared pairs had nonzero interaction in 3,572 of 51,200
candidates, or 6.98%; 314 of 512 shared pairs had at least one nonzero
candidate. The largest raw interaction norm was 5.3948e-6.

The target overlay was independently recomputed for all 76,800 candidates.
Interaction alignment with the negative baseline error was weak: the maximum
observed positive cosine was 0.0882. Pair-local improvements were common, but
they were not evidence of a globally valid repair endpoint. Across the 512
shared pairs, the mean best actual-error ratio was 0.99905; across the 256
disjoint pairs it was 0.99910. The disjoint controls therefore performed at
least as well as the shared interaction sample on this target-conditioned
overlay.

Conditioning on whether the shared candidate had a nonzero interaction made
the result less favorable for the nonlinear story: positive-interaction shared
candidates had mean error ratio 1.00056, while zero-interaction shared
candidates had 1.00027. This is descriptive, not an independent statistical
test, but it reinforces that nonzero interaction is not a useful selection
criterion here.

Interpretation: sequential-f32 interactions are real, sparse, and localized,
but interaction strength is not repair usefulness. The result supports a
distributed additive authority model with sparse threshold interactions as a
secondary correction mechanism. It does not justify a nonlinear interaction
block as the next repair primitive.

Receipts:

- `qualification/sample-9721-9722/pair-map.json` — target-blind map.
- `qualification/sample-9721-9722/overlay-results.json` — target-conditioned overlay.
- `qualification/sample-9721-9722/replay-fixture.json` — independent replay fixture.
- `qualification/sample-9721-9722/execution.json` — event accounting.

Hashes: PREEXECUTION `5CA5207BB7C09D44C371022895F5128ECABE758E77C1B066478353FF2A6CEA35`,
pair map `DC084441F223B93F3EB68CA7786E7D858D19BCEE827B348B50DE2D1822704FD4`,
overlay `0D82EFD4EBC8E93580AC6D5508D3B160399CCF9B31B0BAE8E2AECA3AB4A202C6`.
