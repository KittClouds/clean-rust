# AR-00E-AUD1 — Interaction Capture

AUD1 reconstructs the exact structural E2 partition and the deterministic
per-epoch randomized E3 partition used by AR-00E. Against the frozen INT1 pair
field it measures how much interaction mass each partition captures inside
groups:

```text
capture(P) = within-group interaction mass / total interaction mass
```

It reports absolute, harmful, and synergistic mass, top-10 pair capture, and
capture of same-hidden-unit and `W1↔b1` pairs. This is a read-only audit of the
existing experiment artifacts and scheduler seed; it does not retrain a model.
