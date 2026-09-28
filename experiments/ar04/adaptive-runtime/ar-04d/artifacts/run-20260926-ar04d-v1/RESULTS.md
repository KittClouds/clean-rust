# AR-04D Results

This report is descriptive only. AR-04D has no automatic promotion rule.

- crossed cells: 25
- exposure arms: 7
- runtime steps per trajectory: 4200
- primary measurement: untouched V96 final set
- secondary measurement: untouched population reference of 4096 examples
- collection elapsed: 7513.2 seconds

The exposure curve and cyclic-versus-blocked contrast must be interpreted from
the cell-level outputs, not from a pooled terminal mean alone.

The K=1 and fresh arms are the built-in AR-04C fixed/rotating replication arms.
The AR-04C ordering is a predeclared historical check, not a license to pool
experiments or tune this run.

## Observed terminal means

| arm | unique support | per-decision verifier | final V96 loss | population loss | final accuracy | mean operational gap |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| sentinel_k1 | 128 | 128 | 2.982892 | 3.133756 | 0.6029 | -2.945872 |
| sentinel_k4_cyclic | 512 | 128 | 0.812207 | 0.825244 | 0.6346 | -0.103922 |
| sentinel_k16_cyclic | 2,048 | 128 | 0.784640 | 0.780397 | 0.6367 | -0.022181 |
| sentinel_k16_blocked | 2,048 | 128 | 0.877604 | 0.876753 | 0.6563 | -0.481989 |
| sentinel_k16_pooled | 2,048 | 2,048 | 0.560933 | 0.543047 | 0.7662 | -0.127232 |
| sentinel_k64_cyclic | 8,192 | 128 | 0.777335 | 0.768076 | 0.6563 | -0.033409 |
| sentinel_fresh | 134,400 | 128 | 0.777087 | 0.772360 | 0.6433 | -0.016478 |

## Predeclared checks and contrasts

- The historical K=1/fresh ordering replicated in 25/25 cells: fresh beat K=1.
- K=16 pooled beat K=16 cyclic in 23/25 cells, with equal-cell mean difference
  pooled minus cyclic `-2.2371e-1` on final V96 loss.
- K=16 cyclic beat K=16 blocked in 22/25 cells, with equal-cell mean difference
  cyclic minus blocked `-9.2964e-2`.
- K=64 cyclic and fresh were effectively tied at this scale: K=64 minus fresh
  mean difference `+2.4818e-4`, with 13/25 K=64 wins.

The primary terminal ordering does not support a simple “freshest is always
best” law. It supports a bounded separation: unique support is necessary
relative to one-panel reuse, a stable pooled support of 2,048 examples was
better than rotating V128 over the same support in this run, and cyclic spacing
was better than blocked spacing for the K=16 bank. Those are distinct effects.

The pooled arm is not compute-matched to the other sentinel arms: it evaluates
the same candidate grammar on V2048 rather than V128. Its terminal advantage
therefore cannot be attributed to unique support alone. The pooled-versus-cyclic
contrast isolates support from V128 rotation, while its higher runtime is a
declared cost of that control.

## Disposition

This is a descriptive exposure-frontier result, not a runtime-promotion claim.
The AR-04C fixed/fresh replication gate passed. The data favor a support and
spacing account over a pure-freshness account, but the pooled arm's larger
per-decision verifier means the next practical question is compute-matched
support allocation. No Taylor, adaptive refresh, noise injection, or Phoenix
change is authorized by AR-04D alone.
