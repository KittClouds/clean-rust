# E4-01 status — v05

**As of:** 2026-09-27, Day 7 (same research day)  
**Disposition:** `DESIGN_ONLY / ENTRY_GATE_CLOSED`  
**Scope:** E4-01 remains unopened. This snapshot updates v04 after the authorized E4-0 parity stage; it does not authorize another stage.

## Current E4-0 state

- The scientific E4-0 contract remains v16-v09, SHA-256 `21fc77d5a288b9adef995d88f089890235f8dcb2fbc3c9e452725bb67892a22f`, seal root `278ae16eeb6852d3efad44221556a87be6df54964471f0870931fe2e99b305d1`.
- The Ledger-supervised `E4_0_ONLINE_CACHE_PARITY_V1` stage completed under its own grant and fenced GPU lease. The lease was released and the Ledger custody audit reconciled the registered outputs.
- Runner disposition: `ONLINE_CACHE_PARITY_PASS`. The feature cache matched the sealed E1 FIT cache byte-for-byte, maximum absolute deviation was `0.0`, and each of the five frozen heads had 100% prediction agreement on the label-free parity panel.
- Extractor-process PyTorch CUDA reserved peak was 4,708,106,240 bytes, below the frozen 10 GiB limit. The pre-load and post-reset allocator baselines were zero. Device-wide memory was diagnostic only (`total_gpu_memory_claimed=false`).
- The stage-seal root is `21b5cdd1f1dfbaaa132ffc8cea38f31bb26612bc438fb7e10ac3bffcb673ae73`. Local output hashes and lengths and the root recomputation are recorded in [the parity execution receipt](../audits/e4-0-supervised-adapter-v02/ledger-parity-execution-receipt-v01.json).
- Ledger custody audit artifact: `sha256:beb9b8706e3354c5fd89e52e8e337491fbc51ba3596d6b38924cbdee2b3e532b`; audit seal root: `7feff4b681264214935e8ddb7ccddeccc8c9964362042553cbcaffcc984e4572`.
- This was the E1 FIT parity panel only. No E4 population rows were read, no fresh E4 features were extracted, no held-out truth or labels were opened, and no E4 scoring was performed. Independent scientific metric replay remains pending.

## Next boundary

Wait for Chief Kammi's separate Ledger worker request, stage grant, and fenced lease for E4-0 fresh feature extraction. Do not launch that stage from the parity authorization. After extraction, follow the sealed E4-0 stage sequence and its separate truth/scoring authorization.

E4-0 has no terminal disposition yet. E4-01 remains closed until E4-0 reaches a sealed terminal disposition and Chain of Custody reconciles the eligible inherited artifacts. The current design is [E4-01-PLAN-v02.md](E4-01-PLAN-v02.md); v04 and earlier status snapshots remain unchanged history.

## E4-01 execution status

- No E4-01 run or contract is registered or sealed.
- No E4-01 population, feature source, model, labels, or terminal evaluation have been contacted.
- No E4-01 stage authorization or GPU lease exists.
- The E4-01 activation boundaries remain in force: Frozen Fabrique only; use Kammi Ledger for custody and execution; page Chief for infrastructure issues; do not bypass GPU leases or modify Ledger/Library infrastructure.
