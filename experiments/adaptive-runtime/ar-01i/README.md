# AR-01I — Opportunity Indifference Geometry

Status: complete, engineering-only, diagnostic-only.

AR-01I asks whether G3's low full-96 top-block agreement is harmless because
many opportunities are effectively tied. It replays the fixed G3 trajectory
and does not allow the full-96 measurements to affect commits.

## Frozen protocol

- Same three-class spiral, K2 action proposal, G3 stratified-64 driving
  verifier, 4,800 commits, and three seeds as AR-01H.
- 96 snapshots per seed, before commits 0, 50, …, 4,750.
- At each snapshot, evaluate every current K2-shortlisted program under the
  full-96 training objective.
- Opportunity blocks are the 62 temporary planning blocks in the partition:
  61 pairs plus one singleton.
- A block's value is the best full-96 utility among its shortlisted programs.
- The selected-program value is the actual G3-committed program's full-96
  utility.
- “Neutral” means absolute utility at most `1e-5`; positive and harmful block
  counts use the same tolerance.

## Results

| Seed | Validation loss | Validation accuracy | Mean block regret | P95 block regret | Mean selected rank | Mean blocks within 5% |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `2b7e…d2a6` | 0.046837 | 100.0% | 0.000487 | 0.001614 | 15.7 / 62 | 1.16 / 62 |
| `77a1…0b51` | 0.065881 | 100.0% | 0.000565 | 0.001247 | 19.7 / 62 | 1.18 / 62 |
| `1111…4444` | 0.111649 | 95.8% | 0.000427 | 0.001215 | 15.9 / 62 | 1.25 / 62 |

The selected G3 block was within 1% of the full-96 best block on 14.6–28.1%
of snapshots and within 5% on 16.7–30.2%. The full near-optimal set itself
was much smaller: only about 1.0–1.3 blocks per snapshot on average, or
roughly 1.7–2.0% of the 62 blocks.

Tail block regret was also nontrivial:

- `>1e-4`: 62.5–85.4% of snapshots.
- `>1e-3`: 10.4–19.8%.
- `>1e-2`: 0%.
- Maximum: 0.00193–0.00326.

Under the full-96 immediate reference, the selected block was harmful on
18.8–25.0% of snapshots and the selected program itself was harmful on
22.9–31.3%. Nevertheless, two trajectories reached 100% validation accuracy
and the third reached 95.8%.

## Interpretation

### AR-H31 — Opportunity equivalence

**Not supported in the broad form tested here.** G3 often missed rank 1 and
incurred modest absolute regret, but the near-optimal set was not broad under
the predeclared 1% and 5% relative bands. Low top-1 agreement is therefore not
adequately explained by a large population of interchangeable opportunities.

### AR-H32 — Harm avoidance over oracle imitation

**Open.** The runtime can succeed even when its selected block is not the
full-96 immediate winner, and sometimes when every shortlisted program in that
block is harmful under that one-step reference. This is evidence that exact
one-step full-support utility is not automatically the right trajectory oracle;
it is not yet evidence for a specific harm-avoidance policy.

The key distinction is now:

> Full-96 top-1 is a valid immediate-utility reference, not proven ground truth
> for the best long-run trajectory.

AR-01I therefore rejects the simple “many near-ties” rescue while keeping the
sequential-trajectory explanation alive. A future experiment should compare
short-horizon outcomes or trajectory regret, not add another confidence gate.

## Validation and artifacts

- Source release check and clippy with `-D warnings`: passed.
- `D:` release unit tests: passed, 4/4.
- `D:` release smoke matrix: passed, 1/1 test covering all G arms.
- `D:` release clippy with `-D warnings`: passed.
- Full three-seed diagnostic run: passed.
- `D:` release diagnostic binary reproduced the same three-seed result.
- Report JSON parsed successfully after generation.
- [Report](<C:/code land/clean-rust/experiments/adaptive-runtime/ar-01i/artifacts/ar-01i-report.json>)
- [Per-seed summary CSV](<C:/code land/clean-rust/experiments/adaptive-runtime/ar-01i/artifacts/ar-01i-runs.csv>)
- [Per-snapshot CSV](<C:/code land/clean-rust/experiments/adaptive-runtime/ar-01i/artifacts/ar-01i-snapshots.csv>)

All conclusions remain engineering-only, toy-scale, and carry no biological or
general-optimizer claim.
