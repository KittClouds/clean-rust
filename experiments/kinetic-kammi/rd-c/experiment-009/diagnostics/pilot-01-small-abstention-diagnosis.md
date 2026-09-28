# E009 pilot 01 — small observer abstention diagnosis

Source: preserved `lane-small/*.json` call records and the unchanged E002 thresholds in the pilot run lock. The pilot results are not altered.

| Task family | Proposed action | Applicability | Abstention | Fixed minimum applicability | Fixed maximum abstention | Compiled result | Task check |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| Embedding length-batched execution | 51 | 95/1000 | 0/1000 | 700/1000 | 600/1000 | Rejected as below applicability threshold; large fallback ran | Action 51 passes both frozen checks |
| Asynchronous GPU picking | null | 0/1000 | 0/1000 | 700/1000 | 600/1000 | No action proposed; large fallback ran | No small-lane task action |

The embedding choice is the passing patch, but its applicability score is 7.4 times below the unchanged threshold. The GPU response is internally inconsistent with the prompt: it returns no action and zero abstention. Neither response is near a threshold boundary. The trace is consistent with poorly used or poorly calibrated score fields; it does not establish which explanation is responsible.

The small observer therefore took the direct-action path on 0/2 pilot tasks and the hybrid called the large observer on 2/2. Threshold fitting will use only the new development split. These two pilot observations are not threshold-training examples.
