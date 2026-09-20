# AR-00I — Approximate Interaction Residual

I freezes width-2 planning and a deterministic broad-coverage schedule. It
changes only how the pair utility is scored:

- I0: exhaustive exact 11x11 compound utility;
- I1: additive singleton utility;
- I2: singleton utility plus one exact anchor cross-term;
- I3: conditional beam, keeping three singleton candidates on either side;
- I4: top-3 Cartesian beam;
- I5: deterministic sampled compounds with singleton-informed additions.

Every arm uses three frozen schedule seeds and 3,000 outer epochs. A shadow
audit replays sampled states from the exact I0 trajectory and reports exact
top-choice agreement, exact regret, and whether the approximation's selected
compound is actually improving.

This is engineering-only evidence. It does not establish a general optimizer
claim or any biological correspondence.
