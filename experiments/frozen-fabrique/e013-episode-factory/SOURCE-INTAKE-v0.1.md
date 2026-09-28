# E013 source intake and provenance v0.1

Status: design-source ledger. No released benchmark evaluation instance is imported into E013-D or E013-C by this ledger.

| Source | Official source | Construction role | Boundary |
| --- | --- | --- | --- |
| SWE-rebench V2 | [dataset README](https://huggingface.co/datasets/nebius/SWE-rebench-V2/blob/main/README.md), [toolkit](https://github.com/SWE-rebench/SWE-rebench-V2) | Repo/base-commit/task/patch/test schema, executable verifier patterns | Gold patches, tests, and released instances stay outside observer frames and are not copied as bank rows; per-repo licenses require review before any import. |
| SWE-smith | [official toolkit](https://github.com/SWE-bench/SWE-smith) | Bug mutation, task generation and validation patterns | The upstream toolkit is Linux/Docker oriented; this branch implements its own local Rust replay rather than claiming upstream harness parity. |
| R2E-Gym | [official repository](https://github.com/agentica-project/R2E-Gym) | Procedural environment and verifier separation ideas | No released tasks or checker labels become E013 confirmation rows. |
| Open-Jev | [official repository](https://github.com/Zefan-Cai/Open-Jev) | Grouped counterfactuals, typed choices, abstention/none-valid patterns | It is a symbolic decision source, not an executable Rust adjudicator; mixed downstream dataset licenses are not presumed uniform. |
| AppWorld | [official repository](https://github.com/StonyBrookNLP/appworld), [task-generator guide](https://github.com/StonyBrookNLP/appworld/blob/main/guides/developing_new_task_generators.md) | Scenario siblings and stateful verifier structure | Later noncoding lane only. Protected bundle content is excluded. |
| BIRD | [official benchmark](https://bird-bench.github.io/) | Executable query adjudication and replay pattern | Later SQL lane only; no SQL rows in current Rust banks. |
| CUA-Gym | [official repository](https://github.com/xlang-ai/CUA-Gym) | Environment/action/checker separation | Later GUI/tool lane only and verifier qualification required. |

The factory's authored task templates, code, fixtures, source hashes, and final licenses must be enumerated in the eventual bank manifests. Inspired structure is recorded here; this is not a provenance claim that upstream code or data was copied.

## Pinned source observations

Read-only `git ls-remote ... HEAD` on 2026-09-26 returned these upstream heads. These are design-reference identities, not imported data identities:

| Repository | Observed HEAD |
| --- | --- |
| SWE-rebench V2 | `c71902a8cf8d2b725f63d51f199f4d3e56f68d2d` |
| SWE-smith | `9b74ac08118a85c39c356802f7961893af73e07f` |
| R2E-Gym | `353348a0ff690f2592025eff41b3fef4201a4d8b` |
| Open-Jev | `3308a15ccd7eea1df7a37d6ddc39b023b801ba16` |

## Pattern extraction for this branch

| Pattern | Seed source | E013 construction translation |
| --- | --- | --- |
| Repo plus base revision plus patch plus tests | SWE-rebench V2 | A frozen Rust repo commit and task overlay, with each candidate patch replayed after reset. |
| Mutate an implementation and verify breakage | SWE-smith, R2E-Gym | Generate legal near-miss candidates and adjudicate them with hidden behavioral fixtures. |
| Group truth-changing siblings; include abstention | Open-Jev | Preserve sibling IDs and exactly one `NONE_VALID` instance per repo/family cell. |
| Distinguish state setup from state checking | AppWorld | Keep visible screen and hidden completion fixture roots separate. |
| Cheap deterministic execution comparison | BIRD | Use repeatable semantic test vectors instead of a model judge. |
| Isolate action generator from verifier | CUA-Gym | Candidate producer never receives hidden expected outputs or valid-set receipts. |

No benchmark code, released row, gold patch, or protected fixture was copied to this branch in the intake step.

## Construction authorship

At the user's request, three GPT-6 Luna agents at extra-high reasoning are authoring the factory core and separate D/C family libraries. Their role is source-code and task-grammar construction. They are not the frozen E013 small or large observer bundles, and no E013 observer calls are part of this construction phase. Per-episode candidate provenance must identify the generating adapter and deterministic seed; this authorship note does not substitute for those receipts.
