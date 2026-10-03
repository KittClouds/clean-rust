from common import *

CONTRACT={
 'schema':'BANK_V4_TYPED_EPISODE_V1','identity':NAMESPACE,
 'scope':'fresh synthetic executable typed-decision curricula inspired by seven source libraries; not a replication of those benchmarks',
 'layers':['latent_world','observable_evidence','grounded_clause_state','transition_consequence','decision'],
 'counts':{'families':sum(BUDGET.values())*7,'roots':sum(BUDGET.values())*7*4,'renderings':sum(BUDGET.values())*7*8},
 'families_per_lane_split':BUDGET,'generation_seeds':SEEDS,
 'splits':'TRAIN acquisition; DEV selection; TRANSFER grouped new domain size/permission/schema regime. The same two lossless serialization views occur in all splits. TRANSFER is not a scientific confirmation bank.',
 'pairs':'two truth-changing state siblings, each full and partial observation; partial pairs share exact evidence when only the hidden slot changes; two lossless renderings',
 'targets':{'clause':['SATISFIED','VIOLATED','UNKNOWN'],'legality':['CERTAIN_LEGAL','CERTAIN_ILLEGAL','UNRESOLVED'],
   'permission':'distinct from environment legality','effects':'operator assignments vs actual changed slots incl time effects',
   'progress':'goal-count change and distance change are separate','distance':'exact action count or UNREACHABLE; never zero for unreachable',
   'cost':'exact environmental cost and policy-respecting cost separately','choice':'all optimal offered actions; selected label only singleton',
   'authority':'ACT only observable sufficient, legal, permitted, and optimal; WAIT legal never implies competent',
   'ASK':'hidden slot must change at least one offered candidate legality or permission; reveal resolves its uncertainty',
   'ABSTAIN':'decision mode with NONE action, no offered justified permitted goal-reaching action or goal already achieved; distinct from impossible world goal'},
 'masks':'partial canonical consequences/distance/optimal membership diagnostic only; all observable clause/status targets trainable',
 'entry_points':['observation_to_grounding','gold_grounding_to_consequence','gold_consequence_to_decision','integrated'],
 'fit_adequacy':'future model trials must prospectively register subset-fit, TRAIN ceiling/growth and saturation checks before architecture retirement; no model trial authorized here',
 'firewall':'public input files contain no world state or teacher output; targets are separate. Transfer construction truth access is recorded, not called untouched confirmation.',
 'custody':'protected TRANSFER targets must be separately registered and protected by Library access policy before confirmation use; directory separation alone is not escrow',
 'legacy':'v1/v3 semantics inform interfaces; zero historical rows imported to avoid exposure and old-label contamination',
 'nonclaims':['no E013 bank/protocol change','no learned-model accuracy claim','no real API/GUI execution claim','no 9x9 Sudoku or multi-crate Sokoban coverage claim'],
 'release_gates':['archetype operator qualification','full independent transition replay','observable completion replay','exact forward/backward distance agreement',
   'candidate permutation equivariance','hidden truth pair invariance','renderer roundtrip','group split separation',
   'structural overlap disclosure','full regeneration file equality','target masking','source and byte manifests','mutant rejection']}

if __name__=='__main__':write(OUT/'CONTRACT-v02.json',CONTRACT)
