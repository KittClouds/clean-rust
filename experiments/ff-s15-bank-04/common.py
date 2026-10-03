"""Deterministic construction identities; no model dependencies."""
import hashlib
import json
import pathlib
import random

SOURCE=pathlib.Path(__file__).resolve().parent
OUT=pathlib.Path('C:/phoenix-data/banks/BANK-v4-20261003-v01')
NAMESPACE='BANK-v4-typed-seven-20261003-v01'
LANES=('planning','sokoban','sudoku','household','policy_tools','graph','api_binding')
BUDGET={'TRAIN':1024,'DEV':128,'TRANSFER':128}
SEEDS={s:hashlib.sha256((NAMESPACE+s).encode()).hexdigest() for s in BUDGET}

def encode(x):return json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def digest(x):return hashlib.sha256(encode(x)).hexdigest()
def sha(path):
    with pathlib.Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def rng(*parts):return random.Random(int(digest([NAMESPACE,*parts])[:16],16))
def write(path,x):
    p=pathlib.Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('xb') as f:f.write(encode(x)+b'\n')
def read(path):return json.loads(pathlib.Path(path).read_bytes())
