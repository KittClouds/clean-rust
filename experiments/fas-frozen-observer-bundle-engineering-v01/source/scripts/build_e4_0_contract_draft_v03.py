from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
PLANS = ROOT / "plans"
INPUT = PLANS / "E4-0-CONTRACT-DRAFT-v02.json"
SOURCE_MAP = PLANS / "E4-0-IMPLEMENTATION-SOURCE-MAP-v01.md"
OUTPUT = PLANS / "E4-0-CONTRACT-DRAFT-v03.json"
EXPECTED_V02_SHA256 = "5daa408426a54d5c54a53cf074d8c5ec44c904fa3c28abfb52de56e826c9c92d"


def sha256(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(8 << 20):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main() -> int:
    old_hash, _ = sha256(INPUT)
    if old_hash != EXPECTED_V02_SHA256:
        raise RuntimeError("v02 contract changed; do not derive v03 from an unexpected draft")
    source_map_hash, source_map_bytes = sha256(SOURCE_MAP)
    draft = copy.deepcopy(load(INPUT))
    if any(draft["execution_identity"].values()):
        raise RuntimeError("v02 unexpectedly contains an enabled execution identity")

    draft["contract_id"] = "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V03"
    draft["draft_revision"] = 3
    draft["supersedes"] = {
        "contract_id": "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V02",
        "sha256": old_hash,
        "reason": "Bind the codebase-specific implementation source map; scientific and resource gates are unchanged.",
    }
    draft["design_inputs"]["implementation_source_map_v01_path"] = str(
        SOURCE_MAP.relative_to(ROOT)
    ).replace("\\", "/")
    draft["design_inputs"]["implementation_source_map_v01_sha256"] = source_map_hash
    draft["design_inputs"]["implementation_source_map_v01_bytes"] = source_map_bytes

    builder_hash, builder_bytes = sha256(Path(__file__).resolve())
    draft["draft_builder"] = {
        "path": str(Path(__file__).resolve().relative_to(ROOT)).replace("\\", "/"),
        "sha256": builder_hash,
        "bytes": builder_bytes,
        "role": "Creates an unsealed v03 draft by binding the implementation source map to v02 without changing its scientific or resource gates.",
    }
    OUTPUT.write_text(json.dumps(draft, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": draft["status"],
        "contract_id": draft["contract_id"],
        "output": str(OUTPUT),
        "superseded_v02_sha256": old_hash,
        "source_map_sha256": source_map_hash,
        "source_map_bytes": source_map_bytes,
        "authorizations_open": False,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
