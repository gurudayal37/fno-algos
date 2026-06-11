import { notFound } from "next/navigation";
import { getAllStrategies, getStrategy } from "@/lib/data";
import SummaryCard from "@/components/SummaryCard";
import EquityCurveChart from "@/components/EquityCurveChart";
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

      <h2 className="mt-8 text-lg font-semibold text-gray-100">Equity Curve</h2>
      <div className="mt-3">
        <EquityCurveChart trades={trades} />
      </div>

      <h2 className="mt-8 text-lg font-semibold text-gray-100">Per-Expiry Trades</h2>
      <div className="mt-3">
        <TradesTable trades={trades} />
      </div>
    </div>
  );
}
