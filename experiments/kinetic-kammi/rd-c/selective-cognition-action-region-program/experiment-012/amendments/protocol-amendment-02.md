# E012 Protocol Amendment 02 — Candidate Identity and Sufficiency

- Base: protocol v0 and Amendment 01.
- Status: effective before task construction; no E012 task fixtures or model outputs exist.
- Purpose: repair an identifiability problem in the proposed singleton/sufficiency contrasts before generating the bank.

## Candidate identity is a required action interface

The frozen observer must return an offered action ID. If candidate content is entirely removed, task text alone cannot map the desired semantic repair to an opaque numeric ID without either leaking the mapping or inventing a fixed semantic action codebook. E012 uses no such codebook.

Therefore split the candidate channel operationally:

- `E_c.identity`: the invariant, typed action envelope required by `Pi` (the offered action IDs and schema identity); this remains in every frame.
- `E_c.content`: the task-specific candidate summaries and patch evidence; this is the truth-bearing channel whose PRESENT/ABSENT/CONTROL/SWAPPED treatments are manipulated.

Action IDs remain opaque and randomized independently of candidate role, position, and correctness. In an `E_c.content`-ABSENT condition, IDs remain available but candidate summaries and patch content become the frozen neutral sentinel. No ID maps to a semantic action by itself.

## Support annotation and strata

For an actionable task, `D_i` contains `E_c.content` plus the additional truth-bearing channels needed to identify the correct action by construction. `E_p` remains a coordinate factor and cannot enter `D_i`. Use these support strata:

| Stratum | `D_i` |
| --- | --- |
| Task/request dominant | `{E_c.content, E_t}` |
| Candidate/action dominant | `{E_c.content}` |
| Pre-action test/execution dominant | `{E_c.content, E_x}` |
| Joint support | `{E_c.content, E_t, E_x}` (or a separately frozen `E_c.content + E_t + E_r` family if its fixtures prove that support) |
| Context sensitive | `{E_c.content, E_r}` |
| Abstention positive | no offered action is supported even with the full frame; the correct direct decision is abstain |

An `E_t`-only, `E_x`-only, or `E_r`-only frame is a **diagnostic singleton**, not a sufficiency claim: it lacks the action-content-to-ID mapping. `E_c.content` alone is a valid sufficiency condition only for candidate/action-dominant tasks. A subset is called sufficient only when the generator's paired counterfactual truth table shows that it resolves the candidate identity across all bank worlds in that family.

For each claimed necessary channel, construct twin worlds identical on all other truth-bearing channels and candidate identities, but with different correct-action sets when that channel changes. If the channel is withheld, the shared visible frame therefore maps to conflicting correct actions and the safe response is abstain. This is the construction-level test for necessity; observer behavior is then measured against it.

## Contrast correction

Keep every original full-frame, leave-one-out, control, and coordinate condition. Keep the single-channel diagnostic conditions, but do not label them all “sufficiency.” Pair sufficiency contrasts always retain `E_c.identity`; the valid initial cells are:

```text
E_c.content alone
E_c.content + E_t
E_c.content + E_x
E_c.content + E_r
E_c.content + E_t + E_x
E_c.content + E_t + E_r   (only for a preconstructed context/joint stratum)
```

`E_t+E_x` with `E_c.content` absent is retained only as a diagnostic singleton-pair cell; it is not claimed sufficient to select an opaque action ID. No threshold, observer, prompt, candidate order policy, task count, repository requirement, authority, or scoring rule changes.

The base v0 protocol and Amendments 01/02 compose as effective protocol v0.2. Their source files and prior locks remain immutable.
