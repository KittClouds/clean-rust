import shutil
from common import HERE,OUT,read,sha,receipt


def main():
    source=OUT/'panel-source-v01';source.mkdir()
    for p in HERE.iterdir():
        if p.is_file() and p.suffix in ('.py','.md'):shutil.copy2(p,source/p.name)
    receipt(OUT/'PANEL-SPECIFICATION.json',{'status':'FIXED_BEFORE_DIAGNOSTIC_DEV_SCORING',
        'earned_factors':read(OUT/'gold-audit.json')['earned_families_TRAIN_only'],
        'sources':{p.name:sha(p) for p in source.iterdir()},'gold_receipt_sha256':sha(OUT/'gold-audit.json'),
        'epochs':4,'seed':0,'hidden':64,'batch_roots':64,'evaluation_opened':False})


if __name__=='__main__':main()
