from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from analysis import analyze, load_corpus
from render import write_html, write_markdown


def main() -> int:
    parser = argparse.ArgumentParser(description="RG2 Phase 9 dataset-geometry audit")
    parser.add_argument("--workspace", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    output = (args.output or workspace / "phase9" / "output").resolve()
    output.mkdir(parents=True, exist_ok=True)
    corpus = load_corpus(workspace / "furnace" / "corpus", workspace / "campaign" / "campaign_manifest_rg2_v3.tsv")
    replay_path = workspace / "furnace" / "replay_verification.json"
    replay = json.loads(replay_path.read_text(encoding="utf-8-sig"))
    result = analyze(corpus, replay)

    entropy = result["coverage"][["unit", "dimension", "entropy_bits", "normalized_entropy"]].drop_duplicates()
    data_gaps = result["runs"][["run_key", "window_id", "instrument", "data_source",
        "expected_profile_bars", "observed_profile_bars", "bar_gap", "unexpected_data_gaps",
        "source_frame_valid"]].copy()

    exports = {
        "runs": "run_qc.csv", "coverage": "coverage_tables.csv",
        "continuous": "continuous_distributions.csv", "cross_coverage": "cross_coverage.csv",
        "continuous_stratified": "continuous_stratified.csv",
        "missingness": "missingness.csv", "readiness": "question_readiness.csv",
        "invariants": "qc_invariants.csv", "nodes": "node_lifecycle.csv",
    }
    for key, filename in exports.items():
        result[key].to_csv(output / filename, index=False, na_rep="\\N")
    entropy.to_csv(output / "entropy_summary.csv", index=False, na_rep="\\N")
    data_gaps.to_csv(output / "data_gaps.csv", index=False, na_rep="\\N")

    semantic_hash = hashlib.sha256()
    stable_summary = {key: value for key, value in result["summary"].items()
                      if key not in {"generated_at_utc", "semantic_result_sha256"}}
    semantic_hash.update(json.dumps(stable_summary, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    deterministic_tables = sorted([*exports.values(), "entropy_summary.csv", "data_gaps.csv"])
    for filename in deterministic_tables:
        semantic_hash.update(filename.encode("utf-8"))
        semantic_hash.update((output / filename).read_bytes())
    result["summary"]["semantic_result_sha256"] = semantic_hash.hexdigest()
    (output / "phase9_summary.json").write_text(json.dumps(result["summary"], indent=2), encoding="utf-8")
    write_markdown(result, output / "phase9_report.md")
    write_html(result, output / "phase9_report.html")

    code_hash = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        code_hash.update(path.read_bytes())
    artifacts = {}
    for path in sorted(output.iterdir()):
        if path.name == "analysis_manifest.json" or not path.is_file():
            continue
        artifacts[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {
        "contract": "MST_RG2_PHASE9_ANALYSIS_MANIFEST_V1",
        "status": result["summary"]["status"],
        "corpus_fingerprint": result["summary"]["corpus_fingerprint"],
        "semantic_result_sha256": result["summary"]["semantic_result_sha256"],
        "analysis_code_sha256": code_hash.hexdigest(),
        "artifacts": artifacts,
    }
    (output / "analysis_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"status={result['summary']['status']}")
    print(f"decision={result['summary']['phase9_decision']}")
    print(f"runs={result['summary']['runs']}")
    print(f"episodes={result['summary']['episodes']}")
    print(f"output={output}")
    return 0 if result["summary"]["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
