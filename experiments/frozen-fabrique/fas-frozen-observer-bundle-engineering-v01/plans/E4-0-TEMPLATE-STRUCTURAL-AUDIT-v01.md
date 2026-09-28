# E4-0 Template Structural Audit v01

**Status:** model-free descriptive audit, 2026-09-26. Inputs are the pinned E1 v04 generator templates and E4 held-out template manifest v02. This audit does not inspect episodes, labels, features, model outputs, or scores. It adds no pass gate to E4-0.

## Bound inputs

| Input | SHA-256 |
| --- | --- |
| E1 v04 generator source | fa2bd0617135a0dce4e12f0e0967f82e461133b394a7d969daba5afb11e2cce1 |
| E4 held-out template manifest v02 | e3b8a70b90b06fc4185d2e379cbfc7cf3724238d9505590add1cf8bba2e9b068 |
| E4 template text audit v02 | FAS_E4_0_TEMPLATE_TEXT_AUDIT_V02 |

## Method

The mechanical fingerprint records each template's placeholder order, terminal punctuation, and whether a query is a question or an imperative. A manual surface review records clause shape, voice, and symbolic notation. Slot-order comparison is descriptive: it does not measure semantic distance or predict model behavior.

The observation slot order uses C=context, E=entity, R=relation, S=state. Query order uses C, E, and R. E1 and E4 lists below follow template IDs 0 through 7.

## Slot-order result

| Family | E1 v04 order by ID | E4 v02 order by ID | New E4 orders |
| --- | --- | --- | --- |
| Observation | CERS, CRES, CESR, RECS, CERS, ECSR, RECS, CERS | ECSR, CESR, ECRS, CERS, CERS, RECS, RECS, ECSR | ECRS (1 of 8 templates) |
| Query | REC, REC, RCE, ERC, RCE, REC, REC, CER | CRE, REC, ECR, ERC, REC, CER, REC, ERC | CRE and ECR (2 of 8 templates) |

The candidate set contains four of E1's five unique observation orders plus one new order. It contains three of E1's four unique query orders plus two new orders. Some E1 orders are not reused. Novel ordering exists, but most candidate instances reuse an E1 slot permutation.

## Clause and surface result

- E1 observations mix ordinary declarative prose with equation, arrow, and bracketed record forms. E4 v02 uses complete prose clauses throughout; seven templates are single-clause statements and one combines an imperative with a declarative clause.
- E4 adds a copular observation construction and one two-clause observation pattern. Most observations remain ordinary record/value statements, with active and passive forms already represented in E1.
- Both E1 and E4 queries have two question forms and six imperative forms. E4 therefore does not add a new broad query mood. It adds a do-support WH form and two new slot orders.
- E4 uses familiar sentence punctuation and does not add a punctuation class absent from E1. It removes E1's symbolic query/record notation rather than testing new symbol grammar.

## Disposition

The user review accepts all eight observation templates semantically and flagged query IDs 1 and 6 for possible relation-versus-value ambiguity. Manifest v02 tightens only those two strings by explicitly requesting the value under the named relation, closing both wording flags. Its audit confirms those are the only text changes and that placeholder, exact-collision, normalized-collision, and per-string digest checks pass.

The candidate set supports an **unseen-template transfer** question. It also introduces limited, identifiable structural variation: new slot orders, a copular observation, a two-clause observation, and a do-support WH query. The set remains predominantly within familiar prose statements and direct retrieval questions. Do not describe its result as broad structural invariance. Keep structural descriptors descriptive and frozen before model contact; do not add structural subclasses or performance gates after seeing scores.

Held-out-template and joint-template truth remain escrowed for FF-BUNDLE-TEMPLATE-01. This audit neither opens nor qualifies those outcomes.
