# DH-07R post hoc trajectory audit

This analysis reads the sealed DH-07R outputs and adds no samples or simulator executions. Its intervals are descriptive because trajectory timing was not a primary endpoint.

The true-minus-null behavioral difference first has a descriptive 95% t interval excluding zero at trial **32** with parallel off and **32** with parallel on. Acquisition-axis divergence resolves at trial **32** off and **16** on.

At trial 256, parallel-off true-minus-null old-map margin is **+0.003474** while acquisition-coordinate difference is **+0.003369**. Parallel-on margin is **+0.004507**, accompanied by a much larger acquisition-coordinate difference of **+0.086876**.

The parallel-on axis difference is already resolved at trial 16, before the old-map margin difference resolves at trial 32. The DH-07R primary therefore identifies an adaptive direction-replacement policy effect. It does not isolate a final behavior effect at matched cumulative acquisition-axis position.

The next experiment should branch true and matched-null endpoints from one identical state, probe immediately with learning disabled, discard both branches, and continue a canonical trajectory. That impulse design prevents the intervention from changing the state from which future updates are generated.
