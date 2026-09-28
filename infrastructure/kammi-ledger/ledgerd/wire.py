"""One closed request vocabulary shared by HTTP and schema exporters."""
import json
import re
from pathlib import Path

DOCUMENT = json.loads((Path(__file__).resolve().parents[1] / "schemas/wire-v1.json").read_text())
ROUTES = [(re.compile("^" + re.sub(r"\{[^}]+\}", "[^/]+", path) + "$"), definition)
          for path, definition in DOCUMENT["$defs"].items() if path.startswith("/v1/")]


def validate_request(path, body):
    definition = next((schema for pattern, schema in ROUTES if pattern.fullmatch(path)), None)
    if definition is None:
        return
    if not isinstance(body, dict):
        raise ValueError("request must be an object")
    if set(body) - definition["properties"].keys() or set(definition["required"]) - body.keys():
        raise ValueError("request fields do not match wire-v1")
    for key, value in body.items():
        prop = definition["properties"][key]
        types = prop["type"] if isinstance(prop["type"], list) else [prop["type"]]
        actual = ("null" if value is None else "boolean" if isinstance(value, bool)
                  else "string" if isinstance(value, str) else "object" if isinstance(value, dict)
                  else "array" if isinstance(value, list) else "integer" if isinstance(value, int)
                  else "number" if isinstance(value, float) else "unknown")
        if actual not in types and not (actual == "integer" and "number" in types):
            raise ValueError("invalid request field type: " + key)
        if actual == "array" and any(not isinstance(item, str) for item in value):
            raise ValueError("array items must be strings: " + key)
