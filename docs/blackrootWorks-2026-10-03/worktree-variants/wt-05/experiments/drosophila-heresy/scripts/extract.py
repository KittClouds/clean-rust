"""Anatomy census + bounded, independently indexed hemisphere extracts."""
import collections
import hashlib
import json
import pathlib
import sys
import time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / '.deps'))
import numpy as np
import pyarrow as pa
import pyarrow.feather as feather
import pyarrow.ipc as ipc

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW = pathlib.Path('D:/drosophila-heresy/data')
OUT = ROOT / 'artifacts' / 'anatomy'
CLASS = {'ALPN': 0, 'Kenyon_Cell': 1, 'MBON': 2, 'DAN': 3}


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    start = time.perf_counter()
    OUT.mkdir(parents=True, exist_ok=True)
    receipts = json.loads((RAW / 'sources.json').read_text())
    for source in receipts:
        assert digest(pathlib.Path(source['path'])) == source['sha256']
    ann = feather.read_table(RAW / 'body-annotations-male-cns-v1.0-minconf-0.5.feather', memory_map=True).to_pandas()
    nt = feather.read_table(RAW / 'body-neurotransmitters-male-cns-v1.0.feather', memory_map=True).to_pandas()
    assert ann.bodyId.is_unique and nt.body.is_unique
    eligible_class = ann['class'].isin(CLASS) | ann['type'].eq('APL')
    chosen = ann[eligible_class & ann.status.eq('Traced') & ann.somaSide.isin(['L', 'R'])].copy()
    chosen['kind'] = chosen['class'].map(CLASS).fillna(4).astype(int)
    chosen = chosen.merge(nt, left_on='bodyId', right_on='body', how='left', validate='one_to_one')
    chosen = chosen.sort_values(['somaSide', 'kind', 'bodyId'])
    selected_ids = np.sort(chosen.bodyId.to_numpy())
    annotated_ids = np.sort(ann.bodyId.to_numpy())
    audit = dict(source_receipts=receipts, annotation_rows=len(ann),
                 status_counts=ann.status.value_counts(dropna=False).to_dict(),
                 candidate_class_rows=int(eligible_class.sum()), selected_rows=len(chosen),
                 excluded_class_candidates=int(eligible_class.sum())-len(chosen),
                 hemisphere_counts={}, layers={}, boundary={}, graph_rows=0,
                 graph_weight=0, both_endpoints_annotated_rows=0,
                 selected_internal_rows=0, selected_incoming_boundary_rows=0,
                 selected_outgoing_boundary_rows=0,
                 model_layers=['ALPN->KC', 'KC->MBON', 'KC->DAN', 'MBON->DAN', 'DAN->MBON'],
                 not_modelled='All other edges, APL dynamics, geometry, receptor state, and subcellular modulation.')
    maps = {}
    handles = {}
    rows = {}
    for side in ['R', 'L']:
        group = chosen[chosen.somaSide.eq(side)].copy()
        group['index'] = np.arange(len(group))
        maps[side] = {int(r.bodyId): (int(r.index), int(r.kind)) for r in group.itertuples()}
        audit['hemisphere_counts'][side] = {str(k): int(v) for k, v in group.kind.value_counts().sort_index().items()}
        group.to_json(OUT / f'nodes-{side}.json', orient='records', indent=2)
        with (OUT / f'nodes-{side}.tsv').open('w', newline='') as f:
            f.write('body\tkind\tnt\n')
            for row in group.itertuples():
                neurotransmitter = row.consensus_nt if isinstance(row.consensus_nt, str) else 'unknown'
                f.write(f'{row.bodyId}\t{row.kind}\t{neurotransmitter}\n')
        handles[side] = (OUT / f'edges-{side}.tsv').open('w', newline='')
        handles[side].write('pre\tpost\tweight\n')
        rows[side] = collections.Counter()
        audit['boundary'][side] = dict(incoming_rows=0, outgoing_rows=0, incoming_weight=0, outgoing_weight=0)
    path = RAW / 'connectome-weights-male-cns-v1.0-minconf-0.5.feather'
    with pa.memory_map(str(path), 'r') as source:
        reader = ipc.open_file(source)
        print('EDGE SCHEMA', reader.schema, flush=True)
        names = reader.schema.names
        assert {'body_pre', 'body_post', 'weight'} <= set(names), names
        for batch_id in range(reader.num_record_batches):
            batch = reader.get_batch(batch_id)
            pre = batch.column(names.index('body_pre')).to_numpy()
            post = batch.column(names.index('body_post')).to_numpy()
            weight = batch.column(names.index('weight')).to_numpy()
            assert np.all(weight > 0)
            pre_sel = np.isin(pre, selected_ids)
            post_sel = np.isin(post, selected_ids)
            audit['graph_rows'] += len(pre)
            audit['graph_weight'] += int(weight.sum(dtype=np.int64))
            audit['both_endpoints_annotated_rows'] += int((np.isin(pre, annotated_ids) & np.isin(post, annotated_ids)).sum())
            audit['selected_internal_rows'] += int((pre_sel & post_sel).sum())
            audit['selected_incoming_boundary_rows'] += int((~pre_sel & post_sel).sum())
            audit['selected_outgoing_boundary_rows'] += int((pre_sel & ~post_sel).sum())
            for side in ['R', 'L']:
                mapping = maps[side]
                ids = np.fromiter(mapping, dtype=np.int64)
                a, b = np.isin(pre, ids), np.isin(post, ids)
                boundary = audit['boundary'][side]
                boundary['incoming_rows'] += int((~a & b).sum())
                boundary['outgoing_rows'] += int((a & ~b).sum())
                boundary['incoming_weight'] += int(weight[~a & b].sum(dtype=np.int64))
                boundary['outgoing_weight'] += int(weight[a & ~b].sum(dtype=np.int64))
                for ix in np.flatnonzero(a & b):
                    pi, pk = mapping[int(pre[ix])]
                    qi, qk = mapping[int(post[ix])]
                    w = int(weight[ix])
                    handles[side].write(f'{pi}\t{qi}\t{w}\n')
                    rows[side][f'{pk}->{qk}:edges'] += 1
                    rows[side][f'{pk}->{qk}:synapses'] += w
            if batch_id % 100 == 0:
                print('batch', batch_id, '/', reader.num_record_batches, 'rows', audit['graph_rows'], flush=True)
    for side in handles:
        handles[side].close()
        audit['layers'][side] = dict(sorted(rows[side].items()))
    audit['seconds'] = time.perf_counter()-start
    audit['outputs'] = {p.name: digest(p) for p in sorted(OUT.glob('*')) if p.suffix in ['.tsv', '.json'] and p.name != 'census.json'}
    (OUT / 'census.json').write_text(json.dumps(audit, indent=2) + '\n')
    print(json.dumps({k: v for k, v in audit.items() if k not in ['source_receipts', 'outputs']}, indent=2))


if __name__ == '__main__':
    main()
