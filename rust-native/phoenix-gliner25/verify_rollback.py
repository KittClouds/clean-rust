"""Warm the preserved producer and shut it down; no workspace or graph writes."""
import json
from pathlib import Path
import subprocess
import sys

bridge, ner, nli, output = map(Path, sys.argv[1:])
with output.with_suffix(".stderr.log").open("wb") as stderr:
    result = subprocess.run([str(bridge), "serve", str(ner), str(nli)],
                            input=b"SHUTDOWN\n", stdout=subprocess.PIPE, stderr=stderr,
                            timeout=180, creationflags=subprocess.CREATE_NO_WINDOW)
lines = result.stdout.decode().splitlines()
controls = [s.removeprefix("PHOENIX_CONTROL\t") for s in lines if s.startswith("PHOENIX_CONTROL\t")]
receipt = dict(exit_code=result.returncode, replies=lines,
               passed=result.returncode == 0 and any(s.startswith("READY\t") for s in controls) and "BYE" in controls)
output.write_text(json.dumps(receipt, indent=2))
print(json.dumps(receipt))
assert receipt["passed"], "Preserved producer failed its warm/shutdown smoke"
