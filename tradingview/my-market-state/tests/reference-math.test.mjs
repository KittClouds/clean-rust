import assert from "node:assert/strict";
import test from "node:test";

function nestedTpo(lows, highs, bottom, step, rows) {
  const counts = Array(rows).fill(0);
  for (let row = 0; row < rows; row++) {
    const price = bottom + row * step;
    for (let bar = 0; bar < lows.length; bar++) {
      if (price >= lows[bar] && price <= highs[bar]) counts[row]++;
    }
  }
  return counts;
}

function differenceTpo(lows, highs, bottom, step, rows) {
  const diff = Array(rows + 1).fill(0);
  for (let bar = 0; bar < lows.length; bar++) {
    const first = Math.max(0, Math.min(rows - 1, Math.ceil((lows[bar] - bottom) / step - 1e-9)));
    const last = Math.max(0, Math.min(rows - 1, Math.floor((highs[bar] - bottom) / step + 1e-9)));
    if (first <= last) {
      diff[first]++;
      diff[last + 1]--;
    }
  }
  const counts = Array(rows).fill(0);
  let running = 0;
  for (let row = 0; row < rows; row++) {
    running += diff[row];
    counts[row] = running;
  }
  return counts;
}

function profileMetrics(counts, bottom, step, valueAreaPct) {
  const rows = counts.length;
  const top = bottom + (rows - 1) * step;
  const center = bottom + (top - bottom) / 2;
  let maxTpo = -1;
  let pocRow = 0;
  let bestCenterDistance = Infinity;
  for (let row = rows - 1; row >= 0; row--) {
    const distance = Math.abs(bottom + row * step - center);
    if (counts[row] > maxTpo || (counts[row] === maxTpo && distance < bestCenterDistance)) {
      maxTpo = counts[row];
      pocRow = row;
      bestCenterDistance = distance;
    }
  }
  const target = Math.trunc(counts.reduce((a, b) => a + b, 0) * valueAreaPct * 0.01);
  let tpoCount = counts[pocRow];
  let up = 1;
  let down = 1;
  while (tpoCount < target) {
    const above = pocRow + up;
    const below = pocRow - down;
    if ((below < 0 || (above < rows && counts[above] >= counts[below])) && above < rows) {
      tpoCount += counts[above];
      up++;
    } else if (below >= 0) {
      tpoCount += counts[below];
      down++;
    } else break;
  }
  const poc = bottom + pocRow * step;
  return { poc, vah: poc + up * step, val: poc - down * step + step };
}

function normalizedProfileWidths(counts, widthBars) {
  const maximum = Math.max(...counts);
  return counts.map((count) => count > 0 ? Math.max(1, Math.round(count / maximum * widthBars)) : 0);
}

test("difference-array TPO kernel equals the original nested price/bar scan", () => {
  const lows = [100, 101, 99, 103, 100];
  const highs = [103, 104, 102, 105, 100];
  assert.deepEqual(differenceTpo(lows, highs, 99, 1, 7), nestedTpo(lows, highs, 99, 1, 7));
});

test("POC tie resolves to the center-most row and keeps the higher exact tie", () => {
  const result = profileMetrics([1, 4, 2, 4, 1], 100, 1, 70);
  assert.equal(result.poc, 103);
});

test("value-area expansion prefers the row above when adjacent TPO counts tie", () => {
  const result = profileMetrics([1, 3, 5, 3, 1], 100, 1, 70);
  assert.deepEqual(result, { poc: 102, vah: 104, val: 101 });
});

test("profile rows stay inside a fixed viewport width while the POC row reaches full width", () => {
  const widths = normalizedProfileWidths([0, 1, 7, 20, 4], 24);
  assert.deepEqual(widths, [0, 1, 8, 24, 5]);
  assert.ok(widths.every((width) => width >= 0 && width <= 24));
});

test("high swing zone follows touch, rejection, then close-confirmed break", () => {
  const zone = { low: 104, high: 105, state: "fresh", touches: 0, rejections: 0 };
  const apply = ({ high, low, close }) => {
    if (zone.state === "broken") return;
    const overlaps = high >= zone.low && low <= zone.high;
    if (close > zone.high) zone.state = "broken";
    else if (overlaps) {
      zone.touches++;
      zone.state = close < zone.low ? "rejected" : "touched";
      if (close < zone.low) zone.rejections++;
    }
  };
  apply({ high: 104.5, low: 103.5, close: 104.2 });
  assert.equal(zone.state, "touched");
  apply({ high: 104.5, low: 103.0, close: 103.5 });
  assert.equal(zone.state, "rejected");
  apply({ high: 106, low: 104.5, close: 105.5 });
  assert.deepEqual(zone, { low: 104, high: 105, state: "broken", touches: 2, rejections: 1 });
});
