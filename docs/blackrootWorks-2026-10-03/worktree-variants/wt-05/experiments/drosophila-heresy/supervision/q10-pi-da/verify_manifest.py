"""Check a seal without trusting the protocol's own reviewer implementation."""
import argparse
import hashlib
import json
from pathlib import Path


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify(root, seal):
    root = root.resolve()
    entries = seal['source_manifest']
    seen = set()
    for item in entries:
        relative = item['path']
        assert relative not in seen, f'duplicate entry {relative}'
        seen.add(relative)
        path = (root / relative).resolve()
        assert path.is_relative_to(root), f'path escapes root: {relative}'
        assert digest(path) == item['sha256'].lower(), f'changed source: {relative}'
    executable = Path(seal['executable'])
    assert digest(executable) == seal['executable_sha256'].lower(), 'binary changed'
    for name, key in [('PLAN.md', 'plan_sha256'), ('CONTRACT.json', 'contract_sha256')]:
        if key in seal:
            assert digest(root / name) == seal[key].lower(), name
    return {'source_entries': len(seen), 'binary_matches': True}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    args = parser.parse_args()
    seal = json.loads((args.root / 'PREEXECUTION.json').read_text(encoding='utf-8'))
    print(json.dumps(verify(args.root, seal)))
