"""Only finalize safely: no architecture, loss, dose or target revision."""
import shutil
from common import *


def main():
    folder=OUT/'source-v03';folder.mkdir(exist_ok=False)
    names=[p.name for p in HERE.iterdir() if p.suffix in ('.py','.md')]
    for name in names:shutil.copy2(HERE/name,folder/name)
    spec=read(OUT/'SPECIFICATION-v02.json');spec['sources']={n:sha(folder/n) for n in names}
    spec['closure_repair']='exclude actively written finish stdout/stderr from hash closure; fit continues unchanged in source-v02; no refit or scientific changes'
    receipt(OUT/'SPECIFICATION-v03.json',spec)
    receipt(OUT/'ENGINEERING-RECEIPT.json',{'preparation_failure':'unused padded candidate c-vectors compared to cropped historical zeros; real-candidate .02 tolerance unchanged',
        'failed_source_preserved':'source-v01','fit_source':'source-v02','finish_source':'source-v03',
        'failed_logs':{p.name:sha(p) for p in (OUT/'run.stdout.log',OUT/'run.stderr.log')},
        'closure_repair':'exclude live finish logs; preserve original attempts and all completed scientific bytes',
        'refit':False,'evaluation_opened':False})


if __name__=='__main__':main()
