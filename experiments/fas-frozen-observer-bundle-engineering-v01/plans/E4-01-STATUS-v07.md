# E4-01 status — v07

**As of:** 2026-09-28, Day 7 continuation  
**Disposition:** DESIGN_ONLY / ENTRY_GATE_CLOSED  
**Scope:** Updates v06 after E4-0 fresh feature extraction completed. Research-day numbering remains Day 7 across local midnight.

## Current E4-0 state

- E4-0 v16-v09 remains sealed at root 278ae16eeb6852d3efad44221556a87be6df54964471f0870931fe2e99b305d1.
- Online/cache parity passed and is sealed at root 21b5cdd1f1dfbaaa132ffc8cea38f31bb26612bc438fb7e10ac3bffcb673ae73.
- Fresh feature extraction passed. Its stage root is b0395dd693fb115c74540647722c2e8f36c624fb5621097e9eb197b39acff17a; the cache has 149,336 ordered rows and is 1,223,360,512 bytes with SHA-256 49236412bf7409bd5f8d2c15f43436afa17940d51cc4bfdcdaf9d773029deac4.
- The runner passed shape, ordered row identity, quartet order, finite-value, and resource gates. Extractor-process PyTorch CUDA reserved peak was 4,708,106,240 bytes under the 10 GiB limit; process peak working set was 5,888,626,688 bytes under the 25 GiB limit.
- Ledger registered all four extraction outputs, completed the attempt, and released the fenced lease. Local artifact hashes, lengths, and the stage root were recomputed in [the extraction execution receipt](../audits/e4-0-supervised-adapter-v02/ledger-extract-execution-receipt-v01.json).
- This stage emitted no predictions or class support, opened no labels or held-out truth, performed no scoring, and fitted no observers. E4-0 has not reached a terminal disposition.

## Next boundary

Await Chief Kammi's independent custody reconciliation and separate authorization for the E4-0 fresh qualification truth-opening/scoring stage. Use only the exact Ledger worker request and its stage grant. No E4-01 execution begins before E4-0 has a sealed terminal disposition and Chain of Custody reconciles its eligible artifacts.

The E4-01 design remains [E4-01-PLAN-v02.md](E4-01-PLAN-v02.md). Status versions v04, v05, and v06 remain immutable history.

## E4-01 execution status

- No E4-01 run or contract is registered or sealed.
- No E4-01 population, feature source, model, labels, or terminal evaluation have been contacted.
- No E4-01 stage authorization or GPU lease exists.
- Frozen Fabrique remains the only lab scope; use Kammi Ledger for custody and execution, page Chief for infrastructure issues, and do not modify Ledger or Library infrastructure.