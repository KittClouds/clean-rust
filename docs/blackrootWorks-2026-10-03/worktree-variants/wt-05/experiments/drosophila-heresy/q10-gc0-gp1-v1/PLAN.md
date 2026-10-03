# Q10-GC0-GP1: Full Raw-Group Candidate Palette

GP1 builds the authority-aware local candidate palette for all 801 raw PF5
groups in the fixed RA1 sample. It consumes the complete merged AC2 plus AC3
authority table and the qualified PF0 workload contract. Each group receives a
ZERO candidate and up to eight exact-replayed nonzero candidates using the
sealed authority ranking, horizon `min(32, group size)`, inherited beam and
geometry settings, and canonical coordinate-to-prefix identity.

The runner streams one immutable group receipt per line and writes no parent
artifact. A completed group is not a completed protocol: only the final
execution receipt, support gate, hashes, and all-group count can qualify GP1.
GP1 does not assemble groups globally, run GC1, probe behavior, or promote
science.
