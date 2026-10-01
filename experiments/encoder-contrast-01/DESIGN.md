# ENCODER-CONTRAST-01 — design note (written before any fitting)

## Question

Which capabilities, surfaces, and interface failures change when **causal information flow is
replaced by bidirectional encoding**, at matched scale within the same LFM2.5 family?

| | causal reference | contrast substrate |
|---|---|---|
| model | `LFM2.5-230M-Base` (`lfm2.5-230m-base-9d2be55`, local, read-only) | `LiquidAI/LFM2.5-Encoder-230M` (`0b649ad0c684378b03d4d8304f7577a662ab89bc`) |
| params | 229.7M | 229.7M |
| hidden | 1024 | 1024 |
| layers | 14 (assumed, verified at load) | 14 |
| attention | causal | full bidirectional |
| objective | LM | masked LM |
| params/hidden/depth | matched | matched |

Not "does the encoder score higher". The substrate varies along exactly one axis: **information
access across positions**.

## Firewall

- BANK-v1 is read-only. No modification, no regeneration, no split edits.
- Claudia's and Lexi's runs are read-only. No rerun, no modification.
- No Library / retrieval / authority state touched.
- All output under `D:\codex-runs\encoder-contrast-01\` and this branch.
- Encoder model is contact-authorized by this mission only; it is not the JEV frozen fabric and
  produces no reusable features for any other branch.

## Why the surface vocabulary must be reinterpreted, not reused

In a causal model a position's state is a **prefix summary**. "final token" is privileged because
it has seen everything; "first token" is near-dead because it has seen only the prompt preamble.
That is an *access constraint*, not a capacity statement.

In a bidirectional encoder every position attends to the whole sequence. So the same coordinate
names now measure something different:

| coordinate | causal reading | encoder reading (to test) |
|---|---|---|
| `first` | prefix-only, near-dead | full-context, should be alive |
| `final` | privileged summary | full-context, should be comparable to `first` |
| `mean` | mixes many partial prefixes | mixes many full-context states |
| `layer -4` / `middle` | depth is a mix of "not yet seen the end" and "less transformed" | depth is purely representational |
| local mention span | local only, must propagate forward to be usable at `final` | local, directly available |
| edge pair readout | needs both endpoints reachable from the readout site | both endpoints available locally |

That reinterpretation is the experiment, not a nuisance.

## Preregistered predictions (to falsify, not to satisfy)

- **P1** Final-position privilege shrinks sharply. `final` no longer outperforms `first`/`mean`
  by a large margin on route/decision endpoints.
- **P2** First-token stops being a dead control. `first` becomes informative (vs causal
  first-token ≈ 0.18 route exact / 0.057 abstain-reason macro-F1).
- **P3** Entity/span representations become stronger graph-interface candidates: entity-span
  probe scores improve relative to the causal baseline on the same rows.
- **P4** Edge existence survives with a cheaper readout or a larger held-renderer margin.
- **P5** Template/renderer transfer improves **more** than raw in-family scores — i.e. the
  gain concentrates on TEST-TEMPLATE (S7/S8/S9) rather than TEST-IID.
- **P6** Explicit role binding still matters despite bidirectionality. If a role-superseded
  probe (roles stripped from the state view, or a supplier/recipient-swapped contrast) still
  loses accuracy, then bidirectionality solves *access* but the *interface* must still preserve
  binding. This is the R1 × F4 stitch.

## Smallest comparative battery

**Surfaces (coordinates), identical extraction code for both substrates:**
`first`, `final`, `mean`, `full_mean`, `layer-4`, `middle`, plus `entity_span` (per entity) and
`edge_pair` (per relation edge, pair-ready).

**Heads:** linear logistic (primary), and one tiny-nonlinear head (1 hidden layer, ≤32 units) on
the single best-coordinate linear winner — to separate "nonlinearity needed" from "wrong
interface".

**Controls, always included:**
- `first` as the accessibility probe (it is the falsification instrument for P2).
- A shuffled-surface control (label/entity permutation) to confirm any signal is real.
- Row-identity pairing: both substrates score **identical BANK rows** with identical head seeds.

**Endpoints (from BANK-v1 projections, canonical truth only):**
- route exact (action type + arguments)
- decision macro-F1 (ACT/ASK/ABSTAIN)
- abstain-reason macro-F1
- NLI macro-F1
- edge existence AUC (pair readout)
- route exact on held renderers S7/S8/S9

**Strata:** TEST-IID, TEST-LEXICAL, TEST-ENTITY, TEST-TEMPLATE, TEST-COMPOSITION, TEST-DEPTH,
TEST-ABSTENTION, TEST-JOINT. Report per stratum; do not average into one number.

## Primitives bank (expensive pass, done once)

`BANK-v1-ENCODER-230M-PRIMITIVES` — row surfaces for all rows, entity-span vectors for all rows,
pair-ready edge vectors, token-level states for a fixed 5k-row subset only, plus model/tokenizer
identity, input hashes, and an extraction receipt. Later questions are then free.

## External reference (frozen, recorded not rerun)

Lexi's locked causal 230M atlas numbers are recorded verbatim in `reference/` and used as an
external reference column. The paired contrast additionally runs the *same* readout harness over
the causal checkpoint on the same rows — this is new paired work, not a rerun or modification of
those results.

## Stop conditions

Stop and report if the comparison degenerates into a benchmark sweep (one score, one substrate
winning) instead of an accessibility map. Stop if any BANK-v1 hash moves. Stop if the encoder
contact leaks into another branch.
