"use client";

import { useState, useEffect, useCallback } from "react";
import ReturnHistogram from "./ReturnHistogram";
import IVvsRVChart from "./IVvsRVChart";
import type { StatsResponse, PeriodStats } from "@/lib/statsCompute";

type Period = "ytd" | "1m" | "3m" | "6m" | "1y" | "3y" | "5y";
type ReturnType = "daily" | "weekly" | "monthly";

const PERIODS: { key: Period; label: string }[] = [
  { key: "ytd", label: "YTD" },
  { key: "1m",  label: "1M"  },
  { key: "3m",  label: "3M"  },
  { key: "6m",  label: "6M"  },
  { key: "1y",  label: "1Y"  },
  { key: "3y",  label: "3Y"  },
  { key: "5y",  label: "5Y"  },
];

const RETURN_TYPES: { key: ReturnType; label: string }[] = [
  { key: "daily",   label: "Daily"   },
  { key: "weekly",  label: "Weekly"  },
  { key: "monthly", label: "Monthly" },
];

const COLOR_MAP: Record<string, string> = {
  "^NSEI":  "#3987e5",
  "SENSEX": "#008300",
};

function fmt(v: number, dp = 2, pct = true) {
  const s = v >= 0 ? "+" : "";
  return `${s}${v.toFixed(dp)}${pct ? "%" : ""}`;
}

function KpiTile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-lg border border-gray-800 bg-gray-900 px-4 py-3">
      <div className="text-xs text-gray-500 mb-1">{label}</div>
      <div className="text-xl font-semibold text-gray-100">{value}</div>
      {sub && <div className="text-xs text-gray-600 mt-0.5">{sub}</div>}
    </div>
  );
}

