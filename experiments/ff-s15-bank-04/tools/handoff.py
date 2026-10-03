"""Register concise closeout evidence and preserve failed construction history."""
import json
import pathlib
import sys
import urllib.request
REPO = pathlib.Path('C:/code land/clean-rust')
ROOT = pathlib.Path('C:/phoenix-data/banks/BANK-v4-20261003-v01')
sys.path.insert(0, str(ROOT/'factory'))
from common import digest, encode, sha, write, read


def run():
    token = (REPO/'program-infrastructure/kammi-ledger/.kammi-dev/operational/admin.secret').read_text().strip()
    def call(route, body):
        request = urllib.request.Request('http://127.0.0.1:8765'+route, data=encode(body),
                                         headers={'Authorization': 'Bearer '+token, 'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.loads(response.read())
    source = REPO/'experiments/ff-s15-bank-04'
    paths = [source/'REPORT.md', source/'tools/closeout.py', source/'tools/handoff.py', source/'.gitignore',
             ROOT/'INDEPENDENT-SPLIT-AUDIT.json', ROOT/'LIBRARY-RECEIPT.json']
    for i in range(1, 7):
        paths.append(ROOT.parent/f'BANK-v4-smoke-20261003-v{i:02d}'/'BUILD.json')
    paths.extend([ROOT.parent/f'BANK-v4-smoke-20261003-v{i:02d}'/'REPLAY.json' for i in (5, 6)])
    history = {'schema': 'BANK_V4_CONSTRUCTION_HISTORY_V1',
               'failed_attempt': {'path': str(ROOT.parent/'BANK-v4-smoke-20261003-v03/BUILD.json'),
                                  'failure': 'CLAUSE_DOMAIN overly strict Sudoku signed comparison verifier',
                                  'excluded_families': 6, 'production_replacement': False},
               'attempts': [{'path': str(p), 'sha256': sha(p)} for p in paths if 'smoke-' in str(p)],
               'active_bank_parent': read(ROOT/'LIBRARY-RECEIPT.json')['seal']['root'],
               'model_contact': False}
    write(ROOT/'CONSTRUCTION-HISTORY.json', history)
    paths.append(ROOT/'CONSTRUCTION-HISTORY.json')
    receipts = []
    for path in paths:
        identity = sha(path)
        receipt = call('/v1/artifacts/import-local', {'path': str(path), 'expected_sha256': 'sha256:'+identity,
                       'expected_bytes': path.stat().st_size, 'kind': 'bank-v4-closeout-evidence',
                       'actor': 'chief-kammi', 'request_id': 'bank-v4-closeout-'+identity[:40]})
        receipts.append({'path': str(path), **receipt})
    seal = call('/v1/seals', {'direct_members': sorted({r['artifact_id'] for r in receipts}),
                             'parents': [history['active_bank_parent']], 'actor': 'chief-kammi',
                             'request_id': 'bank-v4-closeout-seal-'+digest(receipts)[:32]})
    handoff = {'schema': 'BANK_V4_HANDOFF_V1', 'root': str(ROOT),
               'qualified_corpus_seal': history['active_bank_parent'], 'closeout_seal': seal['root'],
               'workspace': 'bank-v4-20261003-v01', 'chief_owner': 'chief-kammi',
               'report': str(source/'REPORT.md'), 'counts': read(ROOT/'BUILD.json')['counts'],
               'artifact_receipts': receipts, 'model_contact': False,
               'scientific_confirmation': False}
    write(ROOT/'HANDOFF.json', handoff)
    # Source-only pointer stays lightweight and contains no samples or labels.
    write(source/'DATA-LOCATIONS.json', {k: handoff[k] for k in ('schema', 'root', 'qualified_corpus_seal',
           'closeout_seal', 'workspace', 'chief_owner', 'counts', 'model_contact', 'scientific_confirmation')})
    print(json.dumps({'closeout_seal': seal['root'], 'evidence_files': len(receipts)}, indent=2))


if __name__ == '__main__':
    run()
