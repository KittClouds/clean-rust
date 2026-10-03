"""Frozen Qwen extraction of six inherited surfaces; no truncation or truth inputs."""
import argparse
import json
import time
from pathlib import Path

import torch
import torch.nn.functional as F
from safetensors import safe_open
from transformers import AutoTokenizer, Qwen3_5ForConditionalGeneration

from adapter import rows
from audit_release import ROOT, sha
from runtime import HERE, OUT, MODEL, REVISION, receipt, verify_handoff


def load_model():
    tokenizer = AutoTokenizer.from_pretrained(MODEL, local_files_only=True)
    tokenizer.padding_side = 'right'
    full, info = Qwen3_5ForConditionalGeneration.from_pretrained(
        MODEL, local_files_only=True, dtype=torch.bfloat16,
        attn_implementation='eager', output_loading_info=True)
    if any(info.get(k) for k in ('missing_keys', 'unexpected_keys', 'mismatched_keys')):
        raise ValueError('checkpoint loading identity failed')
    full.requires_grad_(False).eval()
    tower = full.model.language_model
    mapping = json.loads((MODEL / 'model.safetensors.index.json').read_text())['weight_map']
    checked = set()
    for filename in sorted(set(mapping.values())):
        with safe_open(MODEL / filename, framework='pt', device='cpu') as disk:
            for name, param in tower.named_parameters():
                key = 'model.language_model.' + name
                if mapping.get(key) == filename:
                    if not torch.equal(param.detach(), disk.get_tensor(key).to(param.dtype)):
                        raise ValueError('checkpoint parameter mismatch: ' + key)
                    checked.add(name)
    if len(checked) != len(list(tower.named_parameters())):
        raise ValueError('unverified text parameter')
    identity = {'parameters_checked': len(checked), 'max_abs_difference': 0,
                'text_parameters': sum(p.numel() for p in tower.parameters())}
    tower.to('cuda')
    return tokenizer, tower, identity


@torch.inference_mode()
def hidden(tokenizer, tower, texts, maximum):
    batch = tokenizer(texts, padding=True, truncation=False,
                      return_offsets_mapping=True, return_tensors='pt')
    offsets = batch.pop('offset_mapping')
    if batch['input_ids'].shape[1] > maximum:
        raise ValueError('unplanned context length; no silent truncation')
    batch = {k: v.cuda() for k, v in batch.items()}
    result = tower(**batch, use_cache=False, output_hidden_states=True)
    hs = result.hidden_states
    if hs is None or len(hs) != 25 or hs[-1].shape[-1] != 1024:
        raise ValueError('incorrect Qwen hidden stack')
    if any(not torch.isfinite(hs[d]).all() for d in (6, 12, 18, 24)):
        raise ValueError('non-finite Qwen surfaces')
    return hs, batch['attention_mask'], offsets


def mention_tokens(text, mention, offsets):
    start = text.find(mention)
    if start < 0:
        return []
    end = start + len(mention)
    indices = [i for i, (a, b) in enumerate(offsets.tolist()) if b > start and a < end and b > a]
    if not indices or int(offsets[indices[-1], 1]) < end:
        raise ValueError('incomplete mention token span')
    return indices


@torch.inference_mode()
def qualify(tokenizer, tower, sample, maximum, identity):
    texts = [r['input_text'] for r in sample]
    hs, mask, _ = hidden(tokenizer, tower, texts, maximum)
    checks = {}
    for i, text in enumerate(texts):
        single, _, _ = hidden(tokenizer, tower, [text], maximum)
        n = int(mask[i].sum())
        for depth in (6, 12, 18, 24):
            a, b = hs[depth][i, :n].float(), single[depth][0, :n].float()
            cosine = float(F.cosine_similarity(a.flatten(), b.flatten(), dim=0))
            rms = float((a-b).square().mean().sqrt() / b.square().mean().sqrt().clamp_min(1e-9))
            checks[f'{i}@{depth}'] = {'cosine': cosine, 'relative_rms': rms}
            if cosine < .999 or rms > .05:
                raise ValueError('padding invariance failed')
    if any(torch.equal(hs[a], hs[b]) for a, b in ((6,12), (12,18), (18,24))):
        raise ValueError('duplicate depth surfaces')
    return {'status': 'SUBSTRATE_QUALIFIED', 'revision': REVISION,
            'weight_identity': identity, 'padding': checks, 'maximum_context': maximum,
            'frozen': True, 'vision_used': False, 'chat_template_used': False}


