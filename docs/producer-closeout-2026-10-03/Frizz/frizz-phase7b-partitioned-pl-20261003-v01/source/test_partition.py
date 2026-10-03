import pytest
import torch

import partition


def make():
    mask = torch.tensor([[1, 1, 1, 1, 1, 1], [1, 1, 1, 1, 0, 0]], dtype=torch.bool)
    types = torch.tensor([[0, 0, 1, 0, 0, 1], [0, 0, 0, 0, 0, 0]])
    legal = torch.tensor([[1, 1, 0, 1, 0, 0], [1, 1, 0, 0, 0, 0]], dtype=torch.bool)
    sel = torch.tensor([0, 0])
    t = {'mask': mask, 'types': types, 'selected': sel, 'selected_eligible': torch.ones(2, dtype=torch.bool)}
    util = torch.tensor([[3, 2, 1, 4, 0, 5], [5, 4, 1, 0, 0, 0.]])
    return {'targets': t, 'legal': legal}, util


def test_pair_rates_and_orderings_hand_computed():
    D, util = make()
    out, vec = partition.partition_metrics(util, D)
    f = out['full']
    # root0: P1={0:3} P2={1:2, 3:4} P3={2:1, 4:0, 5:5};  root1: P1=5 P2={4} P3={1,0}
    assert vec['full:selected_gt_legal_other'].tolist() == pytest.approx([0.5, 1.0])
    assert vec['full:selected_gt_illegal'].tolist() == pytest.approx([2 / 3, 1.0])
    assert vec['full:legal_other_gt_illegal'].tolist() == pytest.approx([4 / 6, 1.0])
    assert f['selected_gt_legal_other']['pairs'] == 3 and f['selected_gt_legal_other']['roots'] == 2
    assert f['selected_gt_legal_other']['pooled'] == pytest.approx(2 / 3) and f['selected_gt_legal_other']['root_mean'] == pytest.approx(0.75)
    assert f['boundary_P1_over_P2'] == {'roots': 2, 'rate': 0.5}                 # root0 3>4 fails, root1 5>4 holds
    assert f['boundary_P2_over_P3'] == {'roots': 2, 'rate': 0.5}                 # root0 min2=2 > max3=5 fails; root1 4>1 holds
    assert f['strict_three_partition_ordering'] == {'roots': 2, 'rate': 0.5}
    assert f['reduced_full_ordering'] == {'roots': 2, 'rate': 0.5}
    # AUC of all legal (selected + legal-other) vs illegal: root0 legal {3,2,4} vs illegal {1,0,5}
    # legal {3,2,4} vs illegal {1,0,5}: 3>1,3>0 | 2>1,2>0 | 4>1,4>0 -> 6 of 9 pairs
    assert vec['full:legal_gt_illegal_auc'][0] == pytest.approx(6 / 9, abs=1e-6)


def test_same_type_universe_is_restricted_to_the_selected_type():
    D, util = make()
    out, vec = partition.partition_metrics(util, D)
    s = out['same_type']
    # root0 type 0 = {0,1,3,4}: P1=3, P2={2,4}, P3={0}; root1 all type 0, same as full
    assert vec['same_type:selected_gt_legal_other'].tolist() == pytest.approx([0.5, 1.0])
    assert vec['same_type:selected_gt_illegal'].tolist() == pytest.approx([1.0, 1.0])
    assert vec['same_type:legal_other_gt_illegal'].tolist() == pytest.approx([1.0, 1.0])
    assert s['boundary_P2_over_P3']['rate'] == 1.0 and s['boundary_P1_over_P2']['rate'] == 0.5


def test_reduced_sequence_when_a_partition_is_empty():
    mask = torch.ones(1, 4, dtype=torch.bool)
    D = {'targets': {'mask': mask, 'types': torch.zeros(1, 4, dtype=torch.long), 'selected': torch.tensor([0]),
                     'selected_eligible': torch.ones(1, dtype=torch.bool)},
         'legal': torch.tensor([[1, 0, 0, 0]], dtype=torch.bool)}                  # P2 empty: reduced sequence is P1 > P3
    out, _ = partition.partition_metrics(torch.tensor([[2.0, 1.0, 0.0, -1.0]]), D)
    f = out['full']
    assert f['boundary_P1_over_P2']['roots'] == 0 and f['boundary_P1_over_P3_when_P2_empty'] == {'roots': 1, 'rate': 1.0}
    assert f['reduced_full_ordering'] == {'roots': 1, 'rate': 1.0} and f['strict_three_partition_ordering']['roots'] == 0
    out2, _ = partition.partition_metrics(torch.tensor([[0.5, 1.0, 0.0, -1.0]]), D)
    assert out2['full']['reduced_full_ordering']['rate'] == 0.0