function ProbabilityTable({ stats, returnType }: { stats: PeriodStats; returnType: ReturnType }) {
  const rows = stats.prob_table;
  const unit = returnType === "daily" ? "day" : returnType === "weekly" ? "week" : "month";
  if (!rows?.length) return null;

  return (
    <div className="mt-4 rounded-lg border border-gray-800 bg-gray-900 p-4 overflow-x-auto">
      <div className="text-sm font-semibold text-gray-200 mb-3">Probability Table ({unit})</div>
      <table className="w-full text-xs text-right">
        <thead>
          <tr className="text-gray-500 border-b border-gray-800">
            <th className="text-left pb-2">Move &gt;</th>
            <th className="pb-2">Either direction</th>
            <th className="pb-2">Up &gt; threshold</th>
            <th className="pb-2">Down &gt; threshold</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const absColor = row.p_abs >= 30 ? "text-red-400" : row.p_abs >= 10 ? "text-amber-400" : "text-gray-300";
            const upColor  = row.p_up  >= 30 ? "text-red-400" : row.p_up  >= 10 ? "text-amber-400" : "text-gray-300";
            const dnColor  = row.p_down >= 30 ? "text-red-400" : row.p_down >= 10 ? "text-amber-400" : "text-gray-300";
            return (
              <tr key={row.threshold} className="border-b border-gray-800/50">
                <td className="text-left py-1.5 text-gray-400">±{row.threshold}%</td>
                <td className={`py-1.5 font-medium ${absColor}`}>{row.p_abs}%</td>
                <td className={`py-1.5 ${upColor}`}>{row.p_up}%</td>
                <td className={`py-1.5 ${dnColor}`}>{row.p_down}%</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function PercentileRow({ stats }: { stats: PeriodStats }) {
  const tiles = [
    { label: "P5",  value: fmt(stats.p5) },
    { label: "P25", value: fmt(stats.p25) },
    { label: "P50", value: fmt(stats.p50) },
    { label: "P75", value: fmt(stats.p75) },
    { label: "P95", value: fmt(stats.p95) },
  ];
  return (
    <div className="mt-3 flex gap-2">
      {tiles.map((t) => (
        <div key={t.label} className="flex-1 rounded border border-gray-800 bg-gray-900/60 px-2 py-1.5 text-center">
          <div className="text-xs text-gray-500">{t.label}</div>
          <div className="text-sm font-medium text-gray-200">{t.value}</div>
        </div>
      ))}
    </div>
  );
}

interface IndexStatsClientProps {
  symbol: string;
  label: string;
}

export default function IndexStatsClient({ symbol, label }: IndexStatsClientProps) {
  const [period, setPeriod] = useState<Period>("5y");
  const [returnType, setReturnType] = useState<ReturnType>("daily");
  const [data, setData] = useState<StatsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const color = COLOR_MAP[symbol] ?? "#3987e5";

  const fetchData = useCallback(async (p: Period) => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/index-stats?symbol=${encodeURIComponent(symbol)}&period=${p}`);
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.error ?? `HTTP ${res.status}`);
      }
      const json: StatsResponse = await res.json();
      setData(json);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load data");
    } finally {
      setLoading(false);
    }
  }, [symbol]);

  useEffect(() => {
    fetchData(period);
  }, [period, fetchData]);

  const activePeriodStats: PeriodStats | undefined = data?.[returnType];

  return (
    <div>
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-100">{label} — Market Statistics</h1>
        {data && (
          <p className="text-sm text-gray-500 mt-1">
            {data.date_from} → {data.date_to} · n={activePeriodStats?.count ?? "—"} {returnType} returns
          </p>
        )}
      </div>

      {/* Period filter */}
      <div className="flex items-center gap-2 mb-4 flex-wrap">
        <span className="text-xs text-gray-500 mr-1">Period</span>
        {PERIODS.map(({ key, label: lbl }) => (
          <button
            key={key}
            onClick={() => setPeriod(key)}
            className={`px-3 py-1 rounded text-sm font-medium transition-colors ${
              period === key
                ? "bg-blue-600 text-white"
                : "bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-gray-200"
            }`}
          >
            {lbl}
          </button>
        ))}

        <span className="ml-4 text-xs text-gray-500 mr-1">View</span>
        {RETURN_TYPES.map(({ key, label: lbl }) => (
          <button
            key={key}
            onClick={() => setReturnType(key)}
            className={`px-3 py-1 rounded text-sm font-medium transition-colors ${
              returnType === key
                ? "bg-gray-600 text-white"
                : "bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-gray-200"
            }`}
          >
            {lbl}
          </button>
        ))}
      </div>

      {/* Loading / error */}
      {loading && (
        <div className="flex items-center justify-center py-20 text-gray-500">
          Loading statistics…
        </div>
      )}
      {error && (
        <div className="rounded-lg border border-red-800 bg-red-950/40 p-4 text-sm text-red-400">
          {error}
        </div>
      )}

      {/* Main content */}
      {!loading && !error && data && activePeriodStats && (
        <>
          {/* KPI tiles */}
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3 mb-4">
            <KpiTile label="Mean return"   value={fmt(activePeriodStats.mean)} />
            <KpiTile label="Std deviation" value={`${activePeriodStats.std.toFixed(2)}%`} />
            <KpiTile label="Win rate"      value={`${activePeriodStats.positive_pct}%`} sub="positive returns" />
            <KpiTile label="Skewness"      value={activePeriodStats.skew.toFixed(2)} sub={activePeriodStats.skew < 0 ? "left tail heavy" : "right tail heavy"} />
            <KpiTile label="Excess kurtosis" value={activePeriodStats.kurt.toFixed(2)} sub={activePeriodStats.kurt > 0 ? "fat tails" : "thin tails"} />
          </div>

          {/* Histogram */}
          <div className="rounded-lg border border-gray-800 bg-gray-900 p-4">
            <div className="text-sm font-semibold text-gray-200 mb-3 capitalize">
              {returnType} Return Distribution
            </div>
            <ReturnHistogram
              underlying={symbol === "^NSEI" ? "NIFTY" : "SENSEX"}
              histogram={activePeriodStats.histogram}
              normalCurve={activePeriodStats.normal_curve}
              mean={activePeriodStats.mean}
              std={activePeriodStats.std}
              color={color}
              period={returnType}
            />
          </div>

          {/* Percentile row */}
          <PercentileRow stats={activePeriodStats} />

          {/* Probability table */}
          <ProbabilityTable stats={activePeriodStats} returnType={returnType} />

          {/* IV vs RV chart */}
          {data.iv_rv_series?.length > 0 && (
            <IVvsRVChart data={data.iv_rv_series} />
          )}
        </>
      )}
    </div>
  );
}
