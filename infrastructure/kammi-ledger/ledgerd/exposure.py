"""Guarded panel metadata and reconstructable exposure vectors."""

from __future__ import annotations

from collections import Counter

from .graph import SAFE
from .identity import require_id

PURPOSES = (
    "generation", "fit", "selection", "thresholding", "diagnostic", "terminal"
)


def panel_payload(panel_id: str, artifact_id: str, lab: str) -> dict:
    if not all(isinstance(value, str) and SAFE.fullmatch(value) for value in (panel_id, lab)):
        raise ValueError("invalid panel ID or lab")
    return {"panel_id": panel_id, "artifact_id": require_id(artifact_id), "lab": lab}


class ExposureState:
    def __init__(self) -> None:
        self.panels: dict[str, dict] = {}
        self.opened: list[dict] = []
        self.denied: list[dict] = []
        self.by_request: dict[str, tuple[str, dict]] = {}

    def apply(self, kind: str, payload: dict) -> None:
        if kind == "PanelRegistered":
            panel_id = payload["panel_id"]
            if panel_id in self.panels and self.panels[panel_id] != payload:
                raise ValueError("panel identity collision")
            self.panels[panel_id] = payload
        elif kind == "ExposureOpened":
            self.opened.append(payload)
            self.by_request[payload["request_id"]] = (kind, payload)
        elif kind == "ExposureDenied":
            self.denied.append(payload)
            self.by_request[payload["request_id"]] = (kind, payload)

    def report(self, panel_id: str) -> dict:
        if panel_id not in self.panels:
            raise ValueError("unknown panel")
        selected = [entry for entry in self.opened if entry["panel_id"] == panel_id]
        vector = Counter(entry["purpose"] for entry in selected)
        return {
            "panel_id": panel_id,
            "exposure_vector": {purpose: vector[purpose] for purpose in PURPOSES},
            "count": len(selected),
            "openings": selected,
            "denials": [entry for entry in self.denied if entry["panel_id"] == panel_id],
        }
