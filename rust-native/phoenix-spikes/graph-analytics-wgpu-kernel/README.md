# Offline graph analytics GPU proof

This isolated crate accelerates large, generation-bound graph analytics while
keeping graph truth and deterministic community authority in CPU Rust.

## Implemented batch

One policy mask is computed once and reused by every downstream pass:

- directed in/out degree, incident degree, and relation-family histograms;
- exact integer out-strength and undirected total-strength columns;
- weakly connected-component propagation with a convergence proof;
- multi-source weighted personalized diffusion over an incoming CSR;
- bridge preprocessing from existing authoritative partition labels;
- boundary degree/strength and batch neighbor-degree statistics;
- node, relation-family, and minimum-weight edge policy masks.

The GPU input is a packed 16-byte edge row plus compact node/partition columns.
CPU preparation validates every integer accumulator before dispatch and builds
the incoming CSR. `upload_generation` owns the buffers across the prepartition
batch and a later postpartition bridge pass, with compact stage-specific
readbacks rather than a second graph upload.

## Authority boundary

`phoenix-discovery-community/src/leiden.rs` remains unchanged. This crate has no
Leiden or local-move entry point. GPU component labels and metric inputs may
preprocess a generation, but the order-sensitive, stateful Leiden local-move
loop and the authoritative partition remain deterministic CPU Rust.

The contracts are explicit:

- policy masks, histograms, degrees, component labels, bridge inputs, and
  neighborhood integer columns must be byte-identical to the CPU reference;
- component propagation performs bounded hook/compress rounds and then checks
  every parent and admitted edge; non-convergence returns
  `ComponentsDidNotConverge` and never substitutes a hidden CPU result;
- diffusion is `f32` derived data with a parity tolerance of `1e-6`; the final
  recorded qualification observed at most `1e-8` drift;
- unavailable adapters, insufficient binding limits, excessive residency, and
  malformed inputs return named errors;
- neither `GpuGraphAnalyticsRuntime::analyze` nor the resident API falls back;
- `DispatchPolicy` makes the pre-allocation CPU/GPU choice observable.

Dense minimum node identity is the component label in this proof. A production
adapter that requires stable Phoenix identities must canonicalize the proven
component membership by stable ID on CPU before artifact sealing.

## Measured RTX 3080 result

Windows, Vulkan, NVIDIA driver 591.86. Release build, one warm CPU run and one
warm GPU run per size, then five interleaved measured trials. Each trial runs
32 weak-component rounds and eight diffusion iterations for four sources.
GPU totals exercise the resident lifecycle: CPU validation/CSR preparation,
one fresh generation allocation/upload, prepartition execution/readback, the
CPU-owned partition-label handoff, and postpartition execution/readback. Every
displayed size asserts all integer columns against CPU before printing a result.

| Nodes | Edges | CPU median (range) | GPU median (range) | Median speedup | Resident | Readback |
|---:|---:|---:|---:|---:|---:|---:|
| 1K | 10K | 1.048 ms (0.956-1.779) | 1.965 ms (1.781-2.236) | 0.53x | 0.41 MiB | 0.09 MiB |
| 2.5K | 25K | 3.698 ms (3.134-4.953) | 2.226 ms (2.087-2.753) | 1.66x | 1.02 MiB | 0.22 MiB |
| 5K | 50K | 8.424 ms (8.239-8.705) | 2.866 ms (2.747-3.540) | 2.94x | 2.04 MiB | 0.44 MiB |
| 10K | 100K | 18.265 ms (17.969-18.737) | 4.181 ms (3.990-4.929) | 4.37x | 4.08 MiB | 0.88 MiB |
| 25K | 250K | 56.612 ms (50.847-56.875) | 8.917 ms (7.701-9.137) | 6.35x | 10.20 MiB | 2.19 MiB |
| 50K | 500K | 202.831 ms (191.959-224.826) | 15.064 ms (14.503-20.401) | 13.46x | 20.41 MiB | 4.39 MiB |
| 100K | 1M | 356.776 ms (334.148-558.356) | 46.731 ms (41.943-57.432) | 7.63x | 40.82 MiB | 8.77 MiB |
| 250K | 2M | 1254.276 ms (1069.705-1286.241) | 129.547 ms (107.288-149.965) | 9.68x | 88.69 MiB | 20.03 MiB |

