"""Close a qualified construction release; narrow Library intake, no model contact."""
import hashlib
import json
import pathlib
import subprocess
import sys
import urllib.request

ROOT = pathlib.Path('C:/phoenix-data/banks/BANK-v4-20261003-v01')
REBUILD = pathlib.Path('C:/phoenix-data/banks/BANK-v4-reconstruction-20261003-v01')
REPO = pathlib.Path('C:/code land/clean-rust')
sys.path.insert(0, str(ROOT/'factory'))
from common import digest, encode, read, sha, write


def files(root):
    return {str(p.relative_to(root)).replace('\\', '/'): {'sha256': sha(p), 'bytes': p.stat().st_size}
            for p in sorted(root.rglob('*')) if p.is_file()}


def finish():
    corpus = files(ROOT/'corpus')
    reconstructed = files(REBUILD/'corpus')
    if corpus != reconstructed or (ROOT/'BUILD.json').read_bytes() != (REBUILD/'BUILD.json').read_bytes():
        raise RuntimeError('FULL_RECONSTRUCTION_MISMATCH')
    write(ROOT/'RECONSTRUCTION.json', {'status': 'PASS', 'corpus_file_count': len(corpus),
                                      'files_identical': True, 'build_manifest_identical': True,
                                      'corpus_root': digest(corpus), 'source': str(ROOT/'factory'),
                                      'clean_output': str(REBUILD), 'scope': 'every corpus file and BUILD.json'})
    source = files(ROOT/'factory')
    write(ROOT/'SOURCE-MANIFEST.json', {'files': source, 'source_root': digest(source),
                                       'entry_point': 'build.py', 'python': sys.version})
    test = subprocess.run([sys.executable, '-B', str(ROOT/'factory/test_factory.py')],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True)
    (ROOT/'QUALIFICATION.txt').write_bytes(test.stdout)
    replay = read(ROOT/'REPLAY.json')
    if replay['status'] != 'PASS':
        raise RuntimeError('REPLAY_NOT_PASS')
    summary = read(ROOT/'BUILD.json')
    if summary['failures'] or any(summary['overlap'][key]['cross_split_signatures'] for key in ('input', 'structural')):
        raise RuntimeError('RELEASE_ADMISSION_OVERLAP_OR_FAILURE')
    metrics = {'paired_optimal_set_changes': 0, 'paired_grounding_changes': 0,
               'tied_optimal_roots': 0, 'dense_pairwise_rows': 0, 'unknown_grounding_rows': 0,
               'legal_but_forbidden_candidates': 0, 'legal_unreachable_successors': 0,
               'wait_offered_roots': 0, 'wait_optimal_roots': 0}
    lane_policy = {}
    for path in sorted((ROOT/'corpus').rglob('targets.jsonl')):
        lane_policy[str(path.parent.relative_to(ROOT/'corpus')).replace('\\', '/')] = {}
        current = []
        with path.open('rb') as stream:
            for line in stream:
                target = json.loads(line)
                current.append(target)
                key = str(path.parent.relative_to(ROOT/'corpus')).replace('\\', '/')
                mode = target['decision']['mode']
                lane_policy[key][mode] = lane_policy[key].get(mode, 0)+1
                metrics['tied_optimal_roots'] += len(target['canonical_optimal_actions']) > 1
                metrics['dense_pairwise_rows'] += len(target['pairwise_consequence_coordinates'])
                metrics['unknown_grounding_rows'] += sum(r['legality'] == 'UNRESOLVED' or r['permission'] == 'UNRESOLVED' for r in target['grounding'])
                metrics['legal_but_forbidden_candidates'] += sum(r['legal'] and not r['permitted'] for r in target['canonical_consequences'])
                metrics['legal_unreachable_successors'] += sum(r['next_distance_status'] == 'UNREACHABLE' for r in target['canonical_consequences'])
                metrics['wait_offered_roots'] += any(r['candidate_id'] == 'WAIT' for r in target['grounding'])
                metrics['wait_optimal_roots'] += 'WAIT' in target['canonical_optimal_actions']
                if len(current) == 4:
                    metrics['paired_optimal_set_changes'] += current[0]['canonical_optimal_actions'] != current[2]['canonical_optimal_actions']
                    metrics['paired_grounding_changes'] += current[0]['grounding'] != current[2]['grounding']
                    current = []
        if current:
            raise RuntimeError('INCOMPLETE_FAMILY')
    write(ROOT/'CURRICULUM-AUDIT.json', {'metrics': metrics, 'policy_cells': lane_policy,
                                        'diagnostic_partial_pairwise_rows_are_masked': True,
                                        'warning': 'counts of sibling/view rows are not independent sample counts'})
    # No output registration receipts exist yet, so this manifest has no self-cycle.
    inventory = files(ROOT)
    write(ROOT/'RELEASE.json', {'schema': 'BANK_V4_RELEASE_V1', 'status': 'QUALIFIED_CONSTRUCTION_CURRICULUM',
                               'effective_contract': 'CONTRACT-v02.json', 'artifacts': inventory,
                               'root': digest(inventory), 'source_root': digest(source),
                               'counts': summary['counts'], 'observer_model_contact': False,
                               'confirmation_eligibility': False,
                               'qualification': {'unit_and_mutant_tests': 'PASS', 'all_serialized_root_replay': 'PASS',
                                                 'full_clean_regeneration': 'PASS', 'cross_split_exact_input_overlap': 0}})
    print(json.dumps({'root': read(ROOT/'RELEASE.json')['root'], 'metrics': metrics,
                      'files': len(inventory), 'bytes': sum(v['bytes'] for v in inventory.values())}, indent=2))


