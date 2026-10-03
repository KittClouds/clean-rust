"""Qualify frozen pinned Qwen text tower; extract text-only TRAIN/DEV surfaces."""
import argparse
import json
import time

import torch
import torch.nn.functional as F
from safetensors import safe_open
from transformers import AutoTokenizer, Qwen3_5ForConditionalGeneration

from common import MODEL, OUT, REVISION, BANK, OLD, HERE, SURFACES
from common import sha, receipt, old_ids, read_jsonl


def load_model():
    tokenizer = AutoTokenizer.from_pretrained(MODEL, local_files_only=True)
    tokenizer.padding_side = 'right'
    full, info = Qwen3_5ForConditionalGeneration.from_pretrained(
        MODEL, local_files_only=True, dtype=torch.bfloat16,
        attn_implementation='eager', output_loading_info=True)
    if info.get('missing_keys') or info.get('mismatched_keys') or info.get('unexpected_keys'):
        raise RuntimeError(f'checkpoint load identity failed: {info}')
    full.requires_grad_(False).eval()
    tower = full.model.language_model
    # Verify EVERY text-tower parameter, not merely successful wrapper construction.
    index = json.loads((MODEL / 'model.safetensors.index.json').read_text())['weight_map']
    worst = 0.0
    for filename in sorted(set(index.values())):
        with safe_open(MODEL / filename, framework='pt', device='cpu') as disk:
            for name, param in tower.named_parameters():
                key = 'model.language_model.' + name
                if index.get(key) != filename:
                    continue
                stored = disk.get_tensor(key).to(param.dtype)
                diff = float((stored.float() - param.detach().float()).abs().max())
                worst = max(worst, diff)
                if diff != 0:
                    raise RuntimeError(f'weight mismatch {key}: {diff}')
    checked = sum('model.language_model.' + n in index for n, _ in tower.named_parameters())
    if checked != len(list(tower.named_parameters())):
        raise RuntimeError('unverified text-tower parameter')
    tower.to('cuda')
    return tokenizer, tower, {'parameters_checked': checked, 'max_abs_diff': worst,
                              'text_parameters': sum(p.numel() for p in tower.parameters())}


@torch.inference_mode()
def hidden(tokenizer, tower, texts):
    batch = tokenizer(texts, padding=True, truncation=True, max_length=512,
                      return_tensors='pt', return_offsets_mapping=True)
    offsets = batch.pop('offset_mapping')
    batch = {k: v.cuda() for k, v in batch.items()}
    result = tower(**batch, use_cache=False, output_hidden_states=True)
    if result.hidden_states is None or len(result.hidden_states) != 25:
        raise RuntimeError('full 25-entry hidden stack required')
    if any(not torch.isfinite(result.hidden_states[d]).all() for d in (6, 12, 18, 24)):
        raise RuntimeError('non-finite hidden state')
    return result.hidden_states, batch['attention_mask'], offsets


def mention_tokens(text, mention, offsets):
    start = text.find(mention)
    if start < 0:
        raise ValueError(f'absent mention {mention}')
    end = start + len(mention)
    selected = [i for i, (a, b) in enumerate(offsets.tolist()) if b > start and a < end and b > a]
    if not selected or max(int(offsets[i, 1]) for i in selected) < end:
        raise ValueError(f'truncated or unresolved mention {mention}')
    return selected


@torch.inference_mode()
def qualify(tokenizer, tower, identity):
    texts = ['agent is in chamber_a. Goal: place onyx_object in chamber_c',
             'agent is in chamber_a. chamber_a connects to chamber_c. onyx_object is in chamber_a. '
             'switch_p is active. Goal: place onyx_object in chamber_c']
    hs, masks, _ = hidden(tokenizer, tower, texts)
    checks = {}
    for i, text in enumerate(texts):
        single, _, _ = hidden(tokenizer, tower, [text])
        n = int(masks[i].sum())
        for d in (6, 12, 18, 24):
            a, b = hs[d][i, :n].float(), single[d][0, :n].float()
            cosine = float(F.cosine_similarity(a.flatten(), b.flatten(), dim=0))
            rms = float((a-b).square().mean().sqrt()/b.square().mean().sqrt().clamp_min(1e-9))
            checks[f'{i}@{d}'] = {'cosine': cosine, 'relative_rms': rms}
            if cosine < .999 or rms > .05:
                raise RuntimeError(f'padding qualification failed {i}@{d}: {checks[f"{i}@{d}"]}')
    if any(torch.equal(hs[a], hs[b]) for a, b in ((6,12), (12,18), (18,24))):
        raise RuntimeError('depth outputs duplicated')
    return {'status': 'SUBSTRATE_QUALIFIED', 'model': 'Qwen/Qwen3.5-0.8B-Base',
            'revision': REVISION, 'weight_identity': identity, 'padding': checks,
            'hidden_stack_length': len(hs), 'hidden_width': hs[-1].shape[-1],
            'frozen': True, 'vision_used': False, 'chat_template_used': False}


