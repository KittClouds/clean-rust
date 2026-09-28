# E013 Precontact Arithmetic Correction v0.3.2

**Effective protocol lineage:** v0.3 + v0.3.1 amendment + this arithmetic correction  
**Parent lock:** `E013-PROTOCOL-LOCK-v0.3.1.json`, SHA-256 `2dde2c7c2fd3baa6c7bc08debfd01f5118f9ac4348318a9f9be633a0f7357d17`  
**State:** `SEALED_PRECONTACT_DESIGN_ONLY`  
**Scope:** Correct the asymptotic 5% risk FAR calculation only. No protocol gate, bank size, signal, task, model, or authority change.

## Defect and repair

The v0.3.1 feasibility calculation inverted the error-odds factor in its asymptotic FAR ceiling. For `A` expected correct accepted proposals and `W` wrong raw proposals, if fraction `f` of wrong proposals is accepted, then:

```text
f*W / (A + f*W) <= epsilon
f <= (epsilon / (1-epsilon)) * (A/W)
```

The erroneous v0.3.1 expression used `(1-epsilon)/epsilon`. The corrected expression and values are in `E013-FEASIBILITY-PROJECTIONS-v0.3.2.json` and `E013-FEASIBILITY-RECEIPT-v0.3.2.md`.

For C=1,120 at 50/70/90% correct-proposal recall, the corrected asymptotic FAR ceilings are:

| Scenario | 50% | 70% | 90% |
|---|---:|---:|---:|
| E012 pooled | 1.67% | 2.34% | 3.01% |
| Nominal 25/25/50 | 2.63% | 3.68% | 4.74% |
| E012 stratum sensitivity | 1.92% | 2.69% | 3.45% |

The finite exact-gate illustration (0/1/2 max wrong accepts at pooled expected support for 50/70/90% recall, or FAR 0.00/0.39/0.78%) was computed independently and is unchanged. The actual admission rule continues to use realized integer outcomes, `n_min=60`, and the exact one-sided 95% Clopper–Pearson bound of at most 5%.

## Preservation boundary

Keep v0.3.1 unchanged as the preserved first precontact package. This v0.3.2 correction supersedes only its asymptotic FAR field and corresponding displayed comparison. All task-bank, model-contact, and ownership boundaries remain unchanged: the user builds both banks; E013-D/C model contact is unauthorized; the separate positive control awaits its user-built bank. No bank, task, fixture, seed, screen, model call, or score was created here.
