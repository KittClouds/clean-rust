"""VectorControlState-v0.1 — candidate operational coordinate ABI.

Each coordinate carries:
    value
    provenance
    degenerate
    availability_class   <- NEW in v0.1

availability_class semantics — this is the axis that decides whether a control surface is
operational or oracle-dependent:

  DIRECT_OBSERVATION    readable from the rendered input with no model and no truth
                        (surface text facts, token/sentence counts, mention inventory)
  DETERMINISTIC_DERIVATION computable from the rendered input by a fixed rule, but
                        requiring parsing rather than reading (normalized entity count,
                        ordered-pair count, predicate-word presence)
  OBSERVER_ESTIMATE     produced by the frozen observer / fitted head (top-choice prob,
                        margin, entropy, legal-set support)
  TRUTH_ONLY            requires BANK ground truth or the simulator run on the latent
                        world (gold action legality, contradictions, missing facts,
                        plan depth, repair counts)

A surface that only exists in TRUTH_ONLY coordinates is a description of the oracle, not
a control surface an executor could use.

Populations are defined INDEPENDENTLY of every coordinate in this ABI — see POPULATIONS.
"""
from __future__ import annotations

VCS_ABI_VERSION = "vector-control-state/abi-0.1"

DIRECT_OBSERVATION = "DIRECT_OBSERVATION"
DETERMINISTIC_DERIVATION = "DETERMINISTIC_DERIVATION"
OBSERVER_ESTIMATE = "OBSERVER_ESTIMATE"
TRUTH_ONLY = "TRUTH_ONLY"

AVAILABILITY_ORDER = [DIRECT_OBSERVATION, DETERMINISTIC_DERIVATION, OBSERVER_ESTIMATE, TRUTH_ONLY]

# G-restriction ladder
G_LADDER = {
    "G0": "all non-circular coordinates (any availability class)",
    "G1": "G0 minus TRUTH_ONLY",
    "G2": "DIRECT_OBSERVATION + DETERMINISTIC_DERIVATION only",
    "G3": "DIRECT_OBSERVATION + DETERMINISTIC_DERIVATION + OBSERVER_ESTIMATE",
}

# --------------------------------------------------------------------------- coordinates
# (name, kind, availability_class, provenance, description)
BLOCKS: dict[str, tuple[tuple[str, str, str, str, str], ...]] = {
    "observation": (
        ("n_tokens", "count", DIRECT_OBSERVATION, "tokenizer", "tokenized length of the rendering"),
        ("n_sentences", "count", DIRECT_OBSERVATION, "punctuation", "sentence/clause count in the rendering"),
        ("has_goal_clause", "bool", DIRECT_OBSERVATION, "surface_scan", "rendering contains an explicit Goal clause"),
        ("goal_position_frac", "metric", DIRECT_OBSERVATION, "surface_scan", "where the Goal clause starts, as a fraction of length"),
    ),
    "derivation": (
        ("n_distinct_mentions", "count", DETERMINISTIC_DERIVATION, "mention_scan", "distinct surface mentions in the rendering"),
        ("n_mention_tokens", "count", DETERMINISTIC_DERIVATION, "mention_scan", "tokens covered by at least one mention span"),
        ("mention_density", "metric", DETERMINISTIC_DERIVATION, "mention_scan", "mention-covered tokens / total tokens"),
        ("n_fact_lines", "count", DETERMINISTIC_DERIVATION, "line_scan", "number of rendered fact lines"),
        ("has_negation_word", "bool", DETERMINISTIC_DERIVATION, "surface_scan", "rendering contains a negation/exception word"),
        ("n_predicate_words", "count", DETERMINISTIC_DERIVATION, "lexicon_scan", "count of predicate cue words in the rendering"),
    ),
    "observer": (
        ("top_choice_prob", "prob", OBSERVER_ESTIMATE, "head", "probability mass on the top-ranked class"),
        ("margin", "score", OBSERVER_ESTIMATE, "head", "top1 - top2 probability"),
        ("entropy", "metric", OBSERVER_ESTIMATE, "head", "entropy of the choice distribution"),
        ("legal_set_support", "prob", OBSERVER_ESTIMATE, "head", "head mass on simulator-legal classes"),
    ),
    "truth": (
        ("gold_action_legal", "bool", TRUTH_ONLY, "simulator", "canonical answer action is simulator-legal"),
        ("n_legal_actions", "count", TRUTH_ONLY, "simulator", "size of the simulator legal action set"),
        ("n_repair_alternatives", "count", TRUTH_ONLY, "simulator", "legal actions that change the world"),
        ("goal_distance", "count", TRUTH_ONLY, "simulator", "BFS plan depth to the goal"),
        ("has_contradiction", "bool", TRUTH_ONLY, "bank_world", "world carries a genuine contradiction"),
        ("n_missing_facts", "count", TRUTH_ONLY, "bank_world", "missing_information entries"),
        ("n_evidence_facts", "count", TRUTH_ONLY, "bank_world", "evidence facts on the canonical answer"),
        ("legal_set_size_minus_gold", "count", TRUTH_ONLY, "simulator", "legal actions other than the gold one"),
    ),
    "representation": (
        ("substrate", "cat", DIRECT_OBSERVATION, "modelcard", "causal | encoder"),
        ("surface", "cat", DIRECT_OBSERVATION, "modelcard", "coordinate name of the readout"),
    ),
}

