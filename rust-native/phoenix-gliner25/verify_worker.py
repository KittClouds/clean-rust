"""Real framed-worker parity and protocol-failure smoke; no graph publication."""
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import time

bundle_path, cases_path, reference_path, output_path = map(Path, sys.argv[1:])
bundle = json.loads(bundle_path.read_text())
env = dict(os.environ, ORT_DYLIB_PATH=bundle["ort"]["path"], GLINER2_DEVICE="cpu", GLINER2_PRECISION="fp32")
rows = []
start = time.perf_counter()
with output_path.with_suffix(".stderr.log").open("wb") as stderr:
    p = subprocess.Popen([bundle["worker"]["path"], "serve", str(bundle_path)],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr,
                         env=env, creationflags=subprocess.CREATE_NO_WINDOW)
    def read_exact(size):
        value = p.stdout.read(size)
        if len(value) != size:
            raise RuntimeError(f"Truncated reply ({len(value)}/{size}); exit {p.poll()}")
        return value
    def receive():
        size, = struct.unpack("<I", read_exact(4))
        assert 0 < size <= 4 * 1024 * 1024
        return json.loads(read_exact(size))
    def send(request):
        body = json.dumps(request).encode()
        p.stdin.write(struct.pack("<I", len(body)) + body)
        p.stdin.flush()
    try:
        ready = receive()
        assert ready["Ready"]["contract"] == "phoenix.gliner25/v1"
        load_ms = (time.perf_counter() - start) * 1000
        reference = {r["name"]: r["entities"] for r in json.loads(reference_path.read_text())}
        for sequence, case in enumerate(json.loads(cases_path.read_text()), 1):
            send(dict(sequence=sequence, text=case["text"], labels=case["entities"]))
            reply = receive()["Completed"]
            assert reply["sequence"] == sequence
            actual = sorted((s["start"], s["end"], s["label"], s["text"]) for s in reply["spans"])
            expected = sorted((s["start"], s["end"], s["label"], s["text"]) for s in reference[case["name"]])
            valid = all(case["text"].encode()[s["start"]:s["end"]].decode() == s["text"] for s in reply["spans"])
            rows.append(dict(name=case["name"], exact=actual == expected, valid=valid,
                             inference_micros=reply["inference_micros"], actual=actual, expected=expected))
        # Same sequence must terminate rather than return a stale success.
        send(dict(sequence=sequence, text="Stale request.", labels=["person"]))
        p.stdin.close()
        code = p.wait(timeout=10)
        assert code != 0, "stale request accepted"
    finally:
        if p.poll() is None:
            p.kill()
            p.wait(timeout=10)
result = dict(load_ms=load_ms, rows=rows, stale_sequence_rejected=True,
              all_passed=all(r["exact"] and r["valid"] for r in rows))
output_path.write_text(json.dumps(result, indent=2))
print(json.dumps({k:v for k,v in result.items() if k != "rows"}))
assert result["all_passed"], "worker parity failed; inspect receipt"
