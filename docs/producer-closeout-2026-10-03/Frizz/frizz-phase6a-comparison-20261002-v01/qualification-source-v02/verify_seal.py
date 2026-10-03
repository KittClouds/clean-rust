"""Fresh-process final hash closure; owned diagnostic artifacts only."""
from pathlib import Path
from common import OUT,read,receipt,sha


def main():
    path=OUT/'PHASE6A-SEALED.json';seal=read(path)
    for name,digest in seal['artifact_hashes'].items():
        p=Path(name)
        if not p.is_relative_to(OUT) or sha(p)!=digest:
            raise ValueError('Phase6A artifact identity drift: '+name)
    receipt(OUT/'PHASE6A-SEAL-VERIFIED.json',{'status':'PASS','seal_sha256':sha(path),
        'artifacts':len(seal['artifact_hashes']),'evaluation_opened':False})
    print('PHASE6A_SEAL_VERIFIED',flush=True)


if __name__=='__main__':
    main()
