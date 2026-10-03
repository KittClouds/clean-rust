# Q10-GC0-RA1: Raw-Group Authority Coverage Audit

Q10-GC0-RA1 is an engineering-only gate. It asks whether the sealed Q10-RH1-AC2
authority table covers every unique endpoint/set/coordinate pair in the 801 raw
PF5 groups returned for the sealed 14 endpoint/set Q10-GC0 sample.

The runner verifies the sealed UB1, GC0, RH1-F2, AC2, common-runtime, and PF5
bindings before loading the RH1-F2 runtime. It then loads the same 14 sample
keys, checks all raw group identities and size strata, and reads only AC2
feature/effect metadata. Each unique raw pair is classified as:

* `complete`: AC2 feature and effect observations exist, the sealed legal-prefix
  vocabulary is fully accounted for, every effect is complete and finite, and
  AC2 physical support matches the current runtime support for the pair;
* `partial`: some AC2 observation or legal-prefix/effect information exists but
  the complete authority conditions are not satisfied;
* `missing`: no usable AC2 feature/effect observation exists for the pair.

The audit reports pair and group counts, coverage by fixed raw-group size
stratum, required missing pair identities, and the union of physical support
rows contributed by complete-authority coordinates relative to the complete
raw-support upper bound. Pair identities are metadata only; unrelated artifact
bodies and effect vectors are never emitted.

This protocol does not construct candidates, replay prefixes, run GC1, probe
behavior, promote science, or write any parent directory. A future full
authority palette may proceed directly only if every raw pair is complete and
complete-authority support equals the raw physical-support upper bound. Any
partial or missing pair requires authority expansion before the qualified
authority-aware constructor can be used.
