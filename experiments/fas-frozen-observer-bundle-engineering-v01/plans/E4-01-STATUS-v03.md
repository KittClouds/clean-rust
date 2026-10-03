# E4-01 status — v03

**As of:** 2026-09-27  
**Disposition:** E4-01 remains `DESIGN_ONLY / ENTRY_GATE_CLOSED`.  
**No model contact, E4 stage authorization, or GPU lease was issued by this work.**

## E4-01 map

The user-directed mission and boundaries remain in `E4-01-PLAN-v01.md`: combine Surface Survival and Source Value as one engineering-selection flight; preserve the E3 heads; select the cheapest route that meets prospectively frozen operational floors; keep E4-01 closed until E4-0 has a sealed terminal disposition and Ledger has reconciled its inherited artifacts.

## E4-0 entry dependency

- Current scientific contract: E4-0 v16-v09, SHA-256 `21fc77d5a288b9adef995d88f089890235f8dcb2fbc3c9e452725bb67892a22f`, seal root `278ae16eeb6852d3efad44221556a87be6df54964471f0870931fe2e99b305d1`.
- Chief's visible-only inherited-input bridge is sealed at `sha256:aacfd286b6349f0b35adb853a2cd9717c2463fedfeccc052bafaf515c69b027b`. The protected population label bytes were not opened, and the bridge does not grant truth access.
- Library's `KAMMI_LOCAL_EXECUTION_V1` supervised worker passed its CPU-only acceptance fixture. That qualifies the service surface; it does not authorize this scientific run.
- Chief's E4-0 stage authorization remains withheld. There is no live E4 run/stage grant, GPU lease, or model-contact approval. The supervised worker will issue a conservative possible-model-contact event before it launches the child, so it must be called only after the exact stage authorization and lease are current.
- The previous local-lease runner remains immutable history. A new Fabrique adapter now exists, but has only passed synthetic CPU qualification; no actual E4 inputs were run through it.

## Fabrique adapter handoff

- Adapter sources: `source/scripts/e4_supervised_execution_adapter_v01.py`, `source/scripts/e4_runtime_helpers_v01.py`, `source/scripts/e4_runner_modes_v06.py`, and `source/scripts/e4_online_supervised_v01.py`.
- Qualification receipt: `audits/e4-0-supervised-adapter-v01/qualification-receipt.json`.
- Candidate worker specs, commands, per-stage fresh output roots, and output inventories: `plans/E4-0-LEDGER-EXECUTION-SPEC-CANDIDATES-v01.json`.
- The adapter has separate fresh service output roots for parity and fresh-feature extraction under one new shared E4 run root. It verifies inherited seal manifests and named visible members without opening other protected member bytes, and copies the row manifest into the fresh feature output for stage-seal closure.
- The per-stage static input bindings, their source hashes, Ledger run/stage IDs, actor grants, policy/spec registrations, GPU lease, and stage authorizations are still pending Chief/Library. Candidate specs are not registered or authorized.

## Current action boundary

Only Fabrique-side runner/interface and synthetic CPU work has been done. Kammi Ledger and Library Lab files were not edited. Model/tokenizer/CUDA/truth/scoring were not contacted. Wait for Chief to accept the exact adapter/spec candidate, complete current-stage custody closure, and provide a live stage authorization plus fenced lease before E4-0 execution. E4-01 cannot begin before E4-0's sealed terminal disposition.
