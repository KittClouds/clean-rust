# VCS-1a: Vector Trust Region Runtime, infrastructure only (FROZEN 2026-09-30, see `VCS-1A-FREEZE.md`)

**Scope (ruled 2026-09-30):** schema-agnostic authority infrastructure. No provisional scientific `z`, no BANK-v1 scoring, no results. Lepori owns the first concrete `VectorControlState` schema (what `z` contains, coordinate semantics, normalization, geometry, stable and unstable regions). Claudia owns how a frozen schema is consumed: region evaluation, authority, receipts, the scalar-vs-vector comparison and transport testing. BANK-v2 stays off limits until V2-0 freezes its cue audit.

```
ObserverBundle -> VectorControlState z (Lepori's schema) -> region membership -> authority -> EXECUTE | ASK | ESCALATE | DECLINE_UNAVAILABLE | NOOP
```

Standard library only (CPython 3.13, Windows). Run from this folder:

```bash
python -m unittest discover -s tests -t .        # 71 tests, ~13 s
python -m vcs validate-schema tests/fixtures/fixture_schema.json
python tools/check_freeze.py                      # the machinery is frozen; exit 1 if anything changed
python tools/make_golden.py                       # regenerate the synthetic golden receipts (only under an amendment)
```

## What is built

| module | job |
|---|---|
| `vcs/canon.py` | canonical JSON, content-derived ids (`sha256` over a domain tag plus canonical bytes), strict loader (no duplicate keys, no NaN) |
| `vcs/schema.py` | `VCS_SCHEMA_DECL_V1` (externally declared coordinates: kind, domain, categories, nullable; `status` FIXTURE or FROZEN; a named owner) and `VCS_ENVELOPE_V1` (`schema_id`, `schema_version`, `producer_bundle_id`, `coordinates`, `applicability`, `provenance`, `representation_id`, content id). Coordinate names are opaque until a declaration is loaded. A wrong schema or version, a missing or extra coordinate, an out-of-domain value or a stale id is rejected with an exception, never turned into a disposition |
| `vcs/region.py` | the region DSL: axis rules (`cmp`, `interval`, `in_set`, `present`, `applicable`), geometry (`ball` with weighted l1/l2/linf, `halfspaces` A z <= b over any real coordinates), `and`/`or`/`not`, and a text form for axis rules. Exact rational arithmetic (a boundary is decided by the stated operator, never by rounding), Kleene three-valued logic, per-leaf `on_missing`. Missing and inapplicable coordinates make a leaf UNKNOWN; an unknown region never fires a rule |
| `vcs/authority.py` | ordered rules over named regions with context guards (for example "ASK needs a non-empty route list"); five typed dispositions; `first_match` or `conflict` overlap; a mandatory, author-declared default; parameters from literals or `{"from_context": key}`; receipts carrying the truth value of every region, and byte-identical `replay` |
| `vcs/scalar.py` | the comparator: one score (from the context, or an externally declared linear scalarizer) and one threshold; same receipt shape |
| `vcs/harness.py` | matched comparison at wrong-ACT harm, coverage and query cost. Exact scalar frontier. The vector policy is matched to the best scalar that is no worse on harm **and** cost; `dominates` when no scalar point is that safe and cheap. The paired bootstrap recomputes the hindsight-best scalar on every resample, which favours the scalar side |
| `vcs/transport.py` | fit on TRAIN (the fit function is handed TRAIN cases only), freeze, apply unchanged to other splits, record drift from TRAIN for both policies. A FIXTURE schema marks all output "NONE"; a FROZEN schema requires a preregistration file (its hash is recorded) |
| `vcs/substrate.py` | one canonical semantic state as the reference frame; each substrate supplies an estimated state for the same cases; the same frozen authority is applied to all; metrics, shortfall, typed-disposition agreement, confusion, unknown-region rate |
| `python -m vcs` | `validate-schema`, `compile`, `decide`, `replay`, `evaluate` (frozen authorities against case files; refuses a FROZEN schema without a preregistration, exit 2) |

The region language is not scalar-first: a diagonal halfspace or a ball is a first-class region, and a test shows a diagonal region cannot be written as a box of per-axis thresholds.

## What the tests establish (software only, zero scientific evidence)

Region boundaries (exact); deterministic tie handling (declaration order); missing and inapplicable coordinates; schema-mismatch rejection; replay identity (golden receipts for all five dispositions, and a forged receipt is detected); receipt hashes; scalar baseline plumbing (the fast frontier equals brute-force decisions); no credit for sliding along a frontier (a threshold region on the scalar's own score has margin at most zero and low credit, while a band-shaped truth gives a region that dominates every monotone scalar); transport drift on a synthetic shift; and hygiene (the source names no science coordinate, no lab and no data path; no `results/`; standard library only).

Fixtures live in `tests/fixtures/`. The synthetic coordinates `x1..x4` mean nothing.

## Handoff: what VCS-1b waits for

Claudia waits for Lepori's **operational** schema (observable or derived semantic coordinates and an estimator per substrate), not the atlas schema. VCS-1b is not run against the current atlas. The full list of preconditions, the frozen conventions (matched comparison, `dominates`, both scalar comparisons, the nasty scalar family, transport, substrate comparison, the circularity guard) and the amendment rule are in `VCS-1A-FREEZE.md`.

Still waiting, by ruling: coordinate selection, normalization, region fitting, BANK-v1 scoring, the scalar-vs-vector comparison result, the transport result.

## Design choices worth knowing

- Reasons and requirements are not a vocabulary this package defines. The authority's author writes them (or takes them from the decision context), and an authority that fires nothing uses its own declared default.
- A matched comparison must not reward a policy for trading harm for coverage along the scalar's own curve. A vector policy earns credit only by dominating the scalar frontier or by a positive coverage margin at matched harm and cost. Both margins are reported, plus `p_credit` over the bootstrap.
- The hindsight scalar (re-tuned on the evaluated split) is a ceiling that favours the scalar; the transported comparison also reports the scalar frozen from TRAIN.
