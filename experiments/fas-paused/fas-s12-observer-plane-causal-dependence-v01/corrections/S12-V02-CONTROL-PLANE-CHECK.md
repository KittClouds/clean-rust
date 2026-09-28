# S12 v02 implementation correction

The sealed v01 attempt completed the 21,272-row base feature and unmodified suffix parity gate and reproduced the sealed S11 terminal prediction IDs. It then stopped on the first intervention, before committing a row or opening labels.

At row 0, source site L04-M, strength 1, random control 1, the v01 implementation tested the random-control output against the target plane's removal identity:

```text
P_target q' = (1 - lambda) P_target q
```

That identity applies only to the target-plane arm. A random-plane arm intentionally moves in another plane, so the observed residual was expected and did not indicate a bad intervention.

The v02 checker separates the invariants:

- Target arm: verify the remaining target-plane component against `(1 - lambda) P_target q`.
- Random control: verify the requested displacement belongs to the selected random plane and the applied summary displacement is its negative.
- All arms: retain the same displacement norm, tensor operator, strength, event, terminal observers, and downstream scoring as contracted.

The S11 panel, model revision, source/terminal probes, target and random plane banks, strengths, repeat quartets, bootstrap plan, primary estimand, and endpoint are unchanged. The correction changes no outcome rule and uses no label or prediction information. The failed v01 run and its bytes remain preserved.

The already sealed v01 base/suffix parity and baseline replay are reused byte-for-byte after root verification. V02 runs the complete intervention stage from the start on the unchanged 21,272-row panel, then performs the frozen repeat, analysis, independent replay, and final seal.
