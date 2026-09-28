"""Infrastructure flight gate bound to immutable acceptance and current bytes."""
import hashlib
import importlib.metadata
import platform
import sys
import os
import base64
from pathlib import Path

from .identity import canonical, raw_id, strict_json

HERE = Path(__file__).resolve().parents[1]
GATES = (
    "artifact_tamper", "journal_tamper", "db_deletion_rebuild", "crash_recovery",
    "windows_durability_characterization", "backup_restore", "single_writer_fencing",
    "actor_authorization", "policy_engine", "exposure_enforcement", "resource_leases",
    "stale_fencing_rejection", "adapter_registry", "failure_history_queries",
    "contact_evidence_scope", "remote_execution", "remote_tamper_replay", "memory_plane",
    "fts_retrieval", "vector_retrieval", "graph_retrieval", "memory_custody_trace",
    "mcp_interface", "python_sdk", "rust_sdk", "e4_legacy_reconstruction", "cleanroom_replay",
    "phoenix_vault",
)


def architecture_identity():
    return raw_id(canonical([
        raw_id((HERE / "ARCHITECTURE-v1.md").read_bytes()),
        raw_id((HERE / "ARCHITECTURE-AMENDMENT-v2-PHOENIX-VAULT.md").read_bytes()),
    ]))


def source_manifest():
    files = []
    for directory, dirs, names in os.walk(HERE, followlinks=False):
        dirs[:] = [d for d in dirs if d not in {".venv", ".kammi-dev", "vendor", "__pycache__", "acceptance", "dist", "build"}
                   and not d.endswith(".egg-info")]
        for name in names:
            path = Path(directory) / name
            if not path.is_symlink() and path.suffix in {".py", ".rs", ".toml", ".lock", ".md", ".json", ".txt"}:
                files.append({"path": path.relative_to(HERE).as_posix(), "artifact_id": raw_id(path.read_bytes()),
                              "bytes": path.stat().st_size})
    manifest = {"schema": "KAMMI_SOURCE_MANIFEST_V1", "files": sorted(files, key=lambda f: f["path"])}
    return manifest, raw_id(canonical(manifest))


