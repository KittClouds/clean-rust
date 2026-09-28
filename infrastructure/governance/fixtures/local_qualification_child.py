"""CPU-only, deterministic child for qualifying Ledger local supervision."""
from pathlib import Path
import sys


root = Path(sys.argv[1])
root.mkdir(parents=True, exist_ok=False)
with (root / "large-output.bin").open("xb") as stream:
    block = b"KAMMI-LOCAL-QUALIFICATION-v1\n" * 1024
    for _ in range(640):
        stream.write(block)
