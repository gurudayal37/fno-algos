"use client";

import {
  ResponsiveContainer,
  ComposedChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ReferenceLine,
} from "recharts";
import type { IVRVPoint } from "@/lib/statsCompute";

interface IVvsRVChartProps {
  data: IVRVPoint[];
}

const GRID   = "#2c2c2a";
const MUTED  = "#898781";
const IV_COLOR = "#d55181";   // palette slot 3 (magenta-dark) — VIX / implied
const RV_COLOR = "#3987e5";   // palette slot 1 (blue) — realized

// Thin out to at most ~300 points for render performance
function downsample<T>(arr: T[], maxPts: number): T[] {
  if (arr.length <= maxPts) return arr;
  const step = Math.ceil(arr.length / maxPts);
  return arr.filter((_, i) => i % step === 0 || i === arr.length - 1);
}

function formatDate(d: string) {
  const dt = new Date(d);
  return dt.toLocaleDateString("en-IN", { month: "short", year: "2-digit" });
}

export default function IVvsRVChart({ data }: IVvsRVChartProps) {
  const displayData = downsample(data, 300).map((p) => ({
    ...p,
    displayDate: formatDate(p.date),
  }));

  if (displayData.length === 0) return null;

  return (
    <div className="mt-6 rounded-lg border border-gray-800 bg-gray-900 p-4">
      <div className="mb-1 text-sm font-semibold text-gray-200">
        India VIX vs 21-Day Realized Volatility
      </div>
      <p className="mb-3 text-xs text-gray-500">
        When VIX (orange) sits above Realized Vol (blue), the options market is pricing in more fear than what actually occurred — this is the premium sellers&apos; edge.
        The gap between the two lines is the <span className="text-gray-400">volatility risk premium (VRP)</span>.
      </p>

      <div className="h-64 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={displayData} margin={{ top: 4, right: 12, bottom: 4, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={GRID} vertical={false} />
            <XAxis
              dataKey="displayDate"
              tick={{ fontSize: 10, fill: MUTED }}
              interval="preserveStartEnd"
              tickLine={false}
            />
            <YAxis
              tick={{ fontSize: 10, fill: MUTED }}
              tickLine={false}
              axisLine={false}
              tickFormatter={(v) => `${v}%`}
              width={40}
            />
            <Tooltip
              contentStyle={{ backgroundColor: "#111827", border: "1px solid #374151", fontSize: 12 }}
              labelStyle={{ color: "#9ca3af" }}
              formatter={(value: number, name: string) => [
                `${value?.toFixed(1)}%`,
                name === "vix" ? "India VIX" : "Realized Vol (21D)",
              ]}
            />
            <Legend
              formatter={(v) => (
                <span style={{ color: "#c3c2b7", fontSize: 11 }}>
                  {v === "vix" ? "India VIX (implied)" : "Realized Vol 21D"}
                </span>
              )}
            />
            <Line
              type="monotone"
              dataKey="vix"
              stroke={IV_COLOR}
              strokeWidth={1.5}
              dot={false}
              name="vix"
              connectNulls
            />
            <Line
              type="monotone"
              dataKey="rv21d"
              stroke={RV_COLOR}
              strokeWidth={1.5}
              dot={false}
              name="rv21d"
              connectNulls
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      <p className="mt-2 text-xs text-gray-600">
        India VIX is the NSE&apos;s 30-day forward volatility estimate derived from NIFTY options order book. Realized vol computed as 21-day rolling std of daily log returns × √252.
      </p>
    </div>
  );
}
