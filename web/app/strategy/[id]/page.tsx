import { notFound } from "next/navigation";
import { getAllStrategies, getIntradayDates, getStrategy } from "@/lib/data";
import { computeExtendedStats, computeYearlyStats } from "@/lib/stats";
import SummaryCard from "@/components/SummaryCard";
import EquityCurveChart from "@/components/EquityCurveChart";
import DrawdownChart from "@/components/DrawdownChart";
import YearlyReturnsTable from "@/components/YearlyReturnsTable";
import TradesTable from "@/components/TradesTable";

function fmtCurrency(n: number) {
  return `Rs. ${n.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
}

export function generateStaticParams() {
  return getAllStrategies().map((s) => ({ id: s.id }));
}

export default function StrategyPage({ params }: { params: { id: string } }) {
  const strategy = getStrategy(params.id);
  if (!strategy) {
    notFound();
  }

  const { name, description, underlying, params: runParams, summary, trades } = strategy;
  const intradayDates = getIntradayDates(params.id);
  const stats = computeExtendedStats(trades);
  const yearlyStats = computeYearlyStats(trades);

  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-gray-400">{underlying}</div>
      <h1 className="mt-1 text-2xl font-semibold text-gray-100">{name}</h1>
      <p className="mt-1 text-gray-400">{description}</p>

      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-sm text-gray-400">
        <span>From: {String(runParams.from_date)}</span>
        <span>To: {String(runParams.to_date)}</span>
        <span>Entry: {String(runParams.entry_time)}</span>
        <span>Exit: {String(runParams.exit_time)}</span>
        {runParams.sl_pct != null && <span>Leg SL: {String(runParams.sl_pct)}</span>}
        {runParams.combined_sl_pct != null && <span>Combined SL: {String(runParams.combined_sl_pct)}</span>}
        {runParams.c2c ? <span>C2C: on</span> : null}
        <span>Slippage: {String(runParams.slippage_pct)}</span>
      </div>

      <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        <SummaryCard
          label="Total Net PnL"
          value={fmtCurrency(summary.total_net_pnl)}
          positive={summary.total_net_pnl >= 0}
          negative={summary.total_net_pnl < 0}
        />
        <SummaryCard label="Win Rate" value={`${summary.win_rate_pct.toFixed(1)}%`} />
        <SummaryCard
          label="Total Expiry Days"
          value={`${summary.total_expiry_days}`}
        />
        <SummaryCard
          label="Winning Days"
          value={`${summary.winning_expiry_days}`}
        />
        <SummaryCard
          label="Avg PnL / Expiry"
          value={fmtCurrency(summary.avg_net_pnl_per_expiry)}
          positive={summary.avg_net_pnl_per_expiry >= 0}
          negative={summary.avg_net_pnl_per_expiry < 0}
        />
        <SummaryCard
          label="Max Drawdown"
          value={fmtCurrency(summary.max_drawdown)}
          negative
        />
        <SummaryCard label="Sharpe Ratio" value={summary.sharpe_ratio.toFixed(2)} />
      </div>

      <h2 className="mt-8 text-lg font-semibold text-gray-100">
        Returns (on Rs. {stats.capitalBase.toLocaleString("en-IN")} capital)
      </h2>
      <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        <SummaryCard
          label="Total Return"
          value={`${stats.totalReturnPct.toFixed(2)}%`}
          positive={stats.totalReturnPct >= 0}
          negative={stats.totalReturnPct < 0}
        />
        <SummaryCard
          label="CAGR"
          value={`${stats.cagrPct.toFixed(2)}%`}
          positive={stats.cagrPct >= 0}
          negative={stats.cagrPct < 0}
        />
        <SummaryCard
          label="End Value"
          value={fmtCurrency(stats.capitalBase + stats.totalNetPnl)}
        />
      </div>

      <h2 className="mt-8 text-lg font-semibold text-gray-100">Risk &amp; Trade Stats</h2>
      <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        <SummaryCard label="No. of Trades" value={`${stats.numTrades}`} />
        <SummaryCard label="Wins" value={`${stats.numWins}`} positive />
        <SummaryCard label="Losses" value={`${stats.numLosses}`} negative />
        <SummaryCard
          label="Profit Factor"
          value={Number.isFinite(stats.profitFactor) ? stats.profitFactor.toFixed(2) : "∞"}
        />
        <SummaryCard
          label="Best Trade"
          value={fmtCurrency(stats.bestTrade)}
          positive={stats.bestTrade >= 0}
        />
        <SummaryCard
          label="Worst Trade"
          value={fmtCurrency(stats.worstTrade)}
          negative={stats.worstTrade < 0}
        />
        <SummaryCard
          label="Avg Win"
          value={fmtCurrency(stats.avgWin)}
          positive
        />
        <SummaryCard
          label="Avg Loss"
          value={fmtCurrency(stats.avgLoss)}
          negative
        />
        <SummaryCard
          label="Expectancy / Trade"
          value={fmtCurrency(stats.expectancy)}
          positive={stats.expectancy >= 0}
          negative={stats.expectancy < 0}
        />
        <SummaryCard
          label="Max Drawdown %"
          value={`${stats.maxDrawdownPct.toFixed(2)}%`}
          negative
        />
        <SummaryCard
          label="Max DD Duration"
          value={`${stats.maxDDDurationTrades} expiries`}
        />
        <SummaryCard
          label="Sortino Ratio"
          value={stats.sortinoRatio.toFixed(2)}
        />
        <SummaryCard
          label="Calmar Ratio"
          value={stats.calmarRatio.toFixed(2)}
        />
        <SummaryCard
          label="Annualized PnL"
          value={fmtCurrency(stats.annualizedPnl)}
          positive={stats.annualizedPnl >= 0}
          negative={stats.annualizedPnl < 0}
        />
        <SummaryCard label="Backtest Span" value={`${stats.years.toFixed(1)} yrs`} />
      </div>

      <h2 className="mt-8 text-lg font-semibold text-gray-100">Equity Curve</h2>
      <div className="mt-3">
        <EquityCurveChart trades={trades} />
      </div>

      <h2 className="mt-8 text-lg font-semibold text-gray-100">Drawdown</h2>
      <div className="mt-3">
        <DrawdownChart trades={trades} />
      </div>

      <h2 className="mt-8 text-lg font-semibold text-gray-100">Returns by Year</h2>
      <div className="mt-3">
        <YearlyReturnsTable years={yearlyStats} />
      </div>

      <h2 className="mt-8 text-lg font-semibold text-gray-100">Per-Expiry Trades</h2>
      <div className="mt-3">
        <TradesTable trades={trades} strategyId={params.id} intradayDates={intradayDates} />
      </div>
    </div>
  );
}
