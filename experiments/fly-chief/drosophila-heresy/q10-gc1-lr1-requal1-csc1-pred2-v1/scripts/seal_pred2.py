"""Freeze a new derived audit; never overwrite an existing seal or result."""
import ast
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
PARENT = ROOT.parent / 'q10-gc1-lr1-requal1-csc1-pred1-v1'


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest().upper()


def write_new(path, obj):
    with path.open('x', encoding='utf-8', newline='\n') as out:
        out.write(json.dumps(obj, indent=2, sort_keys=True) + '\n')


def main():
    assert os.environ.get('PYTHONDONTWRITEBYTECODE') == '1'
    for name in ('CONTRACT.json', 'PREEXECUTION.json', 'REPORT.json', 'source-records.jsonl'):
        assert not (ROOT / name).exists(), f'existing artifact: {name}'
    assert not list(ROOT.rglob('__pycache__')), 'unexpected bytecode tree'
    assert (ROOT / 'scripts/audit_pred2.py').is_file()
    assert json.loads((PARENT / 'REPORT.json').read_text())['status'] == 'CSC1_PRED1_COMPLETE'
    parent = json.loads((PARENT / 'CONTRACT.json').read_text())
    files = {}
    for entry in parent['parent_bindings']:
        path = REPO / entry['path']
        assert path.stat().st_size == entry['bytes'] and sha(path) == entry['sha256'], str(path)
        files[entry['path']] = entry
    for path in [PARENT / name for name in ('CONTRACT.json', 'PREEXECUTION.json', 'REPORT.json')]:
        rel = path.relative_to(REPO).as_posix()
        files[rel] = dict(path=rel, bytes=path.stat().st_size, sha256=sha(path))
    initial = sorted(p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*') if p.is_file())
    for rel in initial:
        path = ROOT / rel
        if path.suffix == '.py':
            ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        key = path.relative_to(REPO).as_posix()
        files[key] = dict(path=key, bytes=path.stat().st_size, sha256=sha(path))
    contract = dict(
        identity=ROOT.name, protocol='Q10-CSC1-PRED2', status='SEALED_PREMEASUREMENT',
        parent_bindings=[files[k] for k in sorted(files)],
        baseline_files=initial, initial_files=initial,
        write_allowlist=['REPORT.json', 'source-records.jsonl'],
        allowed_files=sorted(initial + ['CONTRACT.json', 'PREEXECUTION.json', 'REPORT.json', 'source-records.jsonl']),
        execution_environment={'PYTHONDONTWRITEBYTECODE': '1', 'python_flag': '-B'},
        replay_performed=False, scientific_promotion=False,
        analysis_scope='retrospective difficulty stratification of PRED1 observed geometry-screened pools',
    )
    write_new(ROOT / 'CONTRACT.json', contract)
    write_new(ROOT / 'PREEXECUTION.json', dict(
        identity=ROOT.name, contract_sha256=sha(ROOT / 'CONTRACT.json'),
        status='PREEXECUTION_SEALED', observed_pred2_outcomes=False,
        bound_input_count=len(files),
    ))
    print(json.dumps({'status': 'SEALED_PREMEASUREMENT', 'bindings': len(files)}))


if __name__ == '__main__':
    main()
