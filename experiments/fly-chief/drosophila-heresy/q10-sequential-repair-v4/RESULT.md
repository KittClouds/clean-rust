# Q10-SR4 result

Status: `Q10_SR4_STAGE2A_VALID__CAPACITY_GATED_MIXTURE`

Q10-SR4 completed its fresh engineering qualification under the sparse-effect
Gram-matrix factorization. Stage 1A seed `9531` produced 1,024 committed
events and Stage 1B seeds `9532..9535` produced 4,096 committed events. The
independent standard-library reviewer verified all 20 bundles and replay
receipts: 5,120 audited states in total.

Among 5,015 states eligible for the parent constructor, every state had an
initial sequential-f32 readout mismatch. The new capacity gate classified all
5,015 as `CAPACITY_PARTIAL`; none were exact within the frozen `2e-10`
projection tolerance, none were numerically ambiguous, and no event entered
the repair search. The normalized unreachable residual ranged from
`0.2505027668` to `0.7216418025`, with median `0.4379930798`, so the all-gated
outcome is not a near-threshold rounding artifact.

The sparse Gram redesign achieved the engineering objective that failed under
SR3: Stage 1B completed without a capacity-factorization performance abort.
It does not establish repair capacity, a direction effect, a behavioral result,
an impossibility result, or a scientific finding. It is a valid qualification
of the new bounded gate and a diagnostic that the current one-ULP move banks do
not span the observed sequential-readout errors under the frozen contract.

The old wide-SVD and SR3 identities remain unchanged. No scientific seed bundle
was opened, no behavioral field was emitted, and DH-08B remains unauthorized.
