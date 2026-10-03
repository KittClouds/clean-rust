# E013-D family design v0.1

Status: D-family construction source for sealed `E013-TRUST-SIGNAL-DEVELOPMENT-v0.2`; not a bank seal and not observer-qualified. This directory owns only D family definitions and six repository templates. It contains no generated episode bank or observer output.

## Cell plan

E013-D is fixed at six frozen local-commit Rust repository identities, eight families per repository, and twelve tasks per repository/family cell (576 episodes total). Each cell has exactly one genuine empty-valid-set task (48 total), with four offered patches that all fail the executable hidden contract. The core supplies the private seeded empty ordinal. Task/family selection, candidate count and valid-set strata are fixed before any model contact.

Where the core assigns a matched sibling pair, the pair uses the same four patch identities and candidate order while task evidence changes which patch satisfies the frozen contract. Pair metadata stays private. Repository commits and tree hashes are computed by core when it materializes these authored templates; the adapter does not invent snapshot hashes.

## D archetypes

| ID | Archetype | Intended task seam | Distinguishing failure mode |
| --- | --- | --- | --- |
| `d.boundary` | Domain and boundary semantics | Empty, singleton, maximum, or just-outside-domain input | Off-by-one or invalid-domain acceptance |
| `d.error-context` | Error propagation and context | Preserve the original cause while adding the layer's required context | Error swallowed, replaced, or context lost |
| `d.transition` | State transition invariants | Guard or order a legal state change | Illegal transition or partially updated state |
| `d.cleanup` | Resource and ownership cleanup | Close, release, or restore state on every exit path | Leak, double cleanup, or skipped cleanup after error |
| `d.ordering` | Deterministic ordering | Canonicalize an externally observable sequence | Unstable tie, insertion-order dependence, or wrong stable key |
| `d.limits` | Checked limits and arithmetic | Apply a documented size/count boundary without overflow | Wraparound, unchecked growth, or incorrect limit edge |
| `d.compat` | Public API compatibility | Preserve documented call and return behavior while fixing an implementation defect | Source/behavioral break beyond the requested contract |
| `d.atomic-batch` | Batch and streaming atomicity | Commit a coherent batch or preserve a valid prefix/rollback contract | Partial mutation or duplicate/missing items after failure |

These are cross-cutting correctness contracts. They are distinct in intent from algorithm/data-structure tasks such as tokenization, interval indexing, graph witness generation, delta coding, parser precedence, aggregation, binary framing, and dependency memoization.

## Candidate construction rules

- Candidate patches are ordinary, independently applicable local diffs against the pinned task state. Each must apply cleanly and compile before hidden behavior adjudication; behavioral failures are allowed and expected.
- Use several plausible legal alternatives where the source seam permits it: a complete fix, equivalent implementation variants, and behaviorally plausible distractors. Do not use formatting, candidate names, diff size, ordering, or producer metadata to identify correctness.
- Some tasks may admit more than one valid patch. Empty-valid-set tasks still have only compiling/applicable distractors; none may satisfy the hidden task contract.
- Visible screening fixtures may establish basic public behavior. Completion fixtures and expected outputs stay in the hidden adjudicator under a distinct root, use disjoint case rows, and are never copied into candidate source trees.
- Candidate ordering uses the core's independent `candidate_order_seed`; semantic labels and task seeds never choose presentation position.
- Generator variation is deterministic from the namespaced episode seed. Never curate or replace a task using observer outcomes.

## Implementation boundary

The family adapter implements the core `EpisodeFamily` interface and keeps D identifiers under the `d.` namespace. The six authored Rust templates become frozen local commits through core materialization. Candidate patches are generated against those verified commits, applied independently, and compiled/tested by the core. This source work does not authorize observer contact, signal scoring, fitting, or confirmation.
