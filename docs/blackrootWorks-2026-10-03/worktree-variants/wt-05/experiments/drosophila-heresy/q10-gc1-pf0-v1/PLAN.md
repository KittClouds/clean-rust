# Q10-GC1-PF0: Global Palette Support and Conflict Preflight

PF0 audits the qualified PAR2 palette before any global coalition search. It
loads all 801 local palettes, checks canonical group identity and candidate
mapping uniqueness, computes coordinate-conflict and physical-support-overlap
topology, and verifies that the palette library can physically cover every
baseline mismatch in the fixed 14 endpoint/set states.

This is engineering-only and read-only with respect to PAR2. It does not
combine candidates, replay a global endpoint, run GC1 assembly, probe behavior,
or promote science. A false global-assembly gate here means the palette library
or topology is incomplete; it is not global infeasibility.
