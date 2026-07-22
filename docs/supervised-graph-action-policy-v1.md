# Supervised Graph Action Policy v1

## Status

The identity, launch, promotion, and later-policy non-regression contracts are
implemented. Training is locked. It cannot open until both of these exist:

1. a populated and certified Counterfactual Candidate Groups v1 dataset;
2. a promoted R-GCN Multi-Task Workhorse v3 certificate covering all six heads.

The current repository contains contract and synthetic gate proof only.

## Supervised anchor

The first policy is deliberately supervised. It uses the frozen R-GCN
workhorse to score each exact candidate group and learns the recorded action
with group cross entropy. It must also:

- calibrate action probabilities on validation data with temperature scaling;
- learn the explicit safe-abstention label;
- report reward regret and hard-constraint violations;
- compare with the recorded Phoenix behavior policy;
- pass exact replay and cold-restart checks.

Counterfactual reward vectors remain vectors during this cut. The supervised
training label is the recorded action. No reward scalarization is smuggled into
the trainer identity. A later group-relative policy must name an explicit
scalarization or vector-valued objective as a new policy identity.

## Identity contract

The content-addressed policy identity binds:

```text
counterfactual dataset identity
promoted workhorse model identity
workhorse promotion certificate identity
evaluation protocol identity
complete 11-action vocabulary and ordering
recorded-action ranking loss
validation calibration method
abstention label policy
seed
optimizer identity
clipping partition identity
batch schedule identity
checkpoint selection rule
```

Missing or reordered actions fail closed. Optimizer, clipping, schedule, and
calibration changes create new identities.

## Launch gate

The gate revalidates the complete Counterfactual Candidate Groups artifact and
the R-GCN model identity. It also recomputes the workhorse promotion certificate
identity and verifies every task head still passes the promotion limit. A
boolean `promoted` field by itself is not authority.

No trainer entry point is exposed before this gate is authorized.

## Evaluation contract

The supervised anchor preserves integer-scaled metrics for:

- filtered MRR and Hits@1;
- Brier score, log loss, and calibration error;
- abstention risk and coverage;
- mean frozen reward and regret;
- hard-constraint violations;
- unsupported actions;
- unnecessary edit cost;
- future graph stability.

Promotion additionally requires at least two certified seeds, improvement over
the strongest baseline, paired query improvement, trained abstention,
calibrated probabilities, reproduced weights and certificates, cold restart,
and future-leakage rejection.

The learned policy must be no worse than the recorded behavior policy on every
preserved policy metric. This is intentionally conservative for v1. A future
tradeoff frontier requires a separately named comparison contract rather than
silently weakening the anchor.

## Policy-learning shield

Every later policy, including group-relative or reinforcement-learning work,
must pass a content-addressed comparison against the supervised anchor. It may
not regress on:

```text
ranking
calibration
abstention risk or coverage
reward or regret
hard constraints
unsupported actions
edit cost
future stability
```

The non-regression certificate recomputes the anchor identity and fails before
installation if any metric is worse. This keeps the supervised policy as a
durable safety and capability floor rather than an informal dashboard result.

## Definition of complete

Infrastructure completion means the contracts and gates are tested. Research
completion requires real frozen groups, a promoted workhorse, certified seeds,
authoritative evaluator reports, replay, and restart proof. Until then, neither
Cut 6 nor Cut 7 has an empirical Phoenix result.
