"""Allowlisted immutable schema-view adapters; source bytes are never rewritten."""

from __future__ import annotations

import hashlib
import inspect

from .identity import strict_json


def evaluation_cells_rename_v1(raw: bytes) -> bytes:
    from .identity import canonical

    value = strict_json(raw)
    if not isinstance(value, dict) or value.get("schema") != "evaluation-v1":
        raise ValueError("adapter source schema mismatch")
    if "evaluation_checkpoint_cells" not in value or "evaluation_cells" in value:
        raise ValueError("adapter source field is missing or ambiguous")
    result = dict(value)
    result["evaluation_cells"] = result.pop("evaluation_checkpoint_cells")
    result["schema"] = "evaluation-v2"
    return canonical(result)


BUILTINS = {
    "EVAL_CELLS_RENAME_V1": {
        "source_schema": "evaluation-v1",
        "target_schema": "evaluation-v2",
        "version": "v1",
        "function": evaluation_cells_rename_v1,
    }
}


def implementation_bytes(adapter_id: str) -> bytes:
    item = BUILTINS.get(adapter_id)
    if item is None:
        raise ValueError("unregistered adapter implementation")
    return inspect.getsource(item["function"]).encode("utf-8")


def implementation_hash(adapter_id: str) -> str:
    return "sha256:" + hashlib.sha256(implementation_bytes(adapter_id)).hexdigest()


class AdapterState:
    def __init__(self) -> None:
        self.registered: dict[str, dict] = {}
        self.applications: dict[str, dict] = {}

    def apply(self, kind: str, payload: dict, event_id: str) -> None:
        if kind == "AdapterRegistered":
            name = payload["adapter_id"]
            if name in self.registered and self.registered[name] != payload:
                raise ValueError("adapter identity collision")
            self.registered[name] = payload
        elif kind == "AdapterApplied":
            self.applications[event_id] = payload