The observed crossover is between 1K/10K and 2.5K/25K for this deliberately
heavy four-source workload. The default policy is conservative: GPU only at
10K nodes, 100K edges, 320K diffusion cell updates, a high-performance adapter,
and within the configured residency budget. Other device classes need their
own qualification rather than inheriting the RTX threshold.

The community caller has no diffusion work, so it has a separate qualification.
With the same resident lifecycle and five trials, structural-only medians were:

| Nodes | Edges | CPU | GPU | Speedup |
|---:|---:|---:|---:|---:|
| 1K | 10K | 0.177 ms | 1.568 ms | 0.11x |
| 10K | 100K | 2.470 ms | 3.454 ms | 0.72x |
| 25K | 250K | 7.842 ms | 6.706 ms | 1.17x |
| 50K | 500K | 16.740 ms | 11.820 ms | 1.42x |
| 100K | 1M | 36.676 ms | 23.127 ms | 1.59x |
| 250K | 2M | 81.440 ms | 46.596 ms | 1.75x |

The structural auto-policy therefore requires 50K semantic-core nodes and
500K admitted edges. It selects CPU before adapter initialization below both
gates; this is an explicit path, not an execution fallback.

## Production integration decision

This is a qualified kernel with a feature-gated shadow coordinator, not a live
production route. `graph-analytics-wgpu-shadow` gives `PhoenixApiImpl` one
long-lived coordinator that caches the adapter/runtime, rejects stale
generations, makes CPU/GPU selection explicit, executes exactly one resident
upload plus one prepartition and one postpartition dispatch, and records path,
adapter, timing, digest, and `fallback_count=0` receipts. Shadow results are
never published and no new TauRPC or Angular action is registered.

The shadow coordinator now also accepts Phoenix's content-addressed
`AssertedDiscoveryView` handle. It reopens the binary with `memmap2`, packs only
the admitted semantic-core edges, canonicalizes GPU weak components by stable
`(hash, collision)` identity, runs the existing order-sensitive Leiden code on
CPU, validates GPU bridge inputs against deterministic Rust, and seals the
existing community artifact format. The qualification fixture reopens both
artifacts and proves byte-identical `communities.bin` and `manifest.json`.
PageRank seeds are optional for this path; zero sources skip only diffusion.

The existing `graphGeneration:prepareAssertedQuery` command now passes its live
mmap handle into this coordinator when the feature is enabled. Its response
includes the selected path and timing receipt; Angular validates and exposes
that receipt and rejects any nonzero fallback telemetry.

The remaining honest production slice is:

1. build and restart the feature-enabled desktop without disturbing the current app;
2. capture the exact live cohort receipt and cold-restart artifact proof;
3. qualify a genuinely GPU-sized live generation and its memory ceiling;
4. consider production community authority only after those gates pass.

## Verification

```powershell
cargo test --manifest-path rust-native\phoenix-spikes\graph-analytics-wgpu-kernel\Cargo.toml --target-dir D:\phoenix-target-graph-analytics-wgpu -- --test-threads=1
cargo clippy --manifest-path rust-native\phoenix-spikes\graph-analytics-wgpu-kernel\Cargo.toml --target-dir D:\phoenix-target-graph-analytics-wgpu --all-targets -- -D warnings
cargo bench --manifest-path rust-native\phoenix-spikes\graph-analytics-wgpu-kernel\Cargo.toml --target-dir D:\phoenix-target-graph-analytics-wgpu --bench offline_analytics
$env:PHOENIX_ANALYTICS_BENCH_MODE='structural'; cargo bench --manifest-path rust-native\phoenix-spikes\graph-analytics-wgpu-kernel\Cargo.toml --target-dir D:\phoenix-target-graph-analytics-wgpu --bench offline_analytics
cargo test --manifest-path rust-native\phoenix\Cargo.toml -p phoenix-discovery-community --features wgpu-shadow --target-dir D:\phoenix-target-graph-community-wgpu -- --test-threads=1
cargo test --manifest-path src-tauri\Cargo.toml --features graph-analytics-wgpu-shadow --target-dir D:\phoenix-target-graph-analytics-coordinator --lib graph_offline_analytics::tests -- --test-threads=1
```
