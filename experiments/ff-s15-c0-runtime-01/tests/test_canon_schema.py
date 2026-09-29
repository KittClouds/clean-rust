"""Canonical bytes, identities, quantization and the strict schema validator."""
from __future__ import annotations

import random
import unittest

from . import support  # noqa: F401  (puts the package on sys.path)
from s15 import canon
from s15 import schema as js


class CanonTests(unittest.TestCase):
    def test_canonical_form_is_sorted_compact_ascii(self):
        self.assertEqual(canon.canonical_bytes({"b": 1, "a": [True, None, "x"], "c": {"z": 0, "y": -1}}),
                         b'{"a":[true,null,"x"],"b":1,"c":{"y":-1,"z":0}}')
        self.assertEqual(canon.canonical_bytes({"q": 'a"b\\c'}), b'{"q":"a\\"b\\\\c"}')

    def test_key_order_never_changes_the_bytes(self):
        self.assertEqual(canon.canonical_bytes({"a": 1, "b": {"x": 1, "y": 2}}), canon.canonical_bytes({"b": {"y": 2, "x": 1}, "a": 1}))

    def test_identity_construction_is_frozen(self):
        # If this changes, every id in every stored record changes with it.
        self.assertEqual(canon.derive_id("contract", {"a": 1}), "sha256:1106ef11ba45c2786157fa07426e00d9d15529c5a5525b8a90cbcf5ad176bd7e")
        self.assertEqual(canon.sha256_id(b"abc"), "sha256:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")

    def test_identity_is_domain_separated(self):
        self.assertNotEqual(canon.derive_id("contract", {"a": 1}), canon.derive_id("bundle", {"a": 1}))

    def test_values_that_cannot_be_canonical_are_refused(self):
        for bad in (1.0, 0.5, float("nan"), float("inf"), "café", "line\nbreak", "tab\t", "\x7f", 2**53, -(2**53), {1: "a"}, {"é": 1}, (1, 2), b"x", {"a": {1}}):
            with self.subTest(bad=repr(bad)):
                with self.assertRaises(canon.CanonError):
                    canon.canonical_bytes(bad)
        self.assertEqual(canon.canonical_bytes(2**53 - 1), b"9007199254740991")
        self.assertEqual(canon.canonical_bytes(-(2**53 - 1)), b"-9007199254740991")

    def test_strict_loader_refuses(self):
        cases = {
            "duplicate key": b'{"a":1,"a":2}',
            "nested duplicate key": b'{"x":{"a":1,"a":1}}',
            "float": b'{"a":1.0}',
            "exponent": b'{"a":1e3}',
            "NaN": b'{"a":NaN}',
            "Infinity": b'{"a":Infinity}',
            "byte order mark": b'\xef\xbb\xbf{"a":1}',
            "invalid utf-8": b'{"a":"\xff"}',
            "raw non-ASCII": '{"a":"é"}'.encode("utf-8"),
            "escaped non-ASCII": b'{"a":"\\u00e9"}',
            "integer beyond 2^53-1": b'{"a":9007199254740992}',
            "trailing comma": b'{"a":1,}',
            "trailing garbage": b'{"a":1} x',
            "empty": b"",
        }
        for label, data in cases.items():
            with self.subTest(label):
                with self.assertRaises(canon.CanonError):
                    canon.loads_strict(data)

    def test_strict_loader_accepts_any_whitespace_and_key_order(self):
        self.assertEqual(canon.loads_strict(b'{\r\n  "b": [1,\r\n 2],\r\n\t"a": true\r\n}\r\n'), {"a": True, "b": [1, 2]})

    def test_load_then_canonical_roundtrip(self):
        record = {"z": [1, 2, {"b": None, "a": "x"}], "a": False}
        self.assertEqual(canon.loads_strict(canon.canonical_bytes(record)), record)


class QuantizeTests(unittest.TestCase):
    def test_weights_sum_exactly(self):
        self.assertEqual(canon.quantize_weights([1, 1, 1]), [333334, 333333, 333333])
        self.assertEqual(canon.quantize_weights([1, 0]), [1_000_000, 0])
        self.assertEqual(canon.quantize_weights([3, 1]), [750_000, 250_000])
        self.assertEqual(canon.quantize_weights([0, 0, 5]), [0, 0, 1_000_000])

    def test_weights_property(self):
        rng = random.Random(15)
        for _ in range(500):
            weights = [rng.randint(0, 1000) for _ in range(rng.randint(1, 12))]
            if sum(weights) == 0:
                continue
            ppm = canon.quantize_weights(weights)
            self.assertEqual(sum(ppm), 1_000_000)
            total = sum(weights)
            for w, p in zip(weights, ppm):
                self.assertLessEqual(abs(p * total - w * 1_000_000), total)  # within one unit of the exact share
            for i in range(len(weights)):
                for j in range(len(weights)):
                    if weights[i] > weights[j]:
                        self.assertGreaterEqual(ppm[i], ppm[j])

    def test_probabilities(self):
        self.assertEqual(canon.quantize_probabilities([0.5, 0.25, 0.25]), [500_000, 250_000, 250_000])
        self.assertEqual(canon.quantize_probabilities([1.0, 1.0, 2.0]), [250_000, 250_000, 500_000])  # renormalized
        self.assertEqual(sum(canon.quantize_probabilities([0.1, 0.2, 0.7])), 1_000_000)
        self.assertEqual(canon.quantize_probabilities([0.1, 0.2, 0.7]), canon.quantize_probabilities([0.1, 0.2, 0.7]))
        rng = random.Random(7)
        for _ in range(200):
            values = [rng.random() for _ in range(rng.randint(1, 9))]
            self.assertEqual(sum(canon.quantize_probabilities(values)), 1_000_000)

    def test_invalid_inputs_are_refused(self):
        for bad in ([], [0, 0], [-1, 2]):
            with self.assertRaises(canon.CanonError):
                canon.quantize_weights(bad)
        for bad in ([-0.1, 1.1], [0.0, 0.0]):
            with self.assertRaises(canon.CanonError):
                canon.quantize_probabilities(bad)


