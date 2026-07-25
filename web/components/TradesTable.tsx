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
  const intradaySet    = new Set(intradayDates);
  const isIC           = trades.length > 0 && trades[0].long_ce !== undefined;
  const isStrangle     = !isIC && trades.length > 0 && trades[0].ce_strike !== undefined;
  const isPositional   = isStrangle && trades.length > 0 && trades[0].exit_date !== undefined;

  return (
    <div className="overflow-x-auto rounded-lg border border-gray-800">
      <table className="min-w-full divide-y divide-gray-800 text-sm">
        <thead className="bg-gray-900 text-gray-400">
          <tr>
            <th className="px-3 py-2 text-left font-medium">{isPositional ? "Entry → Exit" : "Date"}</th>
            <th className="px-3 py-2 text-right font-medium">Lot</th>
            {isIC ? (
              <>
                <th className="px-3 py-2 text-right font-medium">PE Long</th>
                <th className="px-3 py-2 text-right font-medium">PE Short</th>
                <th className="px-3 py-2 text-right font-medium">CE Short</th>
                <th className="px-3 py-2 text-right font-medium">CE Long</th>
                <th className="px-3 py-2 text-right font-medium">Net Credit</th>
              </>
            ) : isStrangle ? (
              <>
                <th className="px-3 py-2 text-right font-medium">CE Strike</th>
                <th className="px-3 py-2 text-right font-medium">PE Strike</th>
              </>
            ) : (
              <th className="px-3 py-2 text-right font-medium">Strike</th>
            )}
            <th className="px-3 py-2 text-right font-medium">Spot</th>
            {!isIC && (
              <>
                <th className="px-3 py-2 text-right font-medium">CE Entry</th>
                <th className="px-3 py-2 text-right font-medium">CE Exit</th>
                <th className="px-3 py-2 text-left font-medium">CE Reason</th>
                <th className="px-3 py-2 text-right font-medium">PE Entry</th>
                <th className="px-3 py-2 text-right font-medium">PE Exit</th>
                <th className="px-3 py-2 text-left font-medium">PE Reason</th>
              </>
            )}
            {isIC && (
              <th className="px-3 py-2 text-left font-medium">Exit Reason</th>
            )}
            {isPositional && <th className="px-3 py-2 text-left font-medium">Expiry</th>}
            {isPositional && <th className="px-3 py-2 text-left font-medium">Src</th>}
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
                {isPositional && t.exit_date && (
                  <span className="text-gray-500"> → {t.exit_date}</span>
                )}
              </td>
              <td className="px-3 py-2 text-right text-gray-300">{t.lot_size}</td>

              {isIC ? (
                <>
                  <td className="px-3 py-2 text-right text-gray-500">{t.long_pe}</td>
                  <td className="px-3 py-2 text-right text-gray-300">{t.pe_strike}</td>
                  <td className="px-3 py-2 text-right text-gray-300">{t.ce_strike}</td>
                  <td className="px-3 py-2 text-right text-gray-500">{t.long_ce}</td>
                  <td className="px-3 py-2 text-right text-blue-300 font-medium">
                    {t.net_credit != null ? fmt(t.net_credit) : "—"}
                  </td>
                </>
              ) : isStrangle ? (
                <>
                  <td className="px-3 py-2 text-right text-gray-300">{t.ce_strike}</td>
                  <td className="px-3 py-2 text-right text-gray-300">{t.pe_strike}</td>
                </>
              ) : (
                <td className="px-3 py-2 text-right text-gray-300">{t.strike}</td>
              )}

              <td className="px-3 py-2 text-right text-gray-300">{fmt(t.spot_entry)}</td>

              {!isIC && (
                <>
                  <td className="px-3 py-2 text-right text-gray-300">{fmt(t.ce_entry)}</td>
                  <td className="px-3 py-2 text-right text-gray-300">{fmt(t.ce_exit)}</td>
                  <td className="px-3 py-2 whitespace-nowrap text-gray-400">{t.ce_exit_reason}</td>
                  <td className="px-3 py-2 text-right text-gray-300">{fmt(t.pe_entry)}</td>
                  <td className="px-3 py-2 text-right text-gray-300">{fmt(t.pe_exit)}</td>
                  <td className="px-3 py-2 whitespace-nowrap text-gray-400">{t.pe_exit_reason}</td>
                </>
              )}

              {isIC && (
                <td className="px-3 py-2 whitespace-nowrap text-gray-400">{t.ce_exit_reason}</td>
              )}

              {isPositional && (
                <td className="px-3 py-2 whitespace-nowrap text-gray-500 text-xs">{t.expiry_date ?? "—"}</td>
              )}
              {isPositional && (
                <td className="px-3 py-2 whitespace-nowrap text-xs">
                  {t.entry_src?.includes("BS") ? (
                    <span className="rounded bg-yellow-900/40 px-1 py-0.5 text-yellow-400">BS</span>
                  ) : (
                    <span className="rounded bg-emerald-900/40 px-1 py-0.5 text-emerald-400">REAL</span>
                  )}
                </td>
              )}

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
