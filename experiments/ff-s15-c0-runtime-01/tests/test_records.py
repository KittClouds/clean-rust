"""Identity, tamper detection, the bundle ABI rule, loading refusals and decision-vector validation."""
from __future__ import annotations

import unittest

from . import support
from .support import FIX, Records, deep, read
from s15 import canon, model, runtime

ZERO = "sha256:" + "0" * 64
ONE = "sha256:" + "1" * 64


def set_path(record, path, value):
    node = record
    *head, last = path.split(".")
    for part in head:
        node = node[part]
    node[last] = value


class IdentityTests(support.Base):
    def test_changing_any_field_without_resealing_is_detected(self):
        records = Records()
        targets = [("contract", records.contracts["next_action"], "question", "changed"), ("bundle", records.bundles["router_a"], "training_identity", "changed"),
                   ("policy", records.policy, "policy_revision", 2)]
        for label, record, field, value in targets:
            with self.subTest(label):
                broken = deep(record)
                broken[field] = value
                with self.assertRaises(model.RecordError) as raised:
                    model.check_record(broken)
                self.assertIn("does not match the record's content", str(raised.exception))
        observation, vector = support.case_inputs("c02-confident-observer")
        vector["producer"]["source"] = "someone else"
        with self.assertRaises(model.RecordError):
            model.check_record(vector)
        receipt = support.expected_receipt("c02-confident-observer")
        receipt["cost"]["units"] += 1
        with self.assertRaises(model.RecordError):
            model.check_record(receipt)

    def test_resealing_a_changed_record_gives_a_different_id(self):
        record = Records().contracts["risk"]
        changed = model.seal({**record, "version": 2})
        self.assertNotEqual(changed["contract_id"], record["contract_id"])
        model.check_record(changed)

    def test_ids_do_not_depend_on_field_order(self):
        record = Records().bundles["router_a"]
        reordered = dict(reversed(list(record.items())))
        self.assertEqual(model.seal(reordered)["bundle_id"], record["bundle_id"])


class BundleAbiTests(support.Base):
    """Any compatibility field change makes a different bundle, and a policy naming the old one refuses the new one."""

    FIELDS = [
        ("backbone.model_id", "other-model"), ("backbone.revision", "other-revision"), ("representation.layer", "other_layer"),
        ("representation.surface", "other_surface"), ("representation.dimensions", 4096), ("normalization.center_hash", ZERO),
        ("normalization.scale_hash", ZERO), ("head.architecture", "mlp999"), ("head.weights_hash", ZERO), ("calibration.method", "TEMPERATURE"),
        ("calibration.parameters_hash", ZERO), ("training_identity", "other-training"), ("bundle_version", 2), ("source_hashes", [ZERO, ONE]),
    ]

    def test_every_compatibility_field_makes_a_different_bundle(self):
        for path, value in self.FIELDS:
            with self.subTest(path):
                records = Records()
                old = records.bundles["router_a"]
                new = deep(old)
                set_path(new, path, value)
                new = model.seal(new)
                self.assertNotEqual(new["bundle_id"], old["bundle_id"])
                model.check_record(new)
                records.bundles["router_a"] = new  # the new bundle replaces the old one on disk
                with self.assertRaises(model.RecordError) as raised:
                    records.world(self.tmp())
                self.assertIn("unknown bundle", str(raised.exception))  # the old policy still names the old id

    def test_class_order_is_part_of_the_bundle_and_must_match_the_contract(self):
        records = Records()
        new = deep(records.bundles["router_a"])
        order = new["head"]["class_order"]
        new["head"]["class_order"] = [order[1], order[0], *order[2:]]
        new = model.seal(new)
        self.assertNotEqual(new["bundle_id"], records.bundles["router_a"]["bundle_id"])
        records.bundles["router_a"] = new
        with self.assertRaises(model.RecordError) as raised:
            records.world(self.tmp())
        self.assertIn("class order differs", str(raised.exception))

    def test_a_bundle_cannot_name_a_contract_it_does_not_match(self):
        records = Records()
        new = deep(records.bundles["router_a"])
        new["decision_contract_id"] = records.contracts["risk"]["contract_id"]
        records.bundles["router_a"] = model.seal(new)
        with self.assertRaises(model.RecordError):
            records.world(self.tmp())

    def test_a_changed_contract_orphans_its_bundles(self):
        records = Records()
        records.contracts["next_action"] = model.seal({**records.contracts["next_action"], "question": "a_different_question"})
        with self.assertRaises(model.RecordError) as raised:
            records.world(self.tmp())
        self.assertIn("is not in", str(raised.exception))

    def test_unsorted_source_hashes_are_refused(self):
        records = Records()
        new = deep(records.bundles["router_a"])
        new["source_hashes"] = [ONE, ZERO]
        records.bundles["router_a"] = model.seal(new)
        with self.assertRaises(model.RecordError):
            records.world(self.tmp())


