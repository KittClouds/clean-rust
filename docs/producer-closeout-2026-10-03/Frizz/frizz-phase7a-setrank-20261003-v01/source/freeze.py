"""Freeze the experiment contract BEFORE any DEV scoring (create-only SPECIFICATION.json)."""
from common import OUT, RELEASE_IDENTITY, SOURCE, receipt, read, sha

CODE = ['common.py', 'data.py', 'model.py', 'losses.py', 'metrics.py', 'train.py', 'score.py', 'compare.py',
        'qualify.py', 'diagnostics.py', 'replay.py', 'seal.py', 'verify_inputs.py', 'test_setrank.py', 'freeze.py']


def main():
    receipt(OUT / 'SPECIFICATION.json', {
        'status': 'FROZEN_BEFORE_DEV_SCORING',
        'question': 'Does letting candidates explicitly see one another (full set self-attention) solve more of the ranking '
                    'problem than a matched independent per-candidate scorer?',
        'release_identity': RELEASE_IDENTITY,
        'input_identity_sha256': sha(OUT / 'INPUT-IDENTITY.json'),
        'source_hashes': {n: sha(SOURCE / n) for n in CODE + ['SPECIFICATION.md']},
        'architecture': {'input': '[cs 320; e 32; type one-hot 9; presence 4] = 365 -> Linear 128', 'blocks': 2, 'd_model': 128,
                         'heads': 4, 'head_dim': 32, 'ff': 256, 'norm': 'pre-LayerNorm + final LayerNorm', 'activation': 'GELU',
                         'positional_encoding': None, 'heads_out': ['utility 128->1', 'legality 128->1'],
                         'pointwise_control': 'attention sub-layer replaced by candidate-independent FFN(128->256->128)'},
        'training': {'seed': 0, 'epochs': 12, 'optimizer': 'AdamW', 'lr': 3e-4, 'weight_decay': 0.01, 'grad_clip': 1.0,
                     'schedule': 'cosine to 0, per step, no warmup', 'root_batch': 16, 'precision': 'FP32',
                     'loss_weights': {'selected_full_set_CE': 1.0, 'same_type_selected_CE': 0.5, 'legality_balanced_BCE': 0.25},
                     'candidate_permutation_augmentation': 'TRAIN, within root, dedicated seeded stream shared by both arms',
                     'standardisation': 'TRAIN-only per-dimension mean/std for c, s, e blocks; identical for both arms',
                     'primary_endpoint': 'epoch 12, scored on CPU/FP32', 'checkpoint_selection': 'none'},
        'expected_denominators': {'TRAIN_roots': 12000, 'DEV_roots': 3000, 'TRAIN_eligible': 1333, 'DEV_eligible': 333,
                                  'TRAIN_same_type_pairs': 11883, 'DEV_same_type_pairs': 3180, 'max_candidates': 171},
        'survival_rule': {'STRONG': 'gold-type top1 delta >= +0.05 and paired 95% bootstrap lower bound > 0',
                          'PRESERVE': 'not STRONG, but gold-type MRR delta >= +0.03 with lower bound > 0 and gold-type top1 delta point estimate >= 0',
                          'otherwise': 'FLAT_OR_NEGATIVE; seal without widening',
                          'confirmation': 'only if STRONG or PRESERVE: two further seeds, frozen specification, no redesign'},
        'bootstrap': {'unit': 'canonical root', 'repetitions': 2000, 'seed': 20261003},
        'paired_render_secondary_check': 'NOT RUN: no sealed paired-render state caches exist; Qwen is not regenerated',
        'not_included': ['Plackett-Luce', 'recurrence', 'LoRA', 'stochastic transitions', 'graph inference', 'access organ',
                         'gold legality as input or softmax mask', 'candidate IDs or positions as features'],
        'evaluation_opened': False, 'protected_opened': False})
    print('FROZEN')


if __name__ == '__main__':
    main()
