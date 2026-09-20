# AR-00H — Dynamic Planning Width

H freezes exact compound utility and varies planning width, schedule seed, and
the resource budget. Widths are 1 through 4. Every schedule is constructed by
greedily selecting deterministic random partitions that expose previously
uncovered coordinate pairs, so width is not confounded with a single lucky
partition.

The campaign has three views:

- equal update count: 3,000 outer epochs;
- equal candidate-evaluation budget: 10,000,000 compound candidates;
- equal pair-event budget: 4,096 jointly evaluated pair events.

Each width uses three frozen schedule seeds. Telemetry reports pair coverage per
planning step and per candidate evaluation, allowing higher-order joint
evaluation to be separated from simple relationship exposure.

This is engineering-only evidence. It does not establish a general optimizer
claim or any biological correspondence.
