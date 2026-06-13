import type { YearlyStat } from "@/lib/stats";

function fmtCurrency(n: number) {
  return `Rs. ${n.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

export default function YearlyReturnsTable({ years }: { years: YearlyStat[] }) {
  const maxAbsPnl = Math.max(1, ...years.map((y) => Math.abs(y.pnl)));

  return (
    <div className="overflow-x-auto rounded-lg border border-gray-800 bg-gray-900">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-800 text-left text-xs uppercase tracking-wide text-gray-400">
            <th className="px-4 py-3">Year</th>
            <th className="px-4 py-3">Net PnL</th>
            <th className="px-4 py-3">Trades</th>
            <th className="px-4 py-3">Wins</th>
            <th className="px-4 py-3">Losses</th>
            <th className="px-4 py-3">Win Rate</th>
            <th className="px-4 py-3">Bar</th>
          </tr>
        </thead>
        <tbody>
          {years.map((y) => {
            const positive = y.pnl >= 0;
            const widthPct = (Math.abs(y.pnl) / maxAbsPnl) * 100;
            return (
              <tr key={y.year} className="border-b border-gray-800 last:border-0">
                <td className="px-4 py-2 font-medium text-gray-100">{y.year}</td>
                <td className={`px-4 py-2 ${positive ? "text-emerald-400" : "text-red-400"}`}>
                  {fmtCurrency(y.pnl)}
                </td>
                <td className="px-4 py-2 text-gray-300">{y.trades}</td>
                <td className="px-4 py-2 text-emerald-400">{y.wins}</td>
                <td className="px-4 py-2 text-red-400">{y.losses}</td>
                <td className="px-4 py-2 text-gray-300">{y.winRate.toFixed(1)}%</td>
                <td className="px-4 py-2">
                  <div className="h-2 w-32 overflow-hidden rounded bg-gray-800">
                    <div
                      className={`h-full ${positive ? "bg-emerald-500" : "bg-red-500"}`}
                      style={{ width: `${widthPct}%` }}
                    />
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
