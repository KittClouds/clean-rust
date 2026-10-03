"""Safe default entry points; diagnostic hidden labels require explicit opt-in."""
import json
from pathlib import Path
from teacher import parse


def load(root, split, lane, entry='observation_to_grounding', allow_diagnostic=False):
    if entry not in ('observation_to_grounding', 'gold_grounding_to_consequence', 'gold_consequence_to_decision', 'integrated'):
        raise ValueError('UNKNOWN_ENTRY_POINT')
    directory = Path(root)/'corpus'/split/lane
    # Streams stay aligned by root identity; no unchecked positional target join.
    with (directory/'targets.jsonl').open(encoding='utf-8') as tf, (directory/'inputs.jsonl').open(encoding='utf-8') as inf:
        for target_line in tf:
            target = json.loads(target_line)
            for _ in range(2):
                row = json.loads(next(inf))
                if row['root_id'] != target['root_id']:
                    raise ValueError('TARGET_ALIGNMENT')
                frame = parse(row['input_text'], row['view'])
                labels = {'grounding': target['grounding'], 'decision': target['decision'],
                          'grounded_observation': target['grounded_observation'], 'goal_clauses': target['goal_clauses']}
                for field in ('canonical_consequences', 'canonical_optimal_actions', 'pairwise_consequence_coordinates'):
                    if allow_diagnostic or target['supervision_masks'][field]:
                        labels[field] = target[field]
                if entry == 'observation_to_grounding':
                    yield frame, {k: labels[k] for k in ('grounding', 'grounded_observation', 'goal_clauses')}
                elif entry == 'gold_grounding_to_consequence':
                    if 'canonical_consequences' in labels:
                        yield {'frame': frame, 'gold_grounding': labels['grounding'],
                               'gold_grounded_observation': labels['grounded_observation']}, {'consequences': labels['canonical_consequences']}
                elif entry == 'gold_consequence_to_decision':
                    if 'canonical_consequences' in labels:
                        yield {'candidate_consequences': labels['canonical_consequences']}, {'decision': labels['decision']}
                else:
                    yield frame, labels
        if next(inf, None) is not None:
            raise ValueError('EXTRA_INPUT_ROWS')
