# Official Platform Sources Used During Qualification

Accessed 2026-08-14. These sources qualify platform behavior only. They do not
provide substantive evidence about US30 opening-range behavior.

## Strategy Tester time semantics

Source: <https://www.mql5.com/en/docs/runtime/testing>

The official Strategy Tester documentation states that `TimeLocal()`,
`TimeTradeServer()`, and `TimeGMT()` are equal to simulated server time during
testing. Therefore a tester replay cannot independently recover the historical
UTC offset of the source server from those functions.

## Live trade-server time semantics

Source: <https://www.mql5.com/en/docs/dateandtime/timetradeserver>

The official `TimeTradeServer()` documentation describes the value as a
calculated current trade-server time and notes that it equals `TimeCurrent()` in
the Strategy Tester. OBS-OPEN-01 consequently treats its live value as a
current-instant receipt, not historical timezone authority.

## Broker-reported symbol sessions

Source: <https://www.mql5.com/en/docs/marketinformation/symbolinfosessiontrade>

The official `SymbolInfoSessionTrade()` documentation defines the returned
begin/end values as symbol trade-session times for a day of week. OBS-OPEN-01
records those values as source-availability metadata. They do not independently
identify the New York civil cash-open timestamp.
