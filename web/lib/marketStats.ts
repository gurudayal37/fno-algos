import fs from "fs";
import path from "path";

const STATS_FILE = path.join(process.cwd(), "data", "market_stats.json");

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

export interface LatestSession {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  prev_close: number | null;
  cc_return: number | null;
  oc_return: number;
}

export interface ReturnTypeStats {
  cc: PeriodStats; // close-to-close (overnight gap included)
  oc: PeriodStats; // open-to-close (intraday only)
}

export interface UnderlyingStats {
  date_range: string;
  latest: LatestSession;
  daily: ReturnTypeStats;
  weekly: ReturnTypeStats;
  monthly: ReturnTypeStats;
}

export interface MarketStats {
  NIFTY: UnderlyingStats;
  SENSEX: UnderlyingStats;
}

export function getMarketStats(): MarketStats | null {
  if (!fs.existsSync(STATS_FILE)) return null;
  const raw = fs.readFileSync(STATS_FILE, "utf-8");
  return JSON.parse(raw) as MarketStats;
}
