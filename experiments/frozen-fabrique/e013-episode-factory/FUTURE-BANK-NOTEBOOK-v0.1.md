# Later trust-bank lanes (design notebook)

This notebook preserves source ideas without adding non-Rust tasks to E013-D or E013-C. No future lane is authorized by the E013 construction contract.

| Lane | State | Candidate actions | Independent adjudicator to qualify | First discriminating issue |
| --- | --- | --- | --- | --- |
| Stateful API/tool | AppWorld-like app database and task scenario | Complete API-call programs or bounded next actions | Programmatic state-diff assertions, including unwanted side effects | Sibling scenarios can share setup while changing the correct action; prove hidden state does not leak through visible API responses. |
| SQL | BIRD-like schema, data snapshot, and request | Candidate queries | Execute against multiple independently generated database instances and compare semantics | Matching one fixed snapshot can be accidental; qualify equivalence over counterfactual data. |
| Browser/GUI | CUA-Gym-like environment snapshot and instruction | Click/type/navigation sequences | Independently audited final-state verifier | A generated reward function can share the generator's blind spots; measure verifier false acceptance before using labels. |
| Structured decision | Open-Jev-like typed record and rule state | Choice, null, or score decision | Executable policy/rule interpreter with sealed truth-changing siblings | Ensure syntax and provenance do not expose the answer. |
| Coding beyond Rust | SWE-rebench/SWE-smith/R2E-style repository state | Patches | Language-specific build plus hidden behavioral tests | Toolchain and dependency pinning become part of the task identity. |

Common abstract episode: `state -> stable candidate set -> controlled presentation -> external adjudication`. A later protocol must separately define environment identity, fixture firewall, action-space semantics, and verifier qualification for each lane.
