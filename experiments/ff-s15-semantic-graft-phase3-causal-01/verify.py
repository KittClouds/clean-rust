"""Read-only replay of completed Phase 3; no fitting or new selection."""
import json
from p3_contract import OUTPUT, ARM, verify_spec, sha_file


def main():
    receipt = json.loads((OUTPUT / "PHASE3-RECEIPT.json").read_text())
    spec = json.loads((OUTPUT / "PHASE3-SPEC.json").read_text())
    verify_spec(spec)
    assert sha_file(OUTPUT / "PHASE3-SPEC.json") == receipt["phase3_spec_sha256"]
    for name, digest in receipt["files"].items():
        assert sha_file(OUTPUT / name) == digest, name
    own = receipt["arm"]; root = OUTPUT / ARM
    history = json.loads((root / "training-history.json").read_text())
    assert len(history) == 20 == own["full_TRAIN_passes"]
    assert own["optimizer_steps"] == 3140 and own["trainable_parameters"] == 460662
    assert all(row["rows_seen"] == 20000 for row in history)
    best = min(history, key=lambda row: row["DEV_selection"]["J_select"])
    assert best["epoch"] == own["best_epoch"]
    assert best["checkpoint_sha256"] == sha_file(root / "best-graft.pt") == own["artifact_sha256"]
    assert own["initial_state_sha256"] == spec["initial_state_sha256"]
    metric = json.loads((root / "DEV-METRICS.json").read_text())
    assert metric["row_count"] == 2000 and metric["canonical_world_groups"] == 1668
    assert metric["endpoint"]["eligible"] == 925 and metric["renderer"]["pairs"] == 464
    assert 0 < metric["pair_correctness"]["action"]["n"] <= 464
    for branch in ("global", "candidate"):
        for item in metric["pair_correctness"][branch].values():
            assert sum(item[k] for k in ("both_correct", "first_only_correct", "second_only_correct", "both_wrong")) == item["n"]
    seen = set()
    with (root / "DEV-estimates.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            assert row["world_id"] not in seen
            seen.add(row["world_id"])
            assert row["graft_artifact_sha256"] == own["artifact_sha256"]
            assert len(row["semantic_estimates"]) == 4
            assert 0 < len(row["candidate_estimates"]) <= 28
            for candidate in row["candidate_estimates"]:
                assert len(candidate["estimates"]) == 2
            assert not {"global_y", "candidate_y", "labels", "evidence_facts", "missing_information", "selected_action"} & set(row)
    assert len(seen) == 2000
    for key, value in receipt["exit_gate"].items():
        assert value == (key not in ("PROTECTED_TEST_TRUTH_OPENED", "BANK_V2_USED")), key
    result = {"status": "PHASE3_COMPLETION_REPLAY_PASS", "verified_files": len(receipt["files"]),
        "runtime_envelopes": len(seen), "selected_epoch": best["epoch"],
        "receipt_sha256": sha_file(OUTPUT / "PHASE3-RECEIPT.json"),
        "prior_phases_unchanged": True, "no_new_fit_or_selection": True}
    path = OUTPUT / "COMPLETION-REPLAY.json"
    with path.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, sort_keys=True); stream.write("\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__": main()
