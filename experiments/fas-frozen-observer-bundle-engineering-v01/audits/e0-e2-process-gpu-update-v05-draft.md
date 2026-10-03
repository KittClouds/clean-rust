# E0 v05 / E2 v02 process GPU update (draft)

**Status:** `DRAFT_NOT_FROZEN_NOT_AUTHORIZED`  
**Project:** `fas-frozen-observer-bundle-engineering-v01`

This version proposes a resource-measurement amendment after E2 v01 completed while an independent FAS-S12 workload was using the same RTX 3080. The E2 v01 preservation root remains `0ff309d833cd87017f7384247e4420a508f582ad9f375c5637f586d73b703f4c`; its GPU resource gate remains `UNVERIFIED`. Its cache is not reused and is not eligible for fitting.

## Frozen predecessors

- E0 v04 root: `fef50e3d7efe6ff35adf671940ee73112caf8ba6192596094aa6bb3e69ae9ab2`.
- E1 v04 root: `6ba77a899363651e3ba119b005f59a22e86f011f83c86b873857cd3f9ab64b03`.
- E2 v01 remains preserved with the unverified disposition above.

The E1 population, split, labels, support, task definitions, score floors, pinned model revision, and `V1_FINAL_POSITION` tensor are unchanged. Representation ABI v02 changes its extractor-source binding and adds no alternate surface.

## Process-specific GPU gate

The exact claim is: **“E2 GPU gate = extractor-process PyTorch CUDA caching-allocator reserved peak; not total GPU memory used by E2.”** `torch.cuda.max_memory_reserved(cuda:0)` is a process-local PyTorch caching-allocator metric. It does not include every CUDA context, driver, or other non-PyTorch allocation. Terminal receipts must repeat this scope and set `total_gpu_memory_claimed=false`; device-wide `nvidia-smi` totals remain diagnostics only.

After CUDA initialization, before resetting peak statistics, E2 v02 records current allocated, current reserved, peak allocated, and peak reserved bytes for the extractor process. All four must be exactly zero. It then resets peak statistics and records all four counters again; these must also be exactly zero immediately before tokenizer loading or model transfer. Any nonzero counter stops the run before model/tokenizer loading and leaves an allocator-preflight failure receipt. This prevents pre-existing allocator state from being silently charged to the measured interval.

The reset-to-final-synchronize interval covers model transfer, the registered 256-row deterministic repeat, and the single full-panel extraction.

The 10 GiB gate uses that process's `torch.cuda.max_memory_reserved(cuda:0)` value. It also records current and peak allocated/reserved bytes, extractor PID, parent PID, executable, command line, device, and sampling interval. Peak allocated must not exceed peak reserved. The script writes the cache and a failure receipt before stopping if the gate fails.

`nvidia-smi` used/free memory is sampled separately as a device-wide contention diagnostic. It is never attributed to the extractor PID or substituted for the process gate. E2 v02 uses PyTorch for model and tensor allocations, but that does not make the allocator metric total process VRAM or total E2 GPU memory. A resource receipt must retain this measurement scope.

## Representation-equivalence gate

E2 v02 hashes the preserved E2 v01 cache at the pinned read-only path `D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e2-v01\cache\V1_FINAL_POSITION.f32le` before model/tokenizer contact and again after extraction. The required reference identity is SHA-256 `8eb80df5f73e761fe6c025fc1c66abef2027d639b6c14f56d4177d6e6a7a45a4`, length `872415232` bytes. After producing the v02 cache, require both exact SHA-256 equality and exact byte-length equality with that reference.

The v01 cache is a read-only comparator only. It is not reused as v02 feature input and remains ineligible for observer fitting because its E2 process GPU gate is unverified. If the reference changes, or if the new cache differs by even one byte, preserve the new cache and failure receipt and stop. Do not substitute a tolerance-based comparison or repair the output in place. This is a prospective gate demonstrating that telemetry-only instrumentation did not change the representation bytes.

The versioned Windows resource sampler records the extractor PID's current and peak working set, host-available memory, D: free bytes, and raw device-wide `nvidia-smi` fields at 10-second intervals. It verifies the PID still runs the declared extractor and stops with an explicit status if the PID exits or is reused.

Capture one device-wide `nvidia-smi` snapshot before tokenizer/model contact and one after the extractor exits. Keep these baseline and postflight files beside the raw 10-second sampler CSV; they explain shared-device conditions but do not change the PID-scoped gate.

## Wait gate

Before E2 v02 imports model/tokenizer libraries or contacts CUDA for model work, a read-only waiter checks the observed process identity:

```text
PID:       34332
Executable C:\Users\shuga\AppData\Local\Programs\Python\Python313\python.exe
Script:    D:\codex-runs\fas-s12-observer-plane-causal-dependence-v01\run-v02\source\run_s12_v02.py
Started:   2026-09-25 20:08:43 local time
```

The waiter also searches for relaunches of that exact script path under other PIDs. It records two consecutive empty process snapshots at least 30 seconds apart. It never terminates, suspends, or reprioritizes the concurrent process. If the process is still present, the status stays `WAITING`; a PID reused by another program does not count as the FAS-S12 run.

The completion receipt path is `audits/e2-v02-concurrent-wait-complete-v01.json`. E2 v02 must verify this exact path and its SHA-256 before model or tokenizer contact.

## Authority boundary

These artifacts are a proposal. E0 v05 has not been sealed. E2 v02 has not been authorized. No new model load or extraction is permitted from this draft. After the concurrent run exits, preserve its wait receipt, review and seal E0 v05, then obtain a separate explicit authorization for E2 v02. Successful E2 v02 still does not authorize E3 fitting or scoring.

Normative machine-readable files: [`e0-freeze-v05-draft.json`](../contracts/e0-freeze-v05-draft.json), [`e2-run-v02-draft.json`](../contracts/e2-run-v02-draft.json), and [`representation-abi-v02.json`](../contracts/representation-abi-v02.json). These remain drafts; the additions do not seal E0 v05 or authorize E2 v02.
