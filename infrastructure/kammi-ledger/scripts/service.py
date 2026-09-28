"""Start the qualified local service without exposing credentials in argv."""
import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

from ledgerd.client import KammiClient

HERE = Path(__file__).resolve().parents[1]
SERVICE = HERE / ".kammi-dev/operational"


def client(port):
    return KammiClient(f"http://127.0.0.1:{port}", (SERVICE / "admin.secret").read_text().strip())


def start(port=8765):
    SERVICE.mkdir(parents=True, exist_ok=True)
    for name, raw in (("admin.secret", secrets.token_urlsafe(48).encode()), ("signing.secret", os.urandom(32))):
        path = SERVICE / name
        if not path.exists():
            with path.open("xb") as stream:
                stream.write(raw)
            path.chmod(0o600)
    try:
        state = client(port).status()
        return {"state": "ALREADY_RUNNING", "url": f"http://127.0.0.1:{port}", "status": state}
    except Exception:
        pass
    env = {k: v for k, v in os.environ.items() if not k.startswith("KAMMI_FAULT")
           and k not in {"KAMMI_ACCEPTANCE_MODE", "KAMMI_ACCEPTANCE_FAULTS", "KAMMI_TOKEN"}}
    env.update(KAMMI_ROOT=str(SERVICE / "store"), KAMMI_PORT=str(port),
               KAMMI_TOKEN_FILE=str(SERVICE / "admin.secret"), KAMMI_SIGNING_KEY_FILE=str(SERVICE / "signing.secret"),
               KAMMI_EMBEDDING_CACHE=str(HERE / "vendor/runtime-v1/embedding-cache"))
    log = (SERVICE / "daemon.log").open("a")
    flags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS if os.name == "nt" else 0
    process = subprocess.Popen([sys.executable, "-m", "ledgerd.api"], cwd=HERE, env=env,
        stdin=subprocess.DEVNULL, stdout=log, stderr=log, creationflags=flags,
        start_new_session=os.name != "nt")
    log.close()
    (SERVICE / "launch.json").write_text(json.dumps({"pid_diagnostic_only": process.pid,
        "port": port, "python": sys.executable, "root": str(SERVICE / "store")}))
    for _ in range(600):
        if process.poll() is not None:
            raise RuntimeError("daemon startup failed; inspect operational/daemon.log")
        try:
            state = client(port).status()
            if state["flight_gate"] != "OPEN":
                raise RuntimeError("daemon is running but acceptance gate is closed")
            return {"state": "RUNNING", "url": f"http://127.0.0.1:{port}", "status": state,
                    "credential_file": str(SERVICE / "admin.secret")}
        except (ConnectionError, OSError):
            time.sleep(.05)
    raise RuntimeError("daemon readiness timeout")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("start", "status"))
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    print(json.dumps(start(args.port) if args.operation == "start" else client(args.port).status(), indent=2))
