import Link from "next/link";
import { getAllStrategies } from "@/lib/data";

function fmtCurrency(n: number) {
  return `Rs. ${n.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

export default function Home() {
  const strategies = getAllStrategies();

  return (
    <div>
      <h1 className="text-2xl font-semibold text-gray-100">Strategies</h1>
      <p className="mt-1 text-gray-400">
        Backtest results for option trading strategies on NIFTY and SENSEX.
      </p>

      <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {strategies.map((s) => {
          const pnlPositive = s.summary.total_net_pnl >= 0;
          return (
            <Link
              key={s.id}
              href={`/strategy/${s.id}`}
              className="rounded-lg border border-gray-800 bg-gray-900 p-5 transition hover:border-gray-600"
            >
              <div className="text-xs uppercase tracking-wide text-gray-400">{s.underlying}</div>
              <div className="mt-1 text-lg font-semibold text-gray-100">{s.name}</div>
              <p className="mt-1 line-clamp-2 text-sm text-gray-400">{s.description}</p>

              <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
                <div>
                  <div className="text-gray-400">Total Net PnL</div>
                  <div className={pnlPositive ? "font-medium text-emerald-400" : "font-medium text-red-400"}>
                    {fmtCurrency(s.summary.total_net_pnl)}
                  </div>
                </div>
                <div>
                  <div className="text-gray-400">Win Rate</div>
                  <div className="font-medium text-gray-100">{s.summary.win_rate_pct.toFixed(1)}%</div>
                </div>
                <div>
                  <div className="text-gray-400">Sharpe</div>
                  <div className="font-medium text-gray-100">{s.summary.sharpe_ratio.toFixed(2)}</div>
                </div>
                <div>
                  <div className="text-gray-400">Max Drawdown</div>
                  <div className="font-medium text-red-400">{fmtCurrency(s.summary.max_drawdown)}</div>
                </div>
              </div>
            </Link>
          );
        })}
      </div>

      {strategies.length === 0 && (
        <div className="mt-8 rounded-lg border border-dashed border-gray-700 p-8 text-center text-gray-400">
          No strategy results found. Run a backtest with --export-web to populate this page.
        </div>
      )}
    </div>
  );
}
