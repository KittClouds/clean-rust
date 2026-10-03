# VMAT1 independent finalizer

This read-only identity audits the sealed current-lineage VMAT1 materialization.
It verifies domain coverage, sidecar/index integrity, parent immutability,
unexpected-path hygiene, and a deterministic stratified sample reconstructed
through an independent calculation path. It cannot alter VMAT1 and cannot open
CSC1-R1 unless every audit gate passes.
