"""The externally supplied VectorControlState schema and the envelope that carries a state.

The runtime knows NOTHING about what any coordinate means. Names, kinds and domains come from a declaration that the schema's owner supplies; until one is loaded, no envelope can be read. The declaration's `status` is FIXTURE (software verification only, zero scientific evidence) or FROZEN (owned and frozen by its producer)."""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from . import canon
from .canon import SchemaMismatch, VcsError

DECL_DOMAIN = "vcs-schema-decl-v1"
ENV_DOMAIN = "vcs-envelope-v1"
KINDS = ("real", "bool", "categorical")
STATUSES = ("FIXTURE", "FROZEN")
AUDIT_FIELDS = ("target_derived", "downstream_of_target", "shared_generator")
ENVELOPE_FIELDS = ("schema", "schema_id", "schema_version", "producer_bundle_id", "coordinates", "applicability", "provenance", "representation_id", "envelope_id")


@dataclass(frozen=True)
class Coord:
    name: str
    kind: str
    nullable: bool
    domain: tuple | None          # real: (lo, hi) exact-comparable; None = unbounded
    categories: tuple | None      # categorical
    audit: dict | None = None     # derivation audit: {target_derived, downstream_of_target, shared_generator}, booleans


@dataclass(frozen=True)
class Schema:
    schema_id: str
    schema_version: str
    status: str
    owner: str
    coords: dict                  # name -> Coord (insertion order = declaration order)
    decl: dict
    schema_hash: str

    @property
    def fixture(self) -> bool:
        return self.status == "FIXTURE"


def is_real(v) -> bool:
    return isinstance(v, (int, float, Fraction)) and not isinstance(v, bool)


def exact(v) -> Fraction:
    if not is_real(v):
        raise VcsError(f"not a real number: {v!r}")
    return Fraction(v)


def load_schema(decl: dict) -> Schema:
    if not isinstance(decl, dict) or decl.get("schema") != "VCS_SCHEMA_DECL_V1":
        raise VcsError("not a VCS_SCHEMA_DECL_V1 declaration")
    for f in ("schema_id", "schema_version", "status", "owner", "coordinates"):
        if f not in decl:
            raise VcsError(f"schema declaration lacks {f}")
    if decl["status"] not in STATUSES:
        raise VcsError(f"status must be one of {STATUSES}")
    if not isinstance(decl["owner"], str) or not decl["owner"]:
        raise VcsError("a schema declaration must name its owner")
    if not isinstance(decl["coordinates"], list) or not decl["coordinates"]:
        raise VcsError("a schema declares at least one coordinate")
    coords: dict = {}
    for c in decl["coordinates"]:
        name, kind = c.get("name"), c.get("kind")
        if not isinstance(name, str) or not name or name in coords:
            raise VcsError(f"bad or duplicate coordinate name {name!r}")
        if kind not in KINDS:
            raise VcsError(f"coordinate {name}: kind must be one of {KINDS}")
        dom, cats = None, None
        if kind == "real" and c.get("domain") is not None:
            lo, hi = c["domain"]
            if not (is_real(lo) and is_real(hi)) or exact(lo) > exact(hi):
                raise VcsError(f"coordinate {name}: bad domain")
            dom = (lo, hi)
        if kind == "categorical":
            cats = tuple(c.get("categories") or ())
            if not cats or len(set(cats)) != len(cats) or not all(isinstance(x, str) for x in cats):
                raise VcsError(f"coordinate {name}: categories must be a nonempty list of distinct strings")
        audit = c.get("derivation_audit")
        if audit is not None and (not isinstance(audit, dict) or set(audit) != set(AUDIT_FIELDS) or not all(isinstance(v, bool) for v in audit.values())):
            raise VcsError(f"coordinate {name}: derivation_audit must be exactly {AUDIT_FIELDS}, all boolean")
        if decl["status"] == "FROZEN" and audit is None:
            raise VcsError(f"coordinate {name}: a FROZEN schema must declare its derivation_audit ({AUDIT_FIELDS}) for every coordinate")
        coords[name] = Coord(name, kind, bool(c.get("nullable", False)), dom, cats, audit)
    return Schema(decl["schema_id"], decl["schema_version"], decl["status"], decl["owner"], coords, decl, canon.derive_id(DECL_DOMAIN, decl))


def check_value(c: Coord, v) -> None:
    if v is None:
        if not c.nullable:
            raise SchemaMismatch(f"coordinate {c.name} is not nullable")
        return
    if c.kind == "real":
        if not is_real(v):
            raise SchemaMismatch(f"coordinate {c.name} must be a real number")
        if c.domain is not None and not (exact(c.domain[0]) <= exact(v) <= exact(c.domain[1])):
            raise SchemaMismatch(f"coordinate {c.name} outside its declared domain")
    elif c.kind == "bool":
        if not isinstance(v, bool):
            raise SchemaMismatch(f"coordinate {c.name} must be boolean")
    elif v not in c.categories or not isinstance(v, str):
        raise SchemaMismatch(f"coordinate {c.name} outside its declared categories")


def make_envelope(schema: Schema, *, producer_bundle_id: str, coordinates: dict, representation_id: str, provenance: dict | None = None, applicability: dict | None = None) -> dict:
    env = {"schema": "VCS_ENVELOPE_V1", "schema_id": schema.schema_id, "schema_version": schema.schema_version, "producer_bundle_id": producer_bundle_id,
           "coordinates": dict(coordinates), "applicability": dict(applicability or {}), "provenance": dict(provenance or {}), "representation_id": representation_id}
    return canon.seal(ENV_DOMAIN, "envelope_id", env)


def check_envelope(schema: Schema, env: dict) -> dict:
    """Schema-mismatch rejection: wrong schema or version, a missing or extra coordinate, a value outside its declared kind or domain, a stale id."""
    if not isinstance(env, dict) or env.get("schema") != "VCS_ENVELOPE_V1":
        raise VcsError("not a VCS_ENVELOPE_V1 record")
    if set(env) != set(ENVELOPE_FIELDS):
        raise VcsError(f"envelope fields must be exactly {ENVELOPE_FIELDS}")
    if (env["schema_id"], env["schema_version"]) != (schema.schema_id, schema.schema_version):
        raise SchemaMismatch(f"envelope is {env['schema_id']}@{env['schema_version']}, loaded schema is {schema.schema_id}@{schema.schema_version}")
    for f in ("producer_bundle_id", "representation_id"):
        if not isinstance(env[f], str) or not env[f]:
            raise VcsError(f"envelope {f} must be a nonempty string")
    if not isinstance(env["provenance"], dict) or not isinstance(env["applicability"], dict):
        raise VcsError("provenance and applicability must be objects")
    z = env["coordinates"]
    if not isinstance(z, dict) or set(z) != set(schema.coords):
        raise SchemaMismatch(f"coordinates {sorted(z) if isinstance(z, dict) else z!r} differ from the declared {sorted(schema.coords)}")
    for name, v in z.items():
        check_value(schema.coords[name], v)
    for name, flag in env["applicability"].items():
        if name not in schema.coords or not isinstance(flag, bool):
            raise SchemaMismatch(f"applicability entry {name!r} is not a boolean for a declared coordinate")
    canon.verify_id(ENV_DOMAIN, "envelope_id", env)
    return env
