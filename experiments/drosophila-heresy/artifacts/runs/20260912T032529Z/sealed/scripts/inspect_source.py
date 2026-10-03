"""Anatomy-only source schema and population inspection (no simulation)."""
import collections
import json
import pathlib
import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / '.deps'))
import pyarrow.feather as feather
import pyarrow.ipc as ipc
import pyarrow as pa

root = pathlib.Path('D:/drosophila-heresy/data')
for path in sorted(root.glob('*.feather')):
    print('\nFILE', path.name, flush=True)
    with pa.memory_map(str(path), 'r') as source:
        reader = ipc.open_file(source)
        print(reader.schema, 'batches', reader.num_record_batches, flush=True)
    if path.name.startswith('body-annotations'):
        df = feather.read_table(path, memory_map=True).to_pandas()
        print('rows', len(df), flush=True)
        for col in ['class', 'super_class', 'sub_class', 'type', 'cell_type', 'hemibrain_type', 'soma_side']:
            if col in df:
                print(col, df[col].value_counts().head(35).to_dict(), flush=True)
        for col in ['type', 'cell_type']:
            if col in df:
                selected = df[df[col].fillna('').str.match(r'^(KC|MBON|PAM|PPL|APL)')]
                print('MB types', selected[col].value_counts().to_dict(), flush=True)
                print('MB samples', selected.head(5).to_json(orient='records'), flush=True)
    elif path.name.startswith('body-neurotransmitters'):
        table = feather.read_table(path, memory_map=True)
        print('NT sample', table.slice(0, 3).to_pylist(), flush=True)
