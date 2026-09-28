"""Independent read-only hash and write-surface final check."""
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
repo = root.parents[2]


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest().upper()


contract = json.loads((root / 'CONTRACT.json').read_text())
pre = json.loads((root / 'PREEXECUTION.json').read_text())
assert pre['contract_sha256'] == sha(root / 'CONTRACT.json')
for binding in contract['parent_bindings']:
    path = repo / binding['path']
    assert path.stat().st_size == binding['bytes']
    assert sha(path) == binding['sha256'], binding['path']
actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
assert actual == set(contract['allowed_files']), sorted(actual ^ set(contract['allowed_files']))
assert not list(root.rglob('__pycache__'))
report = json.loads((root / 'REPORT.json').read_text())
count = 0
with (root / 'source-records.jsonl').open(encoding='utf-8') as stream:
    for line in stream:
        if line.strip():
            json.loads(line)
            count += 1
print(json.dumps({'input_bindings_verified': len(contract['parent_bindings']),
                  'unexpected_files': [], 'source_records': count,
                  'report_status': report.get('status'),
                  'report_sha256': sha(root / 'REPORT.json')}, indent=2))
