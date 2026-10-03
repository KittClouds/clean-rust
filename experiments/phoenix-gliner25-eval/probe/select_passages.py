"""Deterministic passage selection for the GLiNER 2.5 schema probe.

Model-free: consecutive prose paragraphs are grouped into passages of at
least 110 words (a new passage never starts mid-paragraph), passages with
fewer than two distinct capitalised non-initial tokens are skipped, and 36
passages are taken at even strides across the book. Byte offsets refer to
the UTF-8 source file.
"""
import hashlib, json, re, sys

source_path, out_path = sys.argv[1], sys.argv[2]
raw = open(source_path, "rb").read()
text = raw.decode("utf-8")

paragraphs = []  # (byte_start, byte_end)
offset = 0
for line in raw.split(b"\n"):
    start, end = offset, offset + len(line)
    offset = end + 1
    body = line.decode("utf-8").strip()
    if not body or body.startswith("```") or re.match(r"^Chapter \d+", body):
        continue
    lead = len(line) - len(line.lstrip())
    paragraphs.append((start + lead, end - (len(line.rstrip()) and len(line) - len(line.rstrip()))))

def words(s):
    return len(s.split())

passages, current = [], []
for p in paragraphs:
    current.append(p)
    if sum(words(raw[a:b].decode("utf-8")) for a, b in current) >= 110:
        passages.append((current[0][0], current[-1][1]))
        current = []

def has_names(s):
    tokens = re.findall(r"(?<![.!?\"“”‘’]\s)(?<!^)\b[A-Z][a-z]+", s)
    return len(set(tokens)) >= 2

eligible = [p for p in passages if has_names(raw[p[0]:p[1]].decode("utf-8"))]
count = 36
stride = len(eligible) / count
chosen = [eligible[int(i * stride)] for i in range(count)]
rows = []
for index, (a, b) in enumerate(chosen):
    body = raw[a:b].decode("utf-8")
    rows.append({"id": f"p{index:02d}", "start": a, "end": b, "text": body})
with open(out_path, "w", encoding="utf-8", newline="\n") as f:
    for row in rows:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
print(f"paragraphs {len(paragraphs)} passages {len(passages)} eligible {len(eligible)} chosen {len(rows)}")
print("source sha256", hashlib.sha256(raw).hexdigest())
