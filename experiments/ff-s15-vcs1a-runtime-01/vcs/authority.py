"""Authority over regions: region membership -> typed disposition, with a replayable receipt.

The authority never reduces the envelope to a scalar. It evaluates named regions and fires ordered rules; a rule fires when its region evaluates to True (unknown never fires) and its context guards hold.
Dispositions are typed and complete: EXECUTE(action), ASK(requirement), ESCALATE(reason), DECLINE_UNAVAILABLE(reason), NOOP. The reason and requirement vocabularies are not defined here: they are strings the authority's author writes
(or takes from the decision context). An authority must declare its own default disposition; nothing is invented when no rule fires.
"""
from __future__ import annotations

from . import canon, region
from .canon import SchemaMismatch, VcsError
from .schema import Schema, check_envelope

AUTH_DOMAIN = "vcs-authority-v1"
RECEIPT_DOMAIN = "vcs-receipt-v1"
CONTEXT_DOMAIN = "vcs-context-v1"
TYPES = {"EXECUTE": "action", "ASK": "requirement", "ESCALATE": "reason", "DECLINE_UNAVAILABLE": "reason", "NOOP": None}
GUARD_TESTS = ("nonempty", "empty", "eq", "present")
OVERLAPS = ("first_match", "conflict")


class Unresolved(Exception):
    pass


# ------------------------------------------------------------------------------------------------ dispositions and guards
def check_disposition(d, where: str) -> dict:
    if not isinstance(d, dict) or d.get("type") not in TYPES:
        raise VcsError(f"{where}: disposition type must be one of {sorted(TYPES)}")
    param = TYPES[d["type"]]
    allowed = {"type"} | ({param} if param else set())
    if set(d) != allowed:
        raise VcsError(f"{where}: {d['type']} takes exactly {sorted(allowed)}")
    if param:
        v = d[param]
        ok = isinstance(v, (str, int, float, bool, list, dict)) and v not in ("", None)
        if isinstance(v, dict) and set(v) == {"from_context"}:
            ok = isinstance(v["from_context"], str) and bool(v["from_context"])
        if not ok:
            raise VcsError(f"{where}: {param} must be a nonempty literal or {{\"from_context\": key}}")
    return dict(d)


def resolve(d: dict, context: dict) -> dict:
    """Fills {"from_context": key} parameters. A missing key raises Unresolved (the authority then uses its declared default)."""
    param = TYPES[d["type"]]
    if not param:
        return {"type": d["type"]}
    v = d[param]
    if isinstance(v, dict) and set(v) == {"from_context"}:
        key = v["from_context"]
        if key not in context or context[key] in (None, "", []):
            raise Unresolved(key)
        v = context[key]
    return {"type": d["type"], param: v}


def guard_holds(g: dict, context: dict) -> bool:
    key, test = g["key"], g["test"]
    val = context.get(key)
    if test == "nonempty":
        return isinstance(val, (list, dict, str)) and len(val) > 0
    if test == "empty":
        return val is None or (isinstance(val, (list, dict, str)) and len(val) == 0)
    if test == "present":
        return key in context and val is not None
    return key in context and val == g["value"]


def check_guards(guards, where: str) -> list:
    out = []
    for g in guards or []:
        if not isinstance(g, dict) or g.get("test") not in GUARD_TESTS or not isinstance(g.get("key"), str) or not g["key"]:
            raise VcsError(f"{where}: a guard is {{key, test in {GUARD_TESTS}[, value]}}")
        if g["test"] == "eq" and "value" not in g:
            raise VcsError(f"{where}: an eq guard needs a value")
        out.append({k: g[k] for k in ("key", "test", "value") if k in g})
    return out


# ------------------------------------------------------------------------------------------------ the authority record
class Authority:
    def __init__(self, spec: dict, schema: Schema):
        self.spec, self.schema = spec, schema

    @property
    def authority_id(self) -> str:
        return self.spec["authority_id"]


