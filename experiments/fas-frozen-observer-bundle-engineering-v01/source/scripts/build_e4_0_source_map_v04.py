from __future__ import annotations

import hashlib
import json
from pathlib import Path


WORKSPACE = Path(__file__).resolve().parents[4]
PROJECT = WORKSPACE / "experiments" / "fas-frozen-observer-bundle-engineering-v01"
OUTPUT = PROJECT / "plans" / "E4-0-IMPLEMENTATION-SOURCE-MAP-v04.md"


def sha256(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1 << 20):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def project_path(path: Path) -> str:
    return path.resolve().relative_to(WORKSPACE.resolve()).as_posix()


def collect_source_files() -> list[tuple[Path, str]]:
    roots = (
        (PROJECT / "source" / "e4-population-v01", "Track A population generator / Rust build closure"),
        (PROJECT / "source" / "panel-generator-v04", "Frozen local E1 schedule dependency"),
        (PROJECT / "source" / "e4-support-plan-v11", "Model-free symbolic support planner"),
        (PROJECT / "source" / "scripts" / "e4_fresh_scorer_v01", "Track C scorer / synthetic tests"),
    )
    files: dict[str, tuple[Path, str]] = {}
    for root, role in roots:
        if not root.is_dir():
            raise RuntimeError(f"required source directory is absent: {root}")
        for path in root.rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            if path.suffix in {".rs", ".toml", ".lock", ".py", ".md"}:
                files[project_path(path)] = (path, role)

    explicit = {
        "source/scripts/e4_online_parity_v01.py": "Track B parity/feature runner entrypoint",
        "source/scripts/e4_runner_common_v01.py": "Track B auth, identity, and parity selection",
        "source/scripts/e4_runner_artifacts_v01.py": "Track B artifact custody and seals",
        "source/scripts/e4_gpu_lease_v01.py": "Track B process lease and resource telemetry",
        "source/scripts/e4_runner_modes_v01.py": "Track B panel, parity, and feature modes",
        "source/tests/test_e4_runner_v01.py": "Track B synthetic source tests",
        "source/scripts/build_e4_0_contract_draft_v05.py": "Historical v05 draft builder",
        "source/scripts/audit_e4_0_contract_draft_v05.py": "Historical v05 draft auditor",
        "source/scripts/build_e4_0_source_map_v04.py": "Final source map builder",
        "source/scripts/finalize_e4_0_contract_v05.py": "Final v05 contract metadata binder",
        "source/scripts/seal_e4_0_contract_v05.py": "Generic final contract seal builder",
        "source/scripts/issue_e4_stage_authorization_v01.py": "Normative stage authorization issuer",
        "source/tests/test_e4_stage_authorization_v01.py": "Stage authorization issuer synthetic tests",
        "audits/e4-0-track-e/audit_e4_0_track_e.py": "Independent Track E contract/source auditor",
        "audits/e4-0-track-e/audit_e4_0_track_e_seal.py": "Independent Track E seal-root and member auditor",
        "audits/e4-0-track-e/test_audit_e4_0_track_e.py": "Independent Track E contract/source auditor tests",
    }
    for rel, role in explicit.items():
        path = PROJECT / rel
        if path.is_file():
            files[rel] = (path, role)
    track_d = PROJECT / "source" / "scripts" / "e4_independent_audit_v01"
    if track_d.is_dir():
        for path in track_d.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix in {".py", ".md"}:
                files[project_path(path)] = (path, "Track D independent population/parity/scoring replay auditor")
    return [files[key] for key in sorted(files, key=lambda item: item.encode("utf-8"))]


def load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def source_row(path: Path, role: str) -> str:
    digest, size = sha256(path)
    return f"| `{project_path(path)}` | {size} | `{digest}` | {role} |"


def input_row(path: Path, role: str) -> str:
    digest, size = sha256(path)
    return f"| `{project_path(path)}` | {size} | `{digest}` | {role} |"


def external_input_row(path: Path, role: str) -> str:
    digest, size = sha256(path)
    return f"| `{str(path.resolve())}` | {size} | `{digest}` | {role} |"


