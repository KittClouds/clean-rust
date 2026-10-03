"""The scalar comparator: an authority that sees ONE number.

A scalar authority is a single score and a one-threshold ladder. The score is either supplied by the decision context (`{"context": key}`, e.g. an observer's own confidence) or an externally declared linear scalarizer over envelope coordinates
(`{"linear": {coord: weight}, "bias": b}`). It exists so the vector-region authority has an honest thing to be compared with: the best scalar threshold at matched harm, coverage and cost.
Receipts have the same shape as the region authority's, so the harness treats both alike."""
from __future__ import annotations

from fractions import Fraction

from . import canon
from .authority import RECEIPT_DOMAIN, Unresolved, check_disposition, resolve
from .canon import VcsError
from .schema import Schema, check_envelope, exact, is_real

SCALAR_DOMAIN = "vcs-scalar-authority-v1"


class ScalarAuthority:
    def __init__(self, spec: dict, schema: Schema):
        self.spec, self.schema = spec, schema

    @property
    def authority_id(self) -> str:
        return self.spec["scalar_id"]


def load_scalar(src: dict, schema: Schema) -> ScalarAuthority:
    """src: {score, threshold, at_or_above, below}. `at_or_above` fires when score >= threshold (the boundary belongs to `at_or_above`)."""
    score = src.get("score")
    if not isinstance(score, dict) or len(score) not in (1, 2) or not (set(score) == {"context"} or set(score) == {"linear", "bias"}):
        raise VcsError('score is {"context": key} or {"linear": {coord: weight}, "bias": b}')
    if "context" in score:
        if not isinstance(score["context"], str) or not score["context"]:
            raise VcsError("score context key must be a nonempty string")
    else:
        if not is_real(score["bias"]) or not isinstance(score["linear"], dict) or not score["linear"]:
            raise VcsError("a linear scalarizer needs weights and a real bias")
        for n, w in score["linear"].items():
            if n not in schema.coords or schema.coords[n].kind != "real" or not is_real(w):
                raise VcsError(f"linear scalarizer names {n!r}: not a declared real coordinate or weight")
    t = src.get("threshold")
    if not is_real(t):
        raise VcsError("threshold must be a real number")
    spec = {"schema": "VCS_SCALAR_AUTHORITY_V1", "bound_schema": {"schema_id": schema.schema_id, "schema_version": schema.schema_version, "schema_hash": schema.schema_hash},
            "score": score, "threshold": t, "at_or_above": check_disposition(src.get("at_or_above"), "at_or_above"), "below": check_disposition(src.get("below"), "below")}
    return ScalarAuthority(canon.seal(SCALAR_DOMAIN, "scalar_id", spec), schema)


def score_of(sa: ScalarAuthority, env: dict, context: dict):
    """The scalar, or None when it cannot be computed (a missing score or coordinate)."""
    sc = sa.spec["score"]
    if "context" in sc:
        v = context.get(sc["context"])
        return v if is_real(v) else None
    tot = exact(sc["bias"])
    for n, w in sc["linear"].items():
        v = env["coordinates"][n]
        if v is None or env["applicability"].get(n, True) is False:
            return None
        tot += exact(w) * exact(v)
    return tot


def decide_scalar(sa: ScalarAuthority, env: dict, context: dict | None = None) -> dict:
    context = {} if context is None else context
    check_envelope(sa.schema, env)
    s = score_of(sa, env, context)
    if s is None:
        branch, via = "below", "no_score"
    else:
        branch, via = ("at_or_above", "threshold") if exact(s) >= exact(sa.spec["threshold"]) else ("below", "threshold")
    try:
        disp = resolve(sa.spec[branch], context)
    except Unresolved as e:
        raise VcsError(f"scalar authority needs context key {e}") from None
    score_repr = None if s is None else (s if not isinstance(s, Fraction) else (float(s) if Fraction(float(s)) == s else str(s)))
    receipt = {"schema": "VCS_RECEIPT_V1", "authority_id": sa.authority_id, "schema_id": sa.schema.schema_id, "schema_version": sa.schema.schema_version, "schema_hash": sa.schema.schema_hash,
               "envelope_id": env["envelope_id"], "representation_id": env["representation_id"], "context_id": canon.derive_id("vcs-context-v1", context),
               "regions": {}, "decision": {"disposition": disp, "rule_id": branch, "via": via, "fired": [branch], "unknown": [], "score": score_repr},
               "evidence_grade": "NONE (fixture schema)" if sa.schema.fixture else "see the preregistration of the run that produced it"}
    return canon.seal(RECEIPT_DOMAIN, "receipt_id", receipt)
