# GLiNER 2.5 schema probe: pre-registration

Written and hashed before any model output for these passages was produced.

## Question

Phoenix uses `fastino/gliner2.5-base-v1` as a drop-in for a bi-encoder: bare,
synonym-expanded labels, entities only. Does using 2.5 as designed (described
labels, span attributes, typed relations) produce cleaner entities and usable
relations on Phoenix fiction?

## Inputs (frozen)

- Source: shortrun (document 3, revision 2), sha256
  `9e05f34c517233cc3d7e6b5d4fc5eed2ba4fc723459c59ba20ad4d28bed3f802`.
- Passages: `passages.jsonl`, 36 passages (4,587 words), chosen by
  `select_passages.py` (model-free: >=110-word paragraph groups, >=2 distinct
  capitalised non-initial tokens, even strides).
- Gold: `gold.json`, single annotator (Claude). Entities are named story
  entities with a coarse type; relations are those a reader would assert from
  the passage alone, from the fixed schema below. References to real-world
  works/people and interjections are in `ignore` (neither credited nor
  penalised).

## Setups

- **A (today):** the entities of the published shortrun generation whose
  mentions fall inside each passage (the full production dynamic-NER path).
- **B1:** 2.5 entities with described labels (character, faction, location,
  item, concept), threshold 0.5.
- **B2 (primary B):** B1 plus a span attribute `form` in
  {proper name, title or role, common noun}; a mention is kept only when its
  `form` is `proper name`.
- **C:** 2.5 joint entity + relation extraction with typed endpoints:
  ally_of, enemy_of, family_of (character-character); member_of, leads
  (character to faction); works_for (character/faction to character/faction);
  located_in (character/faction/location to location); owns (character/faction
  to item/location). Relation threshold 0.5 primary; 0.3 and 0.7 reported as
  sensitivity only.
- **Relation baselines:** (K) the production keyword typed-relationship
  candidates inside each passage; (P) linking every co-occurring gold entity
  pair in the passage.

Each passage is one model window (all are under 512 words).

## Metrics

Surfaces are normalised (lowercase, leading "the ", trailing possessive
removed) and mapped through `aliases` to canonical names.

- Entities: per-passage distinct canonical entities; micro precision and
  recall over all passages. Type accuracy reported on matched entities.
- Relations: canonical (head, type, tail); symmetric types unordered; micro
  precision and recall. Pair-only precision (type ignored) reported as well.

## Decision gates (scored once)

1. Entities: adopt B2 for the NER stage if precision >= A + 0.10 and
   recall >= A - 0.05.
2. Relations: C becomes an automatic evidence tier if precision >= 0.70 at
   threshold 0.5 and it beats baseline K's precision; review-only tier if
   0.50 <= precision < 0.70; dropped (deterministic design only) if < 0.50.
3. No threshold or schema tuning after scoring. Any rerun is a new,
   separately reported probe.
