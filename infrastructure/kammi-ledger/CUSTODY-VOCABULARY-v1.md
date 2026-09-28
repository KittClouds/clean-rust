# Kammi custody assertion vocabulary v1

This is Library Lab's controlled vocabulary for imported historical assertions.
The authoritative record is the CAS object plus journal event. Ladybug indexes it.
An assertion cites a registered evidence artifact and has a scope; it does not
grant execution authority or turn a legacy self-report into direct observation.

`FactRecorded` has exactly these fields: `run_id`, `kind`, `subject`, `object`,
`value`, `evidence_artifact`, and `scope`. Its `fact_id` is domain-separated
canonical JSON identity. A fact's evidence must already be registered in CAS.

| Kind | Permitted values | Meaning |
| --- | --- | --- |
| `ATTEMPT` | `PASS`, `STOP`, `UNKNOWN` | Cited attempt or audit outcome. |
| `SUPERSESSION` | `DECLARED` | `subject` declares that it supersedes `object`. |
| `CONTACT` | `YES`, `NO_ATTESTED`, `UNKNOWN` | Contact claim for the cited scope and class. |
| `EVIDENCE_ACCESS` | `YES`, `NO_ATTESTED`, `UNKNOWN` | Access claim for the cited scope and class. |
| `HEAD` | `SEALED`, `SUPERSEDED`, `UNKNOWN` | Head claim for the cited snapshot and role. |

`NO_ATTESTED` means a cited receipt explicitly says no. It does not prove
absence outside that receipt's scope. Missing fields are never silently treated
as false. An imported `HEAD` identifies a legacy snapshot head; it is not a
Kammi flight authorization. Supersession is a declared edge until independent
source identity and closure checks qualify it.

The E4 importer is a versioned adapter. Its path and legacy-field rules do not
enter the daemon vocabulary. The public service exposes generic history queries
and master-authorized scoped fact registration. Fact registration preserves source
assertions; it cannot create a live authorization.

Scientific labs request new custody terms from Library Lab. They may not add
lab-specific receipt keys as substitute authority. Memory schemas may evolve
separately and never confer custody status.

## Live vocabulary

ledgerd/vocabulary.py is the closed event registry. Actor kinds, contact classes,
exposure purposes, policy predicates, resource kinds and adapter identities each
have one centrally controlled registry. Unknown authoritative events fail replay.
Generic Entity/Link projection tables represent the shared ontology without a
new specialized table for every receipt type. Specification and receipt bytes
remain Artifact kinds. The immutable event/payload graph is always retained.

## Closure accounting

`verify_seal` returns unique transitive **data members**. It excludes Kammi seal
envelope objects and parent envelope objects; their identities are separately bound
and recursively verified. Direct members and parents are ordered duplicate-free sets.
Count CAS objects, seal envelopes and journal payload objects separately.

E4's actual imported closure is 432 original data objects + 1 serialized **legacy**
seal file + 60 newly registered supplement objects = 493 data members.
The contract among the successor's two direct members already exists in the parent's
432 objects and is counted once. A Kammi child seal envelope is not that extra member.
447 legacy entries are paths/identities, not 447 unique byte objects.
