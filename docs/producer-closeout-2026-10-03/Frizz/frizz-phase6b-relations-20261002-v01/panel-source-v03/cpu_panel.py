"""One complete matched CPU backend, not a mixed-backend selected panel."""
import shutil,subprocess,sys
from common import HERE,OUT,read,receipt,sha


def main():
    target=OUT/'panel-source-v03';target.mkdir(exist_ok=False)
    names=('common.py','targets.py','probes.py','panel.py','cpu_panel.py')
    for n in names:shutil.copy2(HERE/n,target/n)
    v=read(OUT/'PANEL-SPECIFICATION.json');v['sources']={n:sha(target/n) for n in names}
    v['backend']='CPU FP32, four threads, deterministic algorithms, all 168 arms'
    v['repair']='complete matched CPU panel after contended CUDA failure; prior CUDA fits preserved and not used in final panel'
    receipt(OUT/'PANEL-SPECIFICATION-v03.json',v)
    for extra in ([],['--replay']):
        subprocess.run([sys.executable,'-u','-B',str(target/'panel.py'),*extra],check=True)


if __name__=='__main__':main()
