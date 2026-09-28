"""Language-neutral HTTP contract exercised by the Python SDK."""

from __future__ import annotations

import json
import os
import base64
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .identity import canonical


class KammiClient:
    def __init__(self, base_url: str, token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token

    @classmethod
    def from_environment(cls) -> "KammiClient":
        token = os.environ.get("KAMMI_TOKEN")
        if not token:
            raise ValueError("KAMMI_TOKEN is required")
        return cls(os.environ.get("KAMMI_URL", "http://127.0.0.1:8765"), token)

    def _request(
        self, method: str, path: str, body: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout_seconds: float = 30,
    ) -> dict:
        request = Request(
            self.base_url + path,
            data=body,
            method=method,
            headers={"Authorization": "Bearer " + self.token, **(headers or {})},
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                return json.load(response)
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Kammi Ledger HTTP {exc.code}: {detail}") from exc

    def status(self) -> dict:
        return self._request("GET", "/v1/status")

    def call(self, method: str, path: str, body: dict | None = None,
             timeout_seconds: float = 30) -> dict:
        """Stable HTTP escape hatch; policy decisions remain server-side."""
        if not path.startswith("/v1/"):
            raise ValueError("only v1 service endpoints are supported")
        return self._request(method, path, canonical(body) if body is not None else None,
                             {"Content-Type": "application/json"}, timeout_seconds)

    def memory_record(self, body: dict) -> dict:
        return self.call("POST", "/v1/memory", body)

    def memory_search(self, body: dict) -> dict:
        return self.call("POST", "/v1/memory/search", body)

    def memory_get(self, identity: str, actor_id: str) -> dict:
        return self.call("GET", f"/v1/memory/{quote(identity, safe=':')}?actor_id={quote(actor_id)}")

    def memory_trace(self, identity: str, actor_id: str) -> dict:
        return self.call("GET", f"/v1/memory/{quote(identity, safe=':')}/trace?actor_id={quote(actor_id)}")

    def acquire_lease(self, body: dict) -> dict:
        return self.call("POST", "/v1/leases/acquire", body)

    def authorization_request(self, body: dict) -> dict:
        return self.call("POST", "/v1/authorize", body)

    def open_panel(self, panel_id: str, body: dict) -> dict:
        request = Request(self.base_url + "/v1/panels/" + quote(panel_id, safe="") + "/open",
                          data=canonical(body), method="POST",
                          headers={"Authorization": "Bearer " + self.token,
                                   "Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=30) as response:
                return {"bytes_base64": base64.b64encode(response.read()).decode(),
                        "exposure_event": response.headers["X-Exposure-Event"]}
        except HTTPError as exc:
            raise RuntimeError(f"Kammi HTTP {exc.code}: {exc.read().decode()}") from exc

    def register_file(self, source: Path, kind: str, actor: str, request_id: str) -> dict:
        data = source.read_bytes()
        return self._request(
            "POST", "/v1/artifacts", data,
            {"X-Kind": kind, "X-Actor": actor, "X-Request-ID": request_id},
        )

    def import_local_file(self, source: Path, *, expected_sha256: str,
                          expected_bytes: int, kind: str, actor: str,
                          request_id: str) -> dict:
        return self.call("POST", "/v1/artifacts/import-local", {
            "path": str(source.resolve(strict=True)),
            "expected_sha256": expected_sha256,
            "expected_bytes": expected_bytes,
            "kind": kind, "actor": actor, "request_id": request_id,
        }, timeout_seconds=3600)

    def create_run(self, run_id: str, lab: str, actor: str, request_id: str) -> dict:
        body = {"run_id": run_id, "lab": lab, "actor": actor, "request_id": request_id}
        return self._request("POST", "/v1/runs", canonical(body),
                             {"Content-Type": "application/json"})

    def create_seal(
        self, members: list[str], parents: list[str], actor: str, request_id: str
    ) -> dict:
        body = {
            "direct_members": members, "parents": parents,
            "actor": actor, "request_id": request_id,
        }
        return self._request("POST", "/v1/seals", canonical(body),
                             {"Content-Type": "application/json"})

    def lineage(self, root: str) -> dict:
        return self._request("GET", f"/v1/seals/{quote(root, safe=':')}/lineage")

    def history(self, run_id: str) -> dict:
        return self._request("GET", f"/v1/runs/{quote(run_id, safe='')}/history")

    def history_summary(self, run_id: str) -> dict:
        return self._request("GET", f"/v1/runs/{quote(run_id, safe='')}/history/summary")

