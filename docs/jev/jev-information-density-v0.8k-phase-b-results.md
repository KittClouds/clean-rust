# JEV Information Density v0.8K — Phase B Results

## Disposition

v0.8K Phase B is complete. The preregistered attribution criterion **passes**:

> A certified invariant sham view carries information beyond an equal-dose repeated-anchor supervision event.

This is attribution evidence, not a universal capability-gain claim. Sensitivity was heterogeneous by seed, while sham locality improved in every seed. No follow-on experiment is authorized by this result.

## Frozen comparison

The six runs compared the identical F100 primary bank, feature universe, targets, auxiliary-event count, weights, optimizer, schedule, and paired seeds. The only auxiliary-loss source differed:

```text
K-DUP   anchor -> anchor target again
K-SHAM  sham   -> anchor target
```

Phase-A identity: `phase-a-v01-clean`

Key identities:

```text
contract SHA-256:    4a48c9eea438fcc94be218718ef70524f04e0f52f99e40767caa1e5e7a9e7825
objective graph:     bd574cd15bc0630ecfcc91116dda5554696313c5b3d03fd161940242f6518670
F100:                fc298d2d38e04b269e648e89fe0431634f076e0c50f859d949e24f33ba33416e
triplets:            6e2597e727ce93969166d4111aba578bfe9abfb2bda586b71d2993b83bb63701
K-DUP events:        5c6a68c6d947bc77672ae60b409133edf66501202a2e9f1b2e0e590d7ab825d2
K-SHAM events:       c96ac027b6f346a2b17d333b79f80f7705786fa4460652d12bc10064e0c112c3
```

Model revision:

```text
LiquidAI/LFM2.5-1.2B-Base
7453bca97ca1e67754c4035a4b4c584e1c9dd725
```

All six runs completed with 18 checkpoints. Evaluation was unlocked only after training and checkpoint sealing. Phoenix access was false; the backbone remained frozen; no LoRA or QLoRA was used.

## Primary direct-contrast result

Terminal means across the three paired seeds:

| Metric | K-DUP | K-SHAM | K-SHAM − K-DUP |
|---|---:|---:|---:|
| Strict old→new fact transition | 0.6050 | 0.5600 | −0.0450 |
| Sham posterior L1 | 0.3393 | 0.1010 | −0.2383 |
| Sham MAP-flip rate | 0.6258 | 0.1745 | −0.4513 |

The preregistered criterion passes:

```text
SHAM sham-L1 lower in all seeds:          PASS
SHAM sham-MAP-flip lower in all seeds:    PASS
Mean strict-transition loss <= 5 pp:     PASS (4.5 pp)
Specific invariant-view effect:           SUPPORTED
```

Per-seed strict-transition deltas were heterogeneous:

| Seed | Strict transition DUP | Strict transition SHAM | SHAM − DUP | Sham L1 delta | Sham flip delta |
|---:|---:|---:|---:|---:|---:|
| 20260927 | 0.3700 | 0.6560 | +0.2860 | −0.1623 | −0.0880 |
| 20260928 | 0.9555 | 0.2835 | −0.6720 | −0.2343 | −0.4570 |
| 20260929 | 0.4895 | 0.7405 | +0.2510 | −0.3183 | −0.8090 |

Therefore the clean conclusion is not that K-SHAM improves sensitivity. It is that the invariant view reliably reduces collateral sham movement beyond repeated supervision, while the relevant-fact response remains seed-dependent.

## Secondary NewTight effects

K-SHAM minus K-DUP means, reported by typed capability rather than a composite score:

| Panel / metric | Mean delta | Reading |
|---|---:|---|
| Choice accuracy | +0.0213 | higher discrimination, seed-variable |
| Choice Brier | +0.0235 | worse probability quality |
| Choice NLL | +0.0865 | worse probability quality |
| Applicability accuracy | −0.0015 | essentially unchanged/slightly lower |
| Applicability Brier | +0.0018 | slightly worse |
| Ordinal accuracy | −0.0505 | worse exact classification |
| Ordinal RPS | −0.00045 | small mixed movement; not a universal gain |

The broader panel confirms that the treatment moves a multidimensional capability surface. It does not justify calling K-SHAM globally better.

## Interpretation

v0.8K rejects the equal-dose explanation as sufficient:

```text
J10-like benefit
    != merely another supervised event
```

The certified same-target sham view supplies additional teaching information. The result is best described as a **specific invariant-view effect**:

```text
relevant-fact sensitivity: heterogeneous
irrelevant-view locality: consistently improved
collateral capabilities: mixed
```

This does not yet distinguish local nuisance information from generic novel same-target input diversity. That is a future question, not authorized by v0.8K.

## Artifact locations

Phase-B run root:

`D:/codex-runs/jev-information-density-v08k/phase-b-v01/`

Primary reports:

- `reports/k-attribution-summary.json`
- `reports/training-execution-summary.json`
- `reports/training-seal-manifest.json`
- `reports/evaluation-unlock.json`
- `reports/direct-contrast-by-arm-seed-epoch.json`
- `reports/paired-effects.json`
- `reports/family-transfer.json`
- `reports/k-newtight-capability-vector.json`
- `reports/k-newtight-paired-effects.json`
- `reports/k-schema-binding.json`
- `reports/k-intervention-analysis.json`
- `reports/k-hard-sibling-analysis.json`
- `reports/k-ood-transfer-analysis.json`

Phase-A seal and provenance remain under:

`D:/codex-runs/jev-information-density-v08k/phase-a-v01-clean/seal/`

No follow-on model experiment, architecture change, adaptation, or Phoenix access is authorized from this report.
