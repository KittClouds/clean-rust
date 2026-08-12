# My Market State

## Recommended build

[`my-market-state-first-principles.pine`](./my-market-state-first-principles.pine)
is the current, compact implementation. It combines the user-supplied LuxAlgo
cluster profile with the Kitt daily-swing state machine on one proven drawing
substrate:

- Fixed-lookback, volume-weighted K-means with one overlap-weighted volume
  profile and POC per cluster.
- Kitt D0–D4 supply/demand zones: latest repeated daily extreme wins;
  body-to-wick geometry; ROYGB age memory; intrabar, deduplicated touches; and
  close-confirmed rejection/break states. Broken zones remain until they age
  out.
- A screen-fixed cluster ledger containing POC, volume, share, price-relative
  role, distance, COG, nearest cluster, and overall market state.

Cluster histograms share one axis just beyond the latest bar and grow left.
Their POC tags therefore have one aligned X coordinate, and profile width no
longer depends on how much future chart whitespace happens to be visible. The
ledger defaults to the bottom-left corner so it does not collide with the
right-side profile stack.

It deliberately contains no `chart.left_visible_bar_time` or
`chart.right_visible_bar_time` dependency. Zooming therefore cannot select a
different calculation range or re-anchor its drawings. A new realtime bar moves
the fixed lookback forward by one bar, which is expected.

This derivative retains LuxAlgo attribution and is licensed under CC BY-NC-SA
4.0, matching the supplied sources.

## Legacy exact-port experiment

`my-market-state.pine` is the earlier Pine Script v6 overlay port of:

- VolKitt Iteration 2 v2.31 core and embedded TPO Market Profile.
- Kitt DailySwingZones 5-Day ROYGB v1.10.

The two MQL5 inputs total 6,310 lines. The Pine overlay is roughly 1,000 lines
because TradingView supplies the bar-series execution model, plots, alerts, and
drawing lifecycle that the MQL versions implement manually.

## Preserved contracts

- Volume-weighted K-means over candle midpoint, with sorted low-to-high cluster
  identity and remembered centroids.
- Per-cluster overlap-weighted price density and local POC selection.
- Global density center of gravity, standard-deviation field width, simple-mean
  true-range ATR, and ATR-per-bar COG velocity.
- Fresh/tested/accepted/rejected/broken/reclaimed cluster state transitions,
  acceptance counters, touch de-duplication, and motion/width/mass snapshots.
- ATR, outer-gap, and hybrid extreme-sentinel latching; broker-day, re-entry,
  and never-reset modes; fixed sentinel memory and promoted outer clusters.
- Five broker-day body-to-wick high/low zones, latest-candle extreme tie-break,
  touch/rejection counts, and close-confirmed rejection/break state.
- Daily, weekly, monthly, or four-window intraday TPO profiles; center-most POC
  tie-break; upper-first equal-TPO value-area expansion; developing levels;
  left-to-right/right-to-left rendering; and optional POC/VA rays.

## Pine-native adaptations

- TradingView exposes one `volume` series rather than MQL's selectable real vs.
  tick-volume pair. The available chart volume is used.
- Pine runs on bars/realtime updates, so MQL timer, object registry, tester, and
  redraw-throttle plumbing has no equivalent and is intentionally absent.
- The TPO calculation is mathematically equivalent but uses difference-array
  range additions: `O(bars + rows)` instead of the MQL `O(bars * rows)` scan.
- Pine limits a script to 500 boxes and 500 lines. The profile therefore uses
  one box per occupied price row and an adaptive tick multiple. `Price-step
  ticks` can force a specific MQL-like step when the resulting object count is
  safe.
- MQL's per-TPO time-gradient rectangles are collapsed to a per-row gradient.
  Profile shape, POC, VAH, VAL, and single-print rows remain represented.
- Profile widths are normalized to a fixed number of chart bars instead of
  multiplying raw TPO counts by bar duration. With `Lock drawings to visible
  window` enabled, TradingView's visible-left/right timestamps drive a redraw
  after every zoom or scroll; profile rows use bar-index coordinates while
  state lines, swing zones, and right-edge labels follow the visible window.
- User-drawn rectangle sessions and stop-at-first-intersection ray mutation are
  excluded because Pine scripts cannot inspect arbitrary user chart objects.
- The screenshot's Daily/Weekly/Monthly VWAP curves are not implemented because
  neither supplied source contains VWAP logic. They should remain a separate,
  explicitly specified layer until its source contract is provided.

## Use the recommended build

1. Open TradingView's Pine Editor.
2. Paste `my-market-state-first-principles.pine` into a new indicator.
3. Start with the defaults: 200 bars, five clusters, 20 profile rows, and a
   40-bar maximum profile width.
4. Zoom several times. Cluster dots, POC lines, and profiles should remain
   attached to the same candles; supply/demand zones remain attached to their
   Kitt daily-extreme source candles; the ledger stays fixed to its selected
   corner.
5. Change the lookback only after this anchor test passes on the target symbol
   and timeframe.

The calculation timeframe may be the chart timeframe or higher. Lower-timeframe
requests are rejected rather than silently sampling incomplete lower-timeframe
data.

## Local reference tests

```powershell
node --test .\tests\first-principles.test.mjs
node --test .\tests\reference-math.test.mjs
```

The first-principles tests cover volume-weighted centroid movement,
overlap-volume conservation, ledger roles, shared-axis profile geometry, and
Kitt body/wick, state-transition, and repeated-extreme contracts. The legacy
tests preserve the older TPO and swing-zone contracts.
