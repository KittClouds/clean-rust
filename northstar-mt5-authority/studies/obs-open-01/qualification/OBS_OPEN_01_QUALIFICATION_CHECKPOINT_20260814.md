# OBS-OPEN-01 Qualification Checkpoint — 2026-08-14

## Outcome

The observer candidate is source-audited and compilable, and one current live
clock/source receipt is admitted. Substantive opening-range results remain
`FROZEN_UNOPENED`.

This checkpoint qualifies an instrument candidate and a current source instant.
It does not qualify historical New York-to-broker clock mappings, data coverage,
grammar behavior under replay, or any scientific finding about US30.

## Exact observer identities

- Source SHA-256: `d2c1f0614ba27289a87172dc9fa79f3b018cace73ebd5829afaf100aed406034`
- Pre-existing compiled candidate SHA-256: `5505e033d487037a9cc5863788b067123fbf5bc3e48d4c40ddfa0fbe721ac290`
- Pinned compiler: MetaEditor `5.0.0.6106`
- CLI compile pass 1: zero errors/warnings; SHA-256 `6876295d46e2c2f68aab8eba1e2a2241cfed35d308710c8d7b7ca6ba5aaa2939`
- CLI compile pass 2: zero errors/warnings; SHA-256 `7f9dfa5df190072e3fd44bd9c27caab5eec546b5d43fe9efbd811dc2f3f9b4e0`

The two successful CLI compiler outputs are not byte-identical and neither
reconstructs the archived pre-existing compiled candidate. Compile success,
source identity, compiled-artifact identity, and byte reconstruction therefore
remain separate claims. The terminal copy was restored to the archived
pre-existing compiled candidate after qualification.

## Current live clock receipt

The exact output is
`clock/OBS_OPEN_01_clock_probe_live.tsv`, SHA-256
`f8186f3948521a4653c84ebc0979a50fb6a0085b5edf3aa8b191af1c97dc941e`.

At the observed instant:

- source/server time: `2026-08-14 14:04:47`, UTC+03:00;
- UTC: `2026-08-14 11:04:47`;
- New York local time: `2026-08-14 07:04:47`, UTC-04:00;
- source time was seven hours ahead of New York.

Therefore the admitted civil target `09:30 America/New_York` mapped to `16:30`
source time at this instant, and `16:00 America/New_York` mapped to `23:00`
source time. The source candidate's default `09:30` server-time input is not an
admitted OBS-OPEN-01 setting.

This receipt proves only the observed live instant. It does not establish the
source/server UTC offset for historical sessions or across either jurisdiction's
DST transitions.

## Qualified source metadata

The receipt identifies `US30` as `US Wall Street 30 Index` on
`MetaQuotes-Demo`, with two digits, tick size `0.01`, and point `0.01`. It also
records the broker-reported weekly trade and quote sessions. Those sessions
describe source availability; they do not identify the New York cash-open clock.

## Blocking gates

The following must pass before substantive results can be opened:

1. historical session-specific clock mapping authority;
2. bounded US30 M1 and M5 source-coverage qualification;
3. R01-R30 causal construction golden suite;
4. interaction-grammar golden suite;
5. repeated bounded replay determinism;
6. frozen study-session universe and untouched confirmation blocks.

No economic or trading authority is granted.
