"""A small, strict JSON Schema validator (standard library only).

C0 must run from files with no dependencies, so the schemas use a deliberately small subset of
JSON Schema 2020-12 and this module implements exactly that subset. A schema that uses a keyword
outside the subset is refused (SchemaError), so a schema can never silently rely on a check this
validator does not perform.

Subset: type (object array string integer boolean null), enum, const, required, properties,
additionalProperties (false, true or a schema), items, minItems, maxItems, uniqueItems, minimum,
maximum, minLength, maxLength, pattern, oneOf, allOf, and local `$ref` to `#/$defs/<name>`.
Annotations ($schema, $id, title, description, $defs) are allowed. There is no "number" type:
C0 records contain no floats.
"""
from __future__ import annotations

import re

ANNOTATIONS = {"$schema", "$id", "title", "description", "$defs"}
KEYWORDS = {
    "$ref", "type", "enum", "const", "required", "properties", "additionalProperties", "items", "minItems",
    "maxItems", "uniqueItems", "minimum", "maximum", "minLength", "maxLength", "pattern", "oneOf", "allOf",
}
TYPES = {"object", "array", "string", "integer", "boolean", "null"}
MAX_DEPTH = 64


class SchemaError(ValueError):
    """The schema itself uses something outside the supported subset."""


def _type_ok(kind: str, value) -> bool:
    if kind == "object":
        return isinstance(value, dict)
    if kind == "array":
        return isinstance(value, list)
    if kind == "string":
        return isinstance(value, str)
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "null":
        return value is None
    raise SchemaError(f"unsupported type {kind!r}")


def _pattern(text: str) -> re.Pattern:
    # JSON Schema `$` means end of string; Python's also matches before a trailing newline.
    if text.endswith("$") and not text.endswith("\\$"):
        text = text[:-1] + r"\Z"
    return re.compile(text)


def _equal(a, b) -> bool:
    """JSON equality: True is not 1."""
    if isinstance(a, bool) != isinstance(b, bool):
        return False
    return a == b


def _resolve(ref: str, root: dict) -> dict:
    if not ref.startswith("#/$defs/"):
        raise SchemaError(f"only local $defs references are supported: {ref}")
    name = ref[len("#/$defs/"):]
    try:
        return root["$defs"][name]
    except KeyError as error:
        raise SchemaError(f"unknown $ref {ref}") from error


def check_schema(schema: dict, path: str = "#") -> None:
    """Refuses schemas that use keywords outside the supported subset."""
    if not isinstance(schema, dict):
        raise SchemaError(f"{path}: a schema must be an object")
    for key in schema:
        if key not in KEYWORDS and key not in ANNOTATIONS:
            raise SchemaError(f"{path}: unsupported schema keyword {key!r}")
    if "type" in schema and (not isinstance(schema["type"], str) or schema["type"] not in TYPES):
        raise SchemaError(f"{path}: unsupported type {schema['type']!r}")
    if "$ref" in schema and not (isinstance(schema["$ref"], str) and schema["$ref"].startswith("#/$defs/")):
        raise SchemaError(f"{path}: only local $defs references are supported: {schema['$ref']!r}")
    for key in ("properties", "$defs"):
        for name, sub in schema.get(key, {}).items():
            check_schema(sub, f"{path}/{key}/{name}")
    if isinstance(schema.get("additionalProperties"), dict):
        check_schema(schema["additionalProperties"], f"{path}/additionalProperties")
    if "items" in schema:
        check_schema(schema["items"], f"{path}/items")
    for key in ("oneOf", "allOf"):
        for index, sub in enumerate(schema.get(key, [])):
            check_schema(sub, f"{path}/{key}/{index}")


def validate(instance, schema: dict, root: dict | None = None) -> list[str]:
    """Returns the sorted list of violations (empty when the instance is valid)."""
    root = root if root is not None else schema
    errors: list[str] = []
    _validate(instance, schema, root, "$", errors, 0)
    return sorted(set(errors))


def _validate(value, schema: dict, root: dict, path: str, errors: list[str], depth: int) -> None:
    if depth > MAX_DEPTH:
        errors.append(f"{path}: nested too deeply")
        return
    if "$ref" in schema:
        _validate(value, _resolve(schema["$ref"], root), root, path, errors, depth + 1)
    if "type" in schema and not _type_ok(schema["type"], value):
        errors.append(f"{path}: expected {schema['type']}")
        return
    if "const" in schema and not _equal(value, schema["const"]):
        errors.append(f"{path}: must be {schema['const']!r}")
    if "enum" in schema and not any(_equal(value, option) for option in schema["enum"]):
        errors.append(f"{path}: must be one of {schema['enum']}")
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path}: shorter than {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{path}: longer than {schema['maxLength']}")
        if "pattern" in schema and not _pattern(schema["pattern"]).search(value):
            errors.append(f"{path}: does not match {schema['pattern']}")
    if isinstance(value, int) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: below {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: above {schema['maximum']}")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: more than {schema['maxItems']} items")
        if schema.get("uniqueItems"):
            seen: list = []
            for item in value:
                if any(_equal(item, other) for other in seen):
                    errors.append(f"{path}: items must be unique")
                    break
                seen.append(item)
        if "items" in schema:
            for index, item in enumerate(value):
                _validate(item, schema["items"], root, f"{path}[{index}]", errors, depth + 1)
    if isinstance(value, dict):
        for name in schema.get("required", []):
            if name not in value:
                errors.append(f"{path}: missing required {name!r}")
        properties = schema.get("properties", {})
        extra = schema.get("additionalProperties", True)
        for name, item in value.items():
            if name in properties:
                _validate(item, properties[name], root, f"{path}.{name}", errors, depth + 1)
            elif extra is False:
                errors.append(f"{path}: unexpected property {name!r}")
            elif isinstance(extra, dict):
                _validate(item, extra, root, f"{path}.{name}", errors, depth + 1)
    if "oneOf" in schema:
        matches = 0
        for branch in schema["oneOf"]:
            branch_errors: list[str] = []
            _validate(value, branch, root, path, branch_errors, depth + 1)
            matches += not branch_errors
        if matches != 1:
            errors.append(f"{path}: must match exactly one alternative (matched {matches})")
    for branch in schema.get("allOf", []):
        _validate(value, branch, root, path, errors, depth + 1)
