# OBS-OPEN-02R1 — Familywise Discovery Rule Completion

Status: `QUALIFIED_REPAIR`

This checkpoint records the narrow repair required after the clean
OBS-OPEN-03 pre-execution abort. The named `FROZEN_FAMILYWISE_DISCOVERY_RULE_V1`
contract did not contain executable semantics for formal estimands, support,
familywise multiplicity, bootstrap decisions, temporal stability, null handling,
or candidate rejection. No substantive discovery or confirmation artifact was
produced by that abort.

## Authority and unchanged parent

- Parent universe root:
  `6b0ca197a394b085707d03dfe06f1569eb0fafbddb2d583817e88647df6f6235`
- Parent OBS-OPEN-02 protocol root:
  `141344869c5e6aba6bc7346594872efdc196cb246c834f8d510a0aad90831bb5`
- Parent commit: `1b0f00f24bcc253f741d26e4472b40fc6bab3f9d`
- Discovery sessions: 257, still `FROZEN_UNOPENED`
- Confirmation sessions: 69, still `FROZEN_UNOPENED`

OBS-OPEN-02 remains historical authority. R1 does not rewrite it and does not
change the observer, source, universe, R01–R30 family, measurement views,
session dependence unit, bootstrap count or seed, temporal strata, or firewall.

## Repaired executable rule

R1 freezes four formal estimand templates expanded to 119 tests:

- 29 adjacent raw-width contrasts;
- 30 first-outside-side symmetry contrasts;
- 30 location-balance symmetry contrasts;
- 30 signed-path-displacement contrasts.

Formal testing uses one complete family with two-sided Holm–Bonferroni control
at `alpha=0.05`. Session-block bootstrap remains 2,000 resamples with seed
`20260814` and percentile intervals. Support floors, null eligibility,
temporal-status rules, class precedence, rejection codes, and future
confirmation-estimand requirements are machine-readable in
`contracts/obs_open_02r1_familywise_rule_v1.json` and implemented by
`tools/obs_open_02r1_familywise_rules.py`.

No predeclared equivalence region exists in R1. Therefore failure to reject a
null is not a supported-null claim; near-null classification is
`NEAR_NULL_NOT_EVALUABLE`. Measurements without a natural null remain
descriptive-only. Scale-stable, conditional, representation-sensitive, and
supported-null promotion are disabled unless their stated pre-data contract is
available.

## Blindness and validation

R1 was authored and tested with synthetic, adversarial, and hand-constructed
fixtures only. Discovery and confirmation observations were not read. No
discovery census, aggregate, plot, candidate registry, or confirmation result
exists under this repair. The confirmation firewall remains fail-closed.

The R1 repair seal is the authority for the completed decision rule. It is not
an OBS-OPEN-03 execution seal. OBS-OPEN-03 may be attempted only in a later,
separate gate after this repair root is accepted.

Economic and trading authority: `false`.
