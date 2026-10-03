# FORGE-RL-01 — Joint Wind Tunnel

`northstar-rl-broker` extends the inert FORGE-RL-00 environment with a read-only
broker observation and offline replay layer. It deliberately exposes no order,
modify, cancel, or position-command API. Northstar remains command authority.

## Authority boundaries

- Live TradeLocker GET responses establish capture authority.
- Normalized records plus raw-payload hashes are retained by default.
- Raw live provider bodies are not persisted without separate retention authority.
- Sealed `.nsb1` bytes establish automated offline replay authority.
- The joint fixture is synthetic contract evidence, not market evidence.
- MT5 and TradeLocker disagreement is preserved as typed comparison receipts.
- Learner execution remains prohibited.

## Commands

```text
northstar-rl broker status tradelocker
northstar-rl broker capture-live <artifact-dir>
northstar-rl broker instruments tradelocker
northstar-rl broker snapshot tradelocker
northstar-rl broker compare <northstar-instrument-id>
northstar-rl joint-qualify <artifact-dir>
```

Live calls require `NORTHSTAR_TRADELOCKER_SERVER` and use the existing Windows
Generic Credential alias (`Northstar/TradeLocker/live` by default). Optional
account selection uses exactly one of `NORTHSTAR_TRADELOCKER_ACCOUNT_ID` or
`NORTHSTAR_TRADELOCKER_ACC_NUM`. Secrets and tokens are zeroized and never
serialized or formatted.

## Topology

```text
MT5 capture ---------\
TradeLocker capture --+-> INSTRUMENT_BINDING_V1 -> typed tapes
RunRaw ---------------/                            |
                                                    v
WIND_TUNNEL_MODE_V1 -> Northstar environment ABI -> trajectory receipt
```

Every mode presents `reset -> observe -> apply_action -> advance -> receipt`.
The current qualification surface includes deterministic synthetic three-source
comparison and an authenticated TradeLocker capture. Live MT5 capture and live
cross-source clock/price matching remain explicitly partial.
