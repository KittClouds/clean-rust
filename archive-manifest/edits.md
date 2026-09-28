# Edits made while assembling the freeze

Everything else is byte-identical to its source (see included.tsv).

- Cargo.toml: added member crates/phoenix-vault-adapter (as on codex/phoenix-vault-product-20260927); excluded apps/analysis-bridge, experiments, infrastructure.
- apps/analysis-bridge/phoenix/Cargo.toml: members reduced to the 17 crates phoenix-analysis-bridge needs. Removed (REFERENCE at b50d3c78:rust-native/phoenix/crates/): phoenix-analytics, phoenix-api, phoenix-automata, phoenix-causal-post, phoenix-causality, phoenix-chat, phoenix-discovery-community, phoenix-discovery-query, phoenix-discovery-runtime, phoenix-er-post, phoenix-event-identity-post, phoenix-evidence-graph, phoenix-graph-post, phoenix-graph-rebuild, phoenix-graph-research, phoenix-ingest-overgraph, phoenix-machine, phoenix-memory-post, phoenix-mentions, phoenix-numerology, phoenix-om, phoenix-proposition, phoenix-qps-experiment, phoenix-state-schema-post, phoenix-structure, phoenix-temporal-post, phoenix-text, phoenix-time.
- apps/analysis-bridge/phoenix/crates/phoenix-analysis-bridge/Cargo.toml: phoenix-analysis-contract path now points at the product crate crates/phoenix-analysis-contract.
- scripts/ renamed to tools/; references updated in: README.md, docs/breeze-e2e-qualification.md, docs/graph-shell-release-staging-20260924.md, docs/native-provider-cache-v1.md, docs/QPS_V3_PROMOTION_LOOP.md, docs/QPS_V3_RELEVANCE_REVIEW.md, docs/reader-contracts-v1.md, docs/reader-voices-editor-build-checkpoint.md, docs/shortrun-chapter-quality.md.
- README.md: product README moved to docs/phoenix-README.md; root README describes the freeze.
- Cargo.lock and apps/analysis-bridge/phoenix/Cargo.lock: updated by `cargo check` for the vault adapter and the pruned bridge workspace (SHA-256 in included.tsv is the pre-update source).
- vault-fixture-20260927*.log moved from the root to docs/vault/.
- PHOENIX_NATIVE_STATUS_HANDOFF_2026-07-26.md and PRODUCT_BRANCH_SCOPE_2026-09-23.md moved from the root to docs/.
