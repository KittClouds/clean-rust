"""Structural JSON diff: prints the paths where two documents differ (first 40)."""
import json
import sys

def walk(a, b, path, out):
    if type(a) != type(b) and not (isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and not isinstance(b, bool)):
        out.append(f"{path}: {type(a).__name__} {str(a)[:120]} != {type(b).__name__} {str(b)[:120]}")
    elif isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                out.append(f"{path}/{k}: only in {'rust' if k not in a else 'python'}")
            else:
                walk(a[k], b[k], f"{path}/{k}", out)
    elif isinstance(a, list):
        if len(a) != len(b):
            out.append(f"{path}: list length {len(a)} != {len(b)}")
        for i, (x, y) in enumerate(zip(a, b)):
            walk(x, y, f"{path}[{i}]", out)
    elif a != b:
        out.append(f"{path}: {str(a)[:120]} != {str(b)[:120]}")

python = json.load(open(sys.argv[1], encoding="utf-8"))
rust = json.load(open(sys.argv[2], encoding="utf-8"))
out = []
walk(python, rust, "", out)
for line in out[:40]:
    print(line)
print(f"{len(out)} differences; sections: {len(python)} python, {len(rust)} rust")
sys.exit(1 if out else 0)
