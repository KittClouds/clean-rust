# Q09-LFA qualification result

Status: `LINEAR_AUDIT_VALID__FREEDOM_PRESENT`

Q09 completed as a qualification-only audit. It used zero scientific seed
bundles and performed no behavioral inference. Q08 remains unchanged and its
archive still verifies independently.

## Scope and receipts

- Stage A: engineering seed `9201`, both slices, both taus, 1,024 audited
  reversal states.
- Stage B: engineering seeds `9202..9205`, both slices, both taus, 4,096 new
  audited states.
- Cumulative Q09 audited states: 5,120.
- Every audited event was `LINEAR_AUDIT_VALID__FREEDOM_PRESENT`.
- Stage A independent reviewer: `VERIFIED`, NumPy replay verified.
- Stage B independent reviewer: `VERIFIED`, NumPy replay verified.
- Scientific seed bundles: `0`.
- Behavioral inference: `false`.
- Box feasibility: `NOT_TESTED`.
- Alternative sequential-f32 endpoint equality: `NOT_TESTED`.

The cue operator used all `16 * post_len` cue-by-MBON rows plus one global
acquisition-axis row. The realized dimensions were `784 + 1 = 785` rows for
the right slice and `768 + 1 = 769` rows for the left slice.

## Linear geometry summary

Stage A ranges across 1,024 states:

- Combined rank: `663..692`, median `680`.
- Nullity: `5,567..9,586`, median `8,049.5`.
- Null-energy fraction: `0.6558..0.8634`, median `0.7698`.
- Retained-subspace condition number: `8.16..20.97`.

Stage B ranges across 4,096 new states:

- Combined rank: `659..692`, median `681`.
- Nullity: `4,745..9,578`, median `7,799`.
- Null-energy fraction: `0.6086..0.8563`, median `0.7597`.
- Retained-subspace condition number: `8.16..20.97`.
- Optimistic absolute cosine floor: `0` for the minimum, median, and maximum
  observed floor values.

Integrity maxima over each completed stage remained within the frozen audit
contract. Stage A maximum normalized integrity error was `4.27e-14`; Stage B
was `4.32e-14`. Maximum pseudoinverse disagreement was `8.13e-15` in Stage A
and `8.93e-15` in Stage B. Maximum null annihilation was `1.03e-14` and
`1.18e-14`, respectively.

The f32 sequential-drive arithmetic diagnostic was recorded descriptively;
its maximum normalized value was `2.34e-6` in Stage A and `3.31e-6` in Stage B.
It was not used as an alternative-endpoint gate.

## Repair and quarantine record

The first complete compact-kernel Stage A attempt was retained at
`qualification/stage-a-9201-compact` and is quarantined. It closed all 1,024
states but correctly failed its integrity manifest on 57 state-dependent
pseudoinverse-agreement checks. No scientific result was taken from it.

The repaired run at `qualification/stage-a-9201-qr` uses a retained-image
Householder QR solve for the minimum-norm inverse. The repair preserves the
frozen SVD rank, singular spectrum, and right retained subspace. The archived
event-62 regression and the full Stage A run pass with the repair.

## Decision

The weaker Q09 linear contract leaves substantial unbounded freedom across
the audited engineering states. This clears the geometry gate for considering
a later bounded-constructor qualification. Q10 was not run or authorized by
this result.
