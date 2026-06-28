"use client";

import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Cell } from "recharts";

interface VolatilityChartProps {
  ceIv?: number;
  peIv?: number;
  realizedVol10d?: number;
}

export default function VolatilityChart({ ceIv, peIv, realizedVol10d }: VolatilityChartProps) {
  const data = [
    ceIv !== undefined && { name: "CE IV", value: Math.round(ceIv * 1000) / 10, color: "#f87171" },
    peIv !== undefined && { name: "PE IV", value: Math.round(peIv * 1000) / 10, color: "#34d399" },
    realizedVol10d !== undefined && { name: "Realized Vol (10D)", value: Math.round(realizedVol10d * 1000) / 10, color: "#60a5fa" },
  ].filter(Boolean) as { name: string; value: number; color: string }[];

  if (data.length === 0) return null;

  return (
    <div className="rounded-lg border border-gray-800 bg-gray-900 p-4">
      <div className="mb-2 text-sm font-medium text-gray-300">
        Implied Volatility (at entry) vs Trailing Realized Volatility
      </div>
      <div className="h-56 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
            <XAxis dataKey="name" tick={{ fontSize: 11, fill: "#9ca3af" }} />
            <YAxis tick={{ fontSize: 11, fill: "#9ca3af" }} unit="%" />
            <Tooltip
              contentStyle={{ backgroundColor: "#111827", border: "1px solid #374151" }}
              labelStyle={{ color: "#e5e7eb" }}
              formatter={(value: number) => [`${value}%`, "Annualized Vol"]}
            />
            <Bar dataKey="value" radius={[4, 4, 0, 0]}>
              {data.map((d) => (
                <Cell key={d.name} fill={d.color} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <p className="mt-2 text-xs text-gray-500">
        IV well above realized vol means the premium sold was rich relative to recent historical
        movement — the core thesis for selling 0DTE premium.
      </p>
    </div>
  );
}
