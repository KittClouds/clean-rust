# Candidate Presentation Validation Microbenchmark

- Date: 2026-09-25
- Target: `x86_64-pc-windows-msvc`, Rust 1.96.0 release profile
- CPU: AMD Ryzen 7 5800X3D
- Harness: Criterion 0.5.1, 20 samples, 2-second warmup and measurement per case
- Workload: validate the same encoded receipt and ordered candidate slice repeatedly; receipt creation is outside the timed loop.

| Candidate count | Central estimate | Criterion interval |
| ---: | ---: | ---: |
| 4 | 478.1 ns | 468.0–490.3 ns |
| 16 | 1.475 μs | 1.433–1.516 μs |
| 64 | 8.583 μs | 8.239–9.005 μs |
| 256 | 66.327 μs | 63.578–69.012 μs |

| Candidate count | Producer-order restoration estimate | Criterion interval |
| ---: | ---: | ---: |
| 4 | 34.34 ns | 33.09–36.05 ns |
| 16 | 188.98 ns | 173.87–206.98 ns |
| 64 | 1.133 μs | 1.116–1.158 μs |
| 256 | 13.219 μs | 12.859–13.741 μs |

Receipt validation makes no heap allocations. Producer-order restoration also sorts in place; setup cloning is outside its timed loop. Duplicate checks are pairwise and bounded to 256 options. The common four-option validation workload is under 0.5 μs here. These figures characterize this host and benchmark loop; they are not end-to-end observer latency claims.
