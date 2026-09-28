"""Seal the fixed Q-R2 source and built-generator inventory before execution."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-r2-late-branch-v01")
OUTPUT = RUN / "provenance/q-r2-instrument-package-seal-v01.json"
VERIFIER = ROOT / "experiments/jev-information-density-v08q-r2-late-branch/source/verify_q_r2_instrument_package_v01.py"


def load_verifier() -> Any:
    spec = importlib.util.spec_from_file_location("jev_q_r2_instrument_verifier_for_seal", VERIFIER)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load fixed Q-R2 instrument verifier")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    verifier = load_verifier()
    if OUTPUT.exists():
        raise FileExistsError(f"refusing to replace Q-R2 instrument seal: {OUTPUT}")
    expected: dict[str, Path] = {path: ROOT / path for path in verifier.REPO_FILES}
    expected.update({path.as_posix(): path for path in verifier.BUILD_FILES})
    entries = []
    for label, path in sorted(expected.items()):
        if not path.is_file():
            raise FileNotFoundError(f"required Q-R2 instrument file missing: {label}")
        entries.append({"path": label, "bytes": path.stat().st_size, "sha256": sha256(path)})
    root = verifier.entry_root(entries)
    try:
        import torch
        runtime = {"python": platform.python_version(), "torch": torch.__version__,
                   "cuda": torch.version.cuda, "cuda_available": torch.cuda.is_available(),
                   "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None}
    except ImportError:
        runtime = {"python": platform.python_version(), "torch": None, "cuda": None}
    receipt = {"status": "Q_R2_INSTRUMENT_PACKAGE_SEALED",
               "identity": "JEV-V08Q-R2-PAIRED-LATE-SHAM-WEIGHT-BRANCH-V01",
               "authorization_packet_sha256": "3f6367cb5bf03400923913fffb9acc5cc21ffa32ffdaee807615725ff7f2c209",
               "contract_bundle_root_sha256": "6b3b826fd3c861e1aa9114371f9db68c704fb9c5ad85e5c8c60a93afba527275",
               "entries_root_sha256": root, "entry_count": len(entries), "entries": entries,
               "runtime_at_seal": runtime,
               "model_contact": False, "head_initialization": False, "training": False,
               "evaluation_panel_opened": False, "inference": False,
               "created_at_utc": datetime.now(timezone.utc).isoformat()}
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(OUTPUT.suffix + ".tmp")
    with temporary.open("x", encoding="utf-8", newline="\n") as destination:
        destination.write(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n")
        destination.flush()
        os.fsync(destination.fileno())
    os.replace(temporary, OUTPUT)
    verified = verifier.verify()
    print(json.dumps({**verified, "runtime": runtime}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
