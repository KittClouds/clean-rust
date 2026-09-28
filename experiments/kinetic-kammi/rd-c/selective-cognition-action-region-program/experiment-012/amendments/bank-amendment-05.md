# E012 bank amendment A05 — producer coordinates and donor locality

**State:** frozen before scored task fixtures. **Model contact remains prohibited.**

This amendment repairs two construction-script defects found before any scored bank existed: candidate arrays were being sorted by numeric action ID, and some swap donors could come from outside the task's locked `pair_id`. No observer output or scored task result informed this repair. Earlier protocol, design, feasibility, and source locks remain unchanged.

## Producer-coordinate schedules

Each task source fixture now carries an explicit producer-native candidate sequence. A family-scoped seed (`E012-A05:<family>:20260925`) drives a deterministic backtracking construction of a four-row Latin schedule. Every action ID occupies each position exactly once. For action tasks, the four primary gold actions also occupy each position exactly once. Among schedules satisfying those constraints, the generator minimizes the spread in the number of executable passing candidates at each position. The locked feasibility matrix shows that exact equality is impossible for two multi-valid families; the chosen schedules still leave every position with both passing and failing cases. Abstention families use a seeded Latin schedule because they have no gold action. The sequence is assigned before frame projection and is retained through serialization and presentation receipts.

The balanced coordinate-control condition uses the reverse of each task's producer sequence. It is a separately declared producer sequence for that condition, has the same exact action-position and gold-position balance, preserves the passing-count spread, and receives its own presentation receipt. No condition mutates a sequence after its receipt is created.

Before model contact, report valid-action frequencies by action ID and candidate position within each family. No action ID or position may be a perfect correctness indicator across all four family tasks. These are bank-construction leakage checks, not a model-performance claim.

The isomorphic-donor coordinate condition selects a nonself task from the same `pair_id`, transfers that donor's role-to-position sequence, and maps those roles onto the recipient's stable action IDs. This changes only the recipient's candidate positions. It does not transfer task labels or donor content.

## Truth-channel swap donors

Every channel-swap donor is a nonself member of the recipient's same `pair_id`. When possible, selection first chooses a donor that differs on the swapped channel and minimizes differences in the other declared truth channels; ties use the predeclared within-family index order. If the pair has no alternative value for that channel, the next nonself pair member is the preregistered isomorphic sham donor. Donor identity remains hidden from the observer and is stored in the sealed truth index.

## Scored-check diagnostics

For the cloned task harnesses with generic `task contract failed` assertions, the scored-check runner may replace the generic assertion with `assert_eq!` carrying field-specific diagnostics. This changes failure text only, not the predicate or pass/fail semantics. The modified test overlay is content-hashed in every trial result. Frozen feasibility logs and source harnesses are not edited.

## Preservation

The 26-condition matrix, 48-task bank, 1,248-frame count, candidate mapping, channel definitions, and all prior feasibility evidence remain unchanged. The only permissible new run remains deterministic source-fixture construction, isolated executable candidate checks, frame projection, and pre-contact audits. No model or observer is contacted.
