# Exposure v1

Purposes: generation, fit, selection, thresholding, diagnostic, terminal.
Each panel report contains all events, counts and the six-coordinate exposure vector.

POST /v1/panels/{id}/open authenticates actor and lab ownership, checks a scoped
grant and current stage authorization, commits ExposureOpened, then reads bytes.
ExposureClosed describes gateway delivery, not proof that a human read the response.
A lost response may overcount an opening conservatively; it cannot reveal unrecorded bytes.
Retrying the same intent returns the same event without a second opening.

Panel bytes in CAS remain inaccessible through ordinary actor download endpoints.
Master administration and direct filesystem access are outside guarded panel operation.
Such access must be explicitly logged and cannot be represented as qualified secrecy.
Remote bundles cannot bypass the panel gateway. Declaring a protected panel as
an input requires a prior opening for the same producer/run/stage. Input delivery
rechecks current authorization and exposure while holding the authority lock.
