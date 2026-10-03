"""The region DSL. A region is a predicate over a VectorControlState envelope, written as a JSON AST (or as text that compiles to the same AST).

Two families, deliberately in one language so the geometry is not secretly axis-aligned:
  axis rules  : cmp, interval, in_set, present, applicable  (per-coordinate predicates)
  geometry    : ball (weighted l1 / l2 / linf distance to a prototype, <= r) and halfspaces (A z <= b over any real coordinates)
combined with and / or / not.

Semantics are exact: every real is compared as an exact Fraction, so a boundary point is decided by the stated operator (<=, >=, closed/open interval ends), never by rounding.
Missing values: a coordinate that is None (missing) or flagged inapplicable makes a leaf UNKNOWN (None) by default; `on_missing` may be set per leaf to "false" or "true". and/or/not use Kleene three-valued logic, so unknown only matters when it decides the outcome. A region is a member only when it evaluates to True.
"""
from __future__ import annotations

import re
from fractions import Fraction

from .canon import VcsError
from .schema import Schema, exact, is_real

CMP = {"<": lambda a, b: a < b, "<=": lambda a, b: a <= b, ">": lambda a, b: a > b, ">=": lambda a, b: a >= b, "==": lambda a, b: a == b, "!=": lambda a, b: a != b}
ORDERING = ("<", "<=", ">", ">=")
MISSING_MODES = ("unknown", "false", "true")
NORMS = ("l1", "l2", "linf")


# ------------------------------------------------------------------------------------------------ compile / normalize
def _coord(schema: Schema, name, *, real=False):
    if name not in schema.coords:
        raise VcsError(f"region names coordinate {name!r}, which the loaded schema does not declare")
    c = schema.coords[name]
    if real and c.kind != "real":
        raise VcsError(f"coordinate {name!r} is {c.kind}; this node needs a real coordinate")
    return c


def _mode(node) -> str:
    m = node.get("on_missing", "unknown")
    if m not in MISSING_MODES:
        raise VcsError(f"on_missing must be one of {MISSING_MODES}")
    return m


def _leaf(node: dict, **fields) -> dict:
    out = {"op": node["op"], **fields}
    out["on_missing"] = _mode(node)
    return out


def _real_val(v, what):
    if not is_real(v):
        raise VcsError(f"{what} must be a real number")
    return v


def compile_region(node, schema: Schema) -> dict:
    """Validates a region against the loaded schema and returns its normalized AST (what gets hashed into an authority id)."""
    if not isinstance(node, dict) or "op" not in node:
        raise VcsError("a region node is an object with an op")
    op = node["op"]
    if op in ("and", "or"):
        args = node.get("args")
        if not isinstance(args, list) or not args:
            raise VcsError(f"{op} needs a nonempty args list")
        return {"op": op, "args": [compile_region(a, schema) for a in args]}
    if op == "not":
        return {"op": "not", "arg": compile_region(node.get("arg"), schema)}
    if op == "cmp":
        c = _coord(schema, node.get("coord"))
        cmp_, val = node.get("cmp"), node.get("value")
        if cmp_ not in CMP:
            raise VcsError(f"cmp must be one of {sorted(CMP)}")
        if cmp_ in ORDERING and c.kind != "real":
            raise VcsError(f"ordering comparison on non-real coordinate {c.name!r}")
        _value_fits(c, val)
        return _leaf(node, coord=c.name, cmp=cmp_, value=val)
    if op == "interval":
        c = _coord(schema, node.get("coord"), real=True)
        lo, hi = _real_val(node.get("lo"), "lo"), _real_val(node.get("hi"), "hi")
        if exact(lo) > exact(hi):
            raise VcsError("interval lo > hi")
        return _leaf(node, coord=c.name, lo=lo, hi=hi, lo_closed=bool(node.get("lo_closed", True)), hi_closed=bool(node.get("hi_closed", True)))
    if op == "in_set":
        c = _coord(schema, node.get("coord"))
        vals = node.get("values")
        if not isinstance(vals, list) or not vals:
            raise VcsError("in_set needs a nonempty values list")
        for v in vals:
            _value_fits(c, v)
        return _leaf(node, coord=c.name, values=list(vals))
    if op in ("present", "applicable"):
        c = _coord(schema, node.get("coord"))
        return {"op": op, "coord": c.name}
    if op == "ball":
        center = node.get("center")
        if not isinstance(center, dict) or not center:
            raise VcsError("ball needs a center object {coordinate: value}")
        norm = node.get("norm", "l2")
        if norm not in NORMS:
            raise VcsError(f"norm must be one of {NORMS}")
        weights = node.get("weights") or {}
        r = _real_val(node.get("radius"), "radius")
        if exact(r) < 0:
            raise VcsError("radius must be >= 0")
        for n, v in center.items():
            _coord(schema, n, real=True)
            _real_val(v, f"center[{n}]")
        for n, w in weights.items():
            if n not in center or not is_real(w) or exact(w) <= 0:
                raise VcsError(f"weight for {n!r} must be a positive real on a center coordinate")
        return _leaf(node, center=dict(center), radius=r, norm=norm, weights=dict(weights))
    if op == "halfspaces":
        rows = node.get("rows")
        if not isinstance(rows, list) or not rows:
            raise VcsError("halfspaces needs a nonempty rows list")
        out = []
        for row in rows:
            coefs = row.get("coefs")
            if not isinstance(coefs, dict) or not coefs:
                raise VcsError("each row needs coefs {coordinate: coefficient}")
            for n, a in coefs.items():
                _coord(schema, n, real=True)
                _real_val(a, f"coef[{n}]")
            out.append({"coefs": dict(coefs), "bound": _real_val(row.get("bound"), "bound")})
        return _leaf(node, rows=out)
    raise VcsError(f"unknown region op {op!r}")