def register():
    token = (REPO/'program-infrastructure/kammi-ledger/.kammi-dev/operational/admin.secret').read_text().strip()
    def call(route, body=None):
        request = urllib.request.Request('http://127.0.0.1:8765'+route,
                                         data=encode(body) if body is not None else None,
                                         headers={'Authorization': 'Bearer '+token, 'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.loads(response.read())
    status = call('/v1/status')
    if status['flight_gate'] != 'OPEN':
        raise RuntimeError('LIBRARY_NOT_OPEN')
    receipts = []
    manifest = read(ROOT/'RELEASE.json')
    inventory = dict(manifest['artifacts'])
    inventory['RELEASE.json'] = {'sha256': sha(ROOT/'RELEASE.json'), 'bytes': (ROOT/'RELEASE.json').stat().st_size}
    for relative, identity in sorted(inventory.items()):
        path = ROOT/relative
        if sha(path) != identity['sha256'] or path.stat().st_size != identity['bytes']:
            raise RuntimeError('PREIMPORT_BYTE_MISMATCH:'+relative)
        kind = 'bank-curriculum-targets' if relative.endswith('/targets.jsonl') else 'bank-construction' if relative.endswith('/construction.jsonl') else 'bank-v4-artifact'
        receipt = call('/v1/artifacts/import-local', {'path': str(path), 'expected_sha256': 'sha256:'+identity['sha256'],
                      'expected_bytes': identity['bytes'], 'kind': kind, 'actor': 'chief-kammi',
                      'request_id': 'bank-v4-intake-'+digest(relative)[:20]+'-'+identity['sha256'][:20]})
        if receipt['artifact_id'] != 'sha256:'+identity['sha256']:
            raise RuntimeError('CAS_RECEIPT_MISMATCH')
        receipts.append({'path': relative, **receipt})
    seal = call('/v1/seals', {'direct_members': sorted({r['artifact_id'] for r in receipts}), 'parents': [],
                             'actor': 'chief-kammi', 'request_id': 'bank-v4-seal-'+manifest['root'][:32]})
    write(ROOT/'LIBRARY-RECEIPT.json', {'artifacts': receipts, 'seal': seal,
                                       'release_root': manifest['root'], 'confirmation_eligible': False})
    print(json.dumps({'artifacts_registered': len(receipts), 'seal': seal}, indent=2))


def split_audit():
    # Recompute exact-text overlap from serialized inputs in a separate operation,
    # rather than adopting the builder's overlap totals as a passing predicate.
    texts = {}
    families = {}
    same_split_repeats = 0
    cross_split = 0
    for path in sorted((ROOT/'corpus').rglob('inputs.jsonl')):
        split = path.parent.parent.name
        with path.open('rb') as stream:
            for line in stream:
                row = json.loads(line)
                key = hashlib.sha256(row['input_text'].encode()).hexdigest()
                prior = texts.setdefault(key, split)
                if prior != split:
                    cross_split += 1
                elif key in families:
                    same_split_repeats += 1
                families[key] = True
    if cross_split or same_split_repeats != 17920:
        raise RuntimeError('INDEPENDENT_SERIALIZED_INPUT_OVERLAP')
    output = {'status': 'PASS', 'cross_split_exact_text_occurrences': cross_split,
              'within_split_repeated_occurrences': same_split_repeats,
              'distinct_rendered_texts': len(texts), 'expected_duplicate_reason': 'identical partial sibling views'}
    write(ROOT/'INDEPENDENT-SPLIT-AUDIT.json', output)
    print(json.dumps(output, indent=2))


if __name__ == '__main__':
    {'finish': finish, 'register': register, 'split-audit': split_audit}[sys.argv[1]]()
