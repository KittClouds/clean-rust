#!/usr/bin/env python3
import hashlib
import json
from pathlib import Path

from huggingface_hub import hf_hub_download

REPOSITORY = "Qwen/Qwen3-Embedding-0.6B"
REVISION = "97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3"
OUTPUT = Path(r"D:\phoenix-target-g-reasoner-34m\qwen")
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "qwen-artifact-manifest.json"
FILES = ("config.json", "tokenizer.json", "tokenizer_config.json", "model.safetensors")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    artifacts = []
    for name in FILES:
        path = Path(
            hf_hub_download(
                REPOSITORY,
                name,
                revision=REVISION,
                local_dir=OUTPUT,
            )
        )
        artifacts.append({"file": name, "bytes": path.stat().st_size, "sha256": sha256(path)})
    manifest = {
        "schema": "phoenix.g-reasoner.qwen-artifacts.v1",
        "repository": REPOSITORY,
        "revision": REVISION,
        "artifacts": artifacts,
    }
    encoded = json.dumps(manifest, indent=2) + "\n"
    (OUTPUT / "artifact-manifest.json").write_text(encoded, encoding="utf-8")
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(encoded, encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
