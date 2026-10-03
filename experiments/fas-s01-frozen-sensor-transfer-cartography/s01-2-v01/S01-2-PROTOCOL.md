# FAS-S01-2: Controlled Counterfactual Sensor Corpus

## Objective

Measure how frozen LFM representations change when context identity, entity
identity, and observation wording are independently substituted while the
serialized world facts and exact answer remain fixed. This is a construction
and measurement-design checkpoint only. No tokenizer or LFM is loaded here.

S01-1 found weaker fixed-linear target transfer on its one held-out context
term than on its held-out entity term. S01-1 did not establish contextual
aliasing or a controlled substitution effect. S01-2 provides paired examples
for those measurements. It does not revise FAS-00 and does not select a view.

## Identity, parent seals, and isolation

- Project: `fas-s01-frozen-sensor-transfer-cartography`.
- Phase: `S01-2-v01`.
- Backbone reserved for a later, separately authorized extraction:
  `LiquidAI/LFM2.5-1.2B-Base`, revision
  `7453bca97ca1e67754c4035a4b4c584e1c9dd725`.
- FAS-S01 construction root:
  `894b4a0c6db98a5d84fe75589168715a00660d48917e47b0c21bb794a2fc3777`.
- FAS-00 terminal closure root:
  `870e1d29d7db3dd458f16fcb56315f6976e4a5f35ba5731d642b3330a8d7d652`.
- S01-1 cartography root:
  `847c0a35e7c0aa6ad7c7120ea1d4fb5b07754add0df861530cd2df5e2631d8ef`.
- S01-1 observation-increment addendum root:
  `e56733793ba4824851b079152c72097b0c615e481bed0185b9e0a470fae665e6`.

S01-2 generates its own world corpus, manifests, receipts, validation results,
and seals. It imports no FAS-00 or S01-1 data, cache, probe, or code. The parent
roots above are provenance references only. No other active project is in
scope.

## Exact counterfactual unit

Each quartet contains `A`, `C`, `E`, and `P`:

- `A`: base wording, base context alias, base entity alias.
- `C`: replace only the context alias in the observation and query.
- `E`: replace only the entity alias in the observation and query.
- `P`: replace only the observation template with its frozen paraphrase
  partner. Query wording and all semantic slots remain byte-identical.

The substituted aliases name the same canonical context or entity in that
quartet. The following are invariant across all four rows: latent fact,
relation, state, target candidate identity, candidate identities and order,
world-family stratum, time step, query template, feedback marker, and term
split. Context/entity lexical IDs and observation template ID change only on
their assigned edge.

The world fact and target are generated before any text is rendered. The
validator reconstructs the target from serialized facts and query semantics
using an independent code path.

## Frozen design and size

Term inventories are fixed at 32 context aliases and 32 entity aliases. IDs
`0..15` in each role are the train-side-style vocabulary; IDs `16..31` are
the novel held-out vocabulary. All terms are generated from a sealed nonce
syllable inventory; no term is selected by model output or geometry. Alias
substitution partner is `(within_split_index + 7) mod 16`.

The balanced factorial track crosses:

- two context term groups and two entity term groups;
- all eight declared world-family strata;
- two relation identities;
- three answer states;
- eight query templates and eight observation templates through a fixed
  balanced schedule;
- 16 distinct context/entity pair indices per represented comparison cell.

It contains 24,576 quartets. The observation template is
`(query_template + family_index + relation_id + 3*state_id) mod 8`; all
observation/query template combinations occur across the family strata. The
entity pair index is a frozen cyclic offset of the replicate index using only
the split, family, relation, and state fields, so it does not change when the
template changes. Each represented geometry cell has exactly 16 quartets.

The separate binding track fully crosses 16 context substitution pairs with
16 individual entity aliases and, reciprocally, 16 entity substitution pairs
with 16 individual context aliases, for each of the four train/held-out split
combinations. It uses one fixed family/relation/state/template condition and
contains 2,048 quartets. Each binding cell therefore has 16 matched
counterfactuals while the other factor varies.

Total: 26,624 quartets and 106,496 rendered inputs. Each quartet has four
rows. This is a fixed construction corpus, not a Phase 5 or evaluation stream.

## Surface and span contract

Eight observation and eight query templates are stored verbatim in the world
contract. The paraphrase partner for observation template `i` is `(i + 4)
mod 8`; query template is unchanged in `P`. Template IDs 6 and 7 are marked
held out from any future probe-fitting partition. S01-2 performs no fitting.

Every rendered input is ASCII. Corpus character offsets are half-open offsets
into the exact UTF-8 input bytes, which equal ASCII character offsets. Context,
entity, and relation spans list every occurrence in the observation and query;
state span records only the observation occurrence. Extraction-time tokenizer
alignment is specified separately and remains unqualified until authorized.
Any span whose token offsets cross a boundary, leave a gap, or cannot be
uniquely mapped is rejected before that row's forward pass and counted.

## Phase boundary

This construction pass may generate, validate, and seal the corpus and all
prospective extraction/geometry contracts. It may compile and run the
synthetic generator and validator. It may not load the tokenizer or LFM,
extract features, materialize an S01 feature cache, train a probe, run a
representation measurement, or authorize S01-3.

Expected terminal state:

```text
S01_2_CORPUS_READY             true
S01_2_EXTRACTION_READY         true
S01_2_MODEL_CONTACT_AUTHORIZED false
S01_3_AUTHORIZED               false
```
