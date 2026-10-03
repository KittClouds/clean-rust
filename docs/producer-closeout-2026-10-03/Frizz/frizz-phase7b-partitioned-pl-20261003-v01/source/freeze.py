"""Freeze the experiment contract BEFORE any DEV scoring (create-only SPECIFICATION.json)."""
from common import OUT, RELEASE_IDENTITY, SOURCE, receipt, read, sha

CODE = ['common.py', 'data.py', 'model.py', 'pl.py', 'losses.py', 'partition.py', 'metrics.py', 'train.py', 'score.py', 'compare.py',
        'qualify.py', 'replay.py', 'seal.py', 'verify_inputs.py', 'freeze.py', 'test_pl.py', 'test_arms.py', 'test_partition.py']


def main():
    receipt(OUT / 'SPECIFICATION.json', {
        'status': 'FROZEN_BEFORE_DEV_SCORING',
        'question': 'Does training the scorer on the actual ordered partition structure recover more useful candidate ranking '
                    'than ordinary selected-candidate CE?',
        'release_identity': RELEASE_IDENTITY,
        'input_identity_sha256': sha(OUT / 'INPUT-IDENTITY.json'),
        'source_hashes': {n: sha(SOURCE / n) for n in CODE + ['SPECIFICATION.md']},
        'arms': {'ce': 'selected-candidate softmax CE + same-type CE (control)',
                 'vanilla_pl': 'ListMLE on a fresh uniformly random linear extension of the partition order (selected > legal-other > illegal)',
                 'partitioned_pl': 'exact grouped Plackett-Luce likelihood of P1 > P2 > P3, internal orders marginalised, + same-type',
                 'vanilla_pl_truncated (supplementary, outside the survival rule)': 'ListMLE on a random linear extension kept through the legal candidates only'},
        'scorer': '365 -> 128 -> 64 -> 1, GELU, candidate-independent, 55,169 parameters, shared initial weights',
        'population': 'endpoint-eligible roots only: TRAIN 1,333, DEV 333',
        'training': {'seed': 0, 'epochs': 12, 'optimizer': 'AdamW', 'lr': 3e-4, 'weight_decay': 0.01, 'grad_clip': 1.0,
                     'schedule': 'cosine to 0, per step, no warmup', 'root_batch': 32, 'precision': 'FP32',
                     'loss_weights': {'full': 1.0, 'same_type': 0.5}, 'candidate_order': 'canonical, shared', 'primary_endpoint': 'epoch 12 (CPU/FP32)',
                     'checkpoint_selection': 'none'},
        'expected_denominators': {'TRAIN_eligible': 1333, 'DEV_eligible': 333, 'TRAIN_roots': 12000, 'DEV_roots': 3000,
                                  'max_legal_other_group': 8},
        'survival_rule': {'SURVIVES': 'gold-type top1 delta >= +0.05 with paired 95% lower bound > 0, OR gold-type MRR delta >= +0.03 with lower bound > 0, '
                                      'AND selected top1 point-estimate delta >= -0.02',
                          'otherwise': 'DOES_NOT_SURVIVE; seal without modifying partitions/weights/auxiliaries',
                          'confirmation': 'seeds 1 and 2 under this frozen specification only if SURVIVES'},
        'bootstrap': {'unit': 'canonical root', 'repetitions': 2000, 'seed': 20261003},
        'not_included': ['candidate self-attention', 'recurrence', 'comparator', 'LoRA', 'access organ', 'legality head / BCE',
                         'gold legality at inference', 'transition distance or simulator state as inputs'],
        'evaluation_opened': False, 'protected_opened': False})
    print('FROZEN')


if __name__ == '__main__':
    main()
