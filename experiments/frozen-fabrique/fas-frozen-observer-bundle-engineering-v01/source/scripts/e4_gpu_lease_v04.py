"""E4-0 v09 WDDM-aware lease primitives; runtime/CUDA work stays lazy until use."""

import csv
import importlib.metadata
import platform
import shlex
import subprocess
import sys
import time
from contextlib import AbstractContextManager
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Sequence

from e4_runner_common_v05 import *  # noqa: F401,F403

def verify_runtime_metadata_only(abi: Mapping[str, Any]) -> dict[str, str]:
    expected = abi.get("runtime_versions")
    if not isinstance(expected, dict):
        raise E4RunnerError("representation ABI does not bind runtime versions")
    observed = {"python": platform.python_version()}
    for package in ("transformers", "tokenizers", "huggingface_hub", "safetensors", "numpy"):
        observed[package] = importlib.metadata.version(package)
    for key, value in observed.items():
        if expected.get(key) != value:
            raise E4RunnerError(f"tokenizer runtime mismatch for {key}: {value} != {expected.get(key)}")
    return observed


def verify_online_runtime(abi: Mapping[str, Any]) -> tuple[Any, Any, Any, dict[str, str]]:
    expected = abi.get("runtime_versions")
    if not isinstance(expected, dict):
        raise E4RunnerError("representation ABI does not bind runtime versions")
    observed = {"python": platform.python_version()}
    for package in ("torch", "transformers", "tokenizers", "huggingface_hub", "safetensors", "numpy"):
        observed[package] = importlib.metadata.version(package)
    for key, value in observed.items():
        if expected.get(key) != value:
            raise E4RunnerError(f"online runtime mismatch for {key}: {value} != {expected.get(key)}")
    import numpy as np
    import torch
    import transformers

    if torch.version.cuda != expected.get("cuda_runtime"):
        raise E4RunnerError("loaded PyTorch CUDA runtime differs from the ABI")
    if not torch.cuda.is_available() or torch.cuda.device_count() < 1:
        raise E4RunnerError("frozen CUDA device 0 is unavailable")
    device_name = torch.cuda.get_device_name(0)
    if device_name != expected.get("expected_device_0"):
        raise E4RunnerError("visible CUDA device identity differs from the ABI")
    observed["cuda_runtime"] = torch.version.cuda
    observed["expected_device_0"] = device_name
    return np, torch, transformers, observed


def verify_local_assets(authorization: Mapping[str, Any], abi: Mapping[str, Any]) -> tuple[Path, Path]:
    paths = authorization.get("paths", {})
    model_root = Path(paths.get("model_snapshot", "")).resolve(strict=True)
    tokenizer_root = Path(paths.get("tokenizer_snapshot", "")).resolve(strict=True)
    model_manifest_path = Path(paths.get("model_asset_manifest", "")).resolve(strict=True)
    tokenizer_manifest_path = Path(paths.get("tokenizer_asset_manifest", "")).resolve(strict=True)
    model_manifest_sha, _ = sha256_file(model_manifest_path)
    if model_manifest_sha != abi.get("model_asset_manifest_sha256"):
        raise E4RunnerError("local model asset manifest hash differs from the ABI")
    model_manifest = read_json(model_manifest_path)
    if model_manifest.get("resolved_revision") != abi.get("model_revision"):
        raise E4RunnerError("local model snapshot revision differs from the ABI")
    for filename, key in (("config.json", "model_config_sha256"), ("model.safetensors", "model_weights_sha256")):
        digest, _ = sha256_file(model_root / filename)
        if digest != abi.get(key):
            raise E4RunnerError(f"pinned model asset hash mismatch: {filename}")
    verify_local_tokenizer_assets(tokenizer_root, tokenizer_manifest_path, abi)
    return model_root, tokenizer_root


