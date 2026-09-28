from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(r"C:\rd-c\selective-cognition-action-region-program\experiment-012")
CONSTRUCTION = ROOT / "bank" / "construction-01"
REPOS = CONSTRUCTION / "repositories"
ARCHIVES = CONSTRUCTION / "source" / "repositories"
OUTPUT = CONSTRUCTION / "repository-source-inventory.json"
E009_FRAME = Path(r"C:\rd-c\experiment-009\tasks\frames\frame-lock.json")
E010_SPLIT = Path(r"C:\rd-c\experiment-010\tasks\heldout-bank-v1\split-manifest.json")
E011_TASKS = Path(r"C:\rd-c\experiment-011\inputs\fresh-integration-bank-v1c\task-manifest.json")

PINNED = {
    "bytes": {
        "remote": "https://github.com/tokio-rs/bytes.git",
        "commit": "417dccdeff249e0c011327de7d92e0d6fbe7cc43",
        "release": "v1.11.1",
    },
    "clap": {
        "remote": "https://github.com/clap-rs/clap.git",
        "commit": "ac5fda6a799e4c640d671edd1111d4a5e723dc1a",
        "release": "v4.6.1",
    },
    "serde-json": {
        "remote": "https://github.com/serde-rs/json.git",
        "commit": "4f6dbfac79647d032b0997b5ab73022340c6dab7",
        "release": "v1.0.149",
    },
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


def repositories_in(value: object, found: set[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in {"repository_id", "repository", "repo_id", "repo_name"}:
                if isinstance(child, str):
                    found.add(child)
            if key.lower() in {"repository_unit", "repositories", "repository_ids"}:
                if isinstance(child, list):
                    found.update(item for item in child if isinstance(item, str))
            repositories_in(child, found)
    elif isinstance(value, list):
        for child in value:
            repositories_in(child, found)


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    if OUTPUT.exists():
        raise SystemExit(f"refusing to overwrite source inventory: {OUTPUT}")
    ARCHIVES.mkdir(parents=True, exist_ok=True)

    prior: dict[str, list[str]] = {}
    e009 = load_json(E009_FRAME)
    e009_sources: set[str] = set()
    repositories_in(e009, e009_sources)
    # E009 frames name the source repository through source IDs rather than repository_id.
    frames = e009.get("frames", []) if isinstance(e009, dict) else []
    for item in frames:
        frame = item.get("frame", {})
        for evidence in frame.get("evidence", []):
            source_id = evidence.get("source_id", "")
            if isinstance(source_id, str) and "/" in source_id:
                e009_sources.add(source_id.split("/", 1)[0])
    prior["E009"] = sorted(e009_sources)
    for run, path in (("E010", E010_SPLIT), ("E011", E011_TASKS)):
        found: set[str] = set()
        repositories_in(load_json(path), found)
        prior[run] = sorted(found)

    if not {"phoenix-native", "rust-native"}.issubset(prior["E009"]):
        raise SystemExit(f"could not verify E009 source repository: {prior['E009']}")
    if prior["E010"] != ["ripgrep", "turbovec"] or prior["E011"] != ["ripgrep", "turbovec"]:
        raise SystemExit(f"unexpected E010/E011 repository set: {prior}")

    rows: list[dict[str, str]] = []
    for name, pin in PINNED.items():
        repo = REPOS / name
        if not repo.is_dir():
            raise SystemExit(f"missing source checkout: {repo}")
        if git(repo, "rev-parse", "HEAD") != pin["commit"]:
            raise SystemExit(f"revision mismatch for {name}")
        if git(repo, "remote", "get-url", "origin") != pin["remote"]:
            raise SystemExit(f"origin mismatch for {name}")
        if git(repo, "status", "--porcelain=v1"):
            raise SystemExit(f"source checkout is dirty: {name}")
        if name in {repo_id for values in prior.values() for repo_id in values}:
            raise SystemExit(f"repository appeared in an earlier evaluation: {name}")

        archive = ARCHIVES / f"{name}-{pin['release']}-source.tar"
        if archive.exists():
            raise SystemExit(f"refusing to overwrite archive: {archive}")
        subprocess.run(
            ["git", "-C", str(repo), "archive", "--format=tar", "--output", str(archive), pin["commit"]],
            check=True,
        )
        archive_hash = sha256(archive.read_bytes())
        cargo = repo / "Cargo.toml"
        rows.append(
            {
                "repository_id": name,
                "remote": pin["remote"],
                "release": pin["release"],
                "commit": pin["commit"],
                "archive_path": archive.relative_to(CONSTRUCTION).as_posix(),
                "archive_sha256": archive_hash,
                "root_cargo_toml_sha256": sha256(cargo.read_bytes()),
            }
        )

    inventory = {
        "schema_version": 1,
        "state": "SOURCE_SNAPSHOTS_PINNED_PRETASK",
        "model_contact_authorized": False,
        "task_fixtures_created": False,
        "previous_evaluation_repositories": prior,
        "selected_repositories": rows,
        "selection_assertion": "all three selected repository IDs are absent from E009, E010, and E011 evaluation repository sets",
    }
    OUTPUT.write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(inventory, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
