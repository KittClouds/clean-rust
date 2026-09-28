"""Build and audit the post-registered E1 candidate-text basis, without LFM weights.

This script reads only sealed contracts, generator candidate definitions,
candidate catalog identities, and the prior target-free schema-join receipt. It
loads the pinned tokenizer locally for a no-truncation metadata check. It never
loads LFM weights, extracts features, loads heads, reads held-out targets, or
computes predictions or metrics.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[4]
PHASE = ROOT / "experiments/jev-information-density-v08n/phase_b"
E1 = PHASE / "e1"
RUN = Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-base-v01")
PANEL = Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-eval-panel-v01")
MODEL_DIR = Path(r"D:\codex-runs\jev-lfm-variable-v07\models\lfm2.5-1.2b-base")

EXPECTED = {
    "run_contract": "da538aa03355732a2ba362da45d947e169b87aa644d0efd6ba7ef7a546306c1f",
    "family_spec": "e56885005487b36b573c1bf4d47741413ca72df0992ff62bcf48891eecacb429",
    "generator": "f04a9b1d4f6682522e5957be3c0075db4bd7aa4e4e25968650f2ff24a42c7f5b",
    "feature_extractor": "b8cd79a9a3265eca0fde5f509ba7c058bc2065d7747efe17ff7c7c1f6335b2d0",
    "candidate_surface": "a3049d52e1183c806c84522a617a05646eb86fbcb69af72b5bb26f4808852cb1",
    "training_candidate_catalog": "1698ea2078951837b3cb780a3f873c3c099e5e3d001c714e1d58a41e2951487e",
    "original_schema_join_receipt": "1db0042f1a15364e6a304daf426a56c561ca44986c632b6453f960bcf4e6d41f",
}

HELDOUT_SCHEMA_SLUGS = (
    "exposure_control",
    "respiratory_monitoring",
    "salinity_control",
    "vibration_monitoring",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def extract_family_candidates(source: str, slug: str) -> list[dict[str, str]]:
    match = re.search(r'FamilySpec\s*\{\s*slug:\s*"' + re.escape(slug) + r'"', source)
    if match is None:
        raise ValueError(f"authoritative FamilySpec missing: {slug}")
    start = source.find("candidates:", match.end())
    open_bracket = source.find("[", start)
    if start < 0 or open_bracket < 0:
        raise ValueError(f"candidate list missing: {slug}")
    depth = 0
    in_string = False
    escaped = False
    close_bracket = -1
    for index in range(open_bracket, len(source)):
        char = source[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                close_bracket = index
                break
    if close_bracket < 0:
        raise ValueError(f"unterminated candidate list: {slug}")
    block = source[open_bracket + 1 : close_bracket]
    pattern = re.compile(
        r'candidate\s*\(\s*"([^"\\]*(?:\\.[^"\\]*)*)"\s*,\s*'
        r'"([^"\\]*(?:\\.[^"\\]*)*)"\s*,\s*'
        r'"([^"\\]*(?:\\.[^"\\]*)*)"\s*,?\s*\)',
        re.DOTALL,
    )
    rows = [
        {"suffix": match.group(1), "name": match.group(2), "description": match.group(3)}
        for match in pattern.finditer(block)
    ]
    if len(rows) != 4 or len({row["suffix"] for row in rows}) != 4:
        raise ValueError(f"expected four unique generator candidates for {slug}; found {len(rows)}")
    return rows


def main() -> int:
    source_paths = {
        "run_contract": PHASE / "phase-b-run-contract-v01.json",
        "family_spec": ROOT / "experiments/jev-information-density-v08n/generator/src/families.rs",
        "generator": ROOT / "experiments/jev-information-density-v08n/generator/src/generator.rs",
        "feature_extractor": ROOT / "experiments/jev-lfm-variable-v07/extract_lfm.py",
        "candidate_surface": ROOT / "experiments/jev-frozen-readout-v01/probe.py",
        "training_candidate_catalog": RUN / "phase-b-v03-inputs/candidate-catalog.json",
        "original_schema_join_receipt": PHASE / "phase-b-evaluator-schema-join-correction-v01.json",
    }
    hashes = {key: sha256_file(path) for key, path in source_paths.items()}
    if hashes != EXPECTED:
        raise RuntimeError(f"E1 metadata source hash drift: {hashes}")

    run_contract = json.loads(source_paths["run_contract"].read_text(encoding="utf-8"))
    model = run_contract["model_and_representation"]
    extraction_contract = run_contract["candidate_feature_extraction"]
    if model["feature_key"] != "mean_full@16" or model["maximum_length"] != 1024:
        raise ValueError("frozen extraction contract differs from the E1 basis recipe")
    if extraction_contract["text_serialization"] != "name + U+2014 EM DASH + one space + description; UTF-8 bytes exactly, no normalization":
        raise ValueError("frozen candidate text serialization is not the expected name-definition surface")

    generator_source = source_paths["generator"].read_text(encoding="utf-8")
    if 'format!("{}::{}", spec.slug, candidate.suffix)' not in generator_source:
        raise ValueError("generator no longer defines candidate semantic IDs from schema plus suffix")
    if 'format!("candidate-{index}")' not in generator_source:
        raise ValueError("generator no longer defines ordered schema-local candidate IDs")
    surface_source = source_paths["candidate_surface"].read_text(encoding="utf-8")
    if 'return f"{name} — {description}"' not in surface_source:
        raise ValueError("frozen name_definition candidate surface implementation changed")

    extractor_source = source_paths["feature_extractor"].read_text(encoding="utf-8")
    extractor_ast = ast.parse(extractor_source)
    encode_fn = next(
        (node for node in extractor_ast.body if isinstance(node, ast.FunctionDef) and node.name == "encode_lfm_texts"),
        None,
    )
    if encode_fn is None or not any(arg.arg == "texts" for arg in encode_fn.args.args):
        raise ValueError("frozen encoder does not expose a generic text-list input")
    function_names = {node.id for node in ast.walk(encode_fn) if isinstance(node, ast.Name)}
    if "candidate_semantic_id" in function_names or "schema_family_id" in function_names:
        raise ValueError("encoder function unexpectedly depends on schema/candidate lookup")

    schema_receipt = json.loads(source_paths["original_schema_join_receipt"].read_text(encoding="utf-8"))
    schema_counts = schema_receipt["whole_panel_schema_join_preflight"]["schema_counts"]
    expected_counts = {f"jev-v08n-schema:{slug}": 500 for slug in HELDOUT_SCHEMA_SLUGS}
    if schema_counts != expected_counts or sum(schema_counts.values()) != 2_000:
        raise ValueError("sealed held-out schema identity/count evidence does not reconcile")

    family_source = source_paths["family_spec"].read_text(encoding="utf-8")
    rows: list[dict[str, Any]] = []
    schema_order: dict[str, list[str]] = {}
    for slug in HELDOUT_SCHEMA_SLUGS:
        candidates = extract_family_candidates(family_source, slug)
        ordered_ids = []
        for local_index, candidate in enumerate(candidates):
            semantic_id = f"{slug}::{candidate['suffix']}"
            model_text = f"{candidate['name']} — {candidate['description']}"
            ordered_ids.append(semantic_id)
            rows.append(
                {
                    "candidate_vector_index": len(rows),
                    "schema_family_id": f"jev-v08n-schema:{slug}",
                    "candidate_id": f"candidate-{local_index}",
                    "candidate_semantic_id": semantic_id,
                    "schema_local_candidate_index": local_index,
                    "profile": "name_definition",
                    "name": candidate["name"],
                    "description": candidate["description"],
                    "model_input_text": model_text,
                    "model_input_utf8_sha256": sha256_text(model_text),
                    "feature_key": model["feature_key"],
                    "expected_feature_dimension": 2_048,
                    "expected_feature_dtype": "float32",
                    "source_family_spec_sha256": hashes["family_spec"],
                }
            )
        schema_order[f"jev-v08n-schema:{slug}"] = ordered_ids

    ids = [row["candidate_semantic_id"] for row in rows]
    if len(rows) != 16 or len(set(ids)) != 16 or len({row["model_input_utf8_sha256"] for row in rows}) != 16:
        raise ValueError("E1 candidate identity/text uniqueness failure")
    catalog = json.loads(source_paths["training_candidate_catalog"].read_text(encoding="utf-8"))
    if catalog.get("feature_dimension") != 2_048 or catalog.get("candidate_count") != 48:
        raise ValueError("sealed candidate feature catalog shape contract drift")
    training_ids = {str(row["candidate_semantic_id"]) for row in catalog["rows"]}
    overlap = sorted(set(ids) & training_ids)
    if overlap:
        raise ValueError(f"held-out candidate identities unexpectedly overlap training catalog: {overlap}")
    for schema_id, count in schema_counts.items():
        ordered = schema_order.get(schema_id)
        if count != 500 or ordered is None or len(ordered) != 4 or len(set(ordered)) != 4:
            raise ValueError(f"held-out neighborhood join does not resolve four unique IDs: {schema_id}")

    # Tokenizer-only check, matching the sealed tokenizer settings. No LFM weights
    # or feature encoder are loaded or called by this preflight.
    tokenizer_files = model["snapshot_file_sha256"]
    for filename in ("tokenizer.json", "tokenizer_config.json", "special_tokens_map.json"):
        path = MODEL_DIR / filename
        if sha256_file(path) != tokenizer_files[filename]:
            raise RuntimeError(f"pinned tokenizer file hash mismatch: {filename}")
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(
        str(MODEL_DIR), local_files_only=True, use_fast=True, trust_remote_code=False
    )
    encoded = tokenizer(
        [row["model_input_text"] for row in rows],
        add_special_tokens=True,
        padding=False,
        truncation=False,
    )
    token_counts = [len(ids_for_text) for ids_for_text in encoded["input_ids"]]
    if len(token_counts) != 16 or max(token_counts) > int(model["maximum_length"]):
        raise ValueError("E1 text basis is not representable within the frozen 1024-token limit")

    manifest_bytes = "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows).encode("utf-8")
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    manifest_path = E1 / "e1-candidate-text-manifest-v01.jsonl"
    audit_path = E1 / "e1-candidate-basis-metadata-audit-v01.json"
    if manifest_path.exists() or audit_path.exists():
        raise FileExistsError("E1 metadata outputs already exist; refusing overwrite")
    E1.mkdir(parents=True, exist_ok=True)
    manifest_path.write_bytes(manifest_bytes)

    audit = {
        "protocol": "jev-information-density/v0.8n-e1-candidate-basis-metadata-audit-v01",
        "status": "PASS_METADATA_ONLY_CANDIDATE_BASIS_CONSTRUCTIBLE",
        "audit_source_sha256": sha256_file(Path(__file__).resolve()),
        "source_sha256": hashes,
        "candidate_text_manifest_sha256": manifest_sha,
        "candidate_count": len(rows),
        "expected_feature_tensor_shape": [16, 2048],
        "expected_feature_dtype": "float32",
        "feature_key": model["feature_key"],
        "model_repo_id": model["repo_id"],
        "model_revision": model["revision"],
        "schema_candidate_order_source": "generator FamilySpec candidate order; candidate_semantic_id is schema slug plus candidate suffix; no training-schema order used",
        "exact_identity_join": {
            schema: {"neighborhoods": schema_counts[schema], "candidate_semantic_ids": values, "unique_count": len(set(values))}
            for schema, values in schema_order.items()
        },
        "training_candidate_identity_overlap": 0,
        "tokenizer_only_preflight": {
            "status": "PASS_NO_TRUNCATION",
            "tokenizer_loaded": True,
            "backbone_weights_loaded": False,
            "feature_encoder_called": False,
            "candidate_feature_vectors_created": False,
            "input_count": len(rows),
            "max_length": int(model["maximum_length"]),
            "token_counts": token_counts,
            "max_observed_tokens": max(token_counts),
        },
        "heldout_targets_read_or_used": False,
        "head_checkpoints_loaded": False,
        "predictions_or_metrics_created": False,
        "panel_reopened": False,
        "phoenix_access": False,
        "next_gate": "Seal E1 extraction/evaluation repair contract, then request separate explicit authorization for 16-vector extraction and a separately authorized second panel opening.",
    }
    audit_path.write_text(json.dumps(audit, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(audit, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
