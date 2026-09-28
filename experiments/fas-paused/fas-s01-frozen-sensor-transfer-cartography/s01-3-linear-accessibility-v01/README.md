# S01-3 Linear Accessibility Cartography

This versioned phase operates on the already sealed S01-2 cache and corpus. It
fits only the fixed multinomial linear probes described in
`S01-3-PROTOCOL.md` and its JSON contracts. It does not load LFM, create
features, modify FAS-00, or authorize adaptation.

The result run is written to:

```text
D:/codex-runs/fas-s01-frozen-sensor-transfer-cartography/s01-3-linear-accessibility-v01
```

The run is exploratory and diagnostic. Identity classifiers see every term
label during fitting; held-out term transfer is measured only by the
relation, state, and exact-target probes trained on the train-side vocabulary.
