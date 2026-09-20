# AR-00J — On-Policy Fidelity

J freezes the six AR-00I width-2 scorers and audits each scorer on its own
training trajectory. An exact I0 trajectory runs in parallel as a reference;
the audit never changes runtime decisions.

At checkpoints it evaluates every pair opportunity with the exact 11x11 oracle
and records local regret, top-choice agreement, utility correlation/bias/error,
sign error, cross-block ranking accuracy, first divergence, cumulative regret,
loss gap, and parameter distance from the exact reference.

This is engineering-only evidence. It does not establish a general optimizer
claim or any biological correspondence.
