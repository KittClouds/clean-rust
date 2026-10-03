"""Read-only verification of imported sealed source and diagnostic input bytes."""
from pathlib import Path
from common import P5,BRIDGE,OUT,sha,read,receipt


def main():
    seal=read(P5/'LANE-SEALED.json');count=0
    roots=(P5/'E'/'source',BRIDGE/'frozen-source-v02')
    for name,expected in seal['artifact_hashes'].items():
        p=Path(name)
        if p.suffix=='.py' and any(p.is_relative_to(root) for root in roots):
            if sha(p)!=expected:
                raise ValueError('imported Phase5 scientific source drift')
            count+=1
    for name,expected in read(OUT/'SPECIFICATION.json')['frozen_inputs'].items():
        if name in seal['artifact_hashes'] and seal['artifact_hashes'][name]!=expected:
            raise ValueError('Phase6A input does not match Phase5 seal')
    receipt(OUT/'Phase5-imported-source-verification.json',{'status':'PASS',
        'source_files':count,'Phase5_seal_sha256':sha(P5/'LANE-SEALED.json'),
        'evaluation_opened':False})


if __name__=='__main__':
    main()
