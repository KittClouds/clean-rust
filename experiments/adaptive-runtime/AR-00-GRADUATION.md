# Adaptive Runtime — AR-00 Graduation Record

Status: graduated from the XOR sandbox; engineering-only, toy-scale, no biological correspondence, no general optimizer claim.

## Frozen candidate primitive

```text
deterministic broad pair coverage
    -> cheap singleton proposal
    -> top-2 x top-2 exact pair verification
    -> compare verified opportunity values
    -> commit best local pair program
    -> update state and replan
```

K2 is the smallest tested beam that remains in the exhaustive width-2 low-loss basin across all three seeds. It averages `0.01724851` final loss versus `0.01358598` for K0, while reducing exact compound evaluations from `3,928,144` to `126,731` per run on average. K1 is not acceptable as the candidate: it averages `0.30281617` despite reaching 100% XOR accuracy.

K4 and K5 are retained as higher-cost controls. K5 is closer to K0 on mean loss (`0.01468280`) but uses `813,400` exact compound evaluations per run. K2 therefore wins the minimum-beam criterion; K5 is the quality-oriented reference.

## What is established on AR-00

- Discrete action interposition can train the nonlinear XOR MLP.
- Linear utility collapses a multiscale action vocabulary to bounded sign descent.
- Singleton finite-effect utility is not compositional.
- Exact temporary joint evaluation matters; persistent topology-aligned groups are not required.
- Broad deterministic pair coverage is sufficient at toy scale; randomness is unnecessary.
- Width 2 is the current practical frontier; wider exact blocks are more expensive and not reliably better.
- Singleton shortlisting plus a small exact Cartesian verifier recovers most exhaustive width-2 behavior.
- Cross-block opportunity calibration and on-policy fidelity matter more than raw off-policy top-choice agreement.

## Graduation boundary

No unresolved AR-00 contradiction remains. Do not add adaptive beam width, learned routing, wider blocks, continual-learning objectives, or biological interpretation inside this family.

The next experiment family should test the frozen K2 primitive on a small stochastic nontrivial MLP, with K5 or exhaustive conditional verification as controls. It should introduce minibatches/noisy proposals and a larger candidate population before any continual-learning claim is attempted.
