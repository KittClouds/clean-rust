from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from research_interface import (
    CorpusContractError,
    HoldoutAccessError,
    QuerySpec,
    ResearchCorpus,
    ResearchResult,
    verify_run_seal,
)


def frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def synthetic_corpus(workspace: Path) -> ResearchCorpus:
    corpus = ResearchCorpus.__new__(ResearchCorpus)
    corpus.workspace = workspace
    corpus.corpus_seal = {"canonical_corpus_sha256": "abc123"}
    corpus._run_receipts = [{"terminal": {
        "run_key": "R", "canonical_instrument": "US30", "window_start": 1, "window_end": 100,
    }, "admission": {"window_id": "W"}}]
    corpus._replay_keys = {"R"}
    corpus._holdouts = frame([{
        "research_generation": 2, "canonical_instrument": "US30", "holdout_id": "H",
        "window_start": 200, "window_end_exclusive": 300, "status": "RESERVED_UNTOUCHED",
    }])
    attempts = frame([
        {"run_key": "R", "invocation_id": "I", "attempt_id": "A1", "episode_id": "E1",
         "node_id": "N1", "ordinal": 1, "is_retest": 0, "start": 1, "end": 2, "contact": 1,
         "break": pd.NA, "accepted": pd.NA, "resolution": "REJECT_TO_ORIGIN",
         "completion_status": "RESOLVED", "censor_reason": "NONE", "start_region": "BELOW",
         "node_region": "MEDIAN_CORE", "start_median_sigma": -1.0,
         "node_from_median_sigma": 0.0, "canonical_instrument": "US30"},
        {"run_key": "R", "invocation_id": "I", "attempt_id": "A2", "episode_id": "E1",
         "node_id": "N1", "ordinal": 2, "is_retest": 0, "start": 2, "end": 3, "contact": 2,
         "break": pd.NA, "accepted": pd.NA, "resolution": "NODE_RETIRED",
         "completion_status": "RESOLVED", "censor_reason": "NONE", "start_region": "BELOW",
         "node_region": "MEDIAN_CORE", "start_median_sigma": -0.8,
         "node_from_median_sigma": 0.0, "canonical_instrument": "US30"},
        {"run_key": "R", "invocation_id": "I", "attempt_id": "A3", "episode_id": "E1",
         "node_id": "N1", "ordinal": 3, "is_retest": 0, "start": 3, "end": 4, "contact": 3,
         "break": pd.NA, "accepted": pd.NA, "resolution": "TIMEOUT",
         "completion_status": "RESOLVED", "censor_reason": "NONE", "start_region": "BELOW",
         "node_region": "MEDIAN_CORE", "start_median_sigma": -0.5,
         "node_from_median_sigma": 0.0, "canonical_instrument": "US30"},
        {"run_key": "R", "invocation_id": "I", "attempt_id": "A4", "episode_id": "E1",
         "node_id": "N1", "ordinal": 4, "is_retest": 0, "start": 4, "end": 5, "contact": 4,
         "break": 4, "accepted": 4, "resolution": "ACCEPT_THROUGH_NODE",
         "completion_status": "RESOLVED", "censor_reason": "NONE", "start_region": "BELOW",
         "node_region": "MEDIAN_CORE", "start_median_sigma": -0.2,
         "node_from_median_sigma": 0.0, "canonical_instrument": "US30"},
        {"run_key": "R", "invocation_id": "I", "attempt_id": "A5", "episode_id": "E1",
         "node_id": "N1", "ordinal": 5, "is_retest": 1, "start": 5, "end": 6, "contact": 5,
         "break": pd.NA, "accepted": pd.NA, "resolution": "ACCEPT_AND_HOLD_RETEST",
         "completion_status": "RESOLVED", "censor_reason": "NONE", "start_region": "ABOVE",
         "node_region": "MEDIAN_CORE", "start_median_sigma": 0.3,
         "node_from_median_sigma": 0.0, "canonical_instrument": "US30"},
    ])
    features = frame([{
        "run_key": "R", "invocation_id": "I", "attempt_id": attempt,
        "canonical_instrument": "US30", "dummy": float(index),
    } for index, attempt in enumerate(attempts["attempt_id"], 1)])
    contexts = []
    for attempt in attempts["attempt_id"]:
        contexts.append({"run_key": "R", "attempt_id": attempt, "episode_id": "E1", "source_key": f"S{attempt}",
                         "family": "PROFILE", "producer": "VOLKITT"})
    contexts.append({"run_key": "R", "attempt_id": "A1", "episode_id": "E1", "source_key": "SX",
                     "family": "DAILY_EXTREME", "producer": "DAY_SWINGS"})
    corpus._tables = {
        "attempts": attempts,
        "features": features,
        "context": frame(contexts),
        "episodes": frame([{
            "run_key": "R", "episode_id": "E1", "node_id": "N1", "resolution": "NODE_RETIRED",
            "completion_status": "RESOLVED", "censor_reason": "NONE", "end": 7,
        }]),
        "events": frame([{
            "run_key": "R", "event_id": f"EV{i}", "attempt_id": attempt, "episode_id": "E1",
        } for i, attempt in enumerate(attempts["attempt_id"], 1)]),
        "transits": frame([{
            "run_key": "R", "transit_id": "T1", "attempt_id": "A4", "episode_id": "E1",
            "source_node_id": "N1", "destination_node_id": "N2", "start": 6, "end": 7,
            "resolution": "TRANSIT_TO_NEXT_NODE", "completion_status": "RESOLVED",
        }]),
        "runs": frame([]),
    }
    corpus._attempt_view = corpus._build_attempt_view()
    corpus._chain_view = corpus._build_attempt_chain_view()
    corpus._transit_view = corpus._build_transit_view()
    return corpus


