import os
from pathlib import Path

os.environ["LBUG_C_API_LIB_PATH"] = str(
    Path(__file__).parent / "vendor/ladybug-v0.20.2/extracted/lbug_shared.dll"
)
_openssl = os.add_dll_directory(r"C:\Program Files\Git\mingw64\bin")

import ladybug as lb

path = Path(__file__).parent / ".kammi-dev/probe.lbdb"
path.parent.mkdir(exist_ok=True)
db = lb.Database(str(path))
conn = lb.Connection(db)
conn.execute("CREATE NODE TABLE IF NOT EXISTS Probe(id STRING PRIMARY KEY, n INT64)")
conn.execute("MERGE (x:Probe {id:'a'}) SET x.n=1")
print(list(conn.execute("MATCH (x:Probe) RETURN x.id, x.n")))
print(lb.__version__)
