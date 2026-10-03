from pathlib import Path
from common import OUT,read,receipt,sha


def main():
    path=OUT/'PHASE6A-SEALED-v02.json';seal=read(path)
    for name,digest in seal['artifact_hashes'].items():
        p=Path(name)
        if not p.is_relative_to(OUT) or sha(p)!=digest:
            raise ValueError('versioned seal artifact drift')
    receipt(OUT/'PHASE6A-SEAL-VERIFIED-v02.json',{'status':'PASS','seal_sha256':sha(path),
        'artifact_count':len(seal['artifact_hashes']),'evaluation_opened':False,
        'prior_model_probe_state_replays':'preserved and hash bound'})
    print('PHASE6A_V02_SEAL_VERIFIED',flush=True)


if __name__=='__main__':
    main()