class SealTests(unittest.TestCase):
    def test_run_seal_detects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = root / "payload.tsv"
            payload.write_text("a\tb\n1\t2\n", encoding="utf-8")
            digest = hashlib.sha256(payload.read_bytes()).hexdigest()
            material = f"payload.tsv\t{payload.stat().st_size}\t{digest}"
            seal = {
                "contract": "MST_IMMUTABLE_RUN_SEAL_V1", "status": "SEALED", "file_count": 1,
                "sealed_payload_sha256": hashlib.sha256(material.encode()).hexdigest(),
                "files": [{"path": "payload.tsv", "bytes": payload.stat().st_size, "sha256": digest}],
            }
            (root / "seal.json").write_text(json.dumps(seal), encoding="utf-8")
            verify_run_seal(root)
            payload.write_text("tampered", encoding="utf-8")
            with self.assertRaises(CorpusContractError):
                verify_run_seal(root)


class ViewContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name)
        self.corpus = synthetic_corpus(self.workspace)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_attempt_view_does_not_expand_contributors(self) -> None:
        self.assertEqual(len(self.corpus.attempt_view()), 5)
        self.assertEqual(len(self.corpus.node_context_view()), 6)

    def test_lifecycle_endings_are_not_behavioral(self) -> None:
        attempts = self.corpus.attempt_view().set_index("attempt_id")
        self.assertEqual(attempts.loc["A2", "termination_class"], "STRUCTURAL_ADMINISTRATIVE")
        self.assertEqual(attempts.loc["A3", "termination_class"], "ATTEMPT_TIMEOUT_BOUNDARY")
        self.assertTrue(pd.isna(attempts.loc["A2", "behavioral_attempt_outcome"]))
        self.assertTrue(pd.isna(attempts.loc["A3", "behavioral_attempt_outcome"]))

    def test_episode_receipt_is_not_projected_as_outcome(self) -> None:
        chain = self.corpus.attempt_chain_view()
        self.assertIn("episode_terminal_receipt", chain)
        self.assertNotIn("episode_outcome", chain)
        self.assertTrue(chain["episode_contains_initial_acceptance"].all())

    def test_holdout_access_fails_closed(self) -> None:
        with self.assertRaises(HoldoutAccessError):
            self.corpus.attempt_view("FUTURE_HOLDOUT")

    def test_denominator_excludes_administrative_and_timeout_rows(self) -> None:
        spec = QuerySpec.create("initial_acceptance_given_initial_contact")
        cohort = self.corpus.target_frame(spec)
        result = self.corpus.estimate(spec)
        row = result.table.iloc[0]
        self.assertEqual(len(cohort.frame), 4)
        self.assertEqual(int(cohort.frame["target_analyzable"].sum()), 2)
        self.assertEqual(int(cohort.frame["target_label"].sum()), 1)
        self.assertEqual(int(row.eligible_count), 4)
        self.assertEqual(int(row.observed_count), 1)
        self.assertEqual(int(row.censored_count), 2)
        self.assertEqual(int(row.analyzable_count), 2)
        self.assertAlmostEqual(float(row.estimate), 0.5)

    def test_retest_and_transit_targets_are_sequence_correct(self) -> None:
        hold = self.corpus.estimate(QuerySpec.create("retest_hold_given_retest_contact")).table.iloc[0]
        transit = self.corpus.estimate(QuerySpec.create("transit_given_episode_acceptance")).table.iloc[0]
        self.assertEqual((int(hold.eligible_count), int(hold.observed_count)), (1, 1))
        self.assertEqual((int(transit.eligible_count), int(transit.observed_count)), (1, 1))

    def test_duplicate_feature_snapshot_fails_cardinality(self) -> None:
        duplicate = self.corpus._tables["features"].iloc[[0]].copy()
        self.corpus._tables["features"] = pd.concat([self.corpus._tables["features"], duplicate])
        with self.assertRaises(CorpusContractError):
            self.corpus._validate_relations()

    def test_result_writer_rejects_sealed_path(self) -> None:
        result = ResearchResult(pd.DataFrame([{"x": 1}]), {"query_spec_sha256": "a" * 64})
        protected = self.workspace / "furnace" / "corpus" / "bad"
        with self.assertRaises(CorpusContractError):
            result.write(protected, self.workspace)


if __name__ == "__main__":
    unittest.main()
