# AR-04D Results — Sentinel Exposure Frontier

AR-04D is a descriptive exposure-frontier experiment. It does not authorize
runtime promotion, Phoenix changes, Taylor-cost work, adaptive refresh, or
noise injection.

## Protocol

- 25 crossed dataset × initialization cells
- 7 exposure arms and 175 trajectories
- 4,200 runtime steps per trajectory
- 735,000 recorded decisions
- primary endpoint: untouched V96 final loss
- secondary endpoint: untouched 4,096-example population reference
- 26,250 master sentinel panels
- collection elapsed: 7,513.2 seconds

The K=1 and fresh arms are the built-in AR-04C fixed/rotating replication
check. They are reported as a historical check and are not pooled with AR-04C.

## Terminal equal-cell means

| arm | unique support | per-decision verifier | final V96 loss | population loss | accuracy |
| --- | ---: | ---: | ---: | ---: | ---: |
| sentinel_k1 | 128 | 128 | 2.982892 | 3.133756 | 0.6029 |
| sentinel_k4_cyclic | 512 | 128 | 0.812207 | 0.825244 | 0.6346 |
| sentinel_k16_cyclic | 2,048 | 128 | 0.784640 | 0.780397 | 0.6367 |
| sentinel_k16_blocked | 2,048 | 128 | 0.877604 | 0.876753 | 0.6563 |
| sentinel_k16_pooled | 2,048 | 2,048 | 0.560933 | 0.543047 | 0.7662 |
| sentinel_k64_cyclic | 8,192 | 128 | 0.777335 | 0.768076 | 0.6563 |
| sentinel_fresh | 134,400 | 128 | 0.777087 | 0.772360 | 0.6433 |

## Predeclared contrasts

- Fresh beat K=1 in 25/25 cells, replicating the AR-04C fixed/fresh ordering.
- K=16 pooled beat K=16 cyclic in 23/25 cells; equal-cell final-loss
  difference, pooled minus cyclic: `-2.2371e-1`.
- K=16 cyclic beat K=16 blocked in 22/25 cells; equal-cell final-loss
  difference, cyclic minus blocked: `-9.2964e-2`.
- K=64 cyclic and fresh were effectively tied at this scale; K=64 minus fresh
  mean difference: `+2.4818e-4`, with K=64 winning 13/25 cells.

## Interpretation

The result does not support a simple “freshest is always best” law. It supports
a bounded separation of effects:

1. One-panel reuse is substantially worse than access to broader independent
   support.
2. Cyclic spacing outperformed blocked exposure for the K=16 bank, so exposure
   spacing matters in this runtime.
3. The pooled K=16 arm outperformed rotating V128, but it evaluates candidates
   on V2048 rather than V128. It is therefore not compute-matched; its advantage
   cannot be attributed to unique support alone.
4. K=64 cyclic was already indistinguishable from fresh in the terminal primary
   endpoint, so unlimited novelty was not required in this run.

The most defensible conclusion is:

> Sentinel exposure geometry matters. Support size and spacing both affect the
> closed-loop trajectory, while pure freshness is not a sufficient explanation.

This remains a bounded synthetic-runtime result. No controller promotion is
authorized by AR-04D alone.

## Integrity

The complete run passed the artifact validator: 25 cells, 7 arms, 175
trajectories, 735,000 decisions, 700 checkpoints, 26,250 master panels, and
the untouched 4,096-example population references. The large trajectory CSV is
preserved locally and tracked remotely as an exact gzip artifact.
