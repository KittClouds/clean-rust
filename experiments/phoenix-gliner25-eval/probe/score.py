"""Scores the schema probe exactly as PREREGISTRATION.md specifies."""
import json, re, sys
from collections import defaultdict

HERE = sys.argv[1] if len(sys.argv) > 1 else "."
source = open(sys.argv[2], "rb").read() if len(sys.argv) > 2 else None
gold = json.load(open(f"{HERE}/gold.json", encoding="utf-8"))
passages = [json.loads(l) for l in open(f"{HERE}/passages.jsonl", encoding="utf-8")]
aliases = {k.lower(): v for k, v in gold["aliases"].items()}
ignore = set(gold["ignore"])
schema = gold["relation_schema"]


def canon(surface):
    s = surface.strip().strip("\"'“”‘’.,;:!?()").strip()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"(’s|'s)$", "", s)
    s = re.sub(r"^the ", "", s, flags=re.I)
    low = s.lower()
    return aliases.get(low, s).lower()


def gold_entities(pid):
    return {name.lower(): kind for name, kind in gold["passages"][pid]["entities"].items()}


def rel_key(head, kind, tail):
    if schema.get(kind, {}).get("symmetric"):
        head, tail = sorted([head, tail])
    return (head, kind, tail)


def gold_relations(pid):
    return {rel_key(h.lower(), k, t.lower()) for h, k, t in gold["passages"][pid]["relations"]}


def score_entities(pred):  # pred: pid -> {canonical: type}
    tp = fp = fn = typed = 0
    wrong = defaultdict(list)
    for p in passages:
        pid = p["id"]
        g = gold_entities(pid)
        predicted = {k: v for k, v in pred.get(pid, {}).items() if k not in ignore}
        for name, kind in predicted.items():
            if name in g:
                tp += 1
                typed += kind == g[name]
            else:
                fp += 1
                wrong[pid].append(name)
        fn += sum(1 for name in g if name not in predicted)
    precision = tp / max(tp + fp, 1)
    recall = tp / max(tp + fn, 1)
    return {"tp": tp, "fp": fp, "fn": fn, "precision": round(precision, 3),
            "recall": round(recall, 3), "type_accuracy": round(typed / max(tp, 1), 3)}, wrong


def score_relations(pred):  # pred: pid -> set of (head, kind, tail)
    tp = fp = fn = pair_tp = 0
    for p in passages:
        pid = p["id"]
        g = gold_relations(pid)
        gold_pairs = {frozenset((h, t)) for h, _, t in g}
        predicted = pred.get(pid, set())
        for key in predicted:
            if key in g:
                tp += 1
            else:
                fp += 1
            pair_tp += frozenset((key[0], key[2])) in gold_pairs
        fn += len(g - predicted)
    n = tp + fp
    return {"predicted": n, "tp": tp, "fp": fp, "fn": fn,
            "precision": round(tp / max(n, 1), 3), "recall": round(tp / max(tp + fn, 1), 3),
            "pair_precision": round(pair_tp / max(n, 1), 3)}


KIND = {1: "character", 3: "character", 2: "location", 4: "faction", 7: "faction",
        6: "concept", 8: "concept", 5: "event"}
KEYWORD = {2: "ally_of", 3: "enemy_of", 4: "owns", 5: "located_in", 7: "family_of"}

rows = [json.loads(l) for l in open(f"{HERE}/predictions.jsonl", encoding="utf-8")]
by_setup = defaultdict(dict)
for row in rows:
    by_setup[row["setup"]][row["id"]] = row

results = {}
examples = {}

# A: production mentions inside the passage (surface text from the source).
production = [json.loads(l) for l in open(f"{HERE}/production.jsonl", encoding="utf-8")]
entities_a, relations_k, relations_k_mappable = {}, {}, {}
for p in passages:
    ents, rels, mapped = {}, set(), set()
    for r in production:
        if r["row"] == "mention" and p["start"] <= r["start"] and r["end"] <= p["end"]:
            surface = source[r["start"]:r["end"]].decode("utf-8") if source else r["entity"]
            ents[canon(surface)] = KIND.get(r["kind"], "other")
        elif r["row"] == "relation" and p["start"] <= r["premise_start"] and r["premise_end"] <= p["end"]:
            kind = KEYWORD.get(r["relation"], f"unmapped:{r['relation']}")
            key = rel_key(canon(r["head"]), kind, canon(r["tail"]))
            rels.add(key)
            if not kind.startswith("unmapped"):
                mapped.add(key)
    entities_a[p["id"]] = ents
    relations_k[p["id"]] = rels
    relations_k_mappable[p["id"]] = mapped
results["A"], examples["A"] = score_entities(entities_a)


def model_entities(setup, keep=lambda e: True):
    out = {}
    for pid, row in by_setup[setup].items():
        out[pid] = {canon(e["text"]): e["label"] for e in row["entities"] if keep(e)}
    return out


results["B1"], examples["B1"] = score_entities(model_entities("B1"))
results["B2"], examples["B2"] = score_entities(
    model_entities("B2", lambda e: e.get("form") == "proper name"))
results["C_entities"], examples["C"] = score_entities(model_entities("C"))

relation_results = {}
for setup in ["C", "C@0.3", "C@0.7"]:
    pred = {pid: {rel_key(canon(r["head"] or ""), r["type"], canon(r["tail"] or ""))
                  for r in row["relations"]} for pid, row in by_setup[setup].items()}
    relation_results[setup] = score_relations(pred)
    if setup == "C":
        c_pred = pred
relation_results["K (keyword, all)"] = score_relations(relations_k)
relation_results["K (keyword, mappable types)"] = score_relations(relations_k_mappable)
# P: every co-occurring gold entity pair, counted as a claim that some relation exists.
pairs_tp = pairs_n = 0
for p in passages:
    names = sorted(gold_entities(p["id"]))
    gold_pairs = {frozenset((h, t)) for h, _, t in gold_relations(p["id"])}
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            pairs_n += 1
            pairs_tp += frozenset((names[i], names[j])) in gold_pairs
relation_results["P (all co-occurring pairs)"] = {
    "predicted": pairs_n, "pair_precision": round(pairs_tp / max(pairs_n, 1), 3)}

a, b2 = results["A"], results["B2"]
gate_entities = b2["precision"] >= a["precision"] + 0.10 and b2["recall"] >= a["recall"] - 0.05
c = relation_results["C"]
k = relation_results["K (keyword, mappable types)"]
if c["precision"] >= 0.70 and c["precision"] > k["precision"]:
    gate_relations = "automatic evidence tier"
elif c["precision"] >= 0.50:
    gate_relations = "review-only tier"
else:
    gate_relations = "dropped"

timing = {s: round(sum(r["elapsed_ms"] for r in by_setup[s].values()) / len(by_setup[s]), 1)
          for s in by_setup}
report = {"entities": results, "relations": relation_results,
          "gates": {"entities_adopt_B2": gate_entities, "relations": gate_relations},
          "mean_ms_per_passage": timing,
          "false_positive_entities": {s: dict(v) for s, v in examples.items()},
          "C_relations": {pid: sorted(map(list, v)) for pid, v in c_pred.items() if v}}
print(json.dumps(report, indent=1, ensure_ascii=False))
