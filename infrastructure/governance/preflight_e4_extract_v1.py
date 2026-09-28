"""Run E4 extraction's visible-only pre-model checks as Chief."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


HERE = Path(__file__).parent
OUT = HERE / "inbox/20260927/E4-0-EXTRACT-PREMODEL-PREFLIGHT-v1.json"
LAB_SCRIPTS = Path(r"C:\Users\shuga\.codex\worktrees\e4-0-contract-work\clean-rust"
                   r"\experiments\fas-frozen-observer-bundle-engineering-v01\source\scripts")
BINDING = Path(r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01"
               r"\e4-0-ledger-bindings-v02\fresh-feature-extraction-binding-v02.json")


def main() -> None:
    if OUT.exists():
        raise ValueError("preflight receipt already exists")
    sys.path.insert(0, str(LAB_SCRIPTS))
    from e4_supervised_execution_adapter_v02 import load_binding
    from e4_runner_modes_v07 import online_authorization_preflight

    binding, digest = load_binding(BINDING, "extract-e4")
    contract, inputs = online_authorization_preflight(binding, "extract-e4")
    imported = {name for name in sys.modules if name.split(".", 1)[0] in {
        "torch", "transformers", "tokenizers"
    }}
    if imported:
        raise ValueError("pre-model preflight imported a model/tokenizer module")
    with BINDING.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != digest:
        raise ValueError("binding bytes changed during preflight")
    receipt = {
        "schema": "CHIEF_E4_0_EXTRACT_PREMODEL_PREFLIGHT_V1",
        "status": "PASS_VISIBLE_ONLY_PREMODEL",
        "binding_path": str(BINDING), "binding_sha256": digest,
        "mode": binding["mode"], "stage": binding["stage"],
        "contract_sha256": binding["contract_sha256"],
        "contract_root": binding["contract_seal_root_sha256"],
        "parity_root": binding["exact_predecessor_roots"]["e4_parity_receipt_root_sha256"],
        "verified_visible_artifact_roles": sorted(inputs),
        "contract_verified": bool(contract),
        "model_tokenizer_modules_imported": False,
        "model_tokenizer_cuda_contact": False,
        "protected_labels_opened": False,
        "extraction_started": False,
    }
    with OUT.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, indent=2)
        stream.write("\n")
    print(json.dumps({"status": receipt["status"], "binding_sha256": digest,
                      "visible_roles": len(inputs)}))


if __name__ == "__main__":
    main()
