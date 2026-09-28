import os
from pathlib import Path
import tempfile

_openssl = os.add_dll_directory(os.environ["KAMMI_OPENSSL_DLL_DIR"])
import ladybug as lb

root = Path(tempfile.mkdtemp(prefix="kammi-memory-probe-"))
db = lb.Database(str(root / "memory.lbdb"))
conn = lb.Connection(db)
for query in (
    "INSTALL FTS",
    "LOAD FTS",
    "INSTALL VECTOR",
    "LOAD VECTOR",
    "CALL SHOW_LOADED_EXTENSIONS() RETURN *",
    "CREATE NODE TABLE Memory(id STRING PRIMARY KEY, text STRING, embedding FLOAT[384])",
    "CREATE (m:Memory {id:'m1', text:'WDDM CUDA lease confusion', embedding:[" + ",".join(["0.1"] * 384) + "]})",
    "CALL CREATE_FTS_INDEX('Memory', 'memory_text', ['text'])",
    "CALL CREATE_VECTOR_INDEX('Memory', 'memory_vector', 'embedding', metric := 'cosine')",
    "CALL QUERY_FTS_INDEX('Memory', 'memory_text', 'CUDA', TOP := 5) RETURN node.id, score",
    "CALL QUERY_VECTOR_INDEX('Memory', 'memory_vector', [" + ",".join(["0.1"] * 384) + "], 5) RETURN node.id, distance",
    "CREATE (m:Memory {id:'m2', text:'CUDA second', embedding:[" + ",".join(["0.1"] * 384) + "]})",
    "CALL QUERY_FTS_INDEX('Memory', 'memory_text', 'second', TOP := 5) RETURN node.id, score",
    "CALL QUERY_VECTOR_INDEX('Memory', 'memory_vector', [" + ",".join(["0.1"] * 384) + "], 5) RETURN node.id, distance",
    "CALL DROP_FTS_INDEX('Memory', 'memory_text')",
    "CALL CREATE_FTS_INDEX('Memory', 'memory_text', ['text'])",
    "CALL QUERY_FTS_INDEX('Memory', 'memory_text', 'second', TOP := 5) RETURN node.id, score",
    "CALL QUERY_FTS_INDEX('Memory', 'memory_text', 'CUDA', TOP := 5) RETURN node.id, score",
    "MATCH (m:Memory) RETURN m.id, m.text",
    "CALL QUERY_FTS_INDEX('Memory', 'memory_text', $query, TOP := 5) RETURN node.id, score",
):
    try:
        rows = list(conn.execute(query, {"query": "CUDA"}) if "$query" in query else conn.execute(query))
        print(query[:80], "OK", rows[:3])
    except Exception as exc:
        print(query[:80], "FAIL", type(exc).__name__, str(exc)[:500])
