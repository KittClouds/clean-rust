"""The frozen contract set: the four normative schemas and the supporting records, exactly as specified."""
from __future__ import annotations

import json
import subprocess
import sys
import unittest

from . import support
from .support import FIX, ROOT, deep
from s15 import model
from s15 import schema as js

SCHEMA_FILES = ["decision-contract", "observer-bundle", "escalation-decision", "authority-decision", "observation-envelope", "decision-vector", "runtime-policy", "runtime-receipt"]
SHARED_DEFS = ["ident", "name", "token", "code", "alias", "signal", "sha256_id", "text", "ppm", "units", "escalation_label"]

# The fields the C0 charter names, per normative contract.
CHARTER = {
    "decision-contract": {"contract_id", "version", "decision_type", "question", "candidate_schema", "output_schema", "abstention_allowed", "unknown_allowed", "cost_class", "authority_class"},
    "observer-bundle": {"bundle_id", "bundle_version", "backbone", "representation", "normalization", "head", "calibration", "decision_contract_id", "training_identity", "source_hashes"},
    "escalation-decision": {"choice", "reason", "confidence_ppm", "triggering_observers", "cost_estimate"},
    "authority-decision": {"effect", "reason_code", "policy_revision", "proposed_action", "actor"},
}
# What this implementation added on top of the charter (reported to the user as design decisions).
ADDED = {
    "decision-contract": {"schema", "name"},
    "observer-bundle": {"schema", "name"},
    "escalation-decision": {"schema", "confidence_signal", "rule_id"},
    "authority-decision": {"schema", "policy_id", "rule_id", "neural_inputs_used"},
}


def load_schema(key):
    return json.loads((ROOT / "schemas" / f"{key}.schema.json").read_text(encoding="utf-8"))


