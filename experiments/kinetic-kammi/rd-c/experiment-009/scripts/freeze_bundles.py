from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(r"C:\rd-c\experiment-009")
MODELS = ROOT / "models"
MODELS.mkdir(parents=True, exist_ok=True)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


prompt = (ROOT / "prompts" / "system-observer-v1.txt").read_bytes()
schema = (ROOT / "schemas" / "observer-output.v1.json").read_bytes()
representation = prompt + b"\0" + schema + b"\0rdc-real-coding-observation.v1"
head_schema_hash = sha256(schema)


def bundle(
    *,
    bundle_id: str,
    implementation_id: str,
    backbone_name: str,
    backbone_revision: str,
    backbone_sha256: str,
    runtime_name: str,
    runtime_revision: str,
    runtime_sha256: str,
) -> dict:
    return {
        "bundle_schema_version": 1,
        "bundle_id": bundle_id,
        "observer_interface_version": 1,
        "implementation_id": implementation_id,
        "input_schema": "rdc-real-coding-observation.v1",
        "output_schema": "rdc-coding-observer-output.v1",
        "backbone_name": backbone_name,
        "backbone_revision": backbone_revision,
        "backbone_sha256": backbone_sha256,
        "runtime_name": runtime_name,
        "runtime_revision": runtime_revision,
        "runtime_sha256": runtime_sha256,
        "representation_surface_id": "system-observer-v1+canonical-task-frame-v1",
        "representation_surface_sha256": sha256(representation),
        "normalization_contract": "line-endings-lf-v1",
        "typed_head_id": "json-schema-output-head-v1",
        "typed_head_kind": "constrained-json-generation-not-trained-weights",
        "typed_head_schema_sha256": head_schema_hash,
        "temperature_milli": 0,
        "top_p_milli": 1000,
        "maximum_output_tokens": 1024,
        "seed": 0,
    }


bundles = [
    bundle(
        bundle_id="minicpm5-2b-q8-local-v1",
        implementation_id="llama.cpp-chat-completions-json-schema-v1",
        backbone_name="MiniCPM5-2B-Q8_0.gguf",
        backbone_revision="2079a22f3beaa4e306449978533478fe0522f4b3",
        backbone_sha256="c5415f8989bf88a8288f1b55a3cc371af53c07b0faa220a63bd7a990cfaba078",
        runtime_name="llama-server.exe",
        runtime_revision="llama.cpp-b10982",
        runtime_sha256="ffaee576ad271ede87b92a7d8c3863dc8f331bbac666ee00099c250e8809e743",
    ),
    bundle(
        bundle_id="ternary-bonsai-2-27b-ptq1-local-v1",
        implementation_id="prism-llama.cpp-chat-completions-json-schema-v1",
        backbone_name="Ternary-Bonsai-2-27B-PTQ1_0.gguf",
        backbone_revision="6ed5e12bf84b7a63069882c91dd9e9218647d17b",
        backbone_sha256="53107f530aa52eb00912263ab1ee29bd199261c87cd7b4ad4ca1318c1fe33ee3",
        runtime_name="llama-server.exe",
        runtime_revision="PrismML-llama.cpp-prism-b10685-7dffb15",
        runtime_sha256="e0ea4fd53e6f0c741cbd28093b427f333ada0eb03b83073e1f99c483793ea976",
    ),
]

artifact_locations = [
    {
        "bundle_id": "minicpm5-2b-q8-local-v1",
        "qualification_status": "qualified_for_live_trial",
        "model_path": r"D:\phoenix-models\candidates\minicpm5-2b\2079a22f3beaa4e306449978533478fe0522f4b3\MiniCPM5-2B-Q8_0.gguf",
        "runtime_path": r"D:\phoenix-runtimes\llama.cpp\b10982\runtime\llama-server.exe",
    },
    {
        "bundle_id": "ternary-bonsai-2-27b-ptq1-local-v1",
        "qualification_status": "experimental_runtime_only",
        "model_path": r"D:\phoenix-models\candidates\ternary-bonsai-2-27b\6ed5e12bf84b7a63069882c91dd9e9218647d17b\Ternary-Bonsai-2-27B-PTQ1_0.gguf",
        "runtime_path": r"D:\phoenix-runtimes\prism-llama.cpp\prism-b10685-7dffb15\win-cuda-12.4\runtime\llama-server.exe",
    },
]
for location in artifact_locations:
    for key in ("model_path", "runtime_path"):
        path = Path(location[key])
        if not path.is_file():
            raise SystemExit(f"missing locked model/runtime file: {path}")
        stat = path.stat()
        location[key.replace("_path", "_size_bytes")] = stat.st_size
        location[key.replace("_path", "_mtime_ns")] = stat.st_mtime_ns
locations_path = MODELS / "artifact-paths.json"
locations_path.write_text(json.dumps({"schema_version": 1, "artifacts": artifact_locations}, indent=2) + "\n", encoding="utf-8")

source = MODELS / "bundle-input.json"
locked = MODELS / "bundle-lock.json"
source.write_text(json.dumps({"bundles": bundles}, indent=2) + "\n", encoding="utf-8")
environment = os.environ.copy()
environment["CARGO_TARGET_DIR"] = r"D:\cargo-targets\rdc-e009"
subprocess.run(
    [
        "cargo",
        "run",
        "--quiet",
        "--manifest-path",
        str(ROOT / "Cargo.toml"),
        "--bin",
        "e009-lock-bundles",
        "--",
        str(source),
        str(locked),
    ],
    cwd=ROOT,
    env=environment,
    check=True,
)
print(f"locked {len(bundles)} observer bundles: {locked}")