class ContractRuleTests(support.Base):
    def rejects(self, name, mutate, fragment=""):
        records = Records()
        mutate(records.contracts[name])
        records.contracts[name] = model.seal(records.contracts[name])
        with self.assertRaises(model.RecordError) as raised:
            records.world(self.tmp())
        self.assertIn(fragment, str(raised.exception))

    def test_contract_consistency_rules(self):
        self.rejects("next_action", lambda c: c["candidate_schema"].update({"labels": ["search", "read"]}), "candidate labels must equal output labels")
        self.rejects("next_action", lambda c: c["output_schema"].update({"kind": "INDEPENDENT"}), "needs a SIMPLEX output")
        self.rejects("entities", lambda c: c["output_schema"].update({"kind": "SIMPLEX"}), "INDEPENDENT")
        self.rejects("abstain", lambda c: c.update({"abstention_allowed": False}), "allows abstention")
        self.rejects("applicable", lambda c: c["output_schema"].update({"labels": ["YES", "NO", "MAYBE"]}), "YES, NO, UNKNOWN")
        self.rejects("applicable", lambda c: c.update({"unknown_allowed": False}), "unknown_allowed")
        self.rejects("risk", lambda c: c.update({"authority_class": "PROPOSES_ACTION"}), "only a CHOICE can propose")
        self.rejects("should_think", lambda c: (c["output_schema"].update({"labels": ["DIRECT", "ABSTAIN"]}), c["candidate_schema"].update({"labels": ["DIRECT", "ABSTAIN"]})), "seven escalation labels")
        self.rejects("should_think", lambda c: c.update({"authority_class": "PROPOSES_ACTION"}), "ESCALATION_ONLY")

    def test_free_form_answers_do_not_exist(self):
        for key, value in (("decision_type", "FREE_TEXT"), ("authority_class", "OWNS_AUTHORITY")):
            record = deep(Records().contracts["next_action"])
            record[key] = value
            with self.assertRaises(model.RecordError):
                model.check_record(model.seal(record))


class LoadingTests(support.Base):
    def test_loader_refusals(self):
        good = canon.canonical_bytes(Records().contracts["risk"])
        cases = {
            "float": good.replace(b'"version":1', b'"version":1.0'),
            "duplicate key": good.replace(b'{"', b'{"question":"x","', 1),
            "non-ascii": good.replace(b'"risk"', '"rïsk"'.encode("utf-8"), 1),
            "byte order mark": b"\xef\xbb\xbf" + good,
            "not json": b"{",
        }
        for label, data in cases.items():
            with self.subTest(label):
                directory = self.tmp()
                (directory / "risk.json").write_bytes(data)
                with self.assertRaises(model.RecordError):
                    model.load_dir(directory, "S15_DECISION_CONTRACT_V1")

    def test_a_record_of_the_wrong_kind_in_a_directory_is_refused(self):
        directory = self.tmp()
        (directory / "x.json").write_bytes((FIX / "bundles" / "router_a.json").read_bytes())
        with self.assertRaises(model.RecordError) as raised:
            model.load_dir(directory, "S15_DECISION_CONTRACT_V1")
        self.assertIn("expected", str(raised.exception))

    def test_a_document_without_a_known_schema_is_refused(self):
        for record in ({}, {"schema": "S15_NOPE_V1"}, [], {"schema": 1}):
            with self.assertRaises(model.RecordError):
                model.check_record(record)

    def test_pretty_printed_and_reordered_files_load_to_the_same_world(self):
        import json
        import random

        rng = random.Random(3)
        records = Records()
        directory = self.tmp()
        records.write(directory, encode=lambda r: (json.dumps(support.shuffled(r, rng), indent=2) + "\r\n").encode("ascii"))
        world = model.load_world(directory / "policy.json", directory / "contracts", directory / "bundles")
        self.assertEqual(world.policy["policy_id"], support.fixture_world().policy["policy_id"])


