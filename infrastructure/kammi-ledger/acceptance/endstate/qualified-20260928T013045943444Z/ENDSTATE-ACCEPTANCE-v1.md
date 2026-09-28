# Kammi Ledger end-state acceptance

All 28 gates PASS. Infrastructure flight state: OPEN.

```json
{
  "schema": "KAMMI_ENDSTATE_TERMINAL_V1",
  "status": "PASS",
  "flight_state": "OPEN",
  "acceptance_identity": "sha256:2578de42c94f7f8cbed72521cb582a47bea465039f7a485ecce30ec1fcd7a898",
  "acceptance_event": "sha256:a06cc515cf593bc5a867a3274b6bd2a906eb5148146658eea161883da14d1048",
  "source_root": "sha256:8019d2281747a5b9d4572e58770fa7ec671c744d9274be43dea3a17ac001a10c",
  "runtime_identity": "sha256:049b1cc9870e9ab7df3f0f70c17fa083cb9656781f2f10b779daffbd1daa99ac",
  "acceptance_suite_root": "sha256:47ae1f58af4175ebc7106b0aba8139b54f9e8cb500837d570d4b6817dcf1bc0f",
  "independent_verification_root": "sha256:e5565a4a5031362c7cac9d9f309d2bf2b1a31e621b274d93616cde282d5eb0e6",
  "evidence_merkle_root": "sha256:0b544691b2b082f8fb830b740f48e20b650dc6264756ac93b8c361fe74160b47",
  "gates_passed": 28,
  "tests_passed": 47,
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
