# E4-0 supervised execution handoff v1

Status: **Library interface qualified; E4-0 stage authorization withheld.** E4-01 remains closed pending a sealed E4-0 terminal disposition.

## Inherited inputs

- Current scientific contract: SHA-256 `21fc77d5a288b9adef995d88f089890235f8dcb2fbc3c9e452725bb67892a22f`; legacy seal root `278ae16eeb6852d3efad44221556a87be6df54964471f0870931fe2e99b305d1`.
- v06 scientific baseline: SHA-256 `ea4f11cec5d65a3be7716c77febf5d448d8ebf1a5a4049aee5d25d51c0c50958`; original stage manifests still bind this baseline.
- Chief's visible-only inheritance bridge is under Ledger seal `sha256:aacfd286b6349f0b35adb853a2cd9717c2463fedfeccc052bafaf515c69b027b`. Six visible member files were rehashed. The two protected population members were neither opened nor verified as current bytes. The bridge is not a truth-access permission or a full population-stage closure.

## Qualified Library surface

The existing `KAMMI_LOCAL_EXECUTION_V1` service path completed a Library-owned, CPU-only fixture with a 19,005,440-byte output. It checked scoped authorization, a live lease and fence at resolve, before process launch, during polling, and before output registration. The output was copied into CAS without the normal 16 MiB request-body upload. The completion receipt was registered, the lease was released, and the old fence was rejected afterward. The fixture did not run a model or E4 code.

| Field | Bound location or meaning |
| --- | --- |
| `run_id`, `stage_id` | New live E4-0 run and phase-scoped stage IDs, issued after the adapter is qualified |
| `actor_id`, grant | Fabrique actor with exact `bind_spec`, `acquire_lease`, `authorize_stage`, and `execute_local` grants for that run/stage/policy hash |
| Scientific identity | Current sealed v16-v09 contract; no scientific field changed by this handoff |
| Execution identity | New immutable adapter and `KAMMI_LOCAL_EXECUTION_V1` spec, sealed separately from the scientific contract |
| Inherited-stage receipt | Visible-only bridge seal above; protected members require their own later access gate |
| `resource_id` | Registered local GPU resource, to be named in the later E4 grant |
| Lease/fence | `lease_id` and monotonic `fencing_token` issued by Ledger, then checked by the supervisor throughout child lifetime |
| Execution request | JSON with `actor_id`, `run_id`, `stage_id`, `authorization_id`, `lease_id`, `resource_id`, `fencing_token`, `attempt_id`, `request_id` |
| Output import | `expected_outputs` relative to a fresh `output_root`; each file streamed by Ledger from the bound path, hashed and registered under the live capability |
| Return | `KAMMI_LOCAL_EXECUTION_RESULT_V1` and `/v1/local/finish` receipt with result, output artifact IDs, contact event, authorization, lease and fence |

The execution spec also binds exact argv, cwd, timeout, polling interval, per-file output cap, and hashed `source_files`. The local worker is `python -m ledgerd.local_client --request <request.json> --receipt-root <fresh-directory>`, with `KAMMI_URL` and `KAMMI_ACTOR_TOKEN_FILE` in its environment. The worker owns a kill-on-close Windows Job; it terminates its child when the lease, authorization, source binding, or service validation fails. The child gets no Ledger credential.

## Fabrique-owned adapter seam

The sealed `e4_runner_modes_v05.py` still calls `make_gpu_lease` from `e4_gpu_lease_v04.py`. Fabrique must supply a separately hashed execution adapter that routes parity and extraction through the supervised process and no longer invokes that lab-local issuer. The adapter must preserve the v16-v09 scientific contract and all E4 output semantics. Its command, source hashes, exact output inventory, and fresh output roots then become the execution spec. Chief will bind and authorize only after that artifact and its no-model-contact qualification receipt are available.

No E4-0 live run, actor/grant, GPU lease, stage authorization, model contact, or E4-01 entry is issued by this handoff.
