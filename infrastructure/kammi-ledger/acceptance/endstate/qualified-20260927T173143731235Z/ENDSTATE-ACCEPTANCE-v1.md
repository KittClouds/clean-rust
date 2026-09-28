# Kammi Ledger end-state acceptance

All 27 gates PASS. Infrastructure flight state: OPEN.

```json
{
  "schema": "KAMMI_ENDSTATE_TERMINAL_V1",
  "status": "PASS",
  "flight_state": "OPEN",
  "acceptance_identity": "sha256:7038435760079a4be053d2f18fa7ad0b49ed9c18adba020a828e43d95fcf4e14",
  "acceptance_event": "sha256:f5a1710408f2bdc54bd644f197a7618fe6d84f6eed4e9bfc94ac8d5ac1ae7c56",
  "source_root": "sha256:9e6025411112b31e0145d40c2fc605c6bb70f1af211331c49ab4236d7ea84af6",
  "runtime_identity": "sha256:049b1cc9870e9ab7df3f0f70c17fa083cb9656781f2f10b779daffbd1daa99ac",
  "acceptance_suite_root": "sha256:68100fe54127e75eda5dda0b948ee1364f16c438fda6c6e9fb471eab485406ce",
  "independent_verification_root": "sha256:4206ba242a3fa0f4a7f1e784c1cf463a97d3e3fb77e1b95d6b954a856b80341b",
  "evidence_merkle_root": "sha256:ffe091267d21f783e6930eafa2b3a37172805af03151e1c4353bc22d6692592a",
  "gates_passed": 27,
  "tests_passed": 38,
  "operational_store": "C:\\code land\\clean-rust\\program-infrastructure\\kammi-ledger\\.kammi-dev\\operational\\store",
  "scientific_observer_contact": false,
  "scientific_flight_authorized": false
}
```

## Qualified boundary

- Trusted local Windows account and loopback clients; direct filesystem access is outside guarded operation.
- Signed workers are trusted attestations; no hostile-code sandbox or hardware attestation.
- Process-kill recovery qualified; no physical power-cut/reboot/directory-metadata durability claim.
- Logical GPU leases and CPU fixture commands; no scientific observer contact or scientific flight authorization.
- Performance ranges and remaining ancestry/filter costs are reported descriptively; no throughput threshold was invented.
