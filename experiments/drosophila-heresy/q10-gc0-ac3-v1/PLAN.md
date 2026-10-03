# Q10-GC0-AC3: Raw-Group Authority Expansion

AC3 expands the sealed AC2 authority instrument to every raw PF5 group-coordinate
context in the fixed RA1 sample. It reuses complete AC2 observations and measures
only the partial or missing contexts identified by RA1. A prefix effect is keyed by
endpoint/set/coordinate; a contextual feature is keyed by endpoint/set/group and
coordinate.

This is an engineering-only qualification. It does not generate candidates, run
GC1, probe behavior, or promote science. Existing AC2 files are immutable. The
runner writes only below this protocol root and fails closed on parent drift,
sample drift, raw-group drift, non-finite effect bits, incomplete prefix domains,
or support mismatch.

Success means that the merged AC2 plus AC3 records form complete authority
coverage for every RA1 raw group-coordinate context and that complete authority
support equals the already-qualified raw PF5 support. This is an instrument gate,
not evidence that a global endpoint exists or that an authority-aware constructor
is optimal.