def _value_fits(c, v):
    if c.kind == "real":
        _real_val(v, f"value for {c.name!r}")
    elif c.kind == "bool":
        if not isinstance(v, bool):
            raise VcsError(f"value for boolean coordinate {c.name!r} must be true or false")
    elif v not in c.categories:
        raise VcsError(f"value {v!r} is not a declared category of {c.name!r}")


def coords_used(node: dict) -> set:
    op = node["op"]
    if op in ("and", "or"):
        return set().union(*(coords_used(a) for a in node["args"]))
    if op == "not":
        return coords_used(node["arg"])
    if op == "ball":
        return set(node["center"])
    if op == "halfspaces":
        return {n for r in node["rows"] for n in r["coefs"]}
    return {node["coord"]}


# ------------------------------------------------------------------------------------------------ evaluation (Kleene logic, exact arithmetic)
def _usable(env: dict, name: str):
    """Returns (usable, value). A missing value or an explicit inapplicability flag makes the coordinate unusable."""
    v = env["coordinates"][name]
    if v is None or env["applicability"].get(name, True) is False:
        return False, None
    return True, v


def _miss(node):
    return {"unknown": None, "false": False, "true": True}[node["on_missing"]]


def evaluate(node: dict, env: dict):
    """True / False / None (unknown)."""
    op = node["op"]
    if op == "and":
        vals = [evaluate(a, env) for a in node["args"]]
        return False if any(v is False for v in vals) else (None if any(v is None for v in vals) else True)
    if op == "or":
        vals = [evaluate(a, env) for a in node["args"]]
        return True if any(v is True for v in vals) else (None if any(v is None for v in vals) else False)
    if op == "not":
        v = evaluate(node["arg"], env)
        return None if v is None else (not v)
    if op == "present":
        return env["coordinates"][node["coord"]] is not None
    if op == "applicable":
        return env["applicability"].get(node["coord"], True) is not False
    if op in ("cmp", "interval", "in_set"):
        ok, v = _usable(env, node["coord"])
        if not ok:
            return _miss(node)
        if op == "cmp":
            a, b = (exact(v), exact(node["value"])) if is_real(v) else (v, node["value"])
            return CMP[node["cmp"]](a, b)
        if op == "in_set":
            return any((exact(v) == exact(x)) if is_real(v) else (v == x) for x in node["values"])
        x, lo, hi = exact(v), exact(node["lo"]), exact(node["hi"])
        return (x > lo or (node["lo_closed"] and x == lo)) and (x < hi or (node["hi_closed"] and x == hi))
    if op == "ball":
        diffs = []
        for n, c in node["center"].items():
            ok, v = _usable(env, n)
            if not ok:
                return _miss(node)
            w = exact(node["weights"].get(n, 1))
            diffs.append((w, abs(exact(v) - exact(c))))
        r = exact(node["radius"])
        if node["norm"] == "l2":
            return sum(w * d * d for w, d in diffs) <= r * r
        if node["norm"] == "l1":
            return sum(w * d for w, d in diffs) <= r
        return max(w * d for w, d in diffs) <= r
    if op == "halfspaces":
        for row in node["rows"]:
            tot = Fraction(0)
            for n, a in row["coefs"].items():
                ok, v = _usable(env, n)
                if not ok:
                    return _miss(node)
                tot += exact(a) * exact(v)
            if tot > exact(row["bound"]):
                return False
        return True
    raise VcsError(f"unknown region op {op!r}")