BLOCK_SPEC = [(b, n, k, a, p, d) for b, cs in BLOCKS.items() for n, k, a, p, d in cs]
ALL_COORDS = [(b, n, k, a, p) for (b, n, k, a, p, _d) in BLOCK_SPEC]
COORD_ORDER = [f"{b}.{n}" for (b, n, _k, _a, _p) in ALL_COORDS]
AVAIL = {f"{b}.{n}": a for (b, n, _k, a, _p) in ALL_COORDS}

# --------------------------------------------------------------------------- populations
# Defined by the simulator acting on the latent world, or by the observer's own correctness.
# None of these read any coordinate in the ABI above.
POPULATIONS = {
    "solvability": {
        "definition": "simulator BFS on the latent world: is a plan to the goal reachable?",
        "levels": ["REACHABLE", "STUCK", "ALREADY_SATISFIED"],
        "independent_of_coordinates": True,
    },
    "observer_correctness": {
        "definition": "does the fitted head's argmax class equal the canonical answer class?",
        "levels": ["CORRECT", "INCORRECT"],
        "independent_of_coordinates": True,
        "note": "depends on the head's output, not on any ABI coordinate value",
    },
}

# --------------------------------------------------------------------------- circularity
# Coordinates that are definitionally entangled with a population label. Mandatory check.
CIRCULARITY_SPEC = {
    "solvability": {
        "truth.goal_distance": "goal_distance is 0 iff ALREADY_SATISFIED and -1 iff STUCK",
        "truth.n_repair_alternatives": "counts only legal actions, which vanish exactly when STUCK",
        "truth.n_legal_actions": "zero when STUCK",
    },
    "observer_correctness": {
        "truth.gold_action_legal": "BANK-v1 derives decision from selected_action; legality is read off it",
        "truth.legal_set_size_minus_gold": "same subtraction from the same derived object",
        "observer.top_choice_prob": "argmax equals the gold class exactly when CORRECT",
        "observer.margin": "monotone in the argmax/gold agreement",
        "observation.n_tokens": "no mechanism linking length to correctness; retained as control",
    },
}


def new_state() -> dict:
    return {b: {n: {"value": None, "kind": k, "availability_class": a, "provenance": p,
                    "degenerate": None}
                for n, k, a, p, _d in cs}
            for b, cs in BLOCKS.items()}


def set_coord(st, block, name, value, provenance=None, degenerate=False):
    if block not in st or name not in st[block]:
        raise KeyError(f"unknown coordinate {block}.{name}")
    c = st[block][name]
    c["value"] = value
    c["provenance"] = provenance or c["provenance"]
    c["degenerate"] = bool(degenerate)
    return st


def to_vector(st, drop_degenerate=True) -> list[float]:
    out = []
    for blk, name, _k, _a, _p in ALL_COORDS:
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


def numeric_columns(rows) -> list[int]:
    keep = []
    for j in range(len(rows[0]) if rows else 0):
        col = [r[j] for r in rows]
        if any(v != v for v in col):
            continue
        if max(col) - min(col) <= 1e-12:
            continue
        keep.append(j)
    return keep


def circular_columns(population: str) -> set[str]:
    return set(CIRCULARITY_SPEC.get(population, {}))


def g_filter(level: str, noncircular: set[str]) -> set[str]:
    """Coordinate names admitted at restriction level G0..G3."""
    if level == "G0":
        return set(noncircular)
    keep = set(noncircular)
    if level in ("G1", "G2", "G3"):
        keep = {c for c in keep if AVAIL[c] != TRUTH_ONLY}
    if level in ("G2", "G3"):
        keep = {c for c in keep if AVAIL[c] in (DIRECT_OBSERVATION, DETERMINISTIC_DERIVATION)}
    if level == "G3":
        keep = {c for c in keep if AVAIL[c] in (DIRECT_OBSERVATION, DETERMINISTIC_DERIVATION,
                                                OBSERVER_ESTIMATE)}
    return keep


def descriptor() -> dict:
    return {
        "abi": VCS_ABI_VERSION,
        "n_coordinates": len(ALL_COORDS),
        "coordinates": {f"{b}.{n}": {"kind": k, "availability_class": a, "provenance": p,
                                     "description": desc}
                        for (b, n, k, a, p, desc) in BLOCK_SPEC},
        "g_ladder": G_LADDER,
        "populations": POPULATIONS,
        "circularity_spec": CIRCULARITY_SPEC,
        "principles": [
            "populations are defined independently of every ABI coordinate",
            "circularity detector is mandatory and runs before any geometry is reported",
            "no scalar collapse, no runtime authority",
            "TRUTH_ONLY coordinates describe the oracle, not an executable control surface",
        ],
    }
