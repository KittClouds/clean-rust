# REQUAL1-PARITY: independent singleton replay audit

This engineering-only audit is downstream of the fresh REQUAL1 singleton
materialization. It uses a separate pure-Python f32 replay implementation over
eight fixed positions in each of the eight immutable singleton shards. The
positions are selected from shard order before inspecting audit outcomes.

For each sampled candidate it independently reconstructs current baseline bytes
from source fixtures and DA2 selected steps, applies the canonical singleton
mapping, computes committed-byte and sequential-readout hashes, recomputes the
score, and recomputes the inherited geometry metrics. Any mismatch fails the
audit. No pair replay or scientific promotion is permitted.