# ------------------------------------------------------------------------------------------------ text form (axis rules only)
_TOK = re.compile(r'\s*(?:(?P<num>-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)|(?P<str>"(?:[^"\\]|\\.)*")|(?P<op><=|>=|==|!=|<|>|\(|\)|\[|\]|\{|\}|,)|(?P<id>[A-Za-z_][A-Za-z_0-9]*))')


def _tokens(text: str):
    pos, out = 0, []
    text = text.strip()
    while pos < len(text):
        m = _TOK.match(text, pos)
        if not m or m.end() == pos:
            raise VcsError(f"cannot parse region text at {text[pos:pos + 12]!r}")
        pos = m.end()
        kind = m.lastgroup
        out.append((kind, m.group(kind)))
    return out


def parse_region(text: str) -> dict:
    """Parses `x["name"] >= 0.71 and x["b"] in [0.12, 0.30] and not (x["c"] == false)`. `in [lo, hi]` is a closed interval; `in {a, b}` a set.
    `present(x["n"])` and `applicable(x["n"])` are supported. Geometric regions are written as JSON (ball, halfspaces)."""
    toks = _tokens(text)
    i = 0

    def peek():
        return toks[i] if i < len(toks) else (None, None)

    def take(expect=None):
        nonlocal i
        if i >= len(toks):
            raise VcsError("unexpected end of region text")
        t = toks[i]
        if expect and t[1] != expect:
            raise VcsError(f"expected {expect!r}, found {t[1]!r}")
        i += 1
        return t

    def literal():
        k, v = take()
        if k == "num":
            return float(v) if any(ch in v for ch in ".eE") else int(v)
        if k == "str":
            return v[1:-1].encode("ascii").decode("unicode_escape")
        if v in ("true", "false"):
            return v == "true"
        raise VcsError(f"expected a literal, found {v!r}")

    def xref():
        take("x")
        take("[")
        name = literal()
        take("]")
        if not isinstance(name, str):
            raise VcsError("coordinate names are strings")
        return name

    def atom():
        k, v = peek()
        if v == "(":
            take("(")
            e = orexp()
            take(")")
            return e
        if v == "not":
            take("not")
            return {"op": "not", "arg": atom()}
        if v in ("present", "applicable"):
            take()
            take("(")
            n = xref()
            take(")")
            return {"op": v, "coord": n}
        n = xref()
        k, v = take()
        if v in CMP:
            return {"op": "cmp", "coord": n, "cmp": v, "value": literal()}
        if v == "in":
            k2, v2 = take()
            if v2 == "[":
                lo = literal()
                take(",")
                hi = literal()
                take("]")
                return {"op": "interval", "coord": n, "lo": lo, "hi": hi}
            if v2 == "{":
                vals = [literal()]
                while peek()[1] == ",":
                    take(",")
                    vals.append(literal())
                take("}")
                return {"op": "in_set", "coord": n, "values": vals}
        raise VcsError(f"expected a comparison or `in` after x[{n!r}]")

    def andexp():
        parts = [atom()]
        while peek()[1] == "and":
            take("and")
            parts.append(atom())
        return parts[0] if len(parts) == 1 else {"op": "and", "args": parts}

    def orexp():
        parts = [andexp()]
        while peek()[1] == "or":
            take("or")
            parts.append(andexp())
        return parts[0] if len(parts) == 1 else {"op": "or", "args": parts}

    e = orexp()
    if i != len(toks):
        raise VcsError(f"unexpected trailing text {toks[i][1]!r}")
    return e
