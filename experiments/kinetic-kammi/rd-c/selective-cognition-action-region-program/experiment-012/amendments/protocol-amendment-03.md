# E012 Protocol Amendment 03 — Effective Channel Matrix

- Base: protocol v0, Amendment 01, and Amendment 02; effective before bank construction.
- State: preconstruction correction. No E012 task fixtures or model outputs exist.
- Purpose: make the human protocol, projection, and bank construction plan agree with Amendment 02's candidate-identity and support contract.

## Candidate channel split

Every frame retains `E_c.identity`: the typed action envelope, schema identity, and opaque offered-action IDs required by the frozen observer output contract. `E_c.content` is the manipulable truth-bearing content: candidate summaries and patch evidence. ABSENT and control treatments replace only `E_c.content`; they preserve the same IDs, schema, option count, and positions for that task-condition frame. IDs do not encode candidate semantics.

## Effective support strata

For actionable tasks, `D_i` always includes `E_c.content` and contains any other truth-bearing channels required by the generator's paired counterfactual truth table:

| Stratum | Effective `D_i` |
| --- | --- |
| Task/request dominant | `{E_c.content, E_t}` |
| Candidate/action dominant | `{E_c.content}` |
| Pre-action test/execution dominant | `{E_c.content, E_x}` |
| Joint support | `{E_c.content, E_t, E_x}`; `{E_c.content, E_t, E_r}` is permitted only for a separately qualified context/joint family |
| Context sensitive | `{E_c.content, E_r}` |
| Abstention positive | no offered action is supported by the full frame |

`E_t`-only, `E_x`-only, and `E_r`-only frames remain diagnostic singleton conditions. `E_t+E_x` without `E_c.content` is a diagnostic pair. They are not sufficient to map a semantic action to an opaque offered-action ID. `E_c.content` alone is called sufficient only for candidate/action-dominant families whose paired truth table proves it. All other sufficiency claims retain `E_c.identity` and the listed `E_c.content` support.

For every claimed necessary channel, paired worlds hold all other truth-bearing channels and candidate identities fixed while changing the channel and the correct-action set. The shared frame with the channel withheld must therefore support abstention, not one of the conflicting actions. For every claimed sufficient set, the family truth table must resolve the same action identity across all constructed worlds in that family.

## Effective condition interpretation

Keep the previously frozen diagnostic cells, including task-only, test-only, context-only, and task-plus-test. Label them diagnostic, not sufficient. The valid initial sufficiency cells are exactly:

```text
E_c.content
E_c.content + E_t
E_c.content + E_x
E_c.content + E_r
E_c.content + E_t + E_x
E_c.content + E_t + E_r  (only for prequalified families)
```

The original producer-order rule remains in force. Coordinate schedules are assigned prospectively by the frozen producer condition argument; each resulting order gets its own ordinal sequence, presentation receipt, frame digest, and replay record. No candidate moves after receipt creation. The runtime restores that condition's producer order before serialization. This does not claim permutation invariance and does not weaken the production-order contract.

## Supersession

This amendment supersedes conflicting support-set, sufficiency, and candidate-channel descriptions in the v0 protocol and earlier construction documents. Other frozen requirements remain unchanged, including all model and threshold identities, repository exclusions, task minimums, controls, authority, scoring, and the no-model-contact stop boundary.
