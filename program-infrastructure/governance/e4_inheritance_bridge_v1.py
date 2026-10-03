"""Chief-only visible E4 inheritance audit; never read protected label files."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


LAB = Path(r"C:\Users\shuga\.codex\worktrees\e4-0-contract-work\clean-rust") / (
    "experiments/fas-frozen-observer-bundle-engineering-v01"
)
RUN = Path(r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e4-0-v01")
OUT = Path(__file__).parent / "inbox/20260927/E4-0-INHERITANCE-BRIDGE-v1.json"
CURRENT = LAB / "contracts/e4-0-contract-v16-v09-final.json"
CURRENT_SEAL = LAB / "seals/e4-0-contract-v16-v09-seal.json"
OLD = LAB / "contracts/e4-0-contract-v06-final.json"
OLD_SEAL = LAB / "seals/e4-0-contract-v06-seal.json"
STAGES = ("stage-seal-v01.json", "parity-panel/stage-seal-v01.json")


def digest(path: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    count = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            h.update(chunk)
            count += len(chunk)
    return h.hexdigest(), count


def checked(path: Path, expected: str, size: int | None = None) -> dict:
    actual, count = digest(path)
    if actual != expected or (size is not None and count != size):
        raise ValueError(f"identity mismatch: {path}")
    return {"path": str(path), "sha256": actual, "bytes": count}


def main() -> None:
    current = json.loads(CURRENT.read_bytes())
    current_seal = json.loads(CURRENT_SEAL.read_bytes())
    old_seal = json.loads(OLD_SEAL.read_bytes())
    baseline = current["finalization"]
    old_contract_id = baseline["immutable_baseline_contract_sha256"]
    old_entry = next(
        (item for item in current_seal["entries"]
         if item.get("sha256") == old_contract_id), None
    )
    if old_entry is None:
        raise ValueError("v06 baseline contract is absent from current seal")
    contracts = {
        "current_contract": checked(CURRENT, current_seal["contract_sha256"]),
        "current_seal": {**checked(CURRENT_SEAL, digest(CURRENT_SEAL)[0]),
                         "root_sha256": current_seal["root_sha256"]},
        "v06_contract": checked(OLD, old_contract_id,
                                baseline["immutable_baseline_contract_bytes"]),
        "v06_seal": {**checked(OLD_SEAL, digest(OLD_SEAL)[0]),
                     "root_sha256": old_seal["root_sha256"]},
    }
    stages = []
    for name in STAGES:
        path = RUN / name
        seal = json.loads(path.read_bytes())
        if (seal["contract_sha256"] != old_contract_id
                or seal["contract_seal_root_sha256"] != old_seal["root_sha256"]):
            raise ValueError("inherited stage points to a different v06 contract")
        visible = []
        withheld = []
        for entry in seal["entries"]:
            if entry["path"].startswith("labels/"):
                withheld.append({"artifact_id": entry["artifact_id"],
                                 "declared_sha256": entry["sha256"],
                                 "declared_bytes": entry["bytes"]})
                continue
            item = checked(RUN / entry["path"], entry["sha256"], entry["bytes"])
            visible.append({"artifact_id": entry["artifact_id"], **item})
        stages.append({"stage": seal["stage"], "manifest": checked(path, digest(path)[0]),
                       "declared_root_sha256": seal["root_sha256"],
                       "visible_members_verified": visible,
                       "protected_members_not_opened": withheld,
                       "full_legacy_stage_closure_verified": not withheld})
    bridge = {
        "schema": "CHIEF_E4_INHERITANCE_BRIDGE_V1",
        "status": "VISIBLE_INHERITANCE_VERIFIED_PROTECTED_CLOSURE_WITHHELD",
        "lab": "Frozen Fabrique", "scientific_contract_preserved": True,
        "contracts": contracts, "stages": stages,
        "authorization_conferred": False, "model_contact_authorized": False,
        "truth_label_bytes_opened": False,
        "interpretation": "v06 generated these stages; v16-v09 includes v06 as the immutable scientific baseline. Visible bytes match their original manifests. The population's protected members remain declared identities only and require a separate custody gate before scoring.",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(bridge, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": bridge["status"], "output": str(OUT),
                      "sha256": digest(OUT)[0], "visible_members": sum(
                          len(stage["visible_members_verified"]) for stage in stages),
                      "protected_members_opened": False}))


if __name__ == "__main__":
    main()
