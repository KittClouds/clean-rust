# Kammi Ledger end-state acceptance

All 28 gates PASS. Infrastructure flight state: OPEN.

```json
{
  "schema": "KAMMI_ENDSTATE_TERMINAL_V1",
  "status": "PASS",
  "flight_state": "OPEN",
  "acceptance_identity": "sha256:c02132e58e044331540292da8d8958a7b8a459cac4f594ab9e12b47ff8230af8",
  "acceptance_event": "sha256:a4fbbcf5886e80ecc525dd71a7e1be42f0cbe513356d8b90f0367c064e9ca95c",
  "source_root": "sha256:ecc131c4901b6230f06ce2b258d97ab1e18e7bc1d3a5988c1739dadc486312a2",
  "runtime_identity": "sha256:049b1cc9870e9ab7df3f0f70c17fa083cb9656781f2f10b779daffbd1daa99ac",
  "acceptance_suite_root": "sha256:2ce230415c92ba1bb0d0bc2a13b322623f74e873590640e184e06cbfa5cb1a61",
  "independent_verification_root": "sha256:b8eef83290738f0e2985d4698c64cfd5dad96647370a584dc4db7be5776aa0bb",
  "evidence_merkle_root": "sha256:814bbd812683dea8c9017bdb325292cc106d611b022d1f6732c474c784087eb2",
  "gates_passed": 28,
  "tests_passed": 43,
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
