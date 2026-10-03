from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def code_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.glob("*.py")):
        if path.name.startswith("test_"):
            continue
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def verify_interface(workspace: Path, corpus: Any) -> None:
    output = workspace / "phase10_5" / "output"
    seal = json.loads((output / "interface_seal.json").read_text(encoding="utf-8-sig"))
    if seal.get("status") != "PASS" or seal.get("corpus_sha256") != corpus.corpus_hash:
        raise RuntimeError("Phase 10.5 interface seal identity mismatch")
    if seal.get("analysis_code_sha256") != corpus.interface_code_hash:
        raise RuntimeError("Phase 10.5 code changed after interface seal")
    for name, expected in seal.get("artifacts", {}).items():
        path = output / name
        if not path.is_file() or sha256(path) != expected:
            raise RuntimeError(f"Phase 10.5 artifact mismatch: {name}")


def _safe_output(workspace: Path, output: Path) -> None:
    allowed = (workspace / "phase11").resolve()
    try:
        output.relative_to(allowed)
    except ValueError as exc:
        raise RuntimeError("Phase 11 output must remain under phase11") from exc
    if output == allowed:
        raise RuntimeError("refusing to replace Phase 11 source directory")


def build(workspace: Path, output: Path) -> int:
    _safe_output(workspace, output)
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    sys.path.insert(0, str(workspace))
    sys.path.insert(0, str(workspace / "phase11"))
    from phase10_5 import ResearchCorpus
    from analysis import analyze
    from render import write_html, write_markdown

    corpus = ResearchCorpus(workspace)
    verify_interface(workspace, corpus)
    result = analyze(corpus)

    table_names = (
        "target_summary", "rates", "continuous", "incidence", "dependence", "feature_manifest",
        "model_metrics", "model_predictions", "fold_manifest", "coefficients",
        "nonlinear_metrics", "nonlinear_predictions", "candidate_protocol", "transitions",
        "transition_stability",
    )
    for name in table_names:
        table = result[name]
        if table.empty:
            table = pd.DataFrame({"status": ["NOT_RUN_OR_EMPTY"]})
        table.to_csv(output / f"{name}.tsv", sep="\t", index=False, na_rep="\\N")
    (output / "model_gates.json").write_text(json.dumps(result["model_gates"], indent=2), encoding="utf-8")
    (output / "latent_gate.json").write_text(json.dumps(result["latent_gate"], indent=2), encoding="utf-8")
    (output / "cohort_receipts.json").write_text(json.dumps(result["cohort_receipts"], indent=2), encoding="utf-8")
    write_markdown(result, output / "phase11_report.md")
    write_html(result, output / "phase11_report.html")

    stable_summary = dict(result["summary"])
    semantic = hashlib.sha256()
    semantic.update(json.dumps(stable_summary, sort_keys=True, separators=(",", ":")).encode())
    for name in table_names:
        semantic.update(name.encode())
        semantic.update((output / f"{name}.tsv").read_bytes())
    result["summary"]["semantic_result_sha256"] = semantic.hexdigest()
    result["summary"]["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
    (output / "phase11_summary.json").write_text(json.dumps(result["summary"], indent=2), encoding="utf-8")

    package_hash = code_hash(workspace / "phase11")
    artifacts = {
        path.relative_to(output).as_posix(): sha256(path)
        for path in sorted(output.rglob("*")) if path.is_file() and path.name != "phase11_seal.json"
    }
    seal = {
        "contract": "MST_RG2_PHASE11_RESEARCH_SEAL_V1",
        "status": result["summary"]["status"],
        "sealed_at_utc": datetime.now(timezone.utc).isoformat(),
        "corpus_sha256": corpus.corpus_hash,
        "phase10_5_interface_sha256": corpus.interface_code_hash,
        "phase11_code_sha256": package_hash,
        "semantic_result_sha256": result["summary"]["semantic_result_sha256"],
        "holdout_windows_touched": 0,
        "artifacts": artifacts,
    }
    (output / "phase11_seal.json").write_text(json.dumps(seal, indent=2), encoding="utf-8")
    print(
        f"status={seal['status']} targets={result['summary']['targets']} "
        f"candidates={result['summary']['frozen_research_candidates']} semantic={seal['semantic_result_sha256']}"
    )
    return 0 if seal["status"] == "PASS" else 2


def verify(workspace: Path, output: Path) -> int:
    sys.path.insert(0, str(workspace))
    from phase10_5 import ResearchCorpus
    failures = []
    seal_path = output / "phase11_seal.json"
    if not seal_path.is_file():
        print("status=FAIL failures=missing_phase11_seal")
        return 2
    seal = json.loads(seal_path.read_text(encoding="utf-8-sig"))
    try:
        corpus = ResearchCorpus(workspace)
        verify_interface(workspace, corpus)
        if seal.get("corpus_sha256") != corpus.corpus_hash:
            failures.append("corpus_sha256")
        if seal.get("phase10_5_interface_sha256") != corpus.interface_code_hash:
            failures.append("phase10_5_interface_sha256")
    except Exception as exc:
        failures.append(f"substrate:{type(exc).__name__}")
    if seal.get("phase11_code_sha256") != code_hash(workspace / "phase11"):
        failures.append("phase11_code_sha256")
    for name, expected in seal.get("artifacts", {}).items():
        path = output / name
        if not path.is_file() or sha256(path) != expected:
            failures.append(name)
    status = "PASS" if not failures and seal.get("status") == "PASS" else "FAIL"
    print(f"status={status} failures={','.join(failures)}")
    return 0 if status == "PASS" else 2


def main() -> int:
    parser = argparse.ArgumentParser(description="RG2 Phase 11 empirical structure research")
    parser.add_argument("command", choices=("build", "verify"))
    parser.add_argument("--workspace", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    output = (args.output or workspace / "phase11" / "output").resolve()
    return build(workspace, output) if args.command == "build" else verify(workspace, output)


if __name__ == "__main__":
    raise SystemExit(main())