class VectorValidationTests(support.Base):
    def setUp(self):
        self.world = support.fixture_world()
        self.observation, self.vector = support.case_inputs("c02-confident-observer")

    def refused(self, vector, observation=None, exceptions=(runtime.InputError,)):
        with self.assertRaises(exceptions):
            runtime.run(self.world, observation or self.observation, vector)

    def entry(self, alias):
        return next(e for e in self.vector["entries"] if e["bundle_id"] == self.world.alias_bundle[alias]["bundle_id"])

    def test_wrong_probability_sum(self):
        ppm = list(self.entry("router")["probabilities_ppm"])
        ppm[0] -= 1
        self.refused(support.with_outputs(self.vector, self.world, router=ppm))

    def test_wrong_length(self):
        self.refused(support.with_outputs(self.vector, self.world, router=[500_000, 500_000]))

    def test_independent_outputs_need_no_sum_but_must_be_in_range(self):
        support.with_outputs(self.vector, self.world, entities=[1_000_000, 1_000_000, 0, 0])  # legal: independent labels
        runtime.run(self.world, self.observation, support.with_outputs(self.vector, self.world, entities=[1_000_000, 1_000_000, 0, 0]))
        with self.assertRaises(model.RecordError):
            runtime.run(self.world, self.observation, support.with_outputs(self.vector, self.world, entities=[1_000_001, 0, 0, 0]))
        with self.assertRaises(model.RecordError):
            runtime.run(self.world, self.observation, support.with_outputs(self.vector, self.world, entities=[-1, 0, 0, 0]))

    def test_output_for_a_bundle_the_policy_does_not_use(self):
        vector = deep(self.vector)
        vector["entries"].append({"bundle_id": "sha256:" + "a" * 64, "probabilities_ppm": [500_000, 500_000]})
        vector["entries"].sort(key=lambda e: e["bundle_id"])
        self.refused(support.reseal_vector(vector))

    def test_two_outputs_for_one_bundle(self):
        vector = deep(self.vector)
        vector["entries"].append(deep(vector["entries"][0]))
        self.refused(support.reseal_vector(vector))

    def test_vector_for_another_observation(self):
        self.refused(support.reseal_vector({**self.vector, "observation_id": "someone-else"}))

    def test_candidate_rules(self):
        vector = deep(self.vector)
        for entry in vector["entries"]:
            entry.pop("candidate", None)
        self.refused(support.reseal_vector(vector))  # applicability needs its candidate
        vector = deep(self.vector)
        for entry in vector["entries"]:
            entry["candidate"] = "search"
        self.refused(support.reseal_vector(vector))  # a plain choice must not carry one

    def test_bad_observation_facts_are_refused(self):
        observation = deep(self.observation)
        observation["facts"]["not a name"] = 1
        self.refused(self.vector, observation, exceptions=(model.RecordError, runtime.InputError))
        observation = deep(self.observation)
        observation["authority_state"]["flags"]["1bad"] = True
        self.refused(self.vector, observation, exceptions=(model.RecordError, runtime.InputError))

    def test_a_vector_is_not_an_observation(self):
        with self.assertRaises((model.RecordError, runtime.InputError)):
            runtime.run(self.world, self.vector, self.vector)


if __name__ == "__main__":
    unittest.main()