@torch.inference_mode()
def extract(tokenizer, tower, split, batch_size):
    ids = old_ids(split)
    rows = read_jsonl(BANK / 'inputs' / f'{split}.jsonl', set(ids))
    folder = OUT / 'primitives' / split
    folder.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    for first in range(0, len(ids), 256):
        chunk_ids = ids[first:first+256]
        path = folder / f'{first:06d}.pt'
        if path.exists():
            old = torch.load(path, mmap=True, weights_only=False)
            if old['row_ids'] != chunk_ids or old['revision'] != REVISION:
                raise RuntimeError('chunk identity mismatch')
            if sha(path) != json.loads(path.with_suffix('.json').read_text())['sha256']:
                raise RuntimeError('chunk checksum mismatch')
            continue
        features, entities, entity_ids, missing_mentions = [], [], [], []
        for st in range(0, len(chunk_ids), batch_size):
            r = [rows[x] for x in chunk_ids[st:st+batch_size]]
            hs, mask, offsets = hidden(tokenizer, tower, [x['input_text'] for x in r])
            for i, row in enumerate(r):
                n = int(mask[i].sum())
                final = hs[24][i, :n]
                features.append(torch.stack([final[-1], final.float().mean(0),
                    final[-16:].float().mean(0), *[hs[d][i,:n].float().mean(0)
                                                 for d in (18,12,6)]]).half().cpu())
                bindings = row['bindings']
                eids = [b['entity_id'] for b in bindings]
                if len(set(eids)) != len(eids):
                    raise RuntimeError('duplicate entity binding')
                entity_ids.append(eids)
                vectors = []
                for b in bindings:
                    if b['mention'] not in row['input_text']:
                        # Inherited observable-only protocol: absent mention means zero.
                        # Never substitute a canonical name or latent-world entity text.
                        vectors.append(torch.zeros(final.shape[-1], device=final.device))
                        missing_mentions.append({'row_id':row['world_id'],
                            'entity_id':b['entity_id'],'mention':b['mention']})
                    else:
                        vectors.append(final[mention_tokens(row['input_text'],b['mention'],
                            offsets[i])].float().mean(0))
                entities.append(torch.stack(vectors).half().cpu())
        # Chunk extraction is restartable; receipt seals bytes before chunk becomes reusable.
        torch.save({'row_ids': chunk_ids, 'revision': REVISION,
                    'row': torch.stack(features), 'entities': entities,
                    'entity_ids': entity_ids}, path)
        receipt(path.with_suffix('.json'), {'sha256': sha(path), 'rows': len(chunk_ids),
                                           'absent_mentions_zeroed':missing_mentions})
        print(json.dumps({'split': split, 'rows_done': first+len(chunk_ids), 'total': len(ids),
                          'seconds': round(time.perf_counter()-started,1)}), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--qualify-only', action='store_true')
    ap.add_argument('--batch-size', type=int, default=8)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    # Pin model bytes and executable source before touching bank/model outputs.
    sources = [HERE/'common.py', HERE/'prepare.py'] + [OLD/'src'/f'{x}.py' for x in
               ('graft','ontology','objective','data')]
    files = list(MODEL.glob('*.safetensors')) + [MODEL/'config.json',MODEL/'tokenizer.json',
                                              MODEL/'tokenizer_config.json']
    lock = {'revision': REVISION, 'model_files': {str(x): sha(x) for x in files},
            'source_files': {str(x): sha(x) for x in sources},
            'bank_files': {str(BANK/k/f'{s}.jsonl'): sha(BANK/k/f'{s}.jsonl')
                           for k in ('inputs','worlds') for s in ('TRAIN','DEV')},
            'protected_test_opened': False}
    lp = OUT / 'prepare-lock.json'
    if lp.exists():
        if json.loads(lp.read_text()) != lock:
            raise RuntimeError('preparation identity changed; use a new version')
    else:
        receipt(lp, lock)
    tokenizer, tower, identity = load_model()
    qualification = qualify(tokenizer,tower,identity)
    qp = OUT/'substrate-qualification.json'
    if not qp.exists():
        receipt(qp, qualification)
    print(json.dumps(qualification), flush=True)
    if not args.qualify_only:
        for split in ('TRAIN','DEV'):
            extract(tokenizer,tower,split,args.batch_size)


if __name__ == '__main__':
    main()
