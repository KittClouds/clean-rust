# Q10-JBR2 result

Status: **verified engineering qualification**.

The independent reviewer accepted all 8 declared engineering events: 2 seeds,
2 sides, 2 tau values, and trial 128. Every event contained the planned 3
shared-pair triples and 3 disjoint triples. Each of the 48 blocks evaluated all
125 simultaneous committed f32 endpoint combinations, for 6,000 direct
sequential-readout replays.

The exact replay machinery was valid, but the tested blocks did not solve the
readout mismatch. Among 24 shared-pair blocks, the best residual ratio was
`0.9914476163`, the median was `1.0`, and no block reached exact readout. Among
24 disjoint controls, the best ratio was `0.9585733487`, the median was
`0.9999153162`, and no block reached exact readout. The largest shared-block
residual reduction was `0.0085523837`; the largest disjoint-control reduction
was `0.0414266513`. One shared block slightly worsened the residual, with a
ratio of `1.0000063731`; negative reductions were preserved in the receipt.

These are local engineering diagnostics, not a repair result and not a
scientific or behavioral finding. The disjoint controls happened to expose a
larger best local reduction than the shared blocks, so this qualification does
not support a claim that shared-row blocks are more repair-capable. It only
shows that jointly committed small blocks can be replayed exactly and that the
tested 3-coordinate, 125-prefix search is insufficient for global repair.

Q10-JBR1 is retained as an invalid predecessor because its stricter all-three-
coordinates-shared selection rule failed block capacity. Q10-JBR2 broadened
the engineering selection to at least one shared pair and passed capacity.

Scientific seed bundles used: **0**. Behavioral inference: **false**.
DH-08B authorization: **false**.