@torch.inference_mode()
def extract_chunk(tokenizer, tower, chunk, maximum, batch_size):
    features, entities, entity_ids, absent = [], [], [], []
    lengths = []
    for first in range(0, len(chunk), batch_size):
        group = chunk[first:first+batch_size]
        hs, mask, offsets = hidden(tokenizer, tower, [r['input_text'] for r in group], maximum)
        for i, row in enumerate(group):
            n = int(mask[i].sum())
            lengths.append(n)
            final = hs[24][i, :n]
            features.append(torch.stack([final[-1].float(), final.float().mean(0),
                final[-16:].float().mean(0), *[hs[d][i,:n].float().mean(0)
                                            for d in (18,12,6)]]).half().cpu())
            ids, vectors = [], []
            for binding in row['bindings']:
                ids.append(binding['id'])
                ix = mention_tokens(row['input_text'], binding['name'], offsets[i])
                if ix:
                    vectors.append(final[ix].float().mean(0))
                else:
                    vectors.append(torch.zeros(1024, device='cuda'))
                    absent.append({'row_id': row['world_id'], 'entity_id': binding['id']})
            if len(set(ids)) != len(ids) or not ids:
                raise ValueError('invalid observable entity bindings')
            entity_ids.append(ids)
            entities.append(torch.stack(vectors).half().cpu())
    return {'row_ids': [r['world_id'] for r in chunk],
            'canonical_ids': [r['canonical_id'] for r in chunk],
            'revision': REVISION, 'row': torch.stack(features),
            'entities': entities, 'entity_ids': entity_ids, 'token_lengths': lengths}, absent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--batch-size', type=int, default=2)
    parser.add_argument('--smoke-only', action='store_true')
    args = parser.parse_args()
    torch.set_num_threads(4)
    handoff, handoff_sha = verify_handoff()
    preflight = json.loads((HERE / 'observable-preflight-v01.json').read_text())
    maximum = max(s['max_tokens'] for s in preflight['splits'].values())
    lock = {'revision': REVISION, 'handoff_v02_sha256': handoff_sha,
            'binding_sha256': sha(HERE / 'release-binding-v01.json'),
            'maximum_context': maximum, 'truncation': False, 'batch_size': args.batch_size,
            'model_files': {p.name: sha(p) for p in sorted(MODEL.iterdir()) if p.is_file()},
            'source_files': {p.name: sha(p) for p in (HERE/'extract.py', HERE/'runtime.py')},
            'evaluation_opened': False}
    OUT.mkdir(parents=True, exist_ok=True)
    lp = OUT / 'extraction-lock.json'
    if lp.exists():
        if json.loads(lp.read_text()) != lock:
            raise ValueError('changed extraction identity; preserve old run')
    else:
        receipt(lp, lock)
    tokenizer, tower, model_identity = load_model()
    sample_path = next(iter(handoff['splits']['TRAIN']['input_files']))
    sample = list(rows(ROOT / sample_path))[:2]
    qualification = qualify(tokenizer, tower, sample, maximum, model_identity)
    qp = OUT / 'substrate-qualification.json'
    if not qp.exists():
        receipt(qp, qualification)
    print(json.dumps(qualification), flush=True)
    if args.smoke_only:
        return
    started = time.perf_counter()
    for split in ('TRAIN', 'DEV'):
        done = 0
        for part, expected in handoff['splits'][split]['input_files'].items():
            if sha(ROOT / part) != expected:
                raise ValueError('changed public shard')
            shard = list(rows(ROOT / part))
            for first in range(0, len(shard), 64):
                chunk = shard[first:first+64]
                path = OUT / 'primitives' / split / f'{Path(part).stem.split(".")[0]}-{first:04d}.pt'
                path.parent.mkdir(parents=True, exist_ok=True)
                seal_path = path.with_suffix('.json')
                if path.exists():
                    sealed = json.loads(seal_path.read_text())
                    if sealed['row_ids'] != [r['world_id'] for r in chunk] or sha(path) != sealed['sha256']:
                        raise ValueError('resume chunk identity mismatch')
                else:
                    data, absent = extract_chunk(tokenizer, tower, chunk, maximum, args.batch_size)
                    torch.save(data, path)
                    receipt(seal_path, {'sha256': sha(path), 'row_ids': data['row_ids'],
                                       'absent_mentions_zeroed': absent})
                done += len(chunk)
                print(json.dumps({'split': split, 'rows_done': done,
                    'total': handoff['splits'][split]['rows'],
                    'seconds': round(time.perf_counter()-started, 1)}), flush=True)
    receipt(OUT/'extraction-complete.json', {'status': 'COMPLETE', 'seconds': time.perf_counter()-started,
            'rows': 30000, 'evaluation_opened': False})


if __name__ == '__main__':
    main()
