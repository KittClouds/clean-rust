"""VectorControlState-v0.2 ABI.

v0.1 used a single `availability_class` axis, which conflated two independent questions:

    provenance_class     -- where did this quantity CONCEPTUALLY come from?
    runtime_availability -- is this quantity actually AVAILABLE at decision time?

The conflation had a concrete cost: `legal_set_support` is conceptually a model estimate
(head probability mass on legal classes) but is UNAVAILABLE at runtime, because deciding
which classes are legal requires the simulator. v0.1 labelled it OBSERVER_ESTIMATE, so it
survived into G3 and made G2 == G3 by accident. Splitting the axes removes that accident.

provenance_class
    DIRECT              readable from the rendering with no model and no truth
    DERIVED             computable from the rendering by a fixed parsing rule
    MODEL_ESTIMATE      produced by a model (frozen observer or fitted head)
    ORACLE_TRUTH        requires the simulator or BANK ground truth

runtime_availability
    AVAILABLE           computable from the inputs an executor actually holds
    ESTIMATABLE         not directly available, but a defined estimator could recover it
                        from available inputs (estimator contract required)
    UNAVAILABLE         cannot be computed at decision time by any declared procedure

The G-ladder now filters on runtime_availability, because the ladder exists to answer
"what may an executor use", not "what is conceptually a model output".
"""
from __future__ import annotations

VCS_ABI_VERSION = "vector-control-state/abi-0.2"

DIRECT, DERIVED, MODEL_ESTIMATE, ORACLE_TRUTH = "DIRECT", "DERIVED", "MODEL_ESTIMATE", "ORACLE_TRUTH"
AVAILABLE, ESTIMATABLE, UNAVAILABLE = "AVAILABLE", "ESTIMATABLE", "UNAVAILABLE"

PROVENANCE_CLASSES = [DIRECT, DERIVED, MODEL_ESTIMATE, ORACLE_TRUTH]
RUNTIME_AVAILABILITY = [AVAILABLE, ESTIMATABLE, UNAVAILABLE]

# G-ladder now defined on runtime availability. G_EST adds ESTIMATABLE coordinates and
# requires an estimator contract for each admitted coordinate.
G_LADDER = {
    "G0": "all non-circular coordinates",
    "G1": "G0 minus UNAVAILABLE",
    "G2": "AVAILABLE only",
    "G3": "AVAILABLE + ESTIMATABLE (each with a declared estimator contract)",
}


def _c(name, kind, prov, runtime, desc, estimator=None):
    return (name, kind, prov, runtime, desc, estimator)


BLOCKS: dict[str, tuple[tuple, ...]] = {
    "observation": (
        _c("n_tokens", "count", DIRECT, AVAILABLE, "tokenized length of the rendering"),
        _c("n_sentences", "count", DIRECT, AVAILABLE, "sentence/clause count in the rendering"),
        _c("has_goal_clause", "bool", DIRECT, AVAILABLE, "rendering contains an explicit Goal clause"),
        _c("goal_position_frac", "metric", DIRECT, AVAILABLE, "where the Goal clause starts, as a fraction of length"),
    ),
    "derivation": (
        _c("n_distinct_mentions", "count", DERIVED, AVAILABLE, "distinct surface mentions in the rendering"),
        _c("n_mention_tokens", "count", DERIVED, AVAILABLE, "tokens covered by at least one mention span"),
        _c("mention_density", "metric", DERIVED, AVAILABLE, "mention-covered characters / total characters"),
        _c("n_fact_lines", "count", DERIVED, AVAILABLE, "number of rendered fact lines"),
        _c("has_negation_word", "bool", DERIVED, AVAILABLE, "rendering contains a negation/exception word"),
        _c("n_predicate_words", "count", DERIVED, AVAILABLE, "count of predicate cue words"),
        _c("n_distinct_entity_types", "count", DERIVED, AVAILABLE,
           "distinct capitalized/known-type mention families in the rendering",
           "type families inferred from mention shape only; no truth"),
    ),
    "observer": (
        _c("top_choice_prob", "prob", MODEL_ESTIMATE, AVAILABLE, "probability mass on the top-ranked class"),
        _c("margin", "score", MODEL_ESTIMATE, AVAILABLE, "top1 - top2 probability"),
        _c("entropy", "metric", MODEL_ESTIMATE, AVAILABLE, "entropy of the choice distribution"),
        _c("legal_set_support", "prob", MODEL_ESTIMATE, UNAVAILABLE,
           "head probability mass on simulator-legal classes",
           "needs the simulator's legal set; no surface-only estimator is declared in v0.2"),
    ),
    "truth": (
        _c("gold_action_legal", "bool", ORACLE_TRUTH, UNAVAILABLE,
           "canonical answer action is simulator-legal",
           "no estimator: the canonical answer is exactly what is unknown at decision time"),
        _c("n_legal_actions", "count", ORACLE_TRUTH, UNAVAILABLE, "size of the simulator legal action set",
           "bounded by an enumerated-action grammar parsed from the rendering; declared ESTIMATABLE in v0.3 candidate"),
        _c("n_repair_alternatives", "count", ORACLE_TRUTH, UNAVAILABLE,
           "legal actions that change the world", "candidate for a parse-based estimator"),
        _c("goal_distance", "count", ORACLE_TRUTH, UNAVAILABLE, "BFS plan depth to the goal",
           "candidate for a bounded symbolic planner over parsed facts"),
        _c("has_contradiction", "bool", ORACLE_TRUTH, UNAVAILABLE,
           "world carries a genuine contradiction",
           "candidate for a pairwise conflict detector over parsed state facts"),
        _c("n_missing_facts", "count", ORACLE_TRUTH, UNAVAILABLE, "missing_information entries",
           "candidate for a required-premise-minus-stated-fact detector"),
        _c("n_evidence_facts", "count", ORACLE_TRUTH, UNAVAILABLE, "evidence facts on the canonical answer",
           "candidate for a goal-relevance scorer over parsed facts"),
        _c("legal_set_size_minus_gold", "count", ORACLE_TRUTH, UNAVAILABLE,
           "legal actions other than the gold one", "candidate for a parse-based estimator"),
        _c("goal_distance_visible", "metric", ORACLE_TRUTH, UNAVAILABLE,
           "stated path length in the rendering, when the rendering states one",
           "directly measurable from text when the renderer emits path length; absent otherwise"),
    ),
    "representation": (
        _c("substrate", "cat", DIRECT, AVAILABLE, "causal | encoder"),
        _c("surface", "cat", DIRECT, AVAILABLE, "coordinate name of the readout"),
    ),
}

