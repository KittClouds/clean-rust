"""Reference oracle: the unmodified Python ledgerd.identity functions.

Usage: python jcs_oracle.py <path to kammi-ledger>
stdin:  one hex-encoded input per line
stdout: "OK <hex canonical bytes>" or "ERR <exception type>" per line

Run with PYTHONDONTWRITEBYTECODE=1 so nothing is written into the Python tree.
"""
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])

from ledgerd.identity import canonical, strict_json  # noqa: E402

out = sys.stdout
for line in sys.stdin.buffer:
    raw = bytes.fromhex(line.strip().decode("ascii"))
    try:
        out.write("OK " + canonical(strict_json(raw)).hex() + "\n")
    except Exception as exc:  # the oracle reports every refusal the same way
        out.write("ERR " + type(exc).__name__ + "\n")
out.flush()
