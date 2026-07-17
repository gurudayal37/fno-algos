"use client";

import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ReferenceArea,
} from "recharts";

interface PayoffChartProps {
  ceStrike: number;
  peStrike: number;
  ceEntry: number;
  peEntry: number;
  lotSize: number;
  totalCosts: number;
  spotEntry: number;
  spotExit?: number;
  /** Iron Condor only: long (wing) CE strike */
  longCeStrike?: number;
  /** Iron Condor only: long (wing) PE strike */
  longPeStrike?: number;
}

function fmt(n: number) {
  return n.toLocaleString("en-IN", { maximumFractionDigits: 0 });
}

export default function PayoffChart({
  ceStrike,
  peStrike,
  ceEntry,
  peEntry,
  lotSize,
  totalCosts,
  spotEntry,
  spotExit,
  longCeStrike,
  longPeStrike,
}: PayoffChartProps) {
  const totalPremium = ceEntry + peEntry;
  const isIC = longCeStrike !== undefined && longPeStrike !== undefined;

  const netPnlAt = (spot: number) => {
    if (isIC) {
      // IC payoff: each side is capped at the wing width
      const wing = longCeStrike! - ceStrike;          // wing points (same on both sides)
      const callLoss = Math.min(Math.max(spot - ceStrike, 0), wing);
      const putLoss  = Math.min(Math.max(peStrike - spot, 0), wing);
      return (totalPremium - callLoss - putLoss) * lotSize - totalCosts;
    }
    // Straddle / strangle: unlimited loss on both sides
    const ceLoss = Math.max(spot - ceStrike, 0);
    const peLoss = Math.max(peStrike - spot, 0);
    return (totalPremium - ceLoss - peLoss) * lotSize - totalCosts;
  };

  // Breakevens
  const breakevenLow  = peStrike - totalPremium + totalCosts / lotSize;
  const breakevenHigh = ceStrike + totalPremium - totalCosts / lotSize;

  // Chart range
  const outerRef = isIC
    ? Math.max(longCeStrike! - spotEntry, spotEntry - longPeStrike!) * 1.5
    : Math.max(Math.abs(breakevenHigh - spotEntry), Math.abs(spotEntry - breakevenLow)) * 1.8 + 1;
  const rangeMin = spotEntry - outerRef;
  const rangeMax = spotEntry + outerRef;

  const points = 100;
  const data = Array.from({ length: points + 1 }, (_, i) => {
    const spot = rangeMin + ((rangeMax - rangeMin) * i) / points;
    return { spot: Math.round(spot * 100) / 100, pnl: Math.round(netPnlAt(spot) * 100) / 100 };
  });

  const maxProfit = netPnlAt((peStrike + ceStrike) / 2);
  const maxLoss   = isIC ? netPnlAt(longCeStrike! + 100) : null; // beyond wing

  return (
    <div className="rounded-lg border border-gray-800 bg-gray-900 p-4">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div className="text-sm font-medium text-gray-300">Payoff at Expiry (entry-time premium)</div>
        <div className="text-xs text-gray-400 flex flex-wrap gap-3">
          <span>Max Profit: <span className="text-emerald-400">Rs. {fmt(maxProfit)}</span></span>
          {maxLoss !== null && <span>Max Loss: <span className="text-red-400">Rs. {fmt(maxLoss)}</span></span>}
          <span>Breakevens: {fmt(breakevenLow)} / {fmt(breakevenHigh)}</span>
        </div>
      </div>
      <div className="h-80 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
            <XAxis
              dataKey="spot"
              type="number"
              domain={[rangeMin, rangeMax]}
              tick={{ fontSize: 11, fill: "#9ca3af" }}
              tickFormatter={(v) => fmt(v)}
            />
            <YAxis
              tick={{ fontSize: 11, fill: "#9ca3af" }}
              domain={["auto", "auto"]}
              tickFormatter={(v) => fmt(v)}
            />
            <Tooltip
              contentStyle={{ backgroundColor: "#111827", border: "1px solid #374151" }}
              labelStyle={{ color: "#e5e7eb" }}
              formatter={(value: number) => [`Rs. ${fmt(value)}`, "PnL"]}
              labelFormatter={(v) => `Spot: ${fmt(v as number)}`}
            />

            {/* Loss zones */}
            <ReferenceArea x1={rangeMin} x2={breakevenLow} fill="#f87171" fillOpacity={0.08} />
            <ReferenceArea x1={breakevenLow} x2={breakevenHigh} fill="#34d399" fillOpacity={0.08} />
            <ReferenceArea x1={breakevenHigh} x2={rangeMax} fill="#f87171" fillOpacity={0.08} />

            {/* IC wing strike markers */}
            {isIC && (
              <>
                <ReferenceLine x={longPeStrike} stroke="#6b7280" strokeDasharray="3 3"
                  label={{ value: `PE Wing\n${fmt(longPeStrike!)}`, position: "insideBottomLeft", fill: "#6b7280", fontSize: 9 }} />
                <ReferenceLine x={longCeStrike} stroke="#6b7280" strokeDasharray="3 3"
                  label={{ value: `CE Wing\n${fmt(longCeStrike!)}`, position: "insideBottomRight", fill: "#6b7280", fontSize: 9 }} />
              </>
            )}

            <ReferenceLine y={0} stroke="#6b7280" />
            <ReferenceLine
              x={spotEntry}
              stroke="#60a5fa"
              strokeDasharray="4 4"
              label={{ value: "Entry", position: "insideTopLeft", fill: "#60a5fa", fontSize: 11 }}
            />
            {spotExit !== undefined && Math.abs(spotExit - spotEntry) > 0.01 && (
              <ReferenceLine
                x={spotExit}
                stroke="#facc15"
                strokeDasharray="4 4"
                label={{ value: "Exit", position: "insideTopRight", fill: "#facc15", fontSize: 11 }}
              />
            )}

            <Line type="linear" dataKey="pnl" name="PnL" stroke="#a78bfa" dot={false} strokeWidth={2} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
