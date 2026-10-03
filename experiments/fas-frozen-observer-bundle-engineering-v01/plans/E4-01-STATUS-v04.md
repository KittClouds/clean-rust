# E4-01 status — v04

**As of:** 2026-09-27  
**Disposition:** `DESIGN_ONLY / ENTRY_GATE_CLOSED`.  
**No E4-0 or E4-01 stage authorization, GPU lease, or model contact was issued by this work.**

## E4-01 map

The current plan is [E4-01-PLAN-v02.md](E4-01-PLAN-v02.md). It combines Surface Survival and Source Value into one engineering-selection flight, preserves all E3 heads, chooses the cheapest reproducible route that meets prospectively frozen operational floors, and remains closed until E4-0 has a sealed terminal disposition and Ledger has reconciled the inherited artifacts. `E4-01-PLAN-v01.md` remains immutable history.

## E4-0 entry dependency

- Current scientific contract: E4-0 v16-v09, SHA-256 `21fc77d5a288b9adef995d88f089890235f8dcb2fbc3c9e452725bb67892a22f`, seal root `278ae16eeb6852d3efad44221556a87be6df54964471f0870931fe2e99b305d1`.
- Chief's 2026-09-27 visible-input inventory v1 is `C:\code land\clean-rust\program-infrastructure\governance\inbox\20260927\E4-0-STATIC-INPUT-INVENTORY-v1.json`, SHA-256 `755618754dc51acd9d43e514e8d6a7c78e1eea090910ddeca29a1e8124a06204`, 7,283 bytes. It binds 19 named visible, nontruth roles. It records `protected_label_bytes_opened=false`, `e4_0_authorization_issued=false`, and `extraction_dynamic_inputs_ready=false`.
- The v02 Fabrique candidate has a versioned current-contract verifier in `source/scripts/e4_supervised_execution_adapter_v02.py`; `e4_runner_modes_v07.py` uses it instead of the inherited v09-only verifier. It pins the actual contract, seal-manifest, and postseal-audit hashes and recomputes the 447-member contract seal root.
- The adapter's no-model-contact CPU qualification passed 12 tests. Python compilation passed. No model, tokenizer, CUDA, label, scoring, or protected truth contact occurred.
- The candidate execution spec is `plans/E4-0-LEDGER-EXECUTION-SPEC-CANDIDATES-v02.json`, SHA-256 `116b4c3c4445de61f55355cb1e6ef85ba795cd72567a194e1f030cc6987ee57a`. It is not registered or authorized.
- Chief owns the authoritative static parity binding, its source registration, E4 run/stage grants, and GPU lease. A Fabrique-local binding candidate was preserved separately as `online-cache-parity-binding-v02-local-candidate-not-authoritative.json` (7,258 bytes; SHA-256 `bf0a9b73319f141551d398bc0c676d09c09242ac6cee80c066f32e7e5354e018`). It is not an authoritative input and must not be registered or used.
- The current qualified LibraryAcceptanceV1 identity is `sha256:f98dcd6743c5e8b7ff091cef2d69aa361e53c252711c7b001f3a71d322744602`. The visible-only inheritance bridge root is `aacfd286b6349f0b35adb853a2cd9717c2463fedfeccc052bafaf515c69b027b`. Neither acceptance nor inheritance grants scientific execution authority.
- E4-0 has not run parity or fresh feature extraction under the corrected candidate and has no terminal disposition. E4-01 remains closed.

## Current action boundary

Only Fabrique-owned adapter, verifier, candidate-plan, and synthetic CPU work has been done. Kammi Ledger and Library Lab were not edited. The authoritative binding and all authorization/lease surfaces remain Chief-owned. Wait for Chief's binding/spec disposition and a live stage grant plus fenced GPU lease before E4-0 contact. Do not begin E4-01 until E4-0 is sealed terminal and its eligible artifact lineage is reconciled.
