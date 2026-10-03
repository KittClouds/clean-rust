"""Download the three official MaleCNS files, with streaming hashes and receipts."""
import concurrent.futures
import hashlib
import json
import pathlib
import time
import urllib.request

ROOT = pathlib.Path('D:/drosophila-heresy/data')
BASE = 'https://storage.googleapis.com/flyem-male-cns/v1.0/connectome-data/flat-connectome/'
FILES = [
    'body-annotations-male-cns-v1.0-minconf-0.5.feather',
    'body-neurotransmitters-male-cns-v1.0.feather',
    'connectome-weights-male-cns-v1.0-minconf-0.5.feather',
]


def fetch(name):
    ROOT.mkdir(parents=True, exist_ok=True)
    path = ROOT / name
    receipt_path = path.with_suffix('.receipt.json')
    if path.exists() and receipt_path.exists():
        receipt = json.loads(receipt_path.read_text())
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        assert digest == receipt['sha256'], f'Changed existing source: {name}'
        return receipt
    assert not path.exists(), f'Unreceipted source already exists: {path}'
    start = time.perf_counter()
    digest = hashlib.sha256()
    size = 0
    partial = path.with_suffix('.partial')
    with urllib.request.urlopen(BASE + name, timeout=120) as response, partial.open('wb') as out:
        expected = int(response.headers['Content-Length'])
        headers = {k: response.headers.get(k) for k in ['ETag', 'Last-Modified', 'x-goog-generation', 'x-goog-hash']}
        while chunk := response.read(4 * 1024 * 1024):
            out.write(chunk)
            digest.update(chunk)
            size += len(chunk)
    assert size == expected, (name, size, expected)
    partial.rename(path)
    receipt = dict(url=BASE + name, path=str(path), bytes=size, sha256=digest.hexdigest(),
                   seconds=time.perf_counter() - start, headers=headers,
                   attribution='MaleCNS v1.0, FlyEM/Janelia and collaborators; CC-BY; https://male-cns.janelia.org/download/')
    receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt), flush=True)
    return receipt


if __name__ == '__main__':
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        receipts = list(pool.map(fetch, FILES))
    (ROOT / 'sources.json').write_text(json.dumps(receipts, indent=2) + '\n')
