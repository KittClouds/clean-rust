"""Seal the experiment (create-only) and verify the seal in a fresh process.

``python seal.py``        writes SEALED.json : sha256 of every artifact + the final disposition
``python seal.py --verify`` re-hashes every sealed artifact and writes SEAL-VERIFIED.json
"""
import sys

from common import OUT, P6A_SEAL_SHA, RELEASE_IDENTITY, P6B, read, receipt, sha

SKIP = ('__pycache__', 'SEALED.json', 'SEAL-VERIFIED.json', '.pytest_cache')


def artifacts():
    files = {}
    for p in sorted(OUT.rglob('*')):
        if p.is_file() and not any(s in p.parts or p.name == s for s in SKIP) and p.suffix != '.pyc':
            files[p.relative_to(OUT).as_posix()] = sha(p)
    return files


def seal():
    disp = read(OUT / 'DISPOSITION.json')
    files = artifacts()
    receipt(OUT / 'SEALED.json', {
        'status': 'SEALED', 'experiment': 'claudia-partitioned-pl', 'disposition': disp['finding'],
        'evaluation_opened': False, 'protected_opened': False, 'BANK_v3_core_release_identity': RELEASE_IDENTITY,
        'upstream': {'phase6a_seal_v02_sha256': P6A_SEAL_SHA, 'phase6b_seal_sha256': sha(P6B / 'PHASE6B-SEALED.json')},
        'artifact_count': len(files), 'artifacts': files})
    print('SEALED', len(files))


def verify():
    s = read(OUT / 'SEALED.json')
    bad = [k for k, v in s['artifacts'].items() if sha(OUT / k) != v]
    extra = sorted(set(artifacts()) - set(s['artifacts']))
    if bad or extra:
        raise ValueError(f'seal drift: changed={bad[:5]} extra={extra[:5]}')
    receipt(OUT / 'SEAL-VERIFIED.json', {'status': 'PASS', 'seal_sha256': sha(OUT / 'SEALED.json'),
                                                  'artifacts_verified': len(s['artifacts']), 'evaluation_opened': False})
    print('SEAL_VERIFIED', len(s['artifacts']))


if __name__ == '__main__':
    verify() if '--verify' in sys.argv else seal()
