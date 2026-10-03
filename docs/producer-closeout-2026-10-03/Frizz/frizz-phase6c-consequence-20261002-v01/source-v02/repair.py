"""Versioned engineering-only repair before consequence fitting."""
import shutil
from common import *


def main():
    target=OUT/'source-v02';target.mkdir(exist_ok=False)
    names=[p.name for p in HERE.iterdir() if p.suffix in ('.py','.md')]
    for name in names:shutil.copy2(HERE/name,target/name)
    spec=read(OUT/'SPECIFICATION.json');spec['sources']={n:sha(target/n) for n in names}
    spec['repair']='valid-candidate reference comparison ignores unscored padding; .02 tolerance unchanged; historical gold oracle permission qualification retained, with pure-distance variant separately reported'
    spec['training_or_DEV_scoring_before_repair']=False
    receipt(OUT/'SPECIFICATION-v02.json',spec)


if __name__=='__main__':main()
