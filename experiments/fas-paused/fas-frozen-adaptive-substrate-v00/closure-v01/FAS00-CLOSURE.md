# FAS-00 terminal closure

FAS-00 terminates at its sealed Phase 3 sensor disposition, `SENSOR_FAIL_NO_SIGNAL`.
This taxonomy means that a required positive sensor gate failed. It does not mean
that the frozen representation lacked all task information.

The preregistered held-out context-term transfer gate required three-class
balanced accuracy at least 0.60. The sealed result was 0.5654062449331388
on a slice with class counts 212, 134, and 66. The held-out entity-term gate
passed at 0.8119478137166816. Observation state, context and entity identity,
query relation, and exact target also passed their frozen gates. QUERY_ONLY
and metadata-only leakage controls remained below their ceilings.

FAS-00's representation, threshold, corpus, probes, and result are not revised.
No Phase 4, Phase 5, or online mechanism authorization follows from this closure.
Any new representation analysis belongs to a new experiment identity and cannot
retroactively change the FAS-00 disposition.
