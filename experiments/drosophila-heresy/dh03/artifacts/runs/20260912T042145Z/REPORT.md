# DH-03 measured results

**ELIGIBILITY_BENEFICIAL__STATE_INCONCLUSIVE**

All conditions began reversal from identical acquired states. The four factorial cells processed identical distractor schedules; only delivery of interval eligibility and post-interval neural state differed.

Eligibility retained minus suppressed: **+6.836 pp**; paired 95% [+5.770, +7.971]; familywise 97.5% [+5.627, +8.154].

State retained minus restored: **-0.065 pp**; paired 95% [-0.423, +0.309]; familywise 97.5% [-0.468, +0.370].

Descriptive interaction: **-0.146 pp**, paired 95% [-1.025, +0.789].

1152 arm runs; 589,824 computed training trials; 192 distinct acquisition streams reused across six conditions; 24 fresh computational seed bundles; two taus; one specimen.

## Final reversal-probe accuracy

| Slice | Arm | Immediate | Quiet | Retain both | Suppress eligibility | Restore state | Suppress both |
|---|---|---:|---:|---:|---:|---:|---:|
| R | E | 55.66% | 33.00% | 39.92% | 33.15% | 40.06% | 33.15% |
| R | Z | 50.21% | 50.21% | 50.21% | 50.21% | 50.21% | 50.21% |
| L | E | 57.31% | 33.08% | 39.87% | 32.80% | 39.95% | 32.71% |
| L | Z | 51.58% | 51.58% | 51.58% | 51.58% | 51.58% | 51.58% |

E uses uniform local learning; Z has fixed weights. Only the two right-slice E factorial main effects are co-primary.

## Right-slice intervention audit

| Factorial cell | Raw interval eligibility L1 | Delivered interval L1 | Pre-restore state mean abs drift | Eligibility removals | State restorations |
|---|---:|---:|---:|---:|---:|
| retain_both | 2466.163 | 2466.163 | 0.203724 | 0 | 0 |
| suppress_eligibility | 2556.757 | 0.000 | 0.208441 | 256 | 0 |
| restore_state | 2559.078 | 2559.078 | 0.205676 | 0 | 256 |
| suppress_both | 2580.451 | 0.000 | 0.208669 | 256 | 256 |

## Integrity and resources

- Complete grid, unique cells, matched acquisition hashes, fixed-weight action parity, exact intervention receipts, event counts, and graph-null invariants passed.
- Simulator execution including setup and diagnostics: 16.799 seconds on 4 workers.
- No online-loop allocations. Observer and intervention snapshots are additional experimental instrumentation.

## Interpretation limits

- These are repeated causal interventions in a synthetic local learner, not a biological mediation analysis.
- Restoring aggregate neural state can alter later eligibility formation; the factorial interaction is therefore reported explicitly.
- Immediate and quiet are descriptive anchors and are not part of the co-primary factorial effects.
- One specimen; left and right are related soma slices. No biological functional validation or universal-learning claim follows.
- No post-outcome tuning, extra seeds, rule search, or endpoint change.

Source: MaleCNS v1.0, FlyEM/Janelia and collaborators, CC-BY. https://male-cns.janelia.org/download/
