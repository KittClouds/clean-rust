"""Capture pinned native/model assets and wheel lock for cleanroom qualification."""
import hashlib
import importlib.metadata
import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
TARGET = HERE / "vendor" / "runtime-v1"


def main():
    TARGET.mkdir(parents=True, exist_ok=True)
    native = TARGET / "native"
    native.mkdir(exist_ok=True)
    shutil.copy2(HERE / "vendor/ladybug-v0.20.2/extracted/lbug_shared.dll", native / "lbug_shared.dll")
    for name in ("libssl-3-x64.dll", "libcrypto-3-x64.dll"):
        shutil.copy2(Path(r"C:\Program Files\Git\mingw64\bin") / name, native / name)
    for name in ("fts", "vector"):
        source = Path.home() / ".lbdb/extension/0.20.0/win_amd64" / name
        shutil.copytree(source, TARGET / "extensions" / name, dirs_exist_ok=True)
    shutil.copytree(HERE / ".kammi-dev/embedding-cache", TARGET / "embedding-cache", dirs_exist_ok=True)
    requirements = []
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata["Name"]
        if name.lower().replace("_", "-") not in {"kammi-ledger", "pip", "setuptools"}:
            requirements.append(f"{name}=={distribution.version}")
    lock = HERE / "runtime/requirements-lock-v1.txt"
    lock.write_text("\n".join(sorted(set(requirements), key=str.casefold)) + "\n")
    subprocess.run([sys.executable, "-m", "pip", "download", "--only-binary=:all:",
                    "--dest", str(TARGET / "wheels"), "-r", str(lock)], check=True)
    files = []
    for path in sorted(TARGET.rglob("*")):
        if path.is_file():
            with path.open("rb") as source:
                digest = hashlib.file_digest(source, "sha256").hexdigest()
            files.append({"path": path.relative_to(TARGET).as_posix(), "sha256": digest,
                          "bytes": path.stat().st_size})
    output = HERE / "runtime/ASSET-MANIFEST-v1.json"
    output.write_text(json.dumps({"schema": "KAMMI_RUNTIME_ASSETS_V1", "files": files}, indent=2) + "\n")
    print(json.dumps({"files": len(files), "bytes": sum(f["bytes"] for f in files)}))


if __name__ == "__main__":
    main()
