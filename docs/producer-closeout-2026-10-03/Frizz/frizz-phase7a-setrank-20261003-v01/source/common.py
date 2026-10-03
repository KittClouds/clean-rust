"""Frizz Phase 7A (SetRank vs matched pointwise control): paths, hashing, create-only receipts."""
import os
os.environ.setdefault('CUBLAS_WORKSPACE_CONFIG', ':4096:8')
import hashlib
import json
from pathlib import Path

SOURCE = Path(__file__).resolve().parent
# Rehearsal only: P7A_SMOKE_OUT redirects every output; real runs never set it.
OUT = Path(os.environ['P7A_SMOKE_OUT']) if os.environ.get('P7A_SMOKE_OUT') else SOURCE.parent
ROOT = Path('C:/phoenix-target-overgraph')
P6A = ROOT / 'frizz-phase6a-comparison-20261002-v01'
P6B = ROOT / 'frizz-phase6b-relations-20261002-v01'
BRIDGE = ROOT / 'frizz-qwen-v3-bridge-20261002-v02'
BANK = ROOT / 'bank-v3-core-20261002-v04'

RELEASE_IDENTITY = '84f0a7e13032e8cdfcecc862217bb33ca23568fade64fafeef410327eb996f12'
HANDOFF_SHA = '08cab38d366d6a30d32af4b0391cafddb243a8ea9e6a7435ad53290462d41a4b'
P6A_SEAL_SHA = '84b91d45a4f46da122a5b2dae22384b7d2fb07d0fd39cf3c07fba556172db0a8'

ACTION_TYPES = ['MOVE', 'TAKE', 'DROP', 'ACTIVATE', 'DEACTIVATE', 'OPEN', 'CLOSE', 'WAIT', 'TRANSFER']
BANDS = [('1-28', 1, 28), ('29-64', 29, 64), ('65-128', 65, 128), ('129-171', 129, 171)]
MAX_N = 171
RELIABLE_ROOTS = 200


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def receipt(path, value):
    """Create-only: an existing receipt is never overwritten."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, allow_nan=False, default=_json_default)
        stream.write('\n')


def _json_default(x):
    if hasattr(x, 'item'):
        return x.item()
    if hasattr(x, 'tolist'):
        return x.tolist()
    raise TypeError(type(x))