BLOCK_SPEC = [(b,) + c for b, cs in BLOCKS.items() for c in cs]
ALL_COORDS = [(b, n, k, p, r) for (b, n, k, p, r, _d, _e) in BLOCK_SPEC]
COORD_ORDER = [f"{b}.{n}" for (b, n, _k, _p, _r) in ALL_COORDS]
PROV = {f"{b}.{n}": p for (b, n, _k, p, _r) in ALL_COORDS}
RUNTIME = {f"{b}.{n}": r for (b, n, _k, _p, r) in ALL_COORDS}
ESTIMATOR = {f"{b}.{n}": e for (b, n, _k, _p, _r, _d, e) in BLOCK_SPEC}

POPULATIONS = {
    "solvability": {
        "definition": "simulator BFS verdict on the latent world",
        "levels": ["REACHABLE", "STUCK", "ALREADY_SATISFIED"],
        "independent_of_coordinates": True,
    },
    "observer_correctness": {
        "definition": "fitted head argmax equals the canonical answer class",
        "levels": ["CORRECT", "INCORRECT"],
        "independent_of_coordinates": True,
    },
}

CIRCULARITY_SPEC = {
    "solvability": {
        "truth.goal_distance": "0 iff ALREADY_SATISFIED, -1 iff STUCK: the label itself",
        "truth.n_legal_actions": "declared circular in principle; empirically weak (means 5.39/5.49/5.26)",
        "truth.n_repair_alternatives": "declared circular in principle; empirically weak",
    },
    "observer_correctness": {
        "truth.gold_action_legal": "1.0 for every CORRECT row vs mean 0.244 for INCORRECT",
        "truth.legal_set_size_minus_gold": "same subtraction from the same derived object",
        "observer.top_choice_prob": "argmax equals the gold class exactly when CORRECT",
        "observer.margin": "monotone in argmax/gold agreement",
        "observation.n_tokens": "no mechanism; retained as a declared-negative control",
    },
}


def new_state():
    return {b: {n: {"value": None, "kind": k, "provenance_class": p,
                    "runtime_availability": r, "estimator_contract": e,
                    "provenance": None, "degenerate": None}
                for n, k, p, r, _d, e in cs}
            for b, cs in BLOCKS.items()}


def set_coord(st, block, name, value, provenance=None, degenerate=False):
    if block not in st or name not in st[block]:
        raise KeyError(f"unknown coordinate {block}.{name}")
    c = st[block][name]
    c["value"] = value
    if provenance:
        c["provenance"] = provenance
    c["degenerate"] = bool(degenerate)
    return st


def to_vector(st, drop_degenerate=True):
    out = []
    for blk, name, _k, _p, _r in ALL_COORDS:
        c = st[blk][name]
        v = c["value"]
        if drop_degenerate and c["degenerate"]:
            out.append(float("nan")); continue
        if v is None:
            out.append(float("nan"))
        elif isinstance(v, bool):
            out.append(1.0 if v else 0.0)
        elif isinstance(v, (int, float)):
            out.append(float(v))
        else:
            out.append(float("nan"))
    return out


def numeric_columns(rows):
    keep = []
    for j in range(len(rows[0]) if rows else 0):
        col = [r[j] for r in rows]
        if any(v != v for v in col):
            continue
        if max(col) - min(col) <= 1e-12:
            continue
        keep.append(j)
    return keep


def circular_columns(population):
    return set(CIRCULARITY_SPEC.get(population, {}))


def g_filter(level, noncircular):
    keep = set(noncircular)
    if level == "G0":
        return keep
    if level in ("G1", "G2", "G3"):
        keep = {c for c in keep if RUNTIME[c] != UNAVAILABLE}
    if level in ("G2", "G3"):
        keep = {c for c in keep if RUNTIME[c] == AVAILABLE}
    if level == "G3":
        keep = {c for c in keep if RUNTIME[c] in (AVAILABLE, ESTIMATABLE)}
    return keep


def descriptor():
    return {
        "abi": VCS_ABI_VERSION,
        "n_coordinates": len(ALL_COORDS),
        "two_axis_semantics": {
            "provenance_class": "where the quantity conceptually comes from",
            "runtime_availability": "whether an executor can actually compute it at decision time",
            "why_split": "v0.1 conflated these; legal_set_support is conceptually a model "
                         "estimate but runtime-unavailable, which made G2 == G3 by accident",
        },
        "coordinates": {f"{b}.{n}": {"kind": k, "provenance_class": p,
                                     "runtime_availability": r, "description": desc,
                                     "estimator_contract": est}
                        for (b, n, k, p, r, desc, est) in BLOCK_SPEC},
        "g_ladder": G_LADDER,
        "populations": POPULATIONS,
        "circularity_spec": CIRCULARITY_SPEC,
    }