class FrozenSchemaTests(support.Base):
    def test_every_schema_is_inside_the_supported_subset(self):
        for key in SCHEMA_FILES:
            with self.subTest(key):
                js.check_schema(load_schema(key))

    def test_schema_files_match_the_generator(self):
        done = subprocess.run([sys.executable, str(ROOT / "tools" / "build_schemas.py"), "--check"], capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_fixtures_match_the_builder(self):
        done = subprocess.run([sys.executable, str(ROOT / "tools" / "make_fixtures.py"), "--check"], capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_shared_definitions_are_identical_everywhere(self):
        for name in SHARED_DEFS:
            found = [json.dumps(load_schema(k)["$defs"][name], sort_keys=True) for k in SCHEMA_FILES if name in load_schema(k).get("$defs", {})]
            with self.subTest(name):
                self.assertTrue(found)
                self.assertEqual(len(set(found)), 1)

    def test_no_schema_admits_a_float(self):
        def walk(node):
            if isinstance(node, dict):
                self.assertNotEqual(node.get("type"), "number")
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)
        for key in SCHEMA_FILES:
            walk(load_schema(key))

    def test_normative_contracts_have_the_charter_fields_and_only_documented_extras(self):
        for key, wanted in CHARTER.items():
            properties = set(load_schema(key)["properties"])
            with self.subTest(key):
                self.assertTrue(wanted <= properties, wanted - properties)
                self.assertEqual(properties - wanted, ADDED[key])
                self.assertEqual(set(load_schema(key)["required"]), properties)  # every field is required: no optional meaning

    def test_closed_vocabularies_are_exactly_the_charter_lists(self):
        contract, bundle = load_schema("decision-contract"), load_schema("observer-bundle")
        self.assertEqual(contract["properties"]["decision_type"]["enum"], ["CHOICE", "MULTI_CHOICE", "APPLICABILITY", "ORDINAL", "ABSTENTION", "ESCALATION"])
        self.assertEqual(load_schema("escalation-decision")["$defs"]["escalation_label"]["enum"],
                         ["DIRECT", "USE_OBSERVER", "USE_OBSERVER_SET", "USE_LARGER_MODEL", "USE_REASONER", "ASK_HUMAN", "ABSTAIN"])
        self.assertEqual(load_schema("authority-decision")["properties"]["effect"]["enum"], ["ALLOW", "DENY", "REQUIRE_ESCALATION"])
        self.assertEqual(model.ESCALATION_LABELS, load_schema("escalation-decision")["$defs"]["escalation_label"]["enum"])
        # No authority class says that a neural output owns authority, and there is no free-form answer type.
        self.assertEqual(contract["properties"]["authority_class"]["enum"], ["ADVISORY", "PROPOSES_ACTION", "ESCALATION_ONLY"])
        candidate_kinds = json.dumps(contract["properties"]["candidate_schema"])
        output_kinds = json.dumps(contract["properties"]["output_schema"])
        for word in ("FREE", "TEXT", "STRING", "OPEN"):
            self.assertNotIn(word, candidate_kinds.upper().replace('"TYPE": "STRING"', ""))
            self.assertNotIn(word, output_kinds.upper().replace('"TYPE": "STRING"', ""))
        self.assertEqual(set(bundle["properties"]["backbone"]["required"]), {"model_id", "revision"})
        self.assertEqual(set(bundle["properties"]["representation"]["required"]), {"layer", "surface", "dimensions"})
        self.assertEqual(set(bundle["properties"]["normalization"]["required"]), {"center_hash", "scale_hash"})
        self.assertEqual(set(bundle["properties"]["head"]["required"]), {"architecture", "weights_hash", "class_order"})
        self.assertEqual(set(bundle["properties"]["calibration"]["required"]), {"method", "parameters_hash"})

    def test_records_have_no_clock(self):
        for key in SCHEMA_FILES:
            text = json.dumps(load_schema(key)).lower()
            for word in ("utc", "timestamp", "created_at", "date-time", "datetime"):
                self.assertNotIn(word, text, key)


class FixtureRecordTests(support.Base):
    def samples(self):
        """One valid record of each kind, plus the nested decisions of a receipt."""
        world = support.fixture_world()
        observation, vector = support.case_inputs("c12-medium-risk-edit")
        receipt = support.expected_receipt("c12-medium-risk-edit")
        return {
            "decision-contract": next(iter(world.contracts.values())),
            "observer-bundle": next(iter(world.bundles.values())),
            "runtime-policy": world.policy,
            "observation-envelope": observation,
            "decision-vector": vector,
            "runtime-receipt": receipt,
            "escalation-decision": receipt["escalation"],
            "authority-decision": receipt["authority"],
        }

    def test_all_stored_records_are_valid_and_their_ids_hold(self):
        for path in sorted(FIX.rglob("*.json")):
            with self.subTest(str(path.relative_to(FIX))):
                record = support.read(path)
                key = model.check_record(record)
                self.assertIn(key, SCHEMA_FILES)
                if key == "runtime-receipt":
                    model.check_record(record["escalation"])
                    if record["authority"] is not None:
                        model.check_record(record["authority"])

    def test_each_kind_rejects_a_missing_field_an_extra_field_and_a_wrong_type(self):
        for key, record in self.samples().items():
            schema = load_schema(key)
            self.assertEqual(js.validate(record, schema), [], key)
            for field in schema["required"]:
                with self.subTest(key=key, missing=field):
                    broken = deep(record)
                    del broken[field]
                    self.assertNotEqual(js.validate(broken, schema), [])
            with self.subTest(key=key, extra=True):
                broken = deep(record)
                broken["surprise"] = 1
                self.assertNotEqual(js.validate(broken, schema), [])
            for field, prop in schema["properties"].items():
                if prop.get("type") in ("string", "integer", "boolean", "array", "object"):
                    with self.subTest(key=key, wrong_type=field):
                        broken = deep(record)
                        broken[field] = None
                        self.assertNotEqual(js.validate(broken, schema), [])


if __name__ == "__main__":
    unittest.main()
