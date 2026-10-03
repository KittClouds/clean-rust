# BANK-v4: typed seven-lane factory

Chief Kammi owns this construction. No observer model, tokenizer, frozen evaluation
bank or active lab output is used to admit families. The seven public sources are
archetype libraries, not interchangeable oracles. This is a controlled finite-state
curriculum, not a reproduction of their full benchmark environments.

## Contract and scale

The effective contract is `CONTRACT-v02.json` in the release. The initial
`CONTRACT.json` is retained as construction history. Each lane has 1,024 TRAIN,
128 DEV and 128 TRANSFER families. One family has two latent truth siblings, each
with a full and partial observation, and two information-preserving renderings.
That is 8,960 families, 35,840 roots and 71,680 views. Views and siblings are not
independent samples. Report family-cluster uncertainty in subsequent research.

TRANSFER changes domain sizes or permission/schema regimes. It is construction-
audited material, **not untouched confirmation**. Repeated semantic structures and
exact inputs are counted in `BUILD.json`; namespace separation alone is not OOD.
No v1/v3 rows or public released examples are silently promoted into these splits.

## Seven lanes

| Seed | Fresh local archetype | Important boundary |
|---|---|---|
| ACPBench | conjunctive transport/key/door prerequisites | not upstream PDDL instances |
| Sokoban | one crate, bounded grid, move/push/deadlock | not multi-crate Sokoban |
| Sudoku | 4x4, 2x2 blocks, signed peer guards | not 9x9 Sudoku |
| MATM | location/holding/washing/heating/serving, timed WAIT | not ALFWorld/WebArena execution |
| tau trajectories | eligibility, authentication, consent, refund | no real customer database/API |
| GraphOmni | weighted directed navigation, exact shortest paths | not all GraphOmni algorithms |
| ToolACE | strict method/argument schema, creation/commit | synthetic local API execution only |

Source cards and schema samples are pinned in `SOURCE-INTAKE.json`. Viewer samples
are explicitly unpinned construction references. Missing licenses prohibit direct
row redistribution/import; zero such rows enter the bank.

## Truth order

1. Latent world and registered mechanics define actual possibility.
2. Observation and admissible completions define evidence-supported knowledge.
3. Grounding provides each clause, binding, legality and permission separately.
4. Consequences preserve operator assignments, actual changes, timed/clock effects,
   goal-count delta, step distance, environmental cost and policy cost.
5. Decision is ACT, ASK or ABSTAIN. ACT targets **all** optimal offered actions;
   singleton selection is optional. ABSTAIN corresponds to a NONE action, with
   already-achieved goal and unavailable offered completion distinguished by reason.

ASK requires differing optimal sets across admissible completions and no common
justified optimum. Revealing the one requested slot reduces that set to the actual
state. A latent solution therefore does not contradict ASK. WAIT is legal but can
be useless; timed WAIT can have effects absent from its operator assignments.

Every distance search explores the complete registered reachable space, capped at
4,096 states. Exceeding the cap is a construction failure, never an impossibility
label. Null distance has an explicit unreachable/inapplicable status; it is not zero.
Environmental distance ignores permission, policy distance respects it. Candidate
Q is immediate environmental+policy cost plus policy-respecting successor cost.

## Safe learning interface

Use `loader.load(root, split, lane, entry=...)`, not arbitrary JSON columns:

- `observation_to_grounding`: observed slot values and candidate clauses/statuses.
- `gold_grounding_to_consequence`: full observations only by default.
- `gold_consequence_to_decision`: full, oracle-supplied consequences by default.
- `integrated`: full+partial observations; hidden canonical consequences masked.

`allow_diagnostic=True` explicitly permits latent-truth diagnostics. Never treat
that mode as integrated acquisition. Input records hold only observer frames;
metadata, labels and latent construction records are separate files. Directory
separation is **not** an OS security claim or a protected-panel access grant.

Pairwise comparison coordinates give dense same-type pressure. Producer order is
frozen before observer contact; action identity is independent of presentation.
Subsequent model work must prospectively register subset-fit, TRAIN growth/ceiling,
saturation and gold-substitution controls before attributing failure to architecture.

## Qualification and replay

```powershell
python -B experiments/ff-s15-bank-04/test_factory.py
python -B experiments/ff-s15-bank-04/build.py --out <new-empty-root>
python -B experiments/ff-s15-bank-04/verify_release.py <root> --output <new-report-path>
```

Construction checks every admitted family using a separate mechanics implementation
and forward Dijkstra, against construction reverse shortest paths. Sokoban geometry,
Sudoku peers and graph operator bindings also get archetype checks. A fresh process
replays every serialized root. Mutant tests corrupt targets, masks, physical moves
and Sudoku guards and require rejection. Full clean regeneration must reproduce
every corpus file and `BUILD.json`; it is reproducibility, not a second scientific
review. See `REPORT.md` for actual evidence and artifact locations after completion.

The implementation is deliberately simple, standard-library Python. Hash-based
seeds, buffered streaming writes, finite packed tuples and cached action bitsets
avoid unnecessary model/GPU dependencies. No Rust product changes are needed.
