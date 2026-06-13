import type { MonthlyRow } from "@/lib/stats";
import { MONTH_KEYS, MONTH_LABELS } from "@/lib/stats";

function fmtCurrency(n: number) {
  return n.toLocaleString("en-IN", { maximumFractionDigits: 0 });
}

function cellColor(v: number | null | undefined) {
  if (v == null) return "text-gray-500";
  if (v > 0) return "text-emerald-400";
  if (v < 0) return "text-red-400";
  return "text-gray-300";
}

export default function MonthlyReturnsTable({ rows }: { rows: MonthlyRow[] }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-gray-800 bg-gray-900">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-800 bg-gray-800/60 text-left text-xs uppercase tracking-wide text-gray-300">
            <th className="px-3 py-3 sticky left-0 bg-gray-800/60">Year</th>
            {MONTH_LABELS.map((m) => (
              <th key={m} className="px-3 py-3 text-right">{m}</th>
            ))}
            <th className="px-3 py-3 text-right">Total</th>
            <th className="px-3 py-3 text-right">Max DD</th>
            <th className="px-3 py-3 text-right">Return/MaxDD</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.year} className="border-b border-gray-800 last:border-0">
              <td className="px-3 py-2 font-medium text-gray-100 sticky left-0 bg-gray-900">{row.year}</td>
              {MONTH_KEYS.map((mk) => (
                <td key={mk} className={`px-3 py-2 text-right ${cellColor(row.months[mk])}`}>
                  {row.months[mk] != null ? fmtCurrency(row.months[mk] as number) : "-"}
                </td>
              ))}
              <td className={`px-3 py-2 text-right font-semibold ${cellColor(row.total)}`}>
                {fmtCurrency(row.total)}
              </td>
              <td className="px-3 py-2 text-right text-red-400">{fmtCurrency(row.maxDD)}</td>
              <td className={`px-3 py-2 text-right ${cellColor(row.returnOverMaxDD)}`}>
                {row.returnOverMaxDD != null ? row.returnOverMaxDD.toFixed(2) : "-"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
