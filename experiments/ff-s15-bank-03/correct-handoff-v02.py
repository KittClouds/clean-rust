"""Append-only split-map repair; verifies TRAIN/DEV bytes, no EVAL reads."""
import copy,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'core-v04'))
from common import OUTPUT,REPO,read,write,sha,sha256_hex

def normalize(files):
    result={}
    for path,h in files.items():
        key=path.replace('\\','/')
        if key.startswith('/') or ':' in key or '..' in key.split('/'):
            raise ValueError('Unsafe manifest path '+path)
        if key in result:raise ValueError('Normalized path collision '+path)
        result[key]=h
    return result

def select(files,prefix,expected):
    result={k:v for k,v in files.items() if k.startswith(prefix+'/') and k.endswith('.jsonl.gz')}
    if len(result)!=expected:raise ValueError(f'{prefix}: expected {expected}, got {len(result)}')
    return result

class Fixtures(unittest.TestCase):
    def test_windows_paths(self):self.assertEqual(normalize({'public\\TRAIN\\part.gz':'h'}),{'public/TRAIN/part.gz':'h'})
    def test_collisions(self):
        with self.assertRaises(ValueError):normalize({'a/b':'x','a\\b':'x'})
    def test_traversal(self):
        with self.assertRaises(ValueError):normalize({'../a':'x'})
    def test_empty_map(self):
        with self.assertRaises(ValueError):select({},'public/TRAIN',48)
    def test_identity_order(self):self.assertEqual(sha256_hex({'b':'2','a':'1'}),sha256_hex({'a':'1','b':'2'}))

def main():
    test=unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromTestCase(Fixtures))
    if not test.wasSuccessful():raise ValueError('Split-map fixtures failed')
    manifest=read(OUTPUT/'RELEASE-MANIFEST.json');old=read(OUTPUT/'PHASE5-HANDOFF.json')
    seal=read(OUTPUT/'BANK-V3-CORE-SEALED.json')
    binding_path=REPO/'experiments/s15-frizz-phase5-split-forge/release-binding-v01.json'
    binding=read(binding_path)
    if sha(OUTPUT/'RELEASE-MANIFEST.json')!=seal['manifest_sha256']:raise ValueError('Manifest identity mismatch')
    if sha(OUTPUT/'PHASE5-HANDOFF.json')!=seal['handoff_sha256']:raise ValueError('Original handoff identity mismatch')
    if binding['release_identity']!=seal['release_identity'] or binding['release_manifest_sha256']!=seal['manifest_sha256']:
        raise ValueError('Frizz release identity mismatch')
    if binding['source_handoff_sha256']!=seal['handoff_sha256']:raise ValueError('Frizz handoff identity mismatch')
    files=normalize(manifest['files']);fixed=copy.deepcopy(old);verified=0;identities={}
    for split,n in [('TRAIN',48),('DEV',12),('EVAL',12)]:
        inputs=select(files,'public/'+split,n)
        prefix='protected/evaluation-truth' if split=='EVAL' else 'data'
        truth=select(files,prefix+'/'+split,n)
        info=fixed['splits'][split];info['input_files']=inputs;info['supervision_files']=truth
        info['input_identity']=sha256_hex(inputs);info['supervision_identity']=sha256_hex(truth)
        identities[split]={'input_identity':info['input_identity'],'supervision_identity':info['supervision_identity']}
        if split!='EVAL':
            for role,mapping in [('public',inputs),('data',truth)]:
                f=binding['splits'][split][role]
                if normalize(f['files'])!=mapping or f['identity']!=sha256_hex(mapping):
                    raise ValueError('Frizz binding differs: '+split+'/'+role)
                for name,h in mapping.items():
                    if sha(OUTPUT/name)!=h:raise ValueError('Shard bytes differ: '+name)
                    verified+=1
            if binding['splits'][split]['rows']!=info['rows'] or binding['splits'][split]['canonical_roots']!=info['canonical_roots']:
                raise ValueError('Population metadata differs')
    fixed['handoff_version']='0.2'
    fixed['correction']={'source_handoff_sha256':seal['handoff_sha256'],
      'original_release_identity':seal['release_identity'],
      'reason':'Windows backslashes in top-level manifest keys failed forward-slash prefix filters',
      'path_encoding':'relative forward-slash paths; SHA256 sorted compact JSON path/hash maps',
      'evaluation_maps':'derived from sealed manifest metadata only; evaluation files not opened',
      'accepted_frizz_binding_sha256':sha(binding_path),'corpus_or_semantics_changed':False}
    out=OUTPUT/'PHASE5-HANDOFF-v02.json';write(out,fixed)
    receipt={'status':'PASS_FRIZZ_BINDINGS_ACCEPTED','handoff_version':'0.2',
      'original_release_identity':seal['release_identity'],'original_seal_unchanged':True,
      'original_handoff_sha256':seal['handoff_sha256'],'corrected_handoff_sha256':sha(out),
      'corrected_handoff_path':str(out),'frizz_binding_sha256':sha(binding_path),
      'TRAIN_DEV_shards_verified':verified,'evaluation_files_opened':0,
      'split_identities':identities,'fixture_tests_passed':test.testsRun,
      'script_sha256':sha(__file__),'corpus_or_target_changes':False,
      'scope':'removes split-binding packaging blocker; bridge first, E remains behind Qwen bridge; no training executed',
      'reliability':'only MOVE meets 200-root DEV action-type floor; others support-only'}
    write(OUTPUT/'HANDOFF-CORRECTION-v02.json',receipt)
    write(REPO/'experiments/ff-s15-bank-03/bank-v3-handoff-correction-v02.json',
      {'status':receipt['status'],'handoff_path':str(out),'handoff_sha256':sha(out),
       'correction_receipt':str(OUTPUT/'HANDOFF-CORRECTION-v02.json'),
       'correction_receipt_sha256':sha(OUTPUT/'HANDOFF-CORRECTION-v02.json'),
       'original_release_identity':seal['release_identity']})
    print('PASS: Frizz bindings accepted; 120 TRAIN/DEV shards verified; 0 evaluation files opened.')

if __name__=='__main__':main()
