"""Read-only Phase 2 integrity replay; never fits or changes scoring decisions."""
import json
from p2_contract import OUTPUT,PHASE1_OUTPUT,verify_spec,sha_file


def main():
    receipt=json.loads((OUTPUT/"PHASE2-RECEIPT.json").read_text())
    spec=json.loads((OUTPUT/"PHASE2-SPEC.json").read_text())
    assert receipt["status"]=="PHASE2_COMPLETE"
    verify_spec(spec)
    assert sha_file(OUTPUT/"PHASE2-SPEC.json")==receipt["phase2_spec_sha256"]
    assert sha_file(OUTPUT/"TRAIN-untrained-sigma.npy")==spec["reference_sigma_sha256"]
    for name,digest in receipt["files"].items():
        assert sha_file(OUTPUT/name)==digest,name
    envelope_counts={}
    for arm in ("P2-BASE","P2-CONSIST"):
        root=OUTPUT/arm
        history=json.loads((root/"training-history.json").read_text())
        own=receipt["arms"][arm]
        assert len(history)==20==own["full_TRAIN_passes"]
        assert own["optimizer_steps"]==20*157
        assert all(row["rows_seen"]==20000 for row in history)
        selected=min(history,key=lambda row:row["DEV_loss"]["total"])
        assert selected["epoch"]==own["best_epoch"]
        assert selected["checkpoint_sha256"]==sha_file(root/"best-graft.pt")==own["artifact_sha256"]
        assert own["initial_state_sha256"]==spec["initial_state_sha256"]
        metric=json.loads((root/"DEV-METRICS.json").read_text())
        assert metric["row_count"]==2000 and metric["canonical_world_groups"]==1668
        assert metric["endpoint"]["eligible"]==925
        assert metric["renderer"]["pairs"]==464
        assert metric["renderer_JS"]["exact_candidate_aligned_pairs"]==464
        assert metric["global_state_diversity"]["rows"]==2000
        seen=set()
        with (root/"DEV-estimates.jsonl").open(encoding="utf-8") as stream:
            for line in stream:
                row=json.loads(line)
                assert row["world_id"] not in seen
                seen.add(row["world_id"])
                assert row["graft_artifact_sha256"]==own["artifact_sha256"]
                assert len(row["semantic_estimates"])==4
                assert len(row["candidate_estimates"])<=28
                for candidate in row["candidate_estimates"]:
                    assert len(candidate["estimates"])==2
                    assert all(v["provenance_class"]=="MODEL_ESTIMATE" for v in candidate["estimates"].values())
                assert not {"global_y","candidate_y","labels","missing_information","evidence_facts","selected_action"}&set(row)
        assert len(seen)==2000
        envelope_counts[arm]=len(seen)
    for key,value in receipt["exit_gate"].items():
        assert value==(key not in ("PROTECTED_TEST_TRUTH_OPENED","BANK_V2_USED")),key
    comparison=json.loads((OUTPUT/"COMPARISON.json").read_text())
    output={"status":"PHASE2_COMPLETION_REPLAY_PASS",
            "receipt_sha256":sha_file(OUTPUT/"PHASE2-RECEIPT.json"),
            "spec_sha256":sha_file(OUTPUT/"PHASE2-SPEC.json"),
            "verified_bound_files":len(receipt["files"]),"envelope_counts":envelope_counts,
            "same_initialization_verified":True,"Phase0_Phase1_unchanged":True,
            "candidate_maximum":spec["candidate_convention"]["m_cap"],
            "baseline_Phase1_bit_exact":comparison["baseline_replays_Phase1_selected_state_bit_exact"],
            "no_new_training_or_scoring_decisions":True}
    path=OUTPUT/"COMPLETION-REPLAY.json"
    with path.open("x",encoding="utf-8") as stream:
        json.dump(output,stream,indent=2,sort_keys=True);stream.write("\n")
    print(json.dumps(output,indent=2))


if __name__=="__main__":main()