def verify_abi_contract_identity(contract: Mapping[str, Any], abi_entry: Mapping[str, Any], abi: Mapping[str, Any]) -> None:
    pin = contract.get("representation_abi", {})
    if pin.get("abi_sha256") != abi_entry.get("sha256"):
        raise E4RunnerError("representation ABI hash differs from the sealed E4-0 contract")
    if pin.get("surface_id") != "V1_FINAL_POSITION" or pin.get("feature_dimension") != DIMENSION:
        raise E4RunnerError("E4-0 contract representation surface differs from the frozen E2 ABI")
    if abi.get("model_revision") != "7453bca97ca1e67754c4035a4b4c584e1c9dd725":
        raise E4RunnerError("representation ABI model revision differs from E2 v07")
    if abi.get("model_config_sha256") != "15d6157fb6df3f8272e2fe90e18f57727ccf02a125c94469198b0f3281510185":
        raise E4RunnerError("representation ABI model config differs from E2 v07")
    if abi.get("model_weights_sha256") != "7678ab9546a0c51c1fca161876b1efc4f0906277f170b5822045f40fdaf9eeff":
        raise E4RunnerError("representation ABI model weights differ from E2 v07")
    serving = abi.get("loader", {})
    tokenize = abi.get("tokenization", {})
    if serving.get("device") != "cuda:0" or serving.get("model_dtype") != "float32":
        raise E4RunnerError("E2 v07 device/dtype ABI changed")
    if tokenize.get("batch_size") != 1 or tokenize.get("padding") is not False or tokenize.get("truncation") is not False:
        raise E4RunnerError("E2 v07 tokenization ABI changed")


def verify_local_tokenizer_assets(tokenizer_root: Path, tokenizer_manifest_path: Path, abi: Mapping[str, Any]) -> dict[str, Any]:
    tokenizer_sha, _ = sha256_file(tokenizer_manifest_path)
    if tokenizer_sha != abi.get("tokenizer_assets_manifest_sha256"):
        raise E4RunnerError("local tokenizer asset manifest hash differs from the ABI")
    tokenizer_manifest = read_json(tokenizer_manifest_path)
    if tokenizer_manifest.get("resolved_commit") != abi.get("tokenizer_revision"):
        raise E4RunnerError("local tokenizer revision differs from the ABI")
    loaded = tokenizer_manifest.get("loaded_snapshot_files")
    if not isinstance(loaded, list) or not loaded:
        raise E4RunnerError("tokenizer manifest has no loaded file identities")
    for item in loaded:
        path = (tokenizer_root / item["path"]).resolve(strict=True)
        path.relative_to(tokenizer_root)
        digest, size = sha256_file(path)
        if digest != item["sha256"] or size != item["bytes"]:
            raise E4RunnerError(f"pinned tokenizer file changed: {item['path']}")
    return tokenizer_manifest


def powershell_json(script: str) -> Any:
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    payload = completed.stdout.strip()
    return json.loads(payload) if payload else None


def windows_process_identity(pid: int) -> dict[str, Any] | None:
    if not isinstance(pid, int) or pid <= 0:
        raise E4RunnerError("GPU process listing returned an invalid PID")
    value = powershell_json(
        f"$p = Get-CimInstance Win32_Process -Filter 'ProcessId = {pid}'; "
        "if ($null -eq $p) { 'null' } else { "
        "$p | Select-Object ProcessId,ExecutablePath,CommandLine | ConvertTo-Json -Compress }"
    )
    if value is None:
        return None
    if not isinstance(value, dict):
        raise E4RunnerError(f"cannot verify exact process identity for PID {pid}")
    command = value.get("CommandLine")
    script_path = extract_script_path(command if isinstance(command, str) else "")
    return {
        "pid": int(value.get("ProcessId", pid)),
        "executable": value.get("ExecutablePath"),
        "command_line": command,
        "script": script_path,
    }


def extract_script_path(command_line: str) -> str | None:
    try:
        parts = shlex.split(command_line, posix=False)
    except ValueError:
        parts = command_line.split()
    for item in parts:
        candidate = item.strip('"')
        if candidate.lower().endswith((".py", ".ps1", ".exe", ".bat", ".cmd")):
            return candidate
    return None


