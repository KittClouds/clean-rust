"""Pin original source cards and schema samples; never import public labels as truth."""
import urllib.request
import urllib.parse
from common import *

REPOS=dict(zip(LANES,('ibm-research/acp_bench','novastar111/s_v5_move_push',
 'yuruny/sudoku_state_transition_model_sft','toeunkim/matm-trajectories',
 'AgentSuite/tau-bench-trajectories','G-A-I/GraphOmni','Team-ACE/ToolACE')))

def fetch(url):
    with urllib.request.urlopen(url,timeout=60) as r:return r.read()

def run():
    root=OUT/'construction/source-intake';rows=[]
    for lane,repo in REPOS.items():
        p=root/lane;p.mkdir(parents=True,exist_ok=True)
        info=json.loads(fetch('https://huggingface.co/api/datasets/'+repo))
        revision=info['sha'];card=fetch(f'https://huggingface.co/datasets/{repo}/resolve/{revision}/README.md')
        (p/'README.upstream.md').write_bytes(card);write(p/'repository.json',info)
        sample_status='NOT_AVAILABLE';sample_hash=None
        try:
            split=json.loads(fetch('https://datasets-server.huggingface.co/splits?dataset='+urllib.parse.quote(repo)))['splits'][0]
            url='https://datasets-server.huggingface.co/first-rows?'+urllib.parse.urlencode({'dataset':repo,'config':split['config'],'split':split['split']})
            sample=fetch(url);(p/'schema-sample.json').write_bytes(sample)
            sample_status='CONSTRUCTION_ONLY_UNPINNED_VIEWER_SAMPLE';sample_hash=sha(p/'schema-sample.json')
        except Exception as e:sample_status='UNAVAILABLE:'+type(e).__name__
        rows.append({'lane':lane,'repo':repo,'url':'https://huggingface.co/datasets/'+repo,
          'revision':revision,'card_sha256':sha(p/'README.upstream.md'),'license_declared':info.get('cardData',{}).get('license'),
          'sample_status':sample_status,'sample_sha256':sample_hash,'released_rows_in_bank':0,
          'role':'archetype/schema inspiration; fresh independently implemented simulator',
          'external_row_admission':'DISALLOWED_WITHOUT_LICENSE_AND_EXECUTABLE_QUALIFICATION'})
        print(lane,revision,sample_status,flush=True)
    write(OUT/'SOURCE-INTAKE.json',rows)

if __name__=='__main__':run()
