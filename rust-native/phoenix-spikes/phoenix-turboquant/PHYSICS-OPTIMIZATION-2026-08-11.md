# Laws-of-physics optimization pass — 2026-08-11

## Decision

Promote the representation-specific 4-bit kernel changes, the 2-bit Rayon
crossover correction, the permanent public-path profiler, and feature-gated
qualification tooling. Reject fused decode-plus-top-k.

The optimized search still consumes the same `.phxq1` artifacts and produces
the same ranked output. No format migration or Phoenix integration is implied.

## Bound machine and build

- CPU: AMD Ryzen 7 5800X3D, 8 cores / 16 logical processors
- Rust: 1.96.0
- LLVM: 22.1.2
- Profile: opt-level 3, fat LTO, one codegen unit, panic abort
- Dimension: 768
- Candidate counts: 1,024 / 4,096 / 16,384 / 65,536 / 100,000
- Top-k: 64
- Samples per public-path cell: 51
- Worker counts: 1 / 2 / 4 / 8 / 16

The profiler uses the immutable projected artifacts from
`D:\phoenix-turboquant-proof-20260810-optimized-topk`.

## What survived measurement

### Four-bit paired-block AVX2

The persisted format remains blocked by eight candidates. The parallel 4-bit
kernel now evaluates two blocks together, keeps four independent u16
accumulator chains, and shares each pair of 16-byte LUT loads across sixteen
candidates. This improves instruction-level parallelism without changing the
artifact.

Scale correction is applied before each 16-score batch is published. That
removes a separate full-score-buffer pass for 4-bit. The same fusion regressed
2-bit and is therefore not used there.

Representative 8-worker public prepared-search medians:

| Rows | Baseline 4-bit | Final 4-bit | Speedup |
| ---: | ---: | ---: | ---: |
| 4,096 | 71.1 us | 57.4 us | 1.24x |
| 16,384 | 201.0 us | 189.4 us | 1.06x |
| 65,536 | 552.8 us | 532.3 us | 1.04x |
| 100,000 | 812.6 us | 770.1 us | 1.06x |

Sixteen-worker results were more scheduler-sensitive, ranging from about
0.73 to 0.89 ms at 100K in final-source repetitions. The bound final receipt
records 0.885 ms; an earlier identical-source repetition recorded 0.731 ms.
The 8-worker comparison above is the more stable adoption number.

### Two-bit crossover

The 2-bit kernel itself remains the prior eight-candidate race engine. At
4,096 rows, Rayon overhead was larger than its lighter scan justified, so its
automatic crossover moved from 4,096 to 8,192 rows. Four-bit remains at 4,096.

Criterion measured the 2-bit 4,096-row end-to-end automatic path improving
from 217.50–228.87 us to 189.75–197.33 us. Criterion's estimated mean change
was -14.58% with p < 0.05.

Final Criterion intervals at 4,096 x 768:

| Path | Estimate interval |
| --- | ---: |
| Exact AVX2 f32 | 335.16–348.75 us |
| 2-bit end-to-end auto | 189.75–197.33 us |
| 2-bit prepared serial | 139.67–149.57 us |
| 4-bit end-to-end auto | 211.19–222.71 us |
| 4-bit prepared serial | 229.64–240.77 us |
| 4-bit prepared Rayon | 112.53–114.22 us |

### Lean build graph

EmbeddingGemma/Jina, Phoenix chunking, frozen-gate, and corpus-census
dependencies are now opt-in Cargo features. A clean `physics_profile` release
build fell from 266.5 seconds to 18.6 seconds, a 14.3x improvement. The final
binary is 391,168 bytes.

## Rejected candidate

Fusing decode, scale, and thread-local top-k removed the full score buffer but
put unpredictable heap maintenance inside every worker's scan loop. At the
best-worker 100K points it regressed roughly 20% at 2-bit and 11% at 4-bit.
That implementation was removed. The result reinforces the processor's
preference for simple streaming SIMD followed by a separate predictable
selection pass.

## Correctness and allocation gates

- All 50 baseline/final public-profile output hashes match.
- Scalar and AVX2 rankings agree.
- Serial and Rayon top-64 results are identical.
- Warmed serial and Rayon search still perform zero heap allocations.
- Mmap authority, corruption rejection, prepared-query binding, deterministic
  encoding, and exact-rerank contracts pass.
- Strict Clippy and formatting pass.

## How far it projects

Using the bound final 8-worker 100K medians and linear arithmetic only:

| Representation | Measured 100K | Projected 1M | Projected 1M QPS | Approx. 1M payload |
| --- | ---: | ---: | ---: | ---: |
| Exact f32 | 10.595 ms | 105.95 ms | 9.4 | 3.072 GB |
| 2-bit | 0.533 ms | 5.33 ms | 187.5 | 204 MB |
| 4-bit | 0.770 ms | 7.70 ms | 129.9 | 396 MB |

These are not 1M measurements. They exclude query rotation/LUT construction,
which measured roughly 40 us for 2-bit and 65 us for 4-bit at 100K, and they do
not predict operating-system paging or concurrent-query contention. The
projection is useful because it shows where the next physical limit moves:
from f32 memory bandwidth toward packed decode, scheduling, and cache residency.

## Receipts

| Receipt | Bytes | SHA-256 |
| --- | ---: | --- |
| `physics-public-baseline-v1.json` | 13,428 | `8b6d16a5d383e53d01c51fa16f16592a3a7347fc54ab653c5235261a7f2bbdab` |
| `physics-public-final-v2.json` | 13,416 | `28efdaf9f07ae06e29bd136931518e8a77ecf5f8568b01d3af3f497222ed5b4c` |
| `physics-phase-final-v1.json` | 19,602 | `07cee387a5e7140bf934c1178fc64ce86321c9f0505e6e7c4255de720e7aaa41` |

Receipt root:

```text
D:\phoenix-turboquant-gate-20260811
```

Final profiler binary:

```text
C:\phoenix-turboquant-physics-test-bin-20260811\physics_profile.exe
SHA-256 117d4abc133af1a61d8431ee02df75e25bd01e9f20891742fa073744b037de5d
```

## Remaining physical frontier

The next serious kernel step requires a new artifact-format experiment:
32-candidate blocking so AVX2/AVX-512 can consume wider contiguous code lanes,
with format-versioned parity and storage receipts. On this AVX2 machine the
current eight-row format is already close enough to the instruction and memory
limits that further local cleverness is unlikely to beat a representation
change.
