"""Canonical custody identities and strict JSON input."""

from __future__ import annotations

import hashlib
import json
import math
from decimal import Decimal
from typing import Any

import jcs

MAX_SAFE_INTEGER = (1 << 53) - 1
DOMAINS = {
    "object": b"kammi-object-v1\0",
    "event": b"kammi-event-v1\0",
    "seal": b"kammi-seal-v1\0",
    "fact": b"kammi-fact-v1\0",
}


def _validate(value: Any) -> None:
    if value is None or isinstance(value, (bool, str)):
        if isinstance(value, str) and any(0xD800 <= ord(ch) <= 0xDFFF for ch in value):
            raise ValueError("unpaired Unicode surrogate")
        return
    if isinstance(value, int):
        if abs(value) > MAX_SAFE_INTEGER:
            raise ValueError("integer is outside JCS safe range; encode as schema string")
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite JSON number")
        return
    if isinstance(value, list):
        for item in value:
            _validate(item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("JSON object key is not a string")
            _validate(key)
            _validate(item)
        return
    raise ValueError(f"unsupported JSON value: {type(value).__name__}")


def canonical(value: Any) -> bytes:
    _validate(value)
    return jcs.canonicalize(value)


def strict_json(raw: bytes) -> Any:
    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON property: {key}")
            result[key] = value
        return result

    def safe_float(token: str) -> float:
        number = float(token)
        if not math.isfinite(number) or (number == 0 and Decimal(token) != 0):
            raise ValueError("JSON number overflows or underflows binary64")
        return number

    value = json.loads(
        raw.decode("utf-8", errors="strict"),
        object_pairs_hook=unique_pairs,
        parse_float=safe_float,
        parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
    )
    _validate(value)
    return value


def raw_id(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def typed_id(kind: str, value: Any) -> str:
    return "sha256:" + hashlib.sha256(DOMAINS[kind] + canonical(value)).hexdigest()


def require_id(value: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 71
        or not value.startswith("sha256:")
        or any(ch not in "0123456789abcdef" for ch in value[7:])
    ):
        raise ValueError("expected lowercase sha256: digest")
    return value

