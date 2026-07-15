// Pure statistical helpers — used in the /api/index-stats route.

export interface HistBin {
  bin_label: string;
  center: number;
  count: number;
  pct: number;
}

export interface ProbRow {
  threshold: number;
  p_abs: number;
  p_up: number;
  p_down: number;
}

export interface PeriodStats {
  count: number;
  mean: number;
  std: number;
  skew: number;
  kurt: number;
  positive_pct: number;
  p5: number;
  p25: number;
  p50: number;
  p75: number;
  p95: number;
  histogram: HistBin[];
  normal_curve: number[];
  prob_table: ProbRow[];
}

export interface IVRVPoint {
  date: string;
  rv21d: number | null;
  vix: number | null;
}

export interface StatsResponse {
  period: string;
  date_from: string;
  date_to: string;
  daily: PeriodStats;
  weekly: PeriodStats;
  monthly: PeriodStats;
  iv_rv_series: IVRVPoint[];
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function normPdf(x: number, mu: number, sigma: number): number {
  return (
    (1 / (sigma * Math.sqrt(2 * Math.PI))) *
    Math.exp(-0.5 * ((x - mu) / sigma) ** 2)
  );
}

function percentile(sorted: number[], p: number): number {
  const idx = (p / 100) * (sorted.length - 1);
  const lo = Math.floor(idx);
  const hi = Math.min(lo + 1, sorted.length - 1);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (idx - lo);
}

function mean(arr: number[]): number {
  return arr.reduce((a, b) => a + b, 0) / arr.length;
}

function stddev(arr: number[], mu: number): number {
  const variance =
    arr.reduce((a, b) => a + (b - mu) ** 2, 0) / (arr.length - 1);
  return Math.sqrt(variance);
}

function skewness(arr: number[], mu: number, sigma: number): number {
  return arr.reduce((a, b) => a + ((b - mu) / sigma) ** 3, 0) / arr.length;
}

function excessKurtosis(arr: number[], mu: number, sigma: number): number {
  return (
    arr.reduce((a, b) => a + ((b - mu) / sigma) ** 4, 0) / arr.length - 3
  );
}

function buildHistogram(
  returns: number[],
  binStart: number,
  binEnd: number,
  binStep: number,
  mu: number,
  sigma: number
): { histogram: HistBin[]; normal_curve: number[] } {
  const n = returns.length;
  const histogram: HistBin[] = [];
  const normalCurve: number[] = [];

  const push = (label: string, center: number, count: number) => {
    histogram.push({
      bin_label: label,
      center: +center.toFixed(4),
      count,
      pct: +((count / n) * 100).toFixed(2),
    });
    normalCurve.push(+(normPdf(center, mu, sigma) * binStep * n).toFixed(2));
  };

  // Underflow
  const under = returns.filter((r) => r < binStart).length;
  push(`<${binStart > 0 ? "+" : ""}${binStart.toFixed(1)}%`, binStart - binStep, under);

  // Regular bins
  let b = binStart;
  while (b < binEnd - 1e-9) {
    const lo = +b.toFixed(8);
    const hi = +(b + binStep).toFixed(8);
    const cnt = returns.filter((r) => r >= lo && r < hi).length;
    push(`${lo >= 0 ? "+" : ""}${lo.toFixed(2)}%`, (lo + hi) / 2, cnt);
    b = hi;
  }

  // Overflow
  const over = returns.filter((r) => r >= binEnd).length;
  push(`>${binEnd >= 0 ? "+" : ""}${binEnd.toFixed(1)}%`, binEnd + binStep, over);

  return { histogram, normal_curve: normalCurve };
}

// ── Public API ────────────────────────────────────────────────────────────────

export function computeStats(
  returns: number[],
  binStart: number,
  binEnd: number,
  binStep: number,
  thresholds: number[]
): PeriodStats {
  if (returns.length < 2) {
    return {
      count: returns.length,
      mean: 0, std: 0, skew: 0, kurt: 0,
      positive_pct: 0, p5: 0, p25: 0, p50: 0, p75: 0, p95: 0,
      histogram: [], normal_curve: [], prob_table: [],
    };
  }

  const mu  = mean(returns);
  const sig = stddev(returns, mu);
  const sorted = [...returns].sort((a, b) => a - b);

  const { histogram, normal_curve } = buildHistogram(returns, binStart, binEnd, binStep, mu, sig);

  const prob_table: ProbRow[] = thresholds.map((t) => ({
    threshold: t,
    p_abs:  +((returns.filter((r) => Math.abs(r) > t).length / returns.length) * 100).toFixed(1),
    p_up:   +((returns.filter((r) => r > t).length              / returns.length) * 100).toFixed(1),
    p_down: +((returns.filter((r) => r < -t).length             / returns.length) * 100).toFixed(1),
  }));

  return {
    count:        returns.length,
    mean:         +mu.toFixed(4),
    std:          +sig.toFixed(4),
    skew:         +skewness(returns, mu, sig).toFixed(3),
    kurt:         +excessKurtosis(returns, mu, sig).toFixed(3),
    positive_pct: +((returns.filter((r) => r > 0).length / returns.length) * 100).toFixed(1),
    p5:           +percentile(sorted, 5).toFixed(3),
    p25:          +percentile(sorted, 25).toFixed(3),
    p50:          +percentile(sorted, 50).toFixed(3),
    p75:          +percentile(sorted, 75).toFixed(3),
    p95:          +percentile(sorted, 95).toFixed(3),
    histogram,
    normal_curve,
    prob_table,
  };
}

/** Resample a daily close series to the last trading day per calendar week. */
export function toWeeklyReturns(
  dates: string[],
  closes: number[]
): number[] {
  const weekMap = new Map<string, number>();
  dates.forEach((d, i) => {
    const dt = new Date(d);
    const year = dt.getUTCFullYear();
    // ISO week number
    const thu = new Date(dt);
    thu.setUTCDate(dt.getUTCDate() + 4 - (dt.getUTCDay() || 7));
    const jan1 = new Date(Date.UTC(thu.getUTCFullYear(), 0, 1));
    const week = Math.ceil(((thu.getTime() - jan1.getTime()) / 86400000 + 1) / 7);
    weekMap.set(`${year}-W${String(week).padStart(2, "0")}`, closes[i]);
  });
  const sorted = [...weekMap.entries()].sort((a, b) =>
    a[0] < b[0] ? -1 : 1
  );
  const closeArr = sorted.map(([, c]) => c);
  return closeArr
    .slice(1)
    .map((c, i) => ((c / closeArr[i] - 1) * 100));
}

/** Resample to last trading day per calendar month. */
export function toMonthlyReturns(
  dates: string[],
  closes: number[]
): number[] {
  const monthMap = new Map<string, number>();
  dates.forEach((d, i) => {
    const key = d.slice(0, 7); // "YYYY-MM"
    monthMap.set(key, closes[i]);
  });
  const sorted = [...monthMap.entries()].sort((a, b) =>
    a[0] < b[0] ? -1 : 1
  );
  const closeArr = sorted.map(([, c]) => c);
  return closeArr
    .slice(1)
    .map((c, i) => ((c / closeArr[i] - 1) * 100));
}

/** Rolling 21-day realized vol (annualized %). Returns one value per date. */
export function rollingRV(closes: number[], window = 21): (number | null)[] {
  const logRets = closes.map((c, i) =>
    i === 0 ? null : Math.log(c / closes[i - 1])
  );
  return logRets.map((_, i) => {
    if (i < window) return null;
    const slice = logRets
      .slice(i - window + 1, i + 1)
      .filter((x): x is number => x !== null);
    if (slice.length < window - 1) return null;
    const mu = slice.reduce((a, b) => a + b, 0) / slice.length;
    const variance =
      slice.reduce((a, b) => a + (b - mu) ** 2, 0) / (slice.length - 1);
    return +( Math.sqrt(variance) * Math.sqrt(252) * 100 ).toFixed(2);
  });
}

/** Convert a period string to a UTC start date. */
export function periodToFromDate(period: string): Date {
  const now = new Date();
  const y = now.getUTCFullYear();
  const m = now.getUTCMonth();
  const d = now.getUTCDate();
  switch (period) {
    case "ytd": return new Date(Date.UTC(y, 0, 1));
    case "1m":  return new Date(Date.UTC(y, m, d - 30));
    case "3m":  return new Date(Date.UTC(y, m, d - 90));
    case "6m":  return new Date(Date.UTC(y, m - 6, d));
    case "1y":  return new Date(Date.UTC(y - 1, m, d));
    case "3y":  return new Date(Date.UTC(y - 3, m, d));
    case "5y":  return new Date(Date.UTC(y - 5, m, d));
    default:    return new Date(Date.UTC(2007, 0, 1)); // "all"
  }
}
