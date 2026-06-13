import Link from "next/link";
import type { Trade } from "@/lib/data";

function fmt(n: number) {
  return n.toLocaleString("en-IN", { maximumFractionDigits: 2, minimumFractionDigits: 2 });
}

function pnlClass(n: number) {
  return n >= 0 ? "text-emerald-400" : "text-red-400";
}

interface TradesTableProps {
  trades: Trade[];
  strategyId: string;
  intradayDates: string[];
}

export default function TradesTable({ trades, strategyId, intradayDates }: TradesTableProps) {
  const intradaySet = new Set(intradayDates);

  return (
    <div className="overflow-x-auto rounded-lg border border-gray-800">
      <table className="min-w-full divide-y divide-gray-800 text-sm">
        <thead className="bg-gray-900 text-gray-400">
          <tr>
            <th className="px-3 py-2 text-left font-medium">Date</th>
            <th className="px-3 py-2 text-right font-medium">Lot Size</th>
            <th className="px-3 py-2 text-right font-medium">Strike</th>
            <th className="px-3 py-2 text-right font-medium">Spot Entry</th>
            <th className="px-3 py-2 text-right font-medium">CE Entry</th>
            <th className="px-3 py-2 text-right font-medium">CE Exit</th>
            <th className="px-3 py-2 text-left font-medium">CE Reason</th>
            <th className="px-3 py-2 text-right font-medium">PE Entry</th>
            <th className="px-3 py-2 text-right font-medium">PE Exit</th>
            <th className="px-3 py-2 text-left font-medium">PE Reason</th>
            <th className="px-3 py-2 text-right font-medium">Net PnL</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-800 bg-gray-950">
          {trades.map((t) => (
            <tr key={t.date}>
              <td className="px-3 py-2 whitespace-nowrap text-gray-300">
                {intradaySet.has(t.date) ? (
                  <Link
                    href={`/strategy/${strategyId}/expiry/${t.date}`}
                    className="text-blue-400 underline-offset-2 hover:underline"
                  >
                    {t.date}
                  </Link>
                ) : (
                  t.date
                )}
              </td>
              <td className="px-3 py-2 text-right text-gray-300">{t.lot_size}</td>
              <td className="px-3 py-2 text-right text-gray-300">{t.strike}</td>
              <td className="px-3 py-2 text-right text-gray-300">{fmt(t.spot_entry)}</td>
              <td className="px-3 py-2 text-right text-gray-300">{fmt(t.ce_entry)}</td>
              <td className="px-3 py-2 text-right text-gray-300">{fmt(t.ce_exit)}</td>
              <td className="px-3 py-2 whitespace-nowrap text-gray-400">{t.ce_exit_reason}</td>
              <td className="px-3 py-2 text-right text-gray-300">{fmt(t.pe_entry)}</td>
              <td className="px-3 py-2 text-right text-gray-300">{fmt(t.pe_exit)}</td>
              <td className="px-3 py-2 whitespace-nowrap text-gray-400">{t.pe_exit_reason}</td>
              <td className={`px-3 py-2 text-right font-medium ${pnlClass(t.total_net_pnl)}`}>
                {fmt(t.total_net_pnl)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
