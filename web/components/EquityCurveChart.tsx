"use client";

import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
} from "recharts";
import type { Trade } from "@/lib/data";

export default function EquityCurveChart({ trades }: { trades: Trade[] }) {
  const data = trades.map((t) => ({
    date: t.date,
    cum_pnl: Math.round(t.cum_pnl * 100) / 100,
    drawdown: Math.round(t.drawdown * 100) / 100,
  }));

  return (
    <div className="h-80 w-full rounded-lg border border-gray-800 bg-gray-900 p-4">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
          <XAxis dataKey="date" tick={{ fontSize: 11, fill: "#9ca3af" }} minTickGap={24} />
          <YAxis tick={{ fontSize: 11, fill: "#9ca3af" }} />
          <Tooltip
            contentStyle={{ backgroundColor: "#111827", border: "1px solid #374151" }}
            labelStyle={{ color: "#e5e7eb" }}
          />
          <Line
            type="monotone"
            dataKey="cum_pnl"
            name="Cumulative PnL"
            stroke="#34d399"
            dot={false}
            strokeWidth={2}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
