import type { Trade } from "./data";

export interface ExtendedStats {
  numTrades: number;
  numWins: number;
  numLosses: number;
  winRate: number;
  bestTrade: number;
  worstTrade: number;
  avgWin: number;
  avgLoss: number;
  profitFactor: number;
  expectancy: number;
  totalNetPnl: number;
  totalCosts: number;
  grossPnl: number;
  avgCostPerTrade: number;
  maxDrawdown: number;
  maxDrawdownPct: number;
  maxDDDurationTrades: number;
  sortinoRatio: number;
  calmarRatio: number;
  annualizedPnl: number;
  years: number;
  capitalBase: number;
  totalReturnPct: number;
  cagrPct: number;
}

export interface YearlyStat {
  year: string;
  pnl: number;
  trades: number;
  wins: number;
  losses: number;
  winRate: number;
}

export function computeExtendedStats(trades: Trade[], capitalBase = 100000): ExtendedStats {
  const numTrades = trades.length;
  const wins = trades.filter((t) => t.total_net_pnl > 0);
  const losses = trades.filter((t) => t.total_net_pnl <= 0);
  const numWins = wins.length;
  const numLosses = losses.length;
  const winRate = numTrades > 0 ? (numWins / numTrades) * 100 : 0;

  const pnls = trades.map((t) => t.total_net_pnl);
  const bestTrade = pnls.length > 0 ? Math.max(...pnls) : 0;
  const worstTrade = pnls.length > 0 ? Math.min(...pnls) : 0;

  const sumWins = wins.reduce((s, t) => s + t.total_net_pnl, 0);
  const sumLosses = losses.reduce((s, t) => s + t.total_net_pnl, 0);
  const avgWin = numWins > 0 ? sumWins / numWins : 0;
  const avgLoss = numLosses > 0 ? sumLosses / numLosses : 0;
  const profitFactor = sumLosses < 0 ? sumWins / Math.abs(sumLosses) : sumWins > 0 ? Infinity : 0;

  const totalNetPnl = trades.length > 0 ? trades[trades.length - 1].cum_pnl : 0;
  const expectancy = numTrades > 0 ? totalNetPnl / numTrades : 0;

  const totalCosts = trades.reduce((s, t) => s + (t.ce_costs ?? 0) + (t.pe_costs ?? 0), 0);
  const grossPnl = totalNetPnl + totalCosts;
  const avgCostPerTrade = numTrades > 0 ? totalCosts / numTrades : 0;

  // Max drawdown (absolute, already tracked per-trade) and as % of the peak it fell from
  let maxDrawdown = 0;
  let maxDrawdownPct = 0;
  for (const t of trades) {
    if (t.drawdown < maxDrawdown) {
      maxDrawdown = t.drawdown;
      maxDrawdownPct = t.peak !== 0 ? (t.drawdown / t.peak) * 100 : 0;
    }
  }

  // Longest drawdown streak, measured in number of trades from peak to new peak
  let maxDDDurationTrades = 0;
  let currentStreak = 0;
  for (const t of trades) {
    if (t.drawdown < 0) {
      currentStreak += 1;
      maxDDDurationTrades = Math.max(maxDDDurationTrades, currentStreak);
    } else {
      currentStreak = 0;
    }
  }

  // Sortino ratio: mean return over downside deviation, annualized for weekly trades
  const mean = pnls.length > 0 ? pnls.reduce((s, p) => s + p, 0) / pnls.length : 0;
  const downsideSqs = pnls.map((p) => (p < 0 ? p * p : 0));
  const downsideDev = pnls.length > 0 ? Math.sqrt(downsideSqs.reduce((s, p) => s + p, 0) / pnls.length) : 0;
  const sortinoRatio = downsideDev > 0 ? (mean / downsideDev) * Math.sqrt(52) : 0;

  // Annualized PnL based on the actual span of the backtest
  let years = 0;
  if (trades.length > 1) {
    const first = new Date(trades[0].date).getTime();
    const last = new Date(trades[trades.length - 1].date).getTime();
    years = (last - first) / (1000 * 60 * 60 * 24 * 365.25);
  }
  const annualizedPnl = years > 0 ? totalNetPnl / years : totalNetPnl;
  const calmarRatio = maxDrawdown < 0 ? annualizedPnl / Math.abs(maxDrawdown) : 0;

  // CAGR / total return relative to an assumed starting capital base
  const endValue = capitalBase + totalNetPnl;
  const totalReturnPct = (totalNetPnl / capitalBase) * 100;
  const cagrPct = years > 0 && endValue > 0 ? (Math.pow(endValue / capitalBase, 1 / years) - 1) * 100 : 0;

  return {
    numTrades,
    numWins,
    numLosses,
    winRate,
    bestTrade,
    worstTrade,
    avgWin,
    avgLoss,
    profitFactor,
    expectancy,
    totalNetPnl,
    totalCosts,
    grossPnl,
    avgCostPerTrade,
    maxDrawdown,
    maxDrawdownPct,
    maxDDDurationTrades,
    sortinoRatio,
    calmarRatio,
    annualizedPnl,
    years,
    capitalBase,
    totalReturnPct,
    cagrPct,
  };
}

export function computeYearlyStats(trades: Trade[]): YearlyStat[] {
  const byYear = new Map<string, Trade[]>();
  for (const t of trades) {
    const year = t.date.slice(0, 4);
    if (!byYear.has(year)) byYear.set(year, []);
    byYear.get(year)!.push(t);
  }

  const result: YearlyStat[] = [];
  for (const [year, yearTrades] of byYear) {
    const pnl = yearTrades.reduce((s, t) => s + t.total_net_pnl, 0);
    const wins = yearTrades.filter((t) => t.total_net_pnl > 0).length;
    const losses = yearTrades.filter((t) => t.total_net_pnl <= 0).length;
    result.push({
      year,
      pnl,
      trades: yearTrades.length,
      wins,
      losses,
      winRate: yearTrades.length > 0 ? (wins / yearTrades.length) * 100 : 0,
    });
  }
  return result.sort((a, b) => a.year.localeCompare(b.year));
}
