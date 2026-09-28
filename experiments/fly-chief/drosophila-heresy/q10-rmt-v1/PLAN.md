# Q10-RMT: residual mismatch topology and local repair authority

Q10-DA2 produced 28 committed endpoints that satisfy the bounded geometry
contract but still differ from the target sequential-f32 readout. Q10-RMT
maps that residual without attempting repair.

The audit uses all 28 DA2 geometry-valid coalitions. The four DA2 geometry
failures are retained in a separate diagnostic count and are excluded from
the primary topology. No scientific seed bundle, behavioral endpoint, old-map
or reversed-map measurement, repair coefficient, or DH08B path is allowed.

For each valid endpoint, the runner reconstructs the committed f32 alternative
and true target states from the sealed DA1 fixtures and DA2 selected steps.
It computes exact learner-order sequential readouts, bitwise mismatch masks,
signed f64 residuals, and monotonic binary32 ULP distances.

Stage RMT-1 enumerates every legal one-ULP move on every permitted interior
coordinate with nonempty readout support that structurally overlaps at least one
mismatched row; legal coordinates outside that union are counted as exact
zero-authority coordinates without replay. It records raw and helpful authority,
geometry signatures, and an interaction-risk marker. Stage RMT-2 is
predeclared: only one-step orphan and fragile rows trigger escalation to legal
2, 4, 8, and 16 ULP moves. No move is ever committed into the canonical DA2
endpoint.

The output builds raw and helpful coordinate-to-row relations, helpful
row-coupling components, cooperative/conflicting shared-coordinate counts,
row persistence summaries, and a bounded relaxed-capacity diagnostic using a
deterministic authority-column cap. Capacity is diagnostic only and is not a
repair claim.

The 28 valid endpoints may execute in fixed deterministic shards and are
merged before the independent audit. Sharding changes only execution layout;
the endpoint order, source hashes, and primary endpoint rule remain frozen.
The relaxed authority projection uses the sealed deterministic column cap in
q10-rmt-config.json; this cap is an engineering bound, not a scientific
capacity claim.