def runtime_identity():
    assets = strict_json((HERE / "runtime/ASSET-MANIFEST-v1.json").read_bytes())
    for entry in assets["files"]:
        path = HERE / "vendor/runtime-v1" / entry["path"]
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != entry["sha256"] or path.stat().st_size != entry["bytes"]:
            raise ValueError("runtime asset changed")
    expected = {entry["path"]: entry["sha256"] for entry in assets["files"]}
    actual_paths = {
        "native/lbug_shared.dll": Path(os.environ.get("KAMMI_LBUG_DLL", str(HERE / "vendor/runtime-v1/native/lbug_shared.dll"))),
        "native/libssl-3-x64.dll": Path(os.environ.get("KAMMI_OPENSSL_DLL_DIR", str(HERE / "vendor/runtime-v1/native"))) / "libssl-3-x64.dll",
        "native/libcrypto-3-x64.dll": Path(os.environ.get("KAMMI_OPENSSL_DLL_DIR", str(HERE / "vendor/runtime-v1/native"))) / "libcrypto-3-x64.dll",
    }
    for extension in ("fts", "vector"):
        rel = f"extensions/{extension}/lib{extension}.lbug_extension"
        actual_paths[rel] = Path(os.environ.get("KAMMI_EXTENSION_DIR", str(HERE / "vendor/runtime-v1/extensions"))) / extension / f"lib{extension}.lbug_extension"
    for rel, path in actual_paths.items():
        with path.open("rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() != expected[rel]:
                raise ValueError("configured native runtime differs from pinned assets")
    packages = {}
    package_records = []
    for line in (HERE / "runtime/requirements-lock-v1.txt").read_text().splitlines():
        name, version = line.split("==")
        installed = importlib.metadata.version(name)
        if installed != version:
            raise ValueError("runtime package version differs from qualification")
        packages[name] = installed
        distribution = importlib.metadata.distribution(name)
        for entry in distribution.files or []:
            if ".." in entry.parts or entry.name == "REQUESTED":
                # Installer-generated launcher shebangs contain the environment
                # location. Qualification uses python -m, not these launchers.
                continue
            if entry.hash is None or entry.hash.mode != "sha256":
                continue
            path = distribution.locate_file(entry)
            with path.open("rb") as source:
                actual = hashlib.file_digest(source, "sha256").digest()
            if base64.urlsafe_b64encode(actual).decode().rstrip("=") != entry.hash.value:
                raise ValueError("installed runtime package bytes changed")
            package_records.append({"distribution": name, "path": str(entry).replace("\\", "/"),
                                    "sha256": actual.hex()})
    with Path(sys._base_executable).open("rb") as source:
        executable = hashlib.file_digest(source, "sha256").hexdigest()
    payload = {"schema": "KAMMI_RUNTIME_IDENTITY_V1", "python": platform.python_version(),
               "platform": platform.system(), "machine": platform.machine(),
               "python_executable_sha256": executable, "packages": packages,
               "package_bytes_root": raw_id(canonical(sorted(package_records, key=lambda f: (f["distribution"], f["path"])))),
               "asset_manifest_id": raw_id(canonical(assets))}
    payload["database_backend"] = "capi"
    payload["projection_buffer_pool_bytes"] = 256 * 1024 * 1024
    payload["projection_threads"] = 2
    return payload, raw_id(canonical(payload))


class ReleaseOperations:
    def accept_library(self, acceptance: dict, request_id: str):
        if acceptance.get("schema") != "LibraryAcceptanceV1" or set(acceptance["gates"]) != set(GATES):
            raise ValueError("acceptance gate schema mismatch")
        if any(value != "PASS" for value in acceptance["gates"].values()):
            raise ValueError("all acceptance gates must pass")
        architecture = architecture_identity()
        _, source_root = source_manifest()
        _, runtime_root = runtime_identity()
        if acceptance["architecture_hash"] != architecture or acceptance["source_root"] != source_root or acceptance["runtime_identity"] != runtime_root:
            raise ValueError("acceptance does not bind current architecture/source/runtime")
        for field in ("acceptance_suite_root", "independent_verification_root"):
            if acceptance[field] not in self.artifacts or not self.cas.verify(acceptance[field]):
                raise ValueError("acceptance evidence is not registered and verified")
        suite = strict_json(self.cas.get(acceptance["acceptance_suite_root"]))
        audit = strict_json(self.cas.get(acceptance["independent_verification_root"]))
        for report, schema in ((suite, "KAMMI_ENDSTATE_ACCEPTANCE_V1"),
                               (audit, "KAMMI_ENDSTATE_INDEPENDENT_AUDIT_V1")):
            if (report.get("schema") != schema or report.get("status") != "PASS"
                    or report.get("source_root") != source_root
                    or report.get("runtime_identity") != runtime_root):
                raise ValueError("acceptance evidence schema/status/identity mismatch")
        if audit.get("acceptance_suite_root") != acceptance["acceptance_suite_root"]:
            raise ValueError("independent audit does not bind acceptance suite")
        if set(suite.get("gates", {})) != set(GATES):
            raise ValueError("suite does not demonstrate every gate")
        for gate, proof in suite["gates"].items():
            if proof.get("status") != "PASS" or not proof.get("evidence"):
                raise ValueError("gate lacks passing evidence: " + gate)
            for identity in proof["evidence"]:
                if identity not in self.artifacts or not self.cas.verify(identity):
                    raise ValueError("gate evidence is unavailable: " + gate)
        with self.lock:
            artifact, _ = self.register_bytes(canonical(acceptance), kind="library-acceptance",
                                              actor="library-auditor", request_id=request_id + ":artifact")
            event = self._emit("LibraryAccepted", {"acceptance_artifact": artifact,
                              "source_root": source_root, "runtime_identity": runtime_root},
                              "library-auditor", request_id + ":accepted")
            self._qualified_runtime = runtime_root
            return artifact, event

    def flight_state(self):
        if self.library_acceptance is None:
            return {"state": "CLOSED_PENDING_ACCEPTANCE", "acceptance_identity": None}
        try:
            acceptance = strict_json(self.cas.get(self.library_acceptance))
            _, current_source = source_manifest()
            # Recheck bytes at the authority boundary, including changes after
            # daemon startup. A cached identity is not a runtime integrity check.
            _, runtime = runtime_identity()
            if current_source != acceptance["source_root"] or runtime != acceptance["runtime_identity"]:
                return {"state": "CLOSED_PENDING_ACCEPTANCE", "acceptance_identity": self.library_acceptance,
                        "reason": "source_or_runtime_identity_changed"}
            return {"state": "OPEN", "acceptance_identity": self.library_acceptance}
        except (ValueError, KeyError, OSError):
            return {"state": "CLOSED_PENDING_ACCEPTANCE", "acceptance_identity": self.library_acceptance,
                    "reason": "acceptance_verification_failed"}
