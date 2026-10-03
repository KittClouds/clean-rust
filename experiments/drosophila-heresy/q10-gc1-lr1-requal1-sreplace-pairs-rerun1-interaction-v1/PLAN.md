# Fresh pair interaction replay

This engineering-only identity independently replays the sealed 4,999-pair
domain from the clean rerun parent and records exact interaction residuals for
committed weights, sequential-f32 readout values, linear-drive vectors, axis,
and norm. It does not alter the parent, use historical evidence, or open
behavior. All replay arithmetic is exact learner-order arithmetic; no additive
surrogate is used for the measurements.

Execution hygiene is sealed: Python `-B`, `PYTHONDONTWRITEBYTECODE=1`, no
preflight cache, and an allowlist of eight shard JSONL files plus execution and
status receipts.