def query_cuda0_compute_processes() -> list[dict[str, Any]]:
    completed = subprocess.run(
        ["nvidia-smi", "pmon", "-i", "0", "-c", "1"],
        check=True, capture_output=True, text=True, timeout=20,
    )
    return classify_pmon_processes(completed.stdout)


def classify_pmon_processes(snapshot: str) -> list[dict[str, Any]]:
    """Preserve pmon rows; only Type C blocks the compute lease."""
    result: list[dict[str, Any]] = []
    for raw_line in snapshot.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "no running processes" in line.lower():
            continue
        fields = line.split()
        if len(fields) < 4:
            raise E4RunnerError("nvidia-smi pmon returned an unexpected process row")
        try:
            gpu_index, pid = int(fields[0]), int(fields[1])
        except ValueError as exc:
            raise E4RunnerError("nvidia-smi pmon returned a nonnumeric GPU/PID field") from exc
        process_type = fields[2]
        if gpu_index != 0 or pid <= 0:
            raise E4RunnerError("nvidia-smi pmon returned an invalid CUDA:0 process identity")
        if process_type not in {"C", "C+G", "G"}:
            raise E4RunnerError(f"CUDA:0 PID {pid} has an unsupported pmon process type: {process_type}")
        if process_type in {"C+G", "G"}:
            result.append({
                "pid": pid, "nvidia_smi_process_type": process_type,
                "nvidia_smi_pmon_metrics": fields[3:9],
                "nvidia_smi_pmon_command": " ".join(fields[9:]),
                "nvidia_smi_pmon_raw_line": raw_line,
                "lease_blocking": False,
                "classification": "GRAPHICS_OR_MIXED_WDDM_CLIENT_DIAGNOSTIC_ONLY",
            })
            continue
        identity = windows_process_identity(pid)
        if identity is None:
            raise E4RunnerError(f"CUDA:0 Type-C process PID {pid} disappeared before exact identity verification")
        if not identity.get("executable") or not identity.get("script"):
            raise E4RunnerError(f"CUDA:0 Type-C process PID {pid} lacks a verifiable executable/script identity")
        result.append({
            **identity,
            "nvidia_smi_process_type": process_type,
            "nvidia_smi_pmon_metrics": fields[3:9],
            "nvidia_smi_pmon_command": " ".join(fields[9:]),
            "nvidia_smi_pmon_raw_line": raw_line,
            "lease_blocking": True,
            "classification": "VERIFIED_TYPE_C_CUDA_COMPUTE_PROCESS",
        })
    return result


