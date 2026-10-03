# F4-SYMMETRY-01 implementation amendment v0.2

**Applies to:** `F4-SYMMETRY-01-IMPLEMENTATION-SPEC-v0.1.md`  
**Controlling experimental contract SHA-256:** `cfef638aaeac1dfc0b768d13cc95afe7724861f74e3d3111d91401925bed6379`  
**Scope:** implementation preflight only; no scientific contract value changes.

## 1. Source manifest digests

`source_manifest_sha256` is the SHA-256 of the manifest JSON value serialized as UTF-8 compact JSON with lexicographically sorted object keys, no insignificant whitespace, and no trailing LF. This is a canonical digest independent of the human-readable file formatting.

The on-disk `SOURCE-INPUT-MANIFEST.json` is UTF-8 JSON with lexicographically sorted object keys, two-space indentation, and exactly one trailing LF. Record its byte-level digest separately as `source_manifest_file_sha256 = SHA256(on_disk_file_bytes)`. The two fields must not be conflated. Verify that parsing the on-disk file and compact-canonicalizing the resulting JSON value reproduces `source_manifest_sha256`.

## 2. Deterministic numerical-library thread policy

Before importing NumPy or any package that can initialize a BLAS/OpenMP runtime, the preflight and every fit process set and require these values:

```text
OPENBLAS_NUM_THREADS=1
OMP_NUM_THREADS=1
MKL_NUM_THREADS=1
BLIS_NUM_THREADS=1
VECLIB_MAXIMUM_THREADS=1
NUMEXPR_NUM_THREADS=1
```

The implementation records the effective environment and NumPy build configuration in the preflight receipt. If a loaded numerical runtime reports more than one worker, stop before fitting. Do not alter these settings between the preflight, fits, repeated prediction check, or analysis.

## 3. Authority and interpretation

This amendment only resolves serialization and numerical-runtime details already identified in implementation review. The fit matrix, feature definitions, gates, target, endpoints, and claim ceiling remain those in the v0.1 implementation specification and frozen contract. No measured REACH-03 namespace or PHENO change is authorized by this amendment.
