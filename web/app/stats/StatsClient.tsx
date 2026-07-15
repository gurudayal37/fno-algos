"use client";

import { useState } from "react";
import ReturnHistogram from "@/components/ReturnHistogram";
import type { MarketStats, PeriodStats } from "@/lib/marketStats";

type Period = "daily" | "weekly" | "monthly";

const PERIOD_LABELS: Record<Period, string> = {
  daily: "Daily",
  weekly: "Weekly",
  monthly: "Monthly",
};

const PERIOD_CONTEXT: Record<Period, string> = {
  daily: "Each bar = one trading day's close-to-close move",
  weekly: "Each bar = one week's close-to-close move",
  monthly: "Each bar = one month's close-to-close move",
};

function fmt(n: number, decimals = 2) {
  return n.toFixed(decimals);
}
function fmtPct(n: number) {
  return `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;
}

interface StatTileProps {
  label: string;
  value: string;
  sub?: string;
  color?: string;
}
function StatTile({ label, value, sub, color }: StatTileProps) {
  return (
    <div className="rounded-lg border border-gray-800 bg-gray-900 px-3 py-2">
      <div className="text-xs text-gray-500">{label}</div>
      <div className={`text-lg font-semibold ${color ?? "text-gray-100"}`}>{value}</div>
      {sub && <div className="text-xs text-gray-500">{sub}</div>}
    </div>
  );
}

interface HistogramPanelProps {
  underlying: "NIFTY" | "SENSEX";
  stats: PeriodStats;
  dateRange: string;
  color: string;
  period: Period;
}

function HistogramPanel({ underlying, stats, dateRange, color, period }: HistogramPanelProps) {
  return (
    <div className="rounded-lg border border-gray-800 bg-gray-900 p-4">
      {/* Header */}
      <div className="mb-3 flex items-center justify-between">
        <div>
          <span
            className="text-base font-semibold"
            style={{ color }}
          >
            {underlying}
          </span>
          <span className="ml-2 text-xs text-gray-500">{dateRange} · n={stats.count}</span>
        </div>
        <div className="text-xs text-gray-500">
          <span className="mr-3">μ {fmtPct(stats.mean)}</span>
          <span>σ {fmt(stats.std)}%</span>
        </div>
      </div>

      {/* KPI tiles */}
      <div className="mb-3 grid grid-cols-5 gap-2">
        <StatTile label="Mean/period" value={fmtPct(stats.mean)} color={stats.mean >= 0 ? "text-emerald-400" : "text-red-400"} />
        <StatTile label="Std Dev" value={`${fmt(stats.std)}%`} />
        <StatTile label="Win Rate" value={`${fmt(stats.positive_pct, 1)}%`} sub="days positive" />
        <StatTile label="Skewness" value={fmt(stats.skew, 2)} sub={stats.skew < -0.5 ? "left tail" : stats.skew > 0.5 ? "right tail" : "~symmetric"} />
        <StatTile label="Excess Kurt" value={fmt(stats.kurt, 1)} sub={stats.kurt > 1 ? "fat tails ⚠" : "near-normal"} />
      </div>

      {/* Histogram */}
      <ReturnHistogram
        underlying={underlying}
        histogram={stats.histogram}
        normalCurve={stats.normal_curve}
        mean={stats.mean}
        std={stats.std}
        color={color}
        period={period}
      />

      <div className="mt-1 flex justify-between text-xs text-gray-600">
        <span>P5: {fmtPct(stats.p5)}</span>
        <span>P25: {fmtPct(stats.p25)}</span>
        <span>Median: {fmtPct(stats.p50)}</span>
        <span>P75: {fmtPct(stats.p75)}</span>
        <span>P95: {fmtPct(stats.p95)}</span>
      </div>

      <p className="mt-2 text-xs text-gray-600">
        Dashed line = fitted normal distribution. Fat tails (excess kurtosis {">"} 0) mean extreme moves happen more often than a normal model predicts.
      </p>
    </div>
  );
}

interface ProbTableProps {
  nifty: PeriodStats;
  sensex: PeriodStats;
  period: Period;
}

function ProbTable({ nifty, sensex, period }: ProbTableProps) {
  const rows = nifty.prob_table.map((nr, i) => ({
    ...nr,
    sx_abs:  sensex.prob_table[i]?.p_abs  ?? "-",
    sx_up:   sensex.prob_table[i]?.p_up   ?? "-",
    sx_down: sensex.prob_table[i]?.p_down ?? "-",
  }));

  const periodLabel = period === "daily" ? "day" : period === "weekly" ? "week" : "month";

  return (
    <div className="mt-6 rounded-lg border border-gray-800 bg-gray-900 p-4">
      <div className="mb-3">
        <div className="text-sm font-semibold text-gray-200">Probability Table</div>
        <p className="text-xs text-gray-500 mt-0.5">
          P(|move| {">"} X%) — probability that a {periodLabel}&apos;s move exceeds the threshold in either direction.
          Core input for option strategy sizing: if you sell a straddle with a {period === "daily" ? "1%" : period === "weekly" ? "2%" : "5%"} SL,
          this is roughly how often it gets hit.
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-gray-800 text-gray-500">
              <th className="pb-2 pr-4 text-left">Threshold</th>
              <th className="pb-2 pr-3 text-right" style={{ color: "#3987e5" }}>NIFTY |Δ|</th>
              <th className="pb-2 pr-3 text-right" style={{ color: "#3987e5" }}>↑ Up</th>
              <th className="pb-2 pr-6 text-right" style={{ color: "#3987e5" }}>↓ Down</th>
              <th className="pb-2 pr-3 text-right" style={{ color: "#008300" }}>SENSEX |Δ|</th>
              <th className="pb-2 pr-3 text-right" style={{ color: "#008300" }}>↑ Up</th>
              <th className="pb-2 text-right" style={{ color: "#008300" }}>↓ Down</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const hi = r.p_abs >= 30;
              const mid = r.p_abs >= 10 && r.p_abs < 30;
              return (
                <tr key={r.threshold} className="border-b border-gray-800/50">
                  <td className="py-1.5 pr-4 font-mono text-gray-300">
                    &gt;{r.threshold}%
                  </td>
                  <td className={`py-1.5 pr-3 text-right font-semibold ${hi ? "text-red-400" : mid ? "text-amber-400" : "text-gray-300"}`}>
                    {r.p_abs}%
                  </td>
                  <td className="py-1.5 pr-3 text-right text-emerald-500">{r.p_up}%</td>
                  <td className="py-1.5 pr-6 text-right text-red-400">{r.p_down}%</td>
                  <td className={`py-1.5 pr-3 text-right font-semibold ${Number(r.sx_abs) >= 30 ? "text-red-400" : Number(r.sx_abs) >= 10 ? "text-amber-400" : "text-gray-300"}`}>
                    {r.sx_abs}%
                  </td>
                  <td className="py-1.5 pr-3 text-right text-emerald-500">{r.sx_up}%</td>
                  <td className="py-1.5 text-right text-red-400">{r.sx_down}%</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-xs text-gray-600">
        Red ≥ 30% · Amber ≥ 10%. Asymmetry between up/down columns reveals directional skew — NIFTY&apos;s down tail is slightly heavier (negative skew from COVID + 2022 bear market in the dataset).
      </p>
    </div>
  );
}

export default function StatsClient({ data }: { data: MarketStats }) {
  const [period, setPeriod] = useState<Period>("daily");

  return (
    <div>
      {/* Period toggle */}
      <div className="mb-6 flex gap-2">
        {(["daily", "weekly", "monthly"] as Period[]).map((p) => (
          <button
            key={p}
            onClick={() => setPeriod(p)}
            className={`rounded-md px-4 py-1.5 text-sm font-medium transition-colors ${
              period === p
                ? "bg-gray-700 text-gray-100"
                : "text-gray-400 hover:text-gray-200"
            }`}
          >
            {PERIOD_LABELS[p]}
          </button>
        ))}
        <span className="ml-2 self-center text-xs text-gray-600">
          {PERIOD_CONTEXT[period]}
        </span>
      </div>

      {/* Two histograms side by side */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <HistogramPanel
          underlying="NIFTY"
          stats={data.NIFTY[period]}
          dateRange={data.NIFTY.date_range}
          color="#3987e5"
          period={period}
        />
        <HistogramPanel
          underlying="SENSEX"
          stats={data.SENSEX[period]}
          dateRange={data.SENSEX.date_range}
          color="#008300"
          period={period}
        />
      </div>

      {/* Probability table */}
      <ProbTable nifty={data.NIFTY[period]} sensex={data.SENSEX[period]} period={period} />

      {/* Quant interpretation */}
      <div className="mt-6 rounded-lg border border-gray-800 bg-gray-900/50 p-4 text-xs text-gray-500 space-y-1">
        <p className="font-medium text-gray-400">Reading this for option strategy design</p>
        <p>• <span className="text-gray-300">Std Dev (σ)</span> is the 1-day realized volatility. Annualized = σ × √252. Compare against implied vol at entry to judge IV richness.</p>
        <p>• <span className="text-gray-300">Excess kurtosis {">"} 0</span> means fat tails — extreme moves happen more than a Black-Scholes model assumes, which is why short-gamma strategies need hard stop-losses.</p>
        <p>• <span className="text-gray-300">P(|move| {">"} SL%)</span> from the table is your expected SL hit rate per expiry. Multiply by average SL loss to estimate the drag on your strategy&apos;s edge.</p>
        <p>• <span className="text-gray-300">Skew {"<"} 0</span> means down moves dominate the tail — short puts carry more tail risk than short calls at the same delta.</p>
      </div>
    </div>
  );
}
