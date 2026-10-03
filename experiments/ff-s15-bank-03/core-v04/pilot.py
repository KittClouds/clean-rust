"""Renderer qualification before final build contract and corpus construction."""
from common import *
from generation import build_root
from checks import check
import cue_check

def main():
    pin_ancestor();dest=OUTPUT/'engineering/pilot-canonical'
    for split,n in [('TRAIN',1200),('DEV',360)]:
        with gz_writer(dest/'data'/split/'fixture.jsonl.gz') as f:
            for i in range(n):
                rows,_=build_root('CUE-PILOT-'+split,i)
                for row in rows:
                    errors=check(row)
                    if errors:raise ValueError(errors)
                    emit(f,row)
    cue_check.OUTPUT=dest;cue_check.main(pilot=True)

if __name__=='__main__':main()
