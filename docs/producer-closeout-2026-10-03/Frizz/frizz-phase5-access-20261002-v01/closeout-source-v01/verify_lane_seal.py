"""Fresh-process final hash closure; no corpus/evaluation file access."""
import json
from pathlib import Path
from audit_release import sha
from runtime import receipt


def main():
    lane=Path('C:/phoenix-target-overgraph/frizz-phase5-access-20261002-v01')
    path=lane/'LANE-SEALED.json';seal=json.loads(path.read_text())
    for name,expected in seal['artifact_hashes'].items():
        target=Path(name)
        # Only the three owned artifact roots, never a bank evaluation shard.
        allowed=(lane,Path('C:/phoenix-target-overgraph/frizz-qwen-v3-bridge-20261002-v02'),
                 Path('C:/phoenix-target-overgraph/frizz-qwen-v3-bridge-20261002-v01'))
        if not any(target.is_relative_to(root) for root in allowed):
            raise ValueError('final manifest escaped owned artifact roots')
        if sha(target)!=expected:
            raise ValueError('sealed artifact drift: '+name)
    receipt(lane/'LANE-SEAL-VERIFIED.json',{'status':'PASS','seal_sha256':sha(path),
        'artifact_count':len(seal['artifact_hashes']),'evaluation_opened':False,
        'scope':'fresh-process hash closure; model/probe replay receipts bound by seal'})
    print(json.dumps({'status':'LANE_SEAL_VERIFIED','artifacts':len(seal['artifact_hashes'])}),flush=True)


if __name__=='__main__':
    main()
