# FLY-PHENO-00 source lineage

This directory is a fresh source snapshot for FLY-PHENO-00. It contains only the DH-08A Cargo manifests, requirements lock, and `src/**` learner implementation copied before PHENO preparation. It does not contain DH-08A run artifacts, posthoc files, qualification receipts, or the DH-08A target directory.

The graph input snapshot is under `../../inputs/anatomy/` and comes from the shared frozen anatomy input tree, not from a DH-08A result directory. The protected-tree receipt at `../../provenance/PROTECTED-DH08A-TREE-RECEIPT.json` records a before/after SHA-256 root check for the complete DH-08A tree while excluding only its build target junction.

The copied DH-08A source is a lineage input, not the FLY-PHENO measured runner. PHENO-specific masking, evaluator isolation, task-bank, null-graph, and recovery orchestration code must be added under the new study identity and hashed before any measured execution.
