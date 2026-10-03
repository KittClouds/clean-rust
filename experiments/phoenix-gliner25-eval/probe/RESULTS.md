# GLiNER 2.5 schema probe: results (scored once, 2026-09-29)

Pre-registration: `PREREGISTRATION.md`; frozen inputs hashed in
`FROZEN.sha256` before any model output. Scores: `SCORES.json` (from
`score.py`). Predictions: `predictions.jsonl`; production dump:
`production.jsonl`. Gold is single-annotator (Claude).

## Entities (36 passages, 160 gold entity occurrences)

| Setup | Precision | Recall | Type accuracy |
| --- | ---: | ---: | ---: |
| A: production dynamic-NER path | **0.940** | 0.688 | 0.845 |
| B1: 2.5, described labels | 0.517 | 0.856 | 0.891 |
| B2: B1 + `form = proper name` attribute | 0.658 | 0.781 | 0.872 |
| C: 2.5 joint IE entities | 0.422 | 0.881 | 0.858 |

Gate 1 (B2 precision >= A + 0.10, recall >= A - 0.05): **fails**. B2 is 28
points less precise. Its false positives are common nouns (briefcase, car,
assassin, beer); the `form` attribute labelled them "proper name", so it does
not discriminate on this prose. Production's 7 false positives are generic
nouns and conjunction spans ("tank truck", "dumpster", "Ryan and Lanka").

## Relations (38 gold relations)

| Setup | Predicted | Precision | Recall | Pair-only precision |
| --- | ---: | ---: | ---: | ---: |
| C at 0.5 (primary) | 174 | **0.086** | 0.395 | 0.178 |
| C at 0.3 | 232 | 0.073 | 0.447 | 0.151 |
| C at 0.7 | 142 | 0.099 | 0.368 | 0.197 |
| P: every co-occurring gold pair | 356 | — | — | 0.107 |

Gate 2: **dropped** (precision < 0.50). The model assigns contradictory types
to the same pair (Ryan and New Rome as allies, enemies and family; Ryan
"leads" New Rome) and relates aliases of one person to each other. Its
pair-only precision (0.18) is barely above linking every co-occurring pair
(0.11).

Baseline K (production keyword relations) produced no rows inside the
passages: its premise ranges are 7-sentence chunks that extend past passage
boundaries, so this framing cannot measure it. It does not affect the gate.

## Cost

Mean per passage (~127 words), 8 threads: entities 0.62 s; joint IE 0.59 to
1.33 s (first call includes relation-head session load).

## Exploratory (not pre-registered)

Adding whole-word, case-sensitive matches of registry entity labels to
production's mentions (the known-name lane that production leaves empty):

| Setup | Precision | Recall |
| --- | ---: | ---: |
| A | 0.940 | 0.688 |
| A + registry-name scan | 0.940 | 0.787 |

About a third of production's misses are entities the registry already knows
(Luigi, Zanbato, Jamie, Augusti, Wyvern, Ghoul). This is a lead for a
deterministic change, not a gated result.

## Consequence

- Keep the production NER path; do not switch to described labels or
  attributes.
- Do not use 2.5 relations as evidence. Build the deterministic edge design
  (speaker turns, same sentence, above-chance paragraph co-occurrence, one
  edge per pair, per-entity cap).
- Feed known registry names to mention recovery (Alex), measured before and
  after with this gold set.
