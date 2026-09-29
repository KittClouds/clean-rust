"""Canonical bytes, identities and strict JSON loading for System 1.5 C0 records.

The C0 gate is byte-identical decisions and receipts for the same inputs. That is only true
across languages and machines if the records contain nothing whose text form can differ, so:

- no floats (probabilities, thresholds and costs are integers, parts per million);
- printable ASCII only in every string and key (so JSON escaping and key order are the same in
  every implementation: code-point order equals UTF-16 order);
- integers within +-(2**53 - 1);
- no wall-clock time anywhere (time belongs to the journal envelope of a later integration).

Canonical form is JSON with sorted keys, no whitespace, ASCII escapes. Identities are SHA-256
over a domain tag plus the canonical bytes of the record without its own id field.
"""
from __future__ import annotations

import hashlib
import json
import re

MAX_SAFE_INT = 2**53 - 1
_ASCII = re.compile(r"[\x20-\x7e]*")


class CanonError(ValueError):
    """A value or document that cannot be part of a canonical C0 record."""


def check_value(value, path: str = "$") -> None:
    """Raises CanonError unless `value` is made only of canonical JSON building blocks."""
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, int):
        if abs(value) > MAX_SAFE_INT:
            raise CanonError(f"{path}: integer beyond 2^53-1")
        return
    if isinstance(value, float):
        raise CanonError(f"{path}: floats are not allowed (probabilities and thresholds are integer ppm)")
    if isinstance(value, str):
        if not _ASCII.fullmatch(value):
            raise CanonError(f"{path}: only printable ASCII is allowed in strings")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            check_value(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or not _ASCII.fullmatch(key):
                raise CanonError(f"{path}: keys must be printable ASCII strings")
            check_value(item, f"{path}.{key}")
        return
    raise CanonError(f"{path}: unsupported value type {type(value).__name__}")


def canonical_bytes(value) -> bytes:
    """The canonical encoding: what is hashed, stored and compared."""
    check_value(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")


def sha256_id(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def derive_id(kind: str, body: dict) -> str:
    """Identity of a record: SHA-256 of `s15-<kind>-v1\\0` plus the canonical body without its id."""
    return sha256_id(b"s15-" + kind.encode("ascii") + b"-v1\0" + canonical_bytes(body))


def without(record: dict, key: str) -> dict:
    return {k: v for k, v in record.items() if k != key}


def loads_strict(data: bytes):
    """Parses a C0 document: UTF-8 without BOM, no duplicate keys, no floats, no NaN, canonical values."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise CanonError(f"not valid UTF-8: {error}") from error
    if text.startswith("﻿"):
        raise CanonError("a byte order mark is not allowed")

    def pairs(items):
        result: dict = {}
        for key, value in items:
            if key in result:
                raise CanonError(f"duplicate key {key!r}")
            result[key] = value
        return result

    def refuse_float(text_form):
        raise CanonError(f"floats are not allowed ({text_form})")

    def refuse_constant(text_form):
        raise CanonError(f"{text_form} is not allowed")

    try:
        value = json.loads(text, object_pairs_hook=pairs, parse_float=refuse_float, parse_constant=refuse_constant)
    except json.JSONDecodeError as error:
        raise CanonError(f"not valid JSON: {error}") from error
    check_value(value)
    return value


def _shares_to_ppm(shares: list) -> list[int]:
    """Exact rational shares that sum to 1,000,000 -> integers summing to exactly 1,000,000.

    Largest remainder: floor every share, then give the missing units to the largest remainders,
    ties to the lowest index. Pure integer/rational arithmetic, so the result is the same on every
    machine.
    """
    floors = [share.numerator // share.denominator for share in shares]
    remainders = [share - floor for share, floor in zip(shares, floors)]
    order = sorted(range(len(shares)), key=lambda index: (-remainders[index], index))
    result = list(floors)
    for index in order[: 1_000_000 - sum(floors)]:
        result[index] += 1
    return result


def quantize_weights(weights: list[int]) -> list[int]:
    """Integer weights -> ppm summing to exactly 1,000,000."""
    from fractions import Fraction

    total = sum(weights)
    if total <= 0 or any(w < 0 for w in weights):
        raise CanonError("weights must be non-negative with a positive sum")
    return _shares_to_ppm([Fraction(w * 1_000_000, total) for w in weights])


def quantize_probabilities(probabilities: list[float]) -> list[int]:
    """Model probabilities -> ppm summing to exactly 1,000,000.

    This is the one place a float meets a C0 record. Each float is converted to its exact rational
    value (so identical floats give identical integers everywhere), renormalized by their sum, and
    rounded by largest remainder.
    """
    from fractions import Fraction

    exact = [Fraction(p) for p in probabilities]
    if any(p < 0 for p in exact) or sum(exact) <= 0:
        raise CanonError("probabilities must be non-negative with a positive sum")
    total = sum(exact)
    return _shares_to_ppm([p / total * 1_000_000 for p in exact])
