# S06 Input Hash Correction v02

The sealed v01 preflight verified S05's complete result tree and every direct
input except the final S01 probability file. It then failed closed before
writing a preflight receipt or any analysis output because the local expected
digest copied into v01 contained `...3cc6de...`. The S01 result manifest and
the file both contain `...3cc6ce...`:

```text
cc1451fdd4823cc6ce139375785af90b087793ce309ec5ec558bcf30593b3b03
```

This correction changes only that expected input identity in a versioned
parent-binding copy and points the new attempt to a separate run directory.
The v01 contract, authorization, features, probes, parent artifacts, and
scientific operations are unchanged. No model contact, extraction, fitting,
or adaptive analysis is authorized or performed by this correction.