def query_cuda0_device_diagnostic() -> dict[str, Any]:
    completed = subprocess.run(
        ["nvidia-smi", "-i", "0", "--query-gpu=name,memory.used,memory.free,utilization.gpu", "--format=csv,noheader,nounits"],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    row = next(csv.reader([completed.stdout.strip()]), None)
    if row is None or len(row) != 4:
        raise E4RunnerError("nvidia-smi device diagnostic returned an unexpected row")
    return {
        "device_name": row[0].strip(),
        "memory_used_mib": int(row[1].strip().split()[0]),
        "memory_free_mib": int(row[2].strip().split()[0]),
        "gpu_utilization_percent": int(row[3].strip().split()[0]),
        "diagnostic_only": True,
        "total_gpu_memory_claimed": False,
    }


def query_process_peak_working_set(pid: int) -> int:
    value = powershell_json(f"(Get-Process -Id {int(pid)}).PeakWorkingSet64 | ConvertTo-Json -Compress")
    if not isinstance(value, (int, float)) or value < 0:
        raise E4RunnerError("could not read extractor process peak working set")
    return int(value)


class GpuLease(AbstractContextManager["GpuLease"]):
    """Exclusive CUDA:0 lease with exact process attribution and append-only release receipt."""

    def __init__(
        self,
        *,
        lock_path: Path,
        receipt_path: Path,
        experiment_id: str,
        authorization_sha256: str,
        authorized_interval: Mapping[str, str],
        expected_reserved_ceiling_bytes: int,
        quiet_window_seconds: int = 30,
        poll_interval_seconds: int = 5,
        process_snapshot: Callable[[], list[dict[str, Any]]] = query_cuda0_compute_processes,
        device_snapshot: Callable[[], dict[str, Any]] = query_cuda0_device_diagnostic,
        process_identity: Callable[[int], dict[str, Any] | None] = windows_process_identity,
        process_alive: Callable[[int], bool] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        utcnow: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.lock_path = lock_path
        self.receipt_path = receipt_path
        self.experiment_id = experiment_id
        self.authorization_sha256 = authorization_sha256
        self.authorized_interval = dict(authorized_interval)
        self.expected_reserved_ceiling_bytes = expected_reserved_ceiling_bytes
        self.quiet_window_seconds = quiet_window_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.process_snapshot = process_snapshot
        self.device_snapshot = device_snapshot
        self.process_identity = process_identity
        self.process_alive = process_alive or self._process_alive
        self.sleep = sleep
        self.monotonic = monotonic
        self.utcnow = utcnow
        self.wait_observations: list[dict[str, Any]] = []
        self._last_pmon_snapshot: list[dict[str, Any]] | None = None
        self.acquired = False
        self.owner_token = hashlib.sha256(os.urandom(32)).hexdigest()
        runner_script = Path(sys.argv[0]).resolve()
        self.owner = {
            "pid": os.getpid(),
            "executable": str(Path(sys.executable).resolve()),
            "script": str(runner_script),
            "command_line": [sys.executable, str(runner_script), *sys.argv[1:]],
        }
        self.acquired_utc: str | None = None

    @staticmethod
    def _process_alive(pid: int) -> bool:
        if os.name == "nt":
            return windows_process_identity(pid) is not None
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def _record_wait(self, reason: str, processes: Sequence[Mapping[str, Any]]) -> None:
        self.wait_observations.append({
            "observed_utc": self.utcnow().isoformat(),
            "reason": reason,
            "cuda0_compute_processes": [dict(item) for item in processes],
        })

    def _record_pmon_snapshot(self, processes: Sequence[Mapping[str, Any]]) -> None:
        current = [dict(item) for item in processes]
        if current != self._last_pmon_snapshot:
            self._record_wait("nvidia_smi_pmon_process_snapshot", current)
            self._last_pmon_snapshot = current

    def _read_active_lock(self) -> dict[str, Any] | None:
        try:
            return read_json(self.lock_path)
        except FileNotFoundError:
            return None

    def acquire(self) -> "GpuLease":
        empty_since: float | None = None
        while True:
            observed = self.process_snapshot()
            self._record_pmon_snapshot(observed)
            active = [item for item in observed
                      if item.get("lease_blocking", True) is not False
                      and int(item.get("pid", -1)) != os.getpid()]
            if active:
                empty_since = None
                self._record_wait("cuda0_compute_process_present", active)
                self.sleep(self.poll_interval_seconds)
                continue
            now_tick = self.monotonic()
            if empty_since is None:
                empty_since = now_tick
                self._record_wait("first_empty_cuda0_compute_snapshot", [])
                self.sleep(self.quiet_window_seconds)
                continue
            if now_tick - empty_since < self.quiet_window_seconds:
                self.sleep(min(self.poll_interval_seconds, self.quiet_window_seconds - (now_tick - empty_since)))
                continue
            self.lock_path.parent.mkdir(parents=True, exist_ok=True)
            lock_record = {
                "lease_id": "FAS_CUDA0_EXCLUSIVE_GPU_LEASE_V01",
                "status": "ACTIVE",
                "lease_token": self.owner_token,
                "experiment_id": self.experiment_id,
                "authorization_sha256": self.authorization_sha256,
                "owner": self.owner,
                "authorized_interval_utc": self.authorized_interval,
                "expected_extractor_process_pytorch_reserved_peak_ceiling_bytes": self.expected_reserved_ceiling_bytes,
                "acquired_utc": self.utcnow().isoformat(),
                "device": "cuda:0",
            }
            try:
                write_json_exclusive(self.lock_path, lock_record)
            except FileExistsError:
                active_record = self._read_active_lock()
                if active_record is None:
                    continue
                owner = active_record.get("owner", {})
                pid = owner.get("pid") if isinstance(owner, dict) else None
                if not isinstance(pid, int) or not self.process_alive(pid):
                    raise E4RunnerError("stale GPU lease found; preserved for manual audit, no lock takeover")
                exact_owner = self.process_identity(pid)
                if exact_owner is None or any(
                    os.path.normcase(str(exact_owner.get(key, "")))
                    != os.path.normcase(str(owner.get(key, "")))
                    for key in ("executable", "script")
                ):
                    raise E4RunnerError("active GPU lease PID/script identity differs; preserved without takeover")
                self._record_wait("exclusive_gpu_lease_held", [{"active_lease": active_record}])
                self.sleep(self.poll_interval_seconds)
                empty_since = None
                continue
            observed_after_lock = self.process_snapshot()
            self._record_pmon_snapshot(observed_after_lock)
            second_snapshot = [item for item in observed_after_lock
                               if item.get("lease_blocking", True) is not False
                               and int(item.get("pid", -1)) != os.getpid()]
            if second_snapshot:
                self._record_wait("cuda0_process_appeared_during_lease_acquisition", second_snapshot)
                self._remove_own_lock()
                empty_since = None
                continue
            self.acquired = True
            self.acquired_utc = lock_record["acquired_utc"]
            self.lock_record = lock_record
            return self

    def _remove_own_lock(self) -> None:
        try:
            record = read_json(self.lock_path)
        except FileNotFoundError:
            return
        if record.get("lease_token") != self.owner_token:
            raise E4RunnerError("GPU lease lock changed ownership before release")
        self.lock_path.unlink()

    def release(self, release_snapshot: Mapping[str, Any] | None, terminal_status: str) -> dict[str, Any]:
        if not self.acquired:
            raise E4RunnerError("cannot release a GPU lease that was not acquired")
        device = self.device_snapshot()
        receipt = {
            "receipt_id": "FAS_CUDA0_EXCLUSIVE_GPU_LEASE_RECEIPT_V01",
            "status": "RELEASED",
            "terminal_status": terminal_status,
            "experiment_id": self.experiment_id,
            "authorization_sha256": self.authorization_sha256,
            "device": "cuda:0",
            "owner": self.owner,
            "authorized_interval_utc": self.authorized_interval,
            "expected_extractor_process_pytorch_reserved_peak_ceiling_bytes": self.expected_reserved_ceiling_bytes,
            "acquired_utc": self.acquired_utc,
            "released_utc": self.utcnow().isoformat(),
            "wait_observations": self.wait_observations,
            "release_process_snapshot": release_snapshot,
            "device_wide_nvidia_smi_diagnostic": device,
            "total_gpu_memory_claimed": False,
        }
        write_json_exclusive(self.receipt_path, receipt)
        self._remove_own_lock()
        self.acquired = False
        return receipt

    def __enter__(self) -> "GpuLease":
        return self.acquire()

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        if self.acquired:
            status = "PASS" if exc is None else "STOPPED_PRESERVED"
            self.release({"release_reason": "context_exit_without_snapshot_provider"}, status)
        return False


def make_gpu_lease(authorization: Mapping[str, Any], mode: str, output_root: Path) -> GpuLease:
    settings = authorization.get("gpu_lease")
    if authorization.get("gpu_lease_required_before_model_contact") is not True:
        raise E4RunnerError("authorization does not require an exclusive GPU lease before model contact")
    interval = {
        "valid_from_utc_unix_seconds": authorization.get("valid_from_utc_unix_seconds"),
        "valid_until_utc_unix_seconds": authorization.get("valid_until_utc_unix_seconds"),
    }
    if not isinstance(settings, dict):
        raise E4RunnerError("authorization omits the CUDA:0 lease or authorized interval")
    ceiling = int(settings.get("expected_reserved_ceiling_bytes", -1))
    if ceiling != GPU_RESERVED_LIMIT_BYTES:
        raise E4RunnerError("GPU lease expected VRAM ceiling differs from the frozen 10 GiB allocator gate")
    lock_path = Path(settings.get("lock_path", ""))
    if not lock_path.is_absolute():
        raise E4RunnerError("GPU lease lock path must be absolute")
    quiet = int(settings.get("quiet_window_seconds", 0))
    poll = int(settings.get("poll_interval_seconds", 0))
    if quiet < 30 or poll < 1:
        raise E4RunnerError("GPU lease requires a 30-second quiet window and positive contention polling")
    output_path = Path(output_root)
    if not output_path.is_absolute():
        raise E4RunnerError("GPU lease output root must be the validated absolute stage directory")
    return GpuLease(
        lock_path=lock_path,
        receipt_path=output_path / "gpu-lease-release-receipt-v01.json",
        experiment_id="fas-frozen-observer-bundle-engineering-v01/E4-0",
        authorization_sha256=str(authorization["authorization_sha256"]),
        authorized_interval=interval,
        expected_reserved_ceiling_bytes=ceiling,
        quiet_window_seconds=quiet,
        poll_interval_seconds=poll,
    )


def gpu_allocator_snapshot(torch: Any, phase: str) -> dict[str, Any]:
    device = torch.device("cuda:0")
    torch.cuda.synchronize(device)
    return {
        "phase": phase,
        "process_id": os.getpid(),
        "allocated_current_bytes": int(torch.cuda.memory_allocated(device)),
        "reserved_current_bytes": int(torch.cuda.memory_reserved(device)),
        "allocated_peak_since_reset_bytes": int(torch.cuda.max_memory_allocated(device)),
        "reserved_peak_since_reset_bytes": int(torch.cuda.max_memory_reserved(device)),
        "scope": "this extractor process PyTorch CUDA caching allocator only",
        "total_gpu_memory_claimed": False,
    }


def allocator_is_zero(snapshot: Mapping[str, Any]) -> bool:
    return all(
        snapshot.get(key) == 0
        for key in ("allocated_current_bytes", "reserved_current_bytes", "allocated_peak_since_reset_bytes", "reserved_peak_since_reset_bytes")
    )


def verify_gpu_limits(snapshot: Mapping[str, Any], ram_peak_bytes: int) -> None:
    allocated_peak = int(snapshot["allocated_peak_since_reset_bytes"])
    reserved_peak = int(snapshot["reserved_peak_since_reset_bytes"])
    if allocated_peak > reserved_peak or reserved_peak > GPU_RESERVED_LIMIT_BYTES:
        raise E4RunnerError("extractor-process PyTorch allocator reserved peak exceeded the frozen 10 GiB gate")
    if ram_peak_bytes > HOST_RAM_LIMIT_BYTES:
        raise E4RunnerError("extractor process peak working set exceeded the frozen 25 GiB host RAM gate")


def feature_bytes(model: Any, tokenizer: Any, torch: Any, np: Any, text: str) -> tuple[bytes, int]:
    token_ids = tokenizer.encode(text, add_special_tokens=True, truncation=False)
    if not token_ids or len(token_ids) > 2048:
        raise E4RunnerError("tokenizer returned an invalid unpadded sequence length")
    input_ids = torch.tensor([token_ids], dtype=torch.long, device="cuda:0")
    attention_mask = torch.ones_like(input_ids)
    with torch.inference_mode():
        output = model(input_ids=input_ids, attention_mask=attention_mask, use_cache=False, return_dict=True)
    hidden = output.last_hidden_state
    if hidden.dtype != torch.float32 or tuple(hidden.shape) != (1, len(token_ids), DIMENSION):
        raise E4RunnerError("online hidden tensor differs from the sealed V1_FINAL_POSITION ABI")
    vector = hidden[0, len(token_ids) - 1, :].detach().contiguous().cpu().numpy()
    encoded = np.asarray(vector, dtype="<f4", order="C").tobytes(order="C")
    if len(encoded) != FEATURE_ROW_BYTES or not bool(np.isfinite(vector).all()):
        raise E4RunnerError("online feature vector is nonfinite or has an invalid serialized shape")
    return encoded, len(token_ids)
