# Candle Trainer Performance and Reproducibility Gate v1

## Purpose

This gate proves that the isolated Candle MLP-16 trainer remains measurable,
reproducible, test-locked, and cheaper to restart than to retrain. Performance
telemetry is deliberately excluded from frozen model identity: wall time and memory
high-water marks may vary, while weights, scores, certificates, and model identity
must not.

## Measured execution receipt

Every successful `CandleTrainerReport` records:

- Candle training microseconds;
- Candle validation, canonical SIMD scoring, complete validation certification,
  artifact writing, restart opening, and restart scoring microseconds;
- process allocation request count and byte volume from authority opening through
  restart certification;
- Windows `PeakWorkingSetSize` for the isolated trainer process;
- exact graph, tensor, topology, and restart-weight mmap bytes;
- exact dense row-staging bytes for train rows, validation rows, and the contiguous
  validation feature matrix;
- BLAKE3 identities for weights, validation score bits, validation certificates,
  and the final frozen model.

The allocation counter wraps the system allocator and therefore observes Candle
worker-thread allocations. It counts requested bytes, including successful realloc
requests, rather than estimating retained heap. Peak working set is the operating
system's process high-water mark and is not inferred from allocator traffic.

## Memory path

Authority validation now opens each source artifact once. The validated topology
mmap is retained for zero-copy row decoding instead of being reopened. A first pass
counts train and validation rows; the second pass fills exactly-sized vectors. Test
rows are skipped before feature materialization.

`sourceMmapBytes` is the sum of the immutable graph, tensor, and topology binaries.
`restartWeightMmapBytes` is the frozen weight blob. `mmapBytes` is their checked sum.
`denseStagingBytes` uses vector capacities and concrete Rust row sizes, so it measures
reserved dense payload rather than a logical estimate.

## Reproducibility gate

The integration gate executes the same certified seed twice and requires identical:

- weight BLAKE3 and physical artifact paths;
- validation score BLAKE3;
- binary and ranking certificate BLAKE3;
- validation metrics and ranking metrics;
- frozen model ID.

A third execution uses another seed from the same certificate and must produce a
different weight digest, validation score digest, certificate digest, and model ID.
Telemetry differences do not affect these identities.

## Pre-scoring failure shields

Seed, protocol, dataset, tensor, topology, split-policy, and audit authority are
validated before model construction, training, or scoring. A source-identity drift
and a single corrupt topology byte both fail with zero model artifacts written. This
ensures corrupt or mixed-source inputs cannot reach validation scoring.

## Performance gate

For 1,024 training rows, 256 validation rows, four epochs, and 64-row batches, restart
open plus inference must be at least twice as fast as training and the complete smoke
must remain below ten seconds.

Windows MSVC release evidence on the local Ryzen 7 5800X3D:

| Counter | Result |
|---|---:|
| End-to-end wall | 20.844 ms |
| Training | 7.340 ms |
| Canonical SIMD scoring | 0.028 ms |
| Mmap restart open plus scoring | 1.167 ms |
| Allocation volume | 11,034,676 bytes |
| Peak working set | 6,254,592 bytes |
| Total mmap bytes | 114,676 bytes |
| Exact dense staging | 105,472 bytes |

The measured restart is 6.29 times faster than retraining.
