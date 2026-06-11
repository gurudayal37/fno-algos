import fs from "fs";
import path from "path";

const STRATEGIES_DIR = path.join(process.cwd(), "data", "strategies");

export interface StrategySummary {
  underlying: string;
  total_expiry_days: number;
  winning_expiry_days: number;
  win_rate_pct: number;
  total_net_pnl: number;
  max_drawdown: number;
  sharpe_ratio: number;
  avg_net_pnl_per_expiry: number;
}

export interface StrategyParams {
  [key: string]: string | number | boolean | null;
}

export interface StrategyIndexEntry {
  id: string;
  name: string;
  description: string;
  underlying: string;
  params: StrategyParams;
  summary: StrategySummary;
}

export interface Trade {
  date: string;
  underlying: string;
  strike: number;
  spot_entry: number;
  ce_entry: number;
  ce_exit: number;
  ce_exit_time: string;
  ce_exit_reason: string;
  ce_net_pnl: number;
  ce_costs: number;
  pe_entry: number;
  pe_exit: number;
  pe_exit_time: string;
  pe_exit_reason: string;
  pe_net_pnl: number;
  pe_costs: number;
  total_net_pnl: number;
  cum_pnl: number;
  peak: number;
  drawdown: number;
}

export interface StrategyDetail extends StrategyIndexEntry {
  trades: Trade[];
}

export interface IntradayCandle {
  time: string;
  spot: number;
  ce: number;
  pe: number;
  pnl: number;
  [key: string]: string | number;
}

export interface ExpiryDetail {
  date: string;
  strike: number;
  ce_entry: number;
  ce_exit: number;
  ce_exit_time: string;
  ce_exit_reason: string;
  pe_entry: number;
  pe_exit: number;
  pe_exit_time: string;
  pe_exit_reason: string;
  total_net_pnl: number;
  candles: IntradayCandle[];
}

export function getAllStrategies(): StrategyIndexEntry[] {
  const indexPath = path.join(STRATEGIES_DIR, "index.json");
  if (!fs.existsSync(indexPath)) {
    return [];
  }
  const raw = fs.readFileSync(indexPath, "utf-8");
  return JSON.parse(raw) as StrategyIndexEntry[];
}

export function getStrategy(id: string): StrategyDetail | null {
  const filePath = path.join(STRATEGIES_DIR, `${id}.json`);
  if (!fs.existsSync(filePath)) {
    return null;
  }
  const raw = fs.readFileSync(filePath, "utf-8");
  return JSON.parse(raw) as StrategyDetail;
}

export function getIntradayDates(strategyId: string): string[] {
  const indexPath = path.join(STRATEGIES_DIR, strategyId, "expiries", "index.json");
  if (!fs.existsSync(indexPath)) {
    return [];
  }
  const raw = fs.readFileSync(indexPath, "utf-8");
  return JSON.parse(raw) as string[];
}

export function getExpiryDetail(strategyId: string, date: string): ExpiryDetail | null {
  const filePath = path.join(STRATEGIES_DIR, strategyId, "expiries", `${date}.json`);
  if (!fs.existsSync(filePath)) {
    return null;
  }
  const raw = fs.readFileSync(filePath, "utf-8");
  return JSON.parse(raw) as ExpiryDetail;
}

export function getAllIntradayParams(): { id: string; date: string }[] {
  const params: { id: string; date: string }[] = [];
  for (const s of getAllStrategies()) {
    for (const date of getIntradayDates(s.id)) {
      params.push({ id: s.id, date });
    }
  }
  return params;
}
