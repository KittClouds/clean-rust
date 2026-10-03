"""Read-only TRAIN/DEV release qualification; never open evaluation truth."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath

ROOT = Path('C:/phoenix-target-overgraph/bank-v3-core-20261002-v04')
MANIFEST_SHA = '2033aabd67bce5a018a32ee7417cf2b282c8bb269419ba2458a320b59002524d'


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def normalized(name):
    path = PurePosixPath(name.replace('\\', '/'))
    if path.is_absolute() or any(x in ('..', '.') for x in path.parts):
        raise ValueError('unsafe manifest path')
    if not path.parts or ':' in path.parts[0]:
        raise ValueError('unsafe manifest root')
    return path.as_posix()


def split_files(files, split, kind):
    if split not in ('TRAIN', 'DEV') or kind not in ('public', 'data'):
        raise ValueError('TRAIN/DEV public/data only')
    prefix = f'{kind}/{split}/'
    return {normalized(name): value for name, value in files.items()
            if normalized(name).startswith(prefix)}


def identity(files):
    payload = json.dumps(files, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(payload).hexdigest()


def audit(root):
    manifest_path = root / 'RELEASE-MANIFEST.json'
    if sha(manifest_path) != MANIFEST_SHA:
        raise ValueError('release manifest differs from assigned identity')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    seal = json.loads((root / 'BANK-V3-CORE-SEALED.json').read_text())
    for name, key in (('PHASE5-HANDOFF.json', 'handoff_sha256'),
                      ('REPORT.md', 'report_sha256'),
                      ('INDEPENDENT-REPLAY.json', 'replay_sha256')):
        if sha(root / name) != seal[key]:
            raise ValueError(f'seal hash mismatch: {name}')
    if seal['manifest_sha256'] != MANIFEST_SHA:
        raise ValueError('seal manifest mismatch')
    handoff = json.loads((root / 'PHASE5-HANDOFF.json').read_text())
    contract_path = root / 'BUILD-CONTRACT.json'
    if sha(contract_path) != manifest['files']['BUILD-CONTRACT.json']:
        raise ValueError('build contract hash mismatch')
    contract = json.loads(contract_path.read_text())
    if handoff['protected_policy']['model_truth_grant']:
        raise ValueError('unexpected model truth grant')
    report = {'status': 'TRAIN_DEV_FILES_VERIFIED_NOT_MODEL_RUN',
              'release_manifest_sha256': MANIFEST_SHA,
              'release_identity': seal['release_identity'],
              'source_handoff_sha256': seal['handoff_sha256'],
              'identity_encoding': 'SHA256(sorted compact JSON of normalized path/hash map)',
              'evaluation_files_opened': 0, 'splits': {},
              'handoff_split_maps_empty': {},
              'max_candidates': handoff['candidate_contract']['max_count'],
              'vocabulary': handoff['candidate_vocabulary'],
              'weights': contract['weights']}
    roots = {}
    for split in ('TRAIN', 'DEV'):
        bindings = {}
        observed_ids, canonical_ids = set(), set()
        row_count = 0
        for kind in ('public', 'data'):
            files = split_files(manifest['files'], split, kind)
            if not files:
                raise ValueError(f'no manifest-bound {kind}/{split} shards')
            actual = {p.relative_to(root).as_posix()
                      for p in (root / kind / split).rglob('*') if p.is_file()}
            if actual != set(files):
                raise ValueError(f'unlisted or missing files: {kind}/{split}')
            for name, expected in files.items():
                path = root / name
                if not path.resolve().is_relative_to(root.resolve()):
                    raise ValueError('path escaped release')
                if sha(path) != expected:
                    raise ValueError(f'shard hash mismatch: {name}')
                if kind == 'public':
                    with gzip.open(path, 'rt', encoding='utf-8') as stream:
                        for line in stream:
                            row = json.loads(line)
                            forbidden = set(handoff['never_input']).intersection(row)
                            if forbidden:
                                raise ValueError(f'forbidden public fields: {forbidden}')
                            wid, cid = row['world_id'], row['canonical_id']
                            if wid in observed_ids:
                                raise ValueError('duplicate public row id')
                            observed_ids.add(wid)
                            canonical_ids.add(cid)
                            row_count += 1
            bindings[kind] = {'files': files, 'identity': identity(files)}
        expected = handoff['splits'][split]
        if row_count != expected['rows'] or len(canonical_ids) != expected['canonical_roots']:
            raise ValueError('public row/root counts differ from handoff')
        roots[split] = canonical_ids
        report['splits'][split] = {'rows': row_count,
                                   'canonical_roots': len(canonical_ids), **bindings}
        report['handoff_split_maps_empty'][split] = (
            not expected['input_files'] and not expected['supervision_files'])
    if roots['TRAIN'].intersection(roots['DEV']):
        raise ValueError('canonical root overlap')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = audit(ROOT)
    if args.output:
        # Own create-only derived receipt, never rewrite the bank release.
        with args.output.open('x', encoding='utf-8') as stream:
            json.dump(result, stream, indent=2)
            stream.write('\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'splits'}, indent=2))
