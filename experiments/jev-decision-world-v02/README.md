# Jev-like decision world v0.2

This crate contains the architecture-neutral semantic substrate and the
source-specific normalizers used by the Mixed Corpus Bridge. It does not train
models and does not access Phoenix production data.

The v0.2 bridge extensions are explicit:

- E01: structured pre-render entities, mentions, and relations.
- E02: probability-source taxonomy and optional raw annotation counts.

Every adapter returns a `CanonicalEpisode`; `validate_episode` is the required
boundary before census, overlap, or split work.
