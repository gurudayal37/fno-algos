"use client";

import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
} from "recharts";
import type { Trade } from "@/lib/data";

export default function DrawdownChart({ trades }: { trades: Trade[] }) {
  const data = trades.map((t) => ({
    date: t.date,
    drawdown: Math.round(t.drawdown * 100) / 100,
  }));

  return (
    <div className="h-64 w-full rounded-lg border border-gray-800 bg-gray-900 p-4">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
          <XAxis dataKey="date" tick={{ fontSize: 11, fill: "#9ca3af" }} minTickGap={24} />
          <YAxis tick={{ fontSize: 11, fill: "#9ca3af" }} />
          <Tooltip
            contentStyle={{ backgroundColor: "#111827", border: "1px solid #374151" }}
            labelStyle={{ color: "#e5e7eb" }}
          />
          <Area
            type="monotone"
            dataKey="drawdown"
            name="Drawdown"
            stroke="#f87171"
            fill="#f87171"
            fillOpacity={0.25}
            dot={false}
            strokeWidth={2}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