def load_authority(src: dict, schema: Schema) -> Authority:
    """src: {bound_schema, regions: {name: AST | {"text": ...}}, rules, default, overlap[, conflict]}. Compiles regions against the loaded schema; ids are over the normalized form."""
    if not isinstance(src, dict):
        raise VcsError("an authority is an object")
    bs = src.get("bound_schema") or {}
    if (bs.get("schema_id"), bs.get("schema_version")) != (schema.schema_id, schema.schema_version):
        raise SchemaMismatch(f"authority is bound to {bs.get('schema_id')}@{bs.get('schema_version')}, loaded schema is {schema.schema_id}@{schema.schema_version}")
    regions = {}
    for name, node in (src.get("regions") or {}).items():
        if isinstance(node, dict) and set(node) == {"text"}:
            node = region.parse_region(node["text"])
        regions[name] = region.compile_region(node, schema)
    if not regions:
        raise VcsError("an authority declares at least one region")
    rules, seen = [], set()
    for r in src.get("rules") or []:
        rid = r.get("rule_id")
        if not isinstance(rid, str) or not rid or rid in seen:
            raise VcsError(f"bad or duplicate rule_id {rid!r}")
        seen.add(rid)
        if r.get("region") not in regions:
            raise VcsError(f"rule {rid} names an undeclared region {r.get('region')!r}")
        rules.append({"rule_id": rid, "region": r["region"], "guards": check_guards(r.get("guards"), f"rule {rid}"), "disposition": check_disposition(r.get("disposition"), f"rule {rid}")})
    if not rules:
        raise VcsError("an authority declares at least one rule")
    overlap = src.get("overlap", "first_match")
    if overlap not in OVERLAPS:
        raise VcsError(f"overlap must be one of {OVERLAPS}")
    spec = {"schema": "VCS_AUTHORITY_V1", "bound_schema": {"schema_id": schema.schema_id, "schema_version": schema.schema_version, "schema_hash": schema.schema_hash},
            "regions": regions, "rules": rules, "overlap": overlap, "default": check_disposition(src.get("default"), "default")}
    if overlap == "conflict":
        spec["conflict"] = check_disposition(src.get("conflict"), "conflict")
    return Authority(canon.seal(AUTH_DOMAIN, "authority_id", spec), schema)


def verify_authority(spec: dict, schema: Schema) -> Authority:
    """Reloads a stored (already normalized) authority and checks its content-derived id."""
    canon.verify_id(AUTH_DOMAIN, "authority_id", spec)
    bs = spec["bound_schema"]
    if (bs["schema_id"], bs["schema_version"], bs["schema_hash"]) != (schema.schema_id, schema.schema_version, schema.schema_hash):
        raise SchemaMismatch("stored authority is bound to a different schema declaration")
    src = {"bound_schema": spec["bound_schema"], "regions": spec["regions"], "rules": spec["rules"], "default": spec["default"], "overlap": spec["overlap"]}
    if "conflict" in spec:
        src["conflict"] = spec["conflict"]
    rebuilt = load_authority(src, schema)
    if rebuilt.authority_id != spec["authority_id"]:
        raise VcsError("stored authority does not normalize to itself")
    return rebuilt


# ------------------------------------------------------------------------------------------------ decide / replay
def _decide_core(auth: Authority, env: dict, context: dict) -> tuple[dict, dict, dict]:
    spec = auth.spec
    truth = {name: region.evaluate(node, env) for name, node in sorted(spec["regions"].items())}
    fired, unknown, results = [], [], {}
    for rule in spec["rules"]:
        v = truth[rule["region"]]
        if v is None:
            unknown.append(rule["rule_id"])
            continue
        if v is True and all(guard_holds(g, context) for g in rule["guards"]):
            try:
                results[rule["rule_id"]] = resolve(rule["disposition"], context)
                fired.append(rule["rule_id"])
            except Unresolved as e:
                return {"disposition": _default(spec, context), "rule_id": None, "via": "unresolved_param", "unresolved": [str(e)], "fired": fired + [rule["rule_id"]], "unknown": unknown}, truth, results
    if not fired:
        return {"disposition": _default(spec, context), "rule_id": None, "via": "default", "fired": [], "unknown": unknown}, truth, results
    if spec["overlap"] == "conflict" and len({canon.canonical(results[f]) for f in fired}) > 1:
        return {"disposition": resolve(spec["conflict"], context), "rule_id": None, "via": "conflict", "fired": fired, "unknown": unknown}, truth, results
    return {"disposition": results[fired[0]], "rule_id": fired[0], "via": "rule", "fired": fired, "unknown": unknown}, truth, results


def _default(spec, context):
    try:
        return resolve(spec["default"], context)
    except Unresolved as e:
        raise VcsError(f"the authority's own default needs context key {e}, which the decision context does not supply") from None


def decide(auth: Authority, env: dict, context: dict | None = None) -> dict:
    """Envelope + context -> receipt. The envelope is checked against the loaded schema first (a mismatch is an exception, not a disposition)."""
    context = {} if context is None else context
    check_envelope(auth.schema, env)
    decision, truth, _ = _decide_core(auth, env, context)
    receipt = {"schema": "VCS_RECEIPT_V1", "authority_id": auth.authority_id, "schema_id": auth.schema.schema_id, "schema_version": auth.schema.schema_version,
               "schema_hash": auth.schema.schema_hash, "envelope_id": env["envelope_id"], "representation_id": env["representation_id"],
               "context_id": canon.derive_id(CONTEXT_DOMAIN, context), "regions": truth, "decision": decision,
               "evidence_grade": "NONE (fixture schema)" if auth.schema.fixture else "see the preregistration of the run that produced it"}
    return canon.seal(RECEIPT_DOMAIN, "receipt_id", receipt)


def replay(receipt: dict, auth: Authority, env: dict, context: dict | None = None) -> bool:
    """Byte-identical replay: recompute from the stored inputs and compare canonical bytes."""
    canon.verify_id(RECEIPT_DOMAIN, "receipt_id", receipt)
    return canon.canonical(decide(auth, env, context)) == canon.canonical(receipt)
