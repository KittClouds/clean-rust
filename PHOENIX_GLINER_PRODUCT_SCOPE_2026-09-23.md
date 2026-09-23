# Phoenix GLiNER2.5 product bridge — 2026-09-23

Branch: `codex/phoenix-product-gliner25-bridge-20260923`

This branch starts from the existing `clean-rust` Phoenix baseline and records
only the GLiNER2.5 worker, IPC contract, analysis-bridge integration, and the
bridge workspace lockfile change found in the shared checkout. It complements
`KittClouds/phoenix-native` branch
`codex/phoenix-native-product-reader-manifolds-20260923` at commit
`97b006bcb33a0cc52ee27b7883d82c9458ca16c3`.

No QPS, memory-lock, JEV, adaptive-runtime, or other agent science changes are
added on this branch. The shared checkout and those agents' branches remain
untouched. The bridge's model and runtime paths are deployment inputs; source
compilation alone is not a combined packaged-app acceptance result.
