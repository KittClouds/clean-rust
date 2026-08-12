import assert from "node:assert/strict";
import test from "node:test";

function weightedKmeans(prices, volumes, k, passes = 20) {
  const minimum = Math.min(...prices);
  const maximum = Math.max(...prices);
  const step = (maximum - minimum) / (k + 1);
  const centroids = Array.from({ length: k }, (_, i) => minimum + (i + 1) * step);
  const assignments = Array(prices.length).fill(0);
  for (let pass = 0; pass < passes; pass++) {
    for (let i = 0; i < prices.length; i++) {
      let best = 0;
      for (let c = 1; c < k; c++) {
        if (Math.abs(prices[i] - centroids[c]) < Math.abs(prices[i] - centroids[best])) best = c;
      }
      assignments[i] = best;
    }
    const weightedPrices = Array(k).fill(0);
    const weights = Array(k).fill(0);
    for (let i = 0; i < prices.length; i++) {
      weightedPrices[assignments[i]] += prices[i] * volumes[i];
      weights[assignments[i]] += volumes[i];
    }
    for (let c = 0; c < k; c++) if (weights[c] > 0) centroids[c] = weightedPrices[c] / weights[c];
  }
  return { assignments, centroids };
}

function distributeByOverlap(candleLow, candleHigh, candleVolume, profileLow, binSize, rows) {
  const bins = Array(rows).fill(0);
  const candleRange = Math.max(candleHigh - candleLow, Number.EPSILON);
  for (let bin = 0; bin < rows; bin++) {
    const bottom = profileLow + bin * binSize;
    const top = bottom + binSize;
    const overlap = Math.max(0, Math.min(candleHigh, top) - Math.max(candleLow, bottom));
    bins[bin] += candleVolume * overlap / candleRange;
  }
  return bins;
}

function roleFor(price, poc, clusterLow, clusterHigh) {
  if (price >= clusterLow && price <= clusterHigh) return "ACTIVE";
  return poc < price ? "DEMAND" : "SUPPLY";
}

function leftFacingRow(axis, width) {
  return { left: axis - width, right: axis };
}

function kittZone(supply, { time, open, high, low, close }) {
  return {
    supply,
    sourceTime: time,
    top: supply ? high : Math.min(open, close),
    bottom: supply ? Math.max(open, close) : low,
    extreme: supply ? high : low,
    state: "FRESH",
    touches: 0,
    rejections: 0,
    lastTouchTime: null,
  };
}

function applyKittClosed(zone, bar) {
  if (zone.state === "BROKEN" || bar.time <= zone.sourceTime) return;
  const overlaps = bar.high >= zone.bottom && bar.low <= zone.top;
  const broken = zone.supply ? bar.close > zone.top : bar.close < zone.bottom;
  if (broken) {
    zone.state = "BROKEN";
    return;
  }
  if (!overlaps) return;
  if (zone.lastTouchTime !== bar.time) {
    zone.lastTouchTime = bar.time;
    zone.touches++;
    if (zone.state === "FRESH") zone.state = "TOUCHED";
  }
  const rejected = zone.supply ? bar.close < zone.bottom : bar.close > zone.top;
  if (rejected) {
    zone.rejections++;
    zone.state = "REJECTED";
  }
}

test("volume weighting pulls a centroid toward the high-volume price", () => {
  const result = weightedKmeans([100, 101, 110, 111], [1, 9, 1, 1], 2);
  assert.deepEqual(result.assignments, [0, 0, 1, 1]);
  assert.equal(result.centroids[0], 100.9);
  assert.equal(result.centroids[1], 110.5);
});

test("overlap-weighted profile conserves candle volume", () => {
  const bins = distributeByOverlap(100, 104, 1_000, 100, 1, 4);
  assert.deepEqual(bins, [250, 250, 250, 250]);
  assert.equal(bins.reduce((sum, value) => sum + value, 0), 1_000);
});

test("ledger roles are price-relative and ACTIVE wins inside the cluster span", () => {
  assert.equal(roleFor(106, 102, 100, 104), "DEMAND");
  assert.equal(roleFor(98, 102, 100, 104), "SUPPLY");
  assert.equal(roleFor(103, 102, 100, 104), "ACTIVE");
});

test("every profile row shares one right axis and grows left", () => {
  const rows = [1, 7, 40].map((width) => leftFacingRow(1_004, width));
  assert.deepEqual(rows, [
    { left: 1_003, right: 1_004 },
    { left: 997, right: 1_004 },
    { left: 964, right: 1_004 },
  ]);
  assert.ok(rows.every((row) => row.left <= row.right && row.right === 1_004));
});

test("Kitt zones use body-to-wick geometry", () => {
  const candle = { time: 1, open: 101, high: 105, low: 97, close: 103 };
  assert.deepEqual(kittZone(true, candle), {
    supply: true, sourceTime: 1, top: 105, bottom: 103, extreme: 105,
    state: "FRESH", touches: 0, rejections: 0, lastTouchTime: null,
  });
  assert.deepEqual(kittZone(false, candle), {
    supply: false, sourceTime: 1, top: 101, bottom: 97, extreme: 97,
    state: "FRESH", touches: 0, rejections: 0, lastTouchTime: null,
  });
});

test("Kitt high zone progresses through touch, rejection, then close-confirmed break", () => {
  const zone = kittZone(true, { time: 1, open: 103, high: 105, low: 102, close: 104 });
  applyKittClosed(zone, { time: 2, high: 104.5, low: 103.5, close: 104 });
  assert.equal(zone.state, "TOUCHED");
  applyKittClosed(zone, { time: 3, high: 104, low: 101, close: 102 });
  assert.equal(zone.state, "REJECTED");
  applyKittClosed(zone, { time: 4, high: 106, low: 104, close: 105.5 });
  assert.deepEqual({ state: zone.state, touches: zone.touches, rejections: zone.rejections },
    { state: "BROKEN", touches: 2, rejections: 1 });
});

test("equal daily extremes select the later source candle", () => {
  const current = { extreme: 105, sourceTime: 10 };
  const candidate = { extreme: 105, sourceTime: 20 };
  const replace = candidate.extreme > current.extreme ||
    (candidate.extreme === current.extreme && candidate.sourceTime > current.sourceTime);
  assert.equal(replace, true);
});
