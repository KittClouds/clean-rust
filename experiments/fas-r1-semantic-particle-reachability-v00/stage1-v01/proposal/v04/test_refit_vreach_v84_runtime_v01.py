from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).with_name("refit_vreach_v84_runtime_v01.py")
SPEC = importlib.util.spec_from_file_location("r1_v04_v84_runtime_refit_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
REFIT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = REFIT
SPEC.loader.exec_module(REFIT)


class V84PolicyIdentityTests(unittest.TestCase):
    def test_composite_identity_binds_v84_raw_sha_and_exact_low_temperature(self) -> None:
        sources = {
            name: f"{index:064x}"
            for index, name in enumerate(REFIT.RUNTIME.POLICY_IDENTITY_SOURCE_FILES, 1)
        }
        identity, policy_sha = REFIT.build_v84_policy_identity(sources)
        validated = REFIT.RUNTIME.validate_policy_identity(
            identity,
            REFIT.V84_PROPOSAL_SHA256,
            REFIT.V84_TEMPERATURE,
            policy_sha,
            expected_source_hashes=sources,
        )

        self.assertEqual(validated["weights_sha256"], REFIT.V84_PROPOSAL_SHA256)
        self.assertEqual(validated["temperature_f64_bits_le_hex"], "3c0f16adcaddc63f")
        self.assertNotEqual(policy_sha, REFIT.V84_PROPOSAL_SHA256)

        with self.assertRaisesRegex(ValueError, "composite policy identity"):
            REFIT.RUNTIME.validate_policy_identity(
                identity,
                REFIT.V84_PROPOSAL_SHA256,
                REFIT.V84_TEMPERATURE,
                "00" * 32,
                expected_source_hashes=sources,
            )

    def test_rejects_rounded_v84_temperature_bits(self) -> None:
        identity, policy_sha = REFIT.build_v84_policy_identity(
            {
                name: f"{index:064x}"
                for index, name in enumerate(REFIT.RUNTIME.POLICY_IDENTITY_SOURCE_FILES, 1)
            }
        )
        identity["temperature_f64_bits_le_hex"] = "3d0f16adcaddc63f"
        with self.assertRaisesRegex(ValueError, "bit pattern"):
            REFIT.RUNTIME.validate_policy_identity(
                identity,
                REFIT.V84_PROPOSAL_SHA256,
                REFIT.V84_TEMPERATURE,
                policy_sha,
                expected_source_hashes=identity["source_sha256"],
            )


class V84DirectProposalLineageTests(unittest.TestCase):
    def test_raw_proposal_pin_rejects_v132_and_accepts_v84(self) -> None:
        self.assertEqual(
            REFIT.validate_v84_proposal_sha256(REFIT.V84_PROPOSAL_SHA256),
            REFIT.V84_PROPOSAL_SHA256,
        )
        with self.assertRaisesRegex(ValueError, "pinned direct V84"):
            REFIT.validate_v84_proposal_sha256(
                "748ceb3d527408b06b7cb46b101c73e2609a7c13e7fd78dcde589fb9914c93d4"
            )

    def test_request_receipt_must_name_v84_weights_not_v132(self) -> None:
        request_receipt = {
            "proposal": {"weights_sha256": REFIT.V84_PROPOSAL_SHA256},
            "inputs": {"proposal_weights": {"sha256": REFIT.V84_PROPOSAL_SHA256}},
        }
        self.assertEqual(
            REFIT.validate_v84_request_proposal_sha(request_receipt),
            REFIT.V84_PROPOSAL_SHA256,
        )
        request_receipt["proposal"]["weights_sha256"] = "748ceb3d527408b06b7cb46b101c73e2609a7c13e7fd78dcde589fb9914c93d4"
        request_receipt["inputs"]["proposal_weights"]["sha256"] = request_receipt["proposal"]["weights_sha256"]
        with self.assertRaisesRegex(ValueError, "pinned direct V84"):
            REFIT.validate_v84_request_proposal_sha(request_receipt)

    def test_direct_lineage_verifies_request_start_and_actual_v04_fit_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {
                name: root / name
                for name in (
                    "proposal.json",
                    "private-trainval.jsonl",
                    "proposal-fit-receipt.json",
                    "starts.jsonl",
                    "starts.receipt.json",
                    "requests.jsonl",
                )
            }
            paths["proposal.json"].write_text("{}", encoding="utf-8")
            paths["private-trainval.jsonl"].write_text("{}\n", encoding="utf-8")
            paths["proposal-fit-receipt.json"].write_text("{}", encoding="utf-8")
            paths["starts.jsonl"].write_text("{}\n", encoding="utf-8")
            paths["starts.receipt.json"].write_text("{}", encoding="utf-8")
            paths["requests.jsonl"].write_text("{}\n", encoding="utf-8")

            records = {
                "proposal_weights": (paths["proposal.json"], REFIT.V84_PROPOSAL_SHA256),
                "private_trainval_only": (paths["private-trainval.jsonl"], "11" * 32),
                "proposal_fit_receipt": (paths["proposal-fit-receipt.json"], "22" * 32),
                "start_states": (paths["starts.jsonl"], "33" * 32),
                "start_state_receipt": (paths["starts.receipt.json"], "44" * 32),
            }
            request_inputs = {
                key: {"path": str(path), "sha256": digest, "bytes": 1}
                for key, (path, digest) in records.items()
            }
            request_inputs["proposal"] = {"private_trainval_sha256": "11" * 32}
            proposal_lineage = {"identity_receipt_sha256": "55" * 32}
            request_receipt = {
                "proposal": {"weights_sha256": REFIT.V84_PROPOSAL_SHA256},
                "inputs": {
                    "proposal_weights": {"sha256": REFIT.V84_PROPOSAL_SHA256}
                },
                "request_file": {"path": str(paths["requests.jsonl"]), "sha256": "66" * 32, "bytes": 1},
            }
            receipt_path_records = {
                str(path.resolve()): {"path": str(path.resolve()), "sha256": digest, "bytes": 1}
                for path, digest in [*records.values(), (paths["requests.jsonl"], "66" * 32)]
            }

            def file_record(record: object, path: Path, label: str) -> dict[str, object]:
                del label
                declared = record
                if not isinstance(declared, dict):
                    raise ValueError("missing record")
                if Path(declared["path"]).resolve() != path.resolve():
                    raise ValueError("record path mismatch")
                return receipt_path_records[str(path.resolve())]

            with (
                mock.patch.object(REFIT.RUNTIME, "sha", side_effect=lambda path: REFIT.V84_PROPOSAL_SHA256 if Path(path) == paths["proposal.json"] else "33" * 32),
                mock.patch.object(REFIT.REQUESTS, "verify_proposal_weights", return_value={"schema": REFIT.REQUESTS.PROPOSAL_SCHEMA}),
                mock.patch.object(REFIT.REFIT, "validate_request_receipt", return_value=(proposal_lineage, request_inputs)) as validate_request,
                mock.patch.object(REFIT.RUNTIME, "_require_file_record", side_effect=file_record),
                mock.patch.object(REFIT.REQUESTS, "iter_jsonl", return_value=[{}] * 80),
                mock.patch.object(REFIT.REQUESTS, "verify_proposal_receipt", return_value=proposal_lineage) as verify_fit,
                mock.patch.object(REFIT.REQUESTS, "verify_start_receipt") as verify_start,
            ):
                result = REFIT.validate_v84_request_start_fit_lineage(
                    request_receipt,
                    paths["starts.jsonl"],
                    paths["starts.receipt.json"],
                    paths["proposal.json"],
                    paths["proposal-fit-receipt.json"],
                )

            validate_request.assert_called_once_with(
                request_receipt, REFIT.V84_PROPOSAL_SHA256, "33" * 32
            )
            verify_fit.assert_called_once()
            verify_start.assert_called_once_with(
                {}, "33" * 32, "11" * 32, "22" * 32
            )
            self.assertEqual(
                result["proposal_fit_receipt_record"]["sha256"], "22" * 32
            )


class V84TemperatureOverrideTests(unittest.TestCase):
    def make_override(self) -> dict[str, object]:
        return {
            "schema": REFIT.V84_TEMPERATURE_OVERRIDE_SCHEMA,
            "status": "COMPLETE",
            "mode": "ADAPTIVE_ENGINEERING",
            "qualification_selection_access": True,
            "scientific_confirmation_eligible": False,
            "proposal_sha256": REFIT.V84_PROPOSAL_SHA256,
            "selected_temperature": REFIT.V84_TEMPERATURE,
            "selected_temperature_f64_bits_le_hex": REFIT.V84_TEMPERATURE_BITS_LE_HEX,
            "source_lineage": {
                "temperature_source": "V19",
                "historical_qualification_selection_access": True,
                "historical_qualification_runs": REFIT.V19_HISTORICAL_QUALIFICATION_RUNS.copy(),
                "qualification_manifest_sha256": REFIT.V19_QUALIFICATION_MANIFEST_SHA256.copy(),
                "proposal_id": "V84",
                "proposal_sha256": REFIT.V84_PROPOSAL_SHA256,
            },
        }

    def test_accepts_exact_v84_override_with_disclosed_qualification_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "temperature-override.json"
            path.write_text("{}\n", encoding="utf-8")
            selected = REFIT.validate_v84_temperature_override(
                self.make_override(), path, REFIT.V84_PROPOSAL_SHA256
            )
        self.assertEqual(selected, REFIT.V84_TEMPERATURE)
        self.assertEqual(
            REFIT.V19_QUALIFICATION_MANIFEST_SHA256["V114"],
            "f1a0f6040510951a51eb5eeba35a37804a69b50902ec03a7a5508fa371f4acda",
        )

    def test_fails_closed_on_wrong_proposal_disclosure_bits_or_status(self) -> None:
        invalid_cases = [
            ("wrong proposal", {"proposal_sha256": "748ceb3d527408b06b7cb46b101c73e2609a7c13e7fd78dcde589fb9914c93d4"}, "direct V84 proposal"),
            ("missing disclosure", {"qualification_selection_access": False}, "qualification selection access"),
            ("wrong bits", {"selected_temperature_f64_bits_le_hex": "3d0f16adcaddc63f"}, "f64 bits"),
            ("wrong status", {"status": "FAILED"}, "not COMPLETE"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "temperature-override.json"
            path.write_text("{}\n", encoding="utf-8")
            for _name, updates, message in invalid_cases:
                with self.subTest(case=_name):
                    override = self.make_override()
                    override.update(updates)
                    with self.assertRaisesRegex(ValueError, message):
                        REFIT.validate_v84_temperature_override(
                            override, path, REFIT.V84_PROPOSAL_SHA256
                        )

    def test_v84_override_binds_v110_v114_manifests_and_all_historical_runs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "temperature-override.json"
            path.write_text("{}\n", encoding="utf-8")
            override = self.make_override()
            override["source_lineage"]["qualification_manifest_sha256"]["V114"] = "00" * 32
            with self.assertRaisesRegex(ValueError, "V110 and V114 manifests"):
                REFIT.validate_v84_temperature_override(
                    override, path, REFIT.V84_PROPOSAL_SHA256
                )


class V84ReplayComparisonTests(unittest.TestCase):
    def make_comparison(self) -> dict[str, object]:
        return {
            "schema": REFIT.V84_REPLAY_COMPARISON_SCHEMA,
            "status": "COMPLETE",
            "mode": "adaptive engineering; qualification partition previously opened; not scientific confirmation",
            "scientific_confirmation_eligible": False,
            "exact_replay": True,
            "temperature_f64_bits_le_hex": REFIT.V84_TEMPERATURE_BITS_LE_HEX,
            "policy_identity_sha256": REFIT.V84_POLICY_IDENTITY_SHA256,
            "raw_proposal_sha256": REFIT.V84_PROPOSAL_SHA256,
            "labels_sha256": REFIT.V84_LABELS_SHA256,
            "traces_sha256": REFIT.V84_TRACES_SHA256,
            "receipt_sha256": {"v167": REFIT.V84_LABEL_RECEIPT_SHA256},
        }

    def test_accepts_sealed_v169_comparison_pinned_to_v167_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "v84-v03-replay-comparison-v01.json"
            path.write_text("{}\n", encoding="utf-8")
            with mock.patch.object(
                REFIT.RUNTIME, "sha", return_value=REFIT.V84_REPLAY_COMPARISON_SHA256
            ):
                record = REFIT.validate_v84_replay_comparison(
                    self.make_comparison(), path, REFIT.V84_REPLAY_COMPARISON_SHA256
                )
        self.assertEqual(record["schema"], REFIT.V84_REPLAY_COMPARISON_SCHEMA)
        self.assertEqual(record["sha256"], REFIT.V84_REPLAY_COMPARISON_SHA256)

    def test_rejects_incomplete_or_mismatched_replay_comparison(self) -> None:
        invalid_cases = [
            ("status", "status", "FAILED", "not COMPLETE"),
            ("replay", "exact_replay", False, "exact replay"),
            ("raw proposal", "raw_proposal_sha256", "748ceb3d527408b06b7cb46b101c73e2609a7c13e7fd78dcde589fb9914c93d4", "raw_proposal_sha256"),
            ("policy", "policy_identity_sha256", "00" * 32, "policy_identity_sha256"),
            ("receipt", "receipt_sha256", {"v167": "00" * 32}, "V167 simulator receipt"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "v84-v03-replay-comparison-v01.json"
            path.write_text("{}\n", encoding="utf-8")
            for name, key, value, message in invalid_cases:
                with self.subTest(case=name):
                    comparison = self.make_comparison()
                    comparison[key] = value
                    with self.assertRaisesRegex(ValueError, message):
                        REFIT.validate_v84_replay_comparison(
                            comparison, path, REFIT.V84_REPLAY_COMPARISON_SHA256
                        )
            with self.assertRaisesRegex(ValueError, "sealed V169 artifact"):
                REFIT.validate_v84_replay_comparison(
                    self.make_comparison(), path, "00" * 32
                )


if __name__ == "__main__":
    unittest.main()
