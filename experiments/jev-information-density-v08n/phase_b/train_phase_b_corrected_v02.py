"""Run the authorized trainer with two receipt-bound implementation adapters.

The adapters expose the sealed state tensor through the frozen runner's
expected container view and relocate a local catalog-ID declaration before
its first use. The on-disk frozen trainer remains byte-identical to the
authorization binding; the source overlay is exact, checked, and hash-receipted.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import torch


ROOT = Path(__file__).resolve().parents[3]
PHASE = ROOT / "experiments/jev-information-density-v08n/phase_b"
RUN = Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-base-v01\phase-b-run-v01")
CORRECTION = PHASE / "phase-b-implementation-correction-v02.json"
PARENT_CORRECTION = PHASE / "phase-b-implementation-correction-v01.json"
TRAINER_PATH = PHASE / "train_phase_b_v01.py"
AUTH_PATH = PHASE / "phase-b-authorization-event-v01.json"

OLD_DECLARATION = '    catalog_ids = [row["candidate_semantic_id"] for row in catalog["rows"]]\n'
TOKEN_CHECK = '    token_rows = token_receipt.get("per_candidate", [])\n    require(len(token_rows) == 48 and [row.get("candidate_semantic_id") for row in token_rows] == catalog_ids, "candidate token receipt semantic ordering mismatch")\n'
LATE_DECLARATION_AND_CHECK = OLD_DECLARATION + '    require(candidate_receipt["semantic_ids"] == catalog_ids and len(catalog_ids) == 48, "candidate tensor semantic ordering mismatch")\n'


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def patch_trainer_source(source: str) -> str:
    """Move the exact catalog-ID declaration before its first use, once only."""
    if source.count(TOKEN_CHECK) != 1 or source.count(LATE_DECLARATION_AND_CHECK) != 1:
        raise RuntimeError("frozen trainer no longer matches the sealed declaration-order patch context")
    source = source.replace(TOKEN_CHECK, "    token_rows = token_receipt.get(\"per_candidate\", [])\n" + OLD_DECLARATION + TOKEN_CHECK.split("\n", 1)[1] + "\n", 1)
    source = source.replace(LATE_DECLARATION_AND_CHECK, '    require(candidate_receipt["semantic_ids"] == catalog_ids and len(catalog_ids) == 48, "candidate tensor semantic ordering mismatch")\n', 1)
    if source.count(OLD_DECLARATION) != 1:
        raise RuntimeError("catalog-ID declaration relocation did not produce one declaration")
    return source


def adapt_state_cache(
    cache: dict[str, Any], feature_key: str, expected_shape: tuple[int, int] = (55_000, 2048)
) -> dict[str, Any]:
    features = cache.get("features")
    if not isinstance(features, torch.Tensor):
        raise RuntimeError("sealed state cache no longer has the audited direct-tensor layout")
    if cache.get("feature_key") != feature_key:
        raise RuntimeError("sealed state cache feature key differs from the frozen contract")
    if tuple(features.shape) != expected_shape or features.dtype != torch.float32 or not features.is_contiguous():
        raise RuntimeError("sealed state cache tensor differs from its frozen shape/dtype/layout")
    return {**cache, "features": {"state": {feature_key: features}}}


def load_trainer() -> Any:
    source_bytes = TRAINER_PATH.read_bytes()
    receipt = read_json(CORRECTION)
    event = read_json(AUTH_PATH)
    relative = "experiments/jev-information-density-v08n/phase_b/train_phase_b_v01.py"
    if sha256_file(TRAINER_PATH) != receipt.get("frozen_trainer_sha256"):
        raise RuntimeError("on-disk frozen trainer differs from the child correction receipt")
    if event.get("implementation_bindings", {}).get(relative) != sha256_file(TRAINER_PATH):
        raise RuntimeError("on-disk frozen trainer no longer matches the original authorization")
    source = patch_trainer_source(source_bytes.decode("utf-8"))
    spec = importlib.util.spec_from_file_location("jev_v08n_frozen_trainer_corrected_v02", TRAINER_PATH)
    if spec is None:
        raise RuntimeError("cannot create frozen trainer module spec")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    exec(compile(source, str(TRAINER_PATH), "exec"), module.__dict__)
    return module


def verify_correction_chain() -> tuple[dict[str, Any], dict[str, Any]]:
    receipt = read_json(CORRECTION)
    parent = read_json(PARENT_CORRECTION)
    event_sha = sha256_file(AUTH_PATH)
    if receipt.get("status") != "IMPLEMENTATION_ONLY_CORRECTION_SEALED":
        raise RuntimeError("v02 implementation correction receipt is not sealed")
    if receipt.get("parent_authorization_event_sha256") != event_sha:
        raise RuntimeError("v02 correction does not bind the active authorization")
    if receipt.get("parent_correction_receipt_sha256") != sha256_file(PARENT_CORRECTION):
        raise RuntimeError("v02 correction does not bind the v01 correction receipt")
    if parent.get("status") != "IMPLEMENTATION_ONLY_CORRECTION_SEALED":
        raise RuntimeError("v01 correction parent is not sealed")
    if receipt.get("corrected_entrypoint_sha256") != sha256_file(Path(__file__)):
        raise RuntimeError("v02 corrected entrypoint hash mismatch")
    if receipt.get("frozen_trainer_sha256") != sha256_file(TRAINER_PATH):
        raise RuntimeError("authorized frozen trainer source changed")
    if receipt.get("parent_frozen_trainer_sha256") != parent.get("frozen_trainer_sha256"):
        raise RuntimeError("v02 correction does not preserve the trainer source parent")
    return receipt, parent


def run(validate_only: bool = False) -> int:
    receipt, parent = verify_correction_chain()
    allowed_dirs = {"feature-cache", "failed-attempts"}
    run_dirs = {path.name for path in RUN.iterdir() if path.is_dir()}
    if run_dirs - allowed_dirs:
        raise RuntimeError(f"head/run artifacts exist before corrected trainer entry: {sorted(run_dirs)}")
    forbidden = [RUN / name for name in ("head-templates", "runs", "attempts", "execution-order.json", "training-seal-manifest.json")]
    if any(path.exists() for path in forbidden):
        raise RuntimeError("head initialization or training artifacts exist; correction cannot be applied retroactively")

    trainer = load_trainer()
    original_load = torch.load
    state_receipt_path = Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-base-v01\shared-feature-cache\shared-feature-cache-receipt.json")
    state_receipt = read_json(state_receipt_path)
    state_path = Path(state_receipt["feature_tensor"]["path"]).resolve()

    def load_with_schema_view(source: Any, *args: Any, **kwargs: Any) -> Any:
        loaded = original_load(source, *args, **kwargs)
        try:
            same_path = Path(source).resolve() == state_path
        except (TypeError, OSError):
            same_path = False
        return adapt_state_cache(loaded, trainer.FEATURE_KEY) if same_path else loaded

    trainer.torch.load = load_with_schema_view
    correction_entries = []
    for path in (PARENT_CORRECTION, CORRECTION):
        correction_entries.append({
            "path": str(path.resolve()),
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
            "purpose": "implementation correction chain provenance",
        })
    correction_chain = [entry["sha256"] for entry in correction_entries]
    base_write_json = trainer.write_json

    def write_with_correction(path: Path, value: Any) -> None:
        if isinstance(value, dict) and path.name in {"run-config.json", "run-integrity.json"}:
            value["implementation_correction_receipt_sha256"] = correction_chain[-1]
            value["implementation_correction_chain_sha256"] = correction_chain
            value["corrected_entrypoint_sha256"] = receipt["corrected_entrypoint_sha256"]
        if isinstance(value, dict) and path.name == "checkpoint-hash-tree.json":
            value["entries"].extend(correction_entries)
            value["entry_count"] = len(value["entries"])
        if isinstance(value, dict) and path.name == "training-seal-manifest.json":
            value["hash_tree_entries"].extend(correction_entries)
            value["implementation_correction_receipt_sha256"] = correction_chain[-1]
            value["implementation_correction_chain_sha256"] = correction_chain
            value["corrected_entrypoint_sha256"] = receipt["corrected_entrypoint_sha256"]
        base_write_json(path, value)

    trainer.write_json = write_with_correction
    if validate_only:
        contract, _analysis, _probe, _components = trainer.frozen_bindings()
        trainer.verify_runtime(contract)
        state, candidates, primary, schedule, arm_rows = trainer.verify_inputs(contract)
        trainer.validate_schedule(primary, schedule, arm_rows)
        result = {
            "status": "CORRECTED_PHASE_B_INPUT_PREFLIGHT_PASS",
            "authorization_event_sha256": sha256_file(AUTH_PATH),
            "parent_correction_receipt_sha256": correction_chain[0],
            "active_correction_receipt_sha256": correction_chain[1],
            "primary_occurrences": len(primary),
            "schedule_rows": len(schedule),
            "arm_rows": {arm: len(rows) for arm, rows in arm_rows.items()},
            "state_tensor_shape": list(state.shape),
            "candidate_tensor_shape": list(candidates.shape),
            "head_initialization": False,
            "optimizer_steps": 0,
            "protected_panel_opened": False,
            "newtight_access": False,
            "phoenix_access": False,
        }
        print(json.dumps(result, separators=(",", ":")))
        return 0
    return trainer.main()


if __name__ == "__main__":
    raise SystemExit(run(validate_only="--validate-only" in sys.argv[1:]))
