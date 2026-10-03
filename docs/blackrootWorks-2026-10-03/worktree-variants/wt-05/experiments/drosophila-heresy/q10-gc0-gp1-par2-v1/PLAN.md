# Q10-GC0-GP1-PAR2: Group-Granular Parallel Palette

PAR2 preserves the GP1 exact candidate semantics and uses four endpoint/set
workers, but schedules one raw group per task. Each worker caches its loaded
endpoint/set state and authority table; the parent streams one completed group
receipt immediately. This is a scheduling and observability correction after
the endpoint/set worker was found too coarse for durable progress.

The candidate horizon, replay ceiling, beam, geometry rules, authority ranking,
prefix identity, and exact sequential-f32 evaluator are unchanged. PAR2 is
engineering-only and does not run global assembly, GC1, behavior, or science.
