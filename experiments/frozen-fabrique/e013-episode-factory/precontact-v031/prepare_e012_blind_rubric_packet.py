#!/usr/bin/env python3
"""Prepare an outcome-free, deidentified E012 input packet for blind rubric scoring."""
from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

RUN_INPUT = Path(r"C:\rd-c\selective-cognition-action-region-program\experiment-012\artifacts\runs\e012-20260926-frame-decomposition-01\inputs\full-frame-lock.json")
ROOT = Path(r"C:\rd-c\selective-cognition-action-region-program\e012-readonly-anatomy-addendum\stage0-blind-rubric")
PACKET = ROOT / "E012-RUBRIC-INPUTS-BLIND.json"
RUBRIC = ROOT / "E012-DIFFICULTY-RUBRIC-v1.json"
MAP = ROOT / "E012-RUBRIC-CASE-MAP-VAULT.json"
SEED = 1306501


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def clean_frame(frame: dict, case_id: str) -> dict:
    context = []
    for item in frame.get("evidence", []):
        content = item.get("content", "")
        if item.get("kind") == "repository_context":
            try:
                parsed = json.loads(content)
                parsed.pop("repository_code", None)
                content = json.dumps(parsed, sort_keys=True, ensure_ascii=False)
            except (TypeError, json.JSONDecodeError):
                content = "[repository context omitted: unparsable metadata]"
        context.append({"kind": item.get("kind", "unknown"), "content": content})
    options = []
    for ordinal, option in enumerate(frame.get("action_options", [])):
        options.append({"producer_ordinal": ordinal, "summary": option.get("summary", ""), "patch_excerpt": option.get("diff_excerpt", "")})
    return {
        "case_id": case_id,
        "task_request": frame.get("task_prompt", ""),
        "repository_context_and_evidence": context,
        "candidates_in_recorded_producer_order": options,
    }


def rubric() -> dict:
    return {
        "schema": "e012-construction-difficulty-rubric.v1",
        "instruction": "Score the task materials only. Do not infer model performance or task labels. Use ordinal integer scores 0-3 for each dimension and provide one concise rationale per score.",
        "dimensions": [
            {"name": "operative_constraints", "anchors": {"0": "one clear constraint", "1": "two constraints", "2": "three constraints", "3": "four or more interacting constraints"}},
            {"name": "wording_ambiguity", "anchors": {"0": "one clear interpretation", "1": "minor ambiguity resolved by normal context", "2": "multiple plausible readings", "3": "materially underspecified or conflicting request"}},
            {"name": "candidate_similarity", "anchors": {"0": "one candidate clearly distinct", "1": "some meaningful differences", "2": "several close alternatives", "3": "near-identical alternatives require fine discrimination"}},
            {"name": "evidence_conflict", "anchors": {"0": "task, code, and exposed checks align", "1": "one weakly inconsistent cue", "2": "multiple cues disagree", "3": "material conflict changes the plausible action"}},
            {"name": "reasoning_depth", "anchors": {"0": "one local edit", "1": "local change with a short consequence chain", "2": "cross-file or multi-step behavior", "3": "nonlocal lifecycle/API interaction or several dependent consequences"}},
            {"name": "distractor_plausibility", "anchors": {"0": "malformed/straw distractor", "1": "obvious miss", "2": "plausible partial/wrong-place/over-broad fix", "3": "all candidates plausible; visible success can hide a hidden-edge failure"}},
        ],
        "output_schema": {"case_id": "string", "scores": "object mapping all six dimension names to integers 0-3", "rationales": "object mapping the same names to short rationales"},
    }


def main() -> None:
    if any(path.exists() for path in (PACKET, RUBRIC, MAP)):
        raise FileExistsError("refusing to overwrite an existing blinded packet artifact")
    raw = RUN_INPUT.read_bytes()
    locked = json.loads(raw.decode("utf-8-sig"))
    if locked.get("selection") != "condition == full_frame; original producer order preserved":
        raise RuntimeError("E012 source is not the frozen full-frame input selection")
    records = locked.get("frames", [])
    if len(records) != 48:
        raise RuntimeError(f"expected 48 E012 full-frame samples, got {len(records)}")
    samples = []
    for record in records:
        frame = record.get("frame", {})
        payload = json.dumps(frame, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if hashlib.sha256(payload).hexdigest() != record.get("frame_sha256"):
            raise RuntimeError("frame digest mismatch")
        if len(frame.get("action_options", [])) != 4:
            raise RuntimeError("unexpected candidate count")
        samples.append((record, frame))
    random.Random(SEED).shuffle(samples)
    packet_cases, case_map = [], []
    for index, (record, frame) in enumerate(samples, 1):
        case_id = f"CASE-{index:03d}"
        packet_cases.append(clean_frame(frame, case_id))
        case_map.append({"case_id": case_id, "sample_id": record["sample_id"], "frame_sha256": record["frame_sha256"], "task_id": record["task_id"]})
    packet = {"schema": "e012-blind-rubric-inputs.v1", "source_sha256": sha_bytes(raw), "case_count": len(packet_cases), "cases": packet_cases}
    rubric_obj = rubric()
    ROOT.mkdir(parents=True, exist_ok=True)
    PACKET.write_text(json.dumps(packet, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    RUBRIC.write_text(json.dumps(rubric_obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    MAP.write_text(json.dumps({"schema": "e012-case-map-vault.v1", "case_map": case_map}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"state": "SEALED_BLIND_PACKET", "cases": len(packet_cases), "source_sha256": sha_bytes(raw), "packet_sha256": sha_bytes(PACKET.read_bytes()), "rubric_sha256": sha_bytes(RUBRIC.read_bytes()), "vault_map_sha256": sha_bytes(MAP.read_bytes()), "rater_inputs": [str(PACKET), str(RUBRIC)], "vault_only": str(MAP)}, indent=2))


if __name__ == "__main__":
    main()