class SchemaValidatorTests(unittest.TestCase):
    def ok(self, schema, value):
        self.assertEqual(js.validate(value, schema), [], value)

    def bad(self, schema, value):
        self.assertNotEqual(js.validate(value, schema), [], value)

    def test_types_are_strict(self):
        self.ok({"type": "integer"}, 3)
        self.bad({"type": "integer"}, True)  # a boolean is not an integer
        self.bad({"type": "integer"}, "3")
        self.bad({"type": "string"}, 3)
        self.bad({"type": "boolean"}, 1)
        self.ok({"type": "null"}, None)
        self.bad({"type": "array"}, {})
        self.bad({"type": "object"}, [])

    def test_bounds_and_lengths(self):
        self.ok({"type": "integer", "minimum": 0, "maximum": 5}, 5)
        self.bad({"type": "integer", "minimum": 0, "maximum": 5}, 6)
        self.bad({"type": "integer", "minimum": 0}, -1)
        self.ok({"type": "string", "minLength": 2, "maxLength": 3}, "ab")
        self.bad({"type": "string", "minLength": 2}, "a")
        self.bad({"type": "string", "maxLength": 1}, "ab")

    def test_pattern_dollar_means_end_of_string(self):
        schema = {"type": "string", "pattern": "^[a-z]+$"}
        self.ok(schema, "abc")
        self.bad(schema, "abc\n")  # Python's `$` alone would accept this
        self.bad(schema, "Abc")

    def test_enum_and_const_use_json_equality(self):
        self.ok({"enum": ["a", 1]}, 1)
        self.bad({"enum": ["a", 1]}, True)  # True is not 1
        self.bad({"enum": [0]}, False)
        self.ok({"const": True}, True)
        self.bad({"const": 1}, True)

    def test_objects(self):
        schema = {"type": "object", "required": ["a"], "properties": {"a": {"type": "integer"}}, "additionalProperties": False}
        self.ok(schema, {"a": 1})
        self.bad(schema, {})
        self.bad(schema, {"a": 1, "b": 2})
        self.bad(schema, {"a": "x"})
        self.ok({"type": "object", "additionalProperties": {"type": "integer"}}, {"x": 1, "y": 2})
        self.bad({"type": "object", "additionalProperties": {"type": "integer"}}, {"x": "no"})
        self.ok({"type": "object"}, {"anything": [1]})

    def test_arrays(self):
        schema = {"type": "array", "items": {"type": "integer"}, "minItems": 1, "maxItems": 2, "uniqueItems": True}
        self.ok(schema, [1, 2])
        self.bad(schema, [])
        self.bad(schema, [1, 2, 3])
        self.bad(schema, [1, 1])
        self.bad(schema, ["a"])
        self.ok({"type": "array", "uniqueItems": True}, [1, True])  # 1 and true are different JSON values

    def test_one_of_all_of_and_refs(self):
        one = {"oneOf": [{"type": "integer"}, {"type": "string"}]}
        self.ok(one, 1)
        self.ok(one, "x")
        self.bad(one, None)
        self.bad({"oneOf": [{"type": "integer"}, {"minimum": 0}]}, 3)  # matches both
        both = {"allOf": [{"type": "integer"}, {"minimum": 2}]}
        self.ok(both, 2)
        self.bad(both, 1)
        ref = {"$defs": {"n": {"type": "integer", "minimum": 0}}, "type": "object", "properties": {"a": {"$ref": "#/$defs/n"}}}
        self.ok(ref, {"a": 0})
        self.bad(ref, {"a": -1})
        recursive = {"$defs": {"t": {"type": "object", "properties": {"kid": {"$ref": "#/$defs/t"}}, "additionalProperties": False}}, "$ref": "#/$defs/t"}
        self.ok(recursive, {"kid": {"kid": {}}})
        self.bad(recursive, {"kid": {"nope": 1}})

    def test_errors_are_sorted_and_deterministic(self):
        schema = {"type": "object", "required": ["b", "a"], "additionalProperties": False, "properties": {}}
        first = js.validate({"z": 1}, schema)
        self.assertEqual(first, sorted(first))
        self.assertEqual(first, js.validate({"z": 1}, schema))

    def test_unsupported_schemas_are_refused(self):
        for schema in ({"format": "date"}, {"not": {}}, {"if": {}}, {"anyOf": []}, {"type": "number"}, {"type": ["string", "null"]},
                       {"$ref": "http://example.com/x"}, {"properties": {"a": {"minProperties": 1}}}, {"items": {"contains": {}}}, {"oneOf": [{"format": "x"}]}):
            with self.subTest(schema=schema):
                with self.assertRaises(js.SchemaError):
                    js.check_schema(schema)
        with self.assertRaises(js.SchemaError):
            js.validate(1, {"$ref": "#/$defs/missing"})


if __name__ == "__main__":
    unittest.main()
