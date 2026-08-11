# Surgical optimization report - 2026-08-10

## What the phase instrumentation found

The initial 16,384-row float-gather implementation spent almost all useful time
inside artifact traversal, packed decode, and accumulation.

| Width | Rotation | Float LUT | Scan/decode/accumulate | Scale | Top-64 | Prepared fused |
|---:|---:|---:|---:|---:|---:|---:|
| 2 | 8.4 us | 162.9 us | 1,564.8 us | 2.1 us | 77.3 us | 1,782.8 us |
| 4 | 8.7 us | 163.4 us | 3,585.6 us | 1.9 us | 80.0 us | 3,693.4 us |

The old LUT occupied 196 KiB at 2-bit and 393 KiB at 4-bit. Scale correction
was negligible. Top-k mattered, but decode/accumulation was the first target.

## Kernel changes

The generic packed-byte float-gather path was replaced with independent race
engines:

- 2-bit: four codes per byte, split into two two-coordinate nibble tables;
- 4-bit: two codes per byte, one coordinate per nibble table;
- 12 KiB u8 query LUT at either width;
- shared per-query scale and accumulated per-subtable bias;
- AVX2/SSSE3 byte shuffles;
- safe u16 low/high accumulation, converted to f32 once per eight candidates;
- no per-row decode allocation or temporary vector.

At 16K this reduced the scan phase to roughly 0.35 ms at 2-bit and 0.67 ms at
4-bit: approximately 4.4x and 5.3x scan improvements respectively. Query LUT
construction fell to roughly 30 us at 2-bit and 54 us at 4-bit.

## Top-k changes

The first parallel path scanned into reusable scores but retained top-64 using
one serial heap. At 100K that cost about 400 us.

The final path assigns each 4,096-row chunk a reusable fixed-capacity min-heap,
runs those heaps in parallel, and merges only the local winners. At 100K and 16
workers, top-64 fell to 117 us at 2-bit and 121 us at 4-bit. Both the serial and
Rayon warmed paths remain at zero heap allocations.

## Worker crossover

> Historical receipt: the 2026-08-11 physics pass subsequently raised the
> 2-bit automatic crossover to 8,192 rows while retaining 4,096 for 4-bit.
> See `PHYSICS-OPTIMIZATION-2026-08-11.md`.

The phase receipt used persistent Rayon pools with 1, 2, 4, 8, and 16 workers.
Selected total times, including preparation and top-64:

| Rows | Engine | 1 worker | 4 workers | 8 workers | 16 workers | Best |
|---:|---|---:|---:|---:|---:|---:|
| 16,384 | f32 | 1.311 ms | 0.389 ms | 0.297 ms | 0.347 ms | 8 |
| 16,384 | 2-bit | 0.473 ms | 0.209 ms | 0.192 ms | 0.258 ms | 8 |
| 16,384 | 4-bit | 0.819 ms | 0.304 ms | 0.256 ms | 0.317 ms | 8 |
| 100,000 | f32 | 16.133 ms | 10.337 ms | 10.479 ms | 10.746 ms | 4 |
| 100,000 | 2-bit | 2.815 ms | 0.782 ms | 0.553 ms | 0.599 ms | 8 |
| 100,000 | 4-bit | 4.868 ms | 1.345 ms | 0.966 ms | 0.891 ms | 16 |

Exact f32 scales poorly after its working set leaves comfortable cache because
the scan becomes memory-bandwidth-bound. The compressed streams continue to
scale because substantially less memory crosses the hierarchy.

The public automatic policy does not construct pools per query; it uses the
caller's persistent Rayon context. The final thresholds are 8,192 rows for
2-bit and 4,096 rows for 4-bit. Applications that own dedicated pools can use
the explicit `SearchExecution` policy and tune worker counts from the receipts.

## Top-k sweep

At 16K, the original diagnostic serial retention loop cost approximately:

| k | Loop and retention cost |
|---:|---:|
| 0 | 49.6 us |
| 1 | 62.9 us |
| 8 | 64.3 us |
| 32 | 69-72 us |
| 64 | 77-80 us |

The base loop over every score is most of that cost. Parallel fixed local heaps
become valuable at larger cohorts; a more elaborate branchless selection
structure is not justified by the remaining profile.

## Criterion cross-check at 4,096 x 768

Twenty-sample estimate intervals after warm-up:

| Path | Estimate interval |
|---|---:|
| exact serial AVX2 f32 | 320.87-344.40 us |
| 2-bit end-to-end auto | 198.34-217.23 us |
| 2-bit prepared serial | 142.60-148.22 us |
| 2-bit prepared Rayon | 134.06-143.52 us |
| 4-bit end-to-end auto | 338.27-359.48 us |
| 4-bit prepared serial | 233.27-254.18 us |
| 4-bit prepared Rayon | 155.09-188.03 us |

The final automatic threshold was lowered to 4,096 for 4-bit after this
cross-check. Query preparation is intentionally visible rather than hidden in
the scan result.
