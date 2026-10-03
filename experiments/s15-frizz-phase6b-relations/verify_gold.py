"""Fresh-process semantic reconstruction with original frozen gold source."""
import sys
from pathlib import Path
from common import OUT,read,receipt,sha


def main():
    sys.path.insert(0,str(OUT/'source-v02'))
    import gold
    from targets import records
    spec=read(OUT/'SPECIFICATION.json')
    for name,digest in spec['sources'].items():
        if sha(OUT/'source-v02'/name)!=digest:raise ValueError('original gold source drift')
    for split in ('TRAIN','DEV'):
        if gold.load_records(split)!=records(split):raise ValueError('canonical factor/planner replay mismatch')
    receipt(OUT/'gold-replay.json',{'status':'PASS','splits':['TRAIN','DEV'],
        'scope':'fresh process pinned canonical simulator, full derived factors and same-type population',
        'evaluation_opened':False})


if __name__=='__main__':main()
