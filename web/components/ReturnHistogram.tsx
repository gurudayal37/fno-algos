"use client";

import {
  ComposedChart,
  Bar,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
  Legend,
} from "recharts";

interface HistBin {
  bin_label: string;
  center: number;
  count: number;
  pct: number;
}

interface ReturnHistogramProps {
  underlying: "NIFTY" | "SENSEX";
  histogram: HistBin[];
  normalCurve: number[];
  mean: number;
  std: number;
  period: string;
  /** primary bar color (blue for NIFTY, green for SENSEX) */
  color: string;
}

const GRID   = "#2c2c2a";
const MUTED  = "#898781";
const CURVE  = "#c3c2b7"; // secondary ink — normal curve line

export default function ReturnHistogram({
  underlying,
  histogram,
  normalCurve,
  mean,
  std,
  color,
}: ReturnHistogramProps) {
  // Merge histogram + normal curve into one data array for Recharts
  const data = histogram.map((bin, i) => ({
    bin_label: bin.bin_label,
    center:    bin.center,
    count:     bin.count,
    normal:    normalCurve[i] ?? 0,
  }));

  const meanLabel = `${mean >= 0 ? "+" : ""}${mean.toFixed(2)}%`;
  const sig1hi = mean + std;
  const sig1lo = mean - std;

  return (
    <div className="h-72 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 4, right: 8, bottom: 4, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={GRID} vertical={false} />

          <XAxis
            dataKey="bin_label"
            tick={{ fontSize: 9, fill: MUTED }}
            interval={3}
            tickLine={false}
          />
          <YAxis
            tick={{ fontSize: 10, fill: MUTED }}
            tickLine={false}
            axisLine={false}
            width={28}
          />

          <Tooltip
            contentStyle={{ backgroundColor: "#111827", border: "1px solid #374151", fontSize: 12 }}
            labelStyle={{ color: "#e5e7eb", fontWeight: 600 }}
            formatter={(value: number, name: string) =>
              name === "Frequency"
                ? [value, "Days"]
                : [value.toFixed(1), "Normal expected"]
            }
          />

          {/* ±1σ reference lines */}
          <ReferenceLine
            x={data.find(d => d.center >= sig1lo)?.bin_label}
            stroke={MUTED}
            strokeDasharray="4 2"
          />
          <ReferenceLine
            x={data.find(d => d.center >= sig1hi)?.bin_label}
            stroke={MUTED}
            strokeDasharray="4 2"
            label={{ value: "±1σ", position: "insideTopRight", fill: MUTED, fontSize: 9 }}
          />
          {/* Mean */}
          <ReferenceLine
            x={data.find(d => d.center >= mean)?.bin_label}
            stroke={color}
            strokeDasharray="2 2"
            label={{ value: `μ ${meanLabel}`, position: "insideTopLeft", fill: color, fontSize: 9 }}
          />

          <Bar
            dataKey="count"
            name="Frequency"
            fill={color}
            fillOpacity={0.75}
            radius={[2, 2, 0, 0]}
            maxBarSize={24}
          />

          {/* Normal distribution overlay */}
          <Line
            dataKey="normal"
            name="Normal curve"
            stroke={CURVE}
            strokeWidth={1.5}
            dot={false}
            strokeDasharray="4 2"
            type="monotone"
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
