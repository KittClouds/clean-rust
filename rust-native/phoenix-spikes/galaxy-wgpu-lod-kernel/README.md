# Galaxy wgpu LOD preprocessing proof

This isolated crate tests GPU presentation preprocessing without changing the
production Galaxy store builder. Stable identities, topology, artifact writes,
and graph truth remain CPU/mmap authoritative.

## Boundary

The GPU may compute:

- finite position bounds;
- presentation Morton keys and tile identities;
- LOD centroid, bounds, density, and node-to-LOD presentation mapping;
- raw edge bundle keys for measurement only.

The CPU retains:

- stable identities and immutable topology;
- deterministic sorting and bundle reduction;
- artifact generation and authority receipts;
- all policy and truth decisions.

Full Morton keys are repeat-identical on the tested adapter. They are not
claimed byte-identical across CPU and GPU because floating-point contraction
can change low quantization bits. In the parity fixture, 231 of 32,777 full
keys differed only below the selected tile prefix; bounds and tile membership
were exact. This is permitted only because Morton ordering and LOD are
presentation data.

## Measured RTX 3080 result

Release benchmark, Vulkan backend, six tile bits, five warm samples for
resident spatial and LOD stages:

| Nodes | Edges | Stage | CPU | GPU prepare | GPU execution | One-shot GPU |
|---:|---:|---|---:|---:|---:|---:|
| 100K | 200K | spatial | 2.45 ms | 0.66 ms | 1.65 ms | 2.31 ms |
| 500K | 1M | spatial | 11.97 ms | 0.76 ms | 5.90 ms | 6.66 ms |
| 1M | 2M | spatial | 31.45 ms | 1.90 ms | 13.37 ms | 15.27 ms |
| 100K | 200K | LOD | 2.41 ms | 0.47 ms | 3.75 ms | 4.22 ms |
| 500K | 1M | LOD | 18.62 ms | 1.75 ms | 12.07 ms | 13.82 ms |
| 1M | 2M | LOD | 21.94 ms | 3.51 ms | 13.71 ms | 17.22 ms |

The initial CPU comparison sort took 3.98 ms, 23.49 ms, and 52.83 ms at the
same node counts. A reusable six-pass, 11-bit stable radix workspace now
preserves exact `(Morton key, node identity)` ordering without moving a second
key per record. Three release runs measured:

| Nodes | Comparison sort range | Radix range | Reusable scratch |
|---:|---:|---:|---:|
| 100K | 3.97-4.25 ms | 2.44-3.09 ms | 0.77 MiB |
| 500K | 24.69-30.84 ms | 14.24-17.85 ms | 3.82 MiB |
| 1M | 51.28-57.25 ms | 28.71-29.41 ms | 7.64 MiB |

The byte-identical radix lane is installed in the production Galaxy builder.
Its scratch buffers are reused across all manifolds in one generation and do
not alter page formats, authority receipts, or downstream ordering.

Raw edge remap is rejected for production in the current shape. At one
million edges it took 12.92 ms GPU end-to-end versus 7.89 ms CPU; at two
million edges it took 34.77 ms versus 12.19 ms. It should be reconsidered only
if edge buffers, remap output, sorting, and reduction all remain GPU-resident.

## Integration gates

No production feature flag should be added until a narrow adapter proves:

1. current-corpus visual parity for every manifold;
2. exact tile membership and exact node-to-LOD/edge-key identity mapping;
3. bounded centroid and density drift;
4. cancellation and generation checks around every result install;
5. a device policy that keeps the CPU lane below the measured crossover;
6. no readback for data consumed only by the renderer.

The initial routing hypothesis is GPU spatial work at roughly 250K or more
resident nodes, GPU LOD only above its measured crossover, and CPU edge remap.
That threshold must be calibrated on supported device classes before shipping.

## Commands

```powershell
cargo test --manifest-path rust-native\phoenix-spikes\galaxy-wgpu-lod-kernel\Cargo.toml --target-dir D:\phoenix-target-galaxy-wgpu-lod -- --test-threads=1
cargo clippy --manifest-path rust-native\phoenix-spikes\galaxy-wgpu-lod-kernel\Cargo.toml --target-dir D:\phoenix-target-galaxy-wgpu-lod --all-targets -- -D warnings
cargo bench --manifest-path rust-native\phoenix-spikes\galaxy-wgpu-lod-kernel\Cargo.toml --target-dir D:\phoenix-target-galaxy-wgpu-lod --bench galaxy_gpu
```
