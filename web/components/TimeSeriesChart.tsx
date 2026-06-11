"use client";

import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from "recharts";

interface LineConfig {
  dataKey: string;
  name: string;
  color: string;
}

interface TimeSeriesChartProps {
  title: string;
  data: Array<{ time: string; [key: string]: string | number }>;
  lines: LineConfig[];
}

export default function TimeSeriesChart({ title, data, lines }: TimeSeriesChartProps) {
  return (
    <div className="rounded-lg border border-gray-800 bg-gray-900 p-4">
      <div className="mb-2 text-sm font-medium text-gray-300">{title}</div>
      <div className="h-72 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
            <XAxis dataKey="time" tick={{ fontSize: 11, fill: "#9ca3af" }} minTickGap={24} />
            <YAxis tick={{ fontSize: 11, fill: "#9ca3af" }} domain={["auto", "auto"]} />
            <Tooltip
              contentStyle={{ backgroundColor: "#111827", border: "1px solid #374151" }}
              labelStyle={{ color: "#e5e7eb" }}
            />
            {lines.length > 1 && <Legend wrapperStyle={{ fontSize: 12 }} />}
            {lines.map((line) => (
              <Line
                key={line.dataKey}
                type="monotone"
                dataKey={line.dataKey}
                name={line.name}
                stroke={line.color}
                dot={false}
                strokeWidth={2}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
