# Jev C100 curated training candidate

Status: gated candidate only. The strict run is underfilled at 93,252 groups,
so this is not promoted or labeled as a complete C100. This directory is not
an active training set and does not contain model, compiler, or
protected-evaluation changes.

The candidate is selected from the v06 synthetic stress universe, using only
training-side source metadata and source gold structure. Root families are the
parent-chain roots used by the frozen v06 splitter. Every episode belonging to
a selected root is retained together. The selector excludes roots used by the
current v05 `s100k` and v06 `s250k` training banks, non-training hash buckets,
and any root with an exact or case/whitespace-normalized observable-text hash
collision against current training. Non-training source buckets are read only
for family accounting and never selected; protected evaluation-bank rows and
model predictions are not read.

## Discovered source and current material

- Source episodes: `D:\\codex-runs\\jev-frozen-scaling-v06\\synthetic-stress\\stress-episodes.jsonl`
- Source metadata: `D:\\codex-runs\\jev-frozen-scaling-v06\\synthetic-stress\\stress-metadata.jsonl`
- Current original 100k training material: `D:\\codex-runs\\jev-frozen-scaling-v05\\banks\\s100k\\train.jsonl`
- Current 250k training material: `D:\\codex-runs\\jev-frozen-scaling-v06\\banks\\s250k\\train.jsonl`

The exact byte counts and SHA-256 receipts for these paths are in
`source-receipt.json`. Current-set counts and fingerprints are in
`current-set-audit.json`.

The strict eligible remainder is only the `system_diagnosis` world family
(1,132 roots). The `network_incident` and `support_routing` source families
are not silently mixed back in because their current-family/text firewall
would be violated. This is a coverage limitation and part of the fail-closed
status, not evidence of a three-family C100.

## Outputs

- `train.jsonl`: gated C100 candidate episodes.
- `selected-metadata.jsonl`: compact audit metadata and fingerprints per episode.
- `selection-manifest.json`: selection policy, counts, root list, and output digests.
- `overlap-audit.json`: exact, normalized, semantic-family, and structural overlap.
- `geometry-audit.json`: training-side coverage and available/unavailable fields.
- `source-receipt.json`: input receipts.
- `curate_c100.py`: reproducible streaming selector; 605 LoC.
- `tests/test_curation.py`: lightweight deterministic helper and artifact checks.

Overlap is classified as follows:

1. Exact episode identity: stable `episode_id` equality.
2. Exact surface duplicate: SHA-256 of observable text.
3. Near duplicate: SHA-256 after Unicode-preserving case folding and whitespace
   collapse.
4. Semantic-family overlap: shared parent-chain root or shared canonical
   `identity.semantic_fingerprint`.
5. Related surface rendering: shared model-facing structural fingerprint,
   excluding surface text and gold outcomes. This is reported, not silently
   treated as semantic-family overlap.

The requested D1/D2/D4 balance is not a canonical field in v06. The report
therefore exposes only `D1_proxy`, `D2_proxy`, and `D4_proxy` derived from the
generator's `candidate_distances`; these are diagnostic and not promoted to a
scientific D1/D2/D4 claim. Causal topology and numeric intervention magnitude
are likewise reported unavailable where the source does not provide them.

## Reproduce

From the repository worktree:

```powershell
python experiments/jev-curated-c100-v01/curate_c100.py
python -m unittest discover -s experiments/jev-curated-c100-v01/tests -p "test_*.py"
```

The default output directory is this directory. Override all source paths with
`--source-episodes`, `--source-metadata`, `--current-v05`, `--current-v06`, and
`--out` when reproducing on another machine. The selector is deterministic for
the same inputs and `--seed`.

## Handoff boundary

The strict boundary is fail-closed: the available eligible universe cannot
support a defensible fixed 100k after exact/normalized surface exclusion. The
later Jev training/evaluation task must not silently pad this file or promote it
as C100. It is also single-world-family after the current firewall. The
smallest safe next step is a separately audited unused source lane or an
explicit boundary revision. This curation pass makes no claim that the
underfilled candidate improves LFM accuracy, calibration, or OOD behavior.
