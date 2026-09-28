# R&D-C / Experiment 010 — Cross-Repository Switchboard Transfer

## Question

Does the frozen E009 v5 observer identify a high-precision, nonzero set of coding tasks where a small action can replace large reasoning on repositories outside the E009 source repository?

The transfer unit is the repository. The bank has two repositories, four task families in each repository, and two prompt variants per family (16 scored tasks total). Both repositories use Rust to isolate repository transfer from a language change.

## Frozen switchboard

Keep the E009 v5 small and large bundles, prompt, output schema, percent-to-milli normalization, 850/150 thresholds, routing rule, and E002 authority fixed. No E010 development fit, threshold selection, prompt repair, or repository-specific tuning is permitted. Observer calls see the same public frame for each task. Sealed completion labels and source truth stay outside observer requests.

Lanes: hand-written policy, small only, small then large on abstention, and always large. All lanes use the same frozen snapshots, action choices, exact completion tests, stable action receipts, and replay authority. Each selected patch runs its exact test in its isolated candidate snapshot; precontact candidate tests establish the bank labels, while scoring reruns the selected candidate's test.

## Active hypotheses

- **H1, high-precision accessibility region:** the small observer can safely act on a nonzero subset of tasks without escalation.
- **H2, evidence transfer:** the accessible subset can be identified from task evidence on repositories outside the E009 source repository, without E010 fitting or repository-specific threshold changes.
- **H3, useful abstention:** preserving completion depends on the observer relinquishing tasks outside its reliable action region.
- **H4, separate efficiency axes:** fewer large calls can come with more total tokens; both are reported independently.
- **H5, explicit authority:** selective cognition remains safe because the observer proposes an offered action while the deterministic runtime validates and receipts the transition.

## Preregistered gate

Each repository must independently satisfy all of these conditions:

1. Hybrid completion is at least always-large completion.
2. Hybrid displaces at least one large call relative to always-large.
3. Every direct small action is correct (100% observed direct-action precision). No error tolerance is fitted after outputs.
4. Illegal commits, duplicate action effects, or replay identity failures are zero.

Latency and tokens are measured outcomes, not promotion requirements. Report direct-action coverage and precision, hybrid completion, large calls avoided, authority invariants, time, and tokens separately for each repository. Pooled totals are descriptive only.

## Bank construction

Select tasks from committed source snapshots before observer contact. Each family starts with one controlled regression in production code and uses an existing repository test as its exact completion check. Two correct patches are intentionally available: a direct repair and the same repair with a contract comment. A plausible incorrect patch and an unchanged patch are also offered. Confirm each outcome before freezing the bank. Record source revisions, archive hashes, patch hashes, test commands, and logs.

The local `turbovec` snapshot is pinned to commit `8202f194a0cbbd52213a004290401e180e5c123d`. The independent `BurntSushi/ripgrep` snapshot is pinned to the 15.2.0 release commit `e89fff89ac9af12e8d4ce9d5fd07beb408ca730f`.

## Interpretation boundary

Promotion supports a bounded cross-repository engineering result for these two repositories and this frozen bank. It does not establish token efficiency, broad repository generalization, or a mechanism for the small observer's behavior. E009 remains the within-repository result; E010 is a separate R&D artifact and does not revise upstream scientific claims.