def main() -> int:
    draft_path = PROJECT / "plans" / "E4-0-CONTRACT-DRAFT-v05.json"
    draft_sha, draft_bytes = sha256(draft_path)
    if draft_sha != "e2910965b53313a34c3a7d870075d83dbc9e035a230fc68f3c177c12c71e9fcf":
        raise RuntimeError("immutable E4-0 v05 draft identity changed")

    receipt_paths = {
        "Track A": PROJECT / "audits" / "e4-0-track-a" / "track-a-receipt-v02.json",
        "Track B": PROJECT / "audits" / "e4-0-track-b" / "track-b-source-tests-v01.json",
        "Track C": PROJECT / "audits" / "e4-0-track-c" / "track-c-source-tests-v02.json",
        "Track D": PROJECT / "audits" / "e4-0-track-d" / "track-d-receipt-v04.json",
        "Track E": PROJECT / "audits" / "e4-0-track-e" / "track-e-source-tests-v06.json",
        "Auth issuer": PROJECT / "audits" / "e4-0-auth-issuer-source-tests-v01.json",
    }
    expected = {
        "Track A": "54e143b1657d5f99a8f730604e4095bc0ece2521492124e6bb5effc52da92dcb",
        "Track B": "acba272c3eb177e8e15b178343a7fcc87ecc43e0bfb6bc665dda9ddf25e400a3",
        "Track C": "e8ada9ff5288baa87c4aefc07a5acb2a31e1227862c36876004da958d5ce571b",
        "Track D": "41d35cc3003faa62ddd9fca33675800a33725ffe1410e565647efea54fb20720",
        "Auth issuer": "0b5d809100319ae8674e60732f76e606fa6d787335fcbf72bad84ca58866b9dc",
    }
    receipt_rows: list[str] = []
    for label, path in receipt_paths.items():
        digest, size = sha256(path)
        if label in expected and digest != expected[label]:
            raise RuntimeError(f"{label} receipt changed after review: {digest}")
        receipt = load_json(path)
        if label not in {"Track A", "Track D"} and "PASS" not in str(receipt.get("status", "")):
            raise RuntimeError(f"{label} source receipt is not a passing receipt")
        if label == "Track D" and receipt.get("status") != "TRACK_D_COMPLETE_PREAUTHORIZATION":
            raise RuntimeError("Track D v04 source receipt is not complete/preauthorization")
        if label == "Track E" and receipt.get("status") != "TRACK_E_SOURCE_TESTS_PASS_PREMAP_UNIT_TESTS":
            raise RuntimeError("Track E pre-map source/unit receipt is not passing")
        if label == "Auth issuer" and "PASS" not in str(receipt.get("status", "")):
            raise RuntimeError("authorization issuer source tests are not passing")
        receipt_rows.append(f"| {label} | `{project_path(path)}` | {size} | `{digest}` | `{receipt.get('status', '')}` |")

    source_rows = [source_row(path, role) for path, role in collect_source_files()]
    frozen_inputs = (
        (PROJECT / "plans" / "E4-CODEBASE-MAP-v01.md", "Pinned E4 codebase orientation."),
        (PROJECT / "plans" / "E4-0-CONTRACT-DRAFT-v05.json", "Immutable scientific/protocol baseline; all gates compared against this file."),
        (PROJECT / "plans" / "E4-0-PRECONDITIONS-DESIGN-v03.md", "Resolved E4-0 scientific design."),
        (PROJECT / "plans" / "E4-0-HELDOUT-TEMPLATES-v02.json", "Frozen held-out template bytes."),
        (PROJECT / "plans" / "E4-0-HELDOUT-TEMPLATES-v02-audit.json", "Exact/normalized template exclusion audit."),
        (PROJECT / "plans" / "E4-0-TEMPLATE-STRUCTURAL-AUDIT-v01.md", "Descriptive structural novelty audit."),
        (PROJECT / "plans" / "E4-0-SYMBOLIC-SUPPORT-PLAN-v11.json", "Frozen 18,667-quartet support/collision plan."),
        (PROJECT / "audits" / "e4-0-support-plan-v11-source-tests.json", "Support planner source/replay validation."),
        (PROJECT / "contracts" / "e4-0-stage-authorization-schema-v01.json", "Normative staged authorization schema."),
        (PROJECT / "contracts" / "e4-0-artifact-seal-schema-v01.json", "Normative artifact seal schema."),
        (PROJECT / "contracts" / "representation-abi-v07.json", "Frozen model/representation ABI."),
        (PROJECT / "contracts" / "e0-freeze-v10-sealed-v01.json", "Frozen E0 v10 predecessor contract."),
        (PROJECT / "seals" / "e0-seal-v10.json", "Frozen E0 v10 seal manifest."),
        (PROJECT / "audits" / "e0-v10-independent-audit-v01.json", "Independent E0 v10 audit."),
        (PROJECT / "audits" / "e1-independent-audit-v04.json", "Independent E1 v04 population audit."),
        (PROJECT / "seals" / "e3-score-v02-seal.json", "Sealed E3 score replay artifact."),
        (PROJECT / "audits" / "e3-score-v02-independent-audit.json", "Independent E3 score replay audit."),
    )
    input_rows = [input_row(path, role) for path, role in frozen_inputs if path.is_file()]
    external_inputs = (
        (Path(r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e1-panel-v04\e1-seal-v01.json"), "Sealed E1 v04 population root and member inventory."),
        (Path(r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e2-v07\e2-v07-seal.json"), "Sealed E2 v07 representation cache root."),
        (Path(r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e2-v07\e2-v07-independent-audit-v01.json"), "Independent E2 v07 audit."),
        (Path(r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e3-v02\e3-v02-seal.json"), "Sealed E3 v02 observer bundle root and head inventory."),
        (Path(r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e3-v02\e3-v02-independent-audit-v01.json"), "Independent E3 v02 bundle audit."),
    )
    for path, role in external_inputs:
        if not path.is_file():
            raise RuntimeError(f"required sealed predecessor artifact is absent: {path}")
        input_rows.append(external_input_row(path, role))
    content = [
        "# E4-0 Implementation Source Map v04",
        "",
        "Status: final implementation closure for E4-0 v05. This map binds the exact frozen protocol inputs, source/build closure, source-test receipts, and independent auditor code. It does not itself grant execution authority.",
        "",
        "## Immutable protocol baseline",
        "",
        "- The immutable v05 draft identity and exact bytes are recorded once in the bound frozen-input table below.",
        "- Scientific, population, representation, parity, truth-access, resource, and scoring gates must match this baseline exactly. Only source-binding/status/receipt metadata may be serialized into the final contract.",
        "- Fresh population: 18,667 whole quartets, 74,668 primary rows, 74,668 held-out-template rows, 149,336 unique feature rows; minimum selected support 252, immediately preceding prefix 248.",
        "- Held-out template/joint truth remains escrowed; E4-0 scores only the eight registered primary endpoints.",
        "",
        "## Bound frozen inputs",
        "",
        "| Input Path | Bytes | SHA-256 | Role |",
        "| --- | ---: | --- | --- |",
        *input_rows,
        "",
        "## Bound source and build closure",
        "",
        "All source, frozen-input, and receipt table paths are relative to the workspace root; only external predecessor diagnostics use absolute paths. The source table includes runtime code, local dependencies, manifests/lockfiles, schemas, tests, and contract processing/audit utilities. Python bytecode and caches are excluded.",
        "",
        "| Path | Bytes | SHA-256 | Role |",
        "| --- | ---: | --- | --- |",
        *source_rows,
        "",
        "## Track receipts",
        "",
        "- The former aggregate source integration receipt v01 is retained as superseded; current Track A/B/C/D/E and authorization-issuer receipts are bound individually.",
        "",
        "| Track | Path | Bytes | SHA-256 | Status |",
        "| --- | --- | ---: | --- | --- |",
        *receipt_rows,
        "",
        "## Runtime identity",
        "",
        "- Python 3.13.15; NumPy 2.5.3; PyTorch 2.11.0+cu128; CUDA runtime/model/tokenizer identities are bound by the included representation ABI v07 and checked at the authorized online stage.",
        "- Rust release profile and exact Cargo resolution are bound by the population and support-planner manifests/lockfiles; the local panel-generator-v04 crate is explicitly included.",
        "- GPU resource claim is process-scoped PyTorch CUDA caching allocator reserved peak, at most 10 GiB; device-wide telemetry is diagnostic only. Host extractor process peak working set is at most 25 GiB.",
        "",
        "## Source map builder identity",
        "",
        "- The source-map builder's exact path, byte length, and SHA-256 are recorded once in the bound source/build closure table above.",
        "",
        "## Execution boundary",
        "",
        "Pre-seal validation uses only synthetic fixtures and frozen public inputs. It does not materialize fresh E4 rows, load a tokenizer/model, initialize CUDA, open E4 terminal labels, emit E4 predictions, or score. Runtime stages require separate stage-specific authorization receipts bound to the final contract seal and exact predecessor roots.",
        "",
    ]
    OUTPUT.write_text("\n".join(content), encoding="utf-8", newline="\n")
    print(json.dumps({"status": "SOURCE_MAP_V04_WRITTEN", "path": project_path(OUTPUT), "bytes": OUTPUT.stat().st_size, "sha256": sha256(OUTPUT)[0], "source_count": len(source_rows), "input_count": len(input_rows)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
