import Link from "next/link";
import { notFound } from "next/navigation";
import { getAllIntradayParams, getExpiryDetail, getStrategy } from "@/lib/data";
import SummaryCard from "@/components/SummaryCard";
import TimeSeriesChart from "@/components/TimeSeriesChart";
import PayoffChart from "@/components/PayoffChart";
import VolatilityChart from "@/components/VolatilityChart";

function fmtCurrency(n: number) {
  return `Rs. ${n.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
}

export function generateStaticParams() {
  return getAllIntradayParams();
}

export default function ExpiryDetailPage({ params }: { params: { id: string; date: string } }) {
  const strategy = getStrategy(params.id);
  const expiry = getExpiryDetail(params.id, params.date);
  if (!strategy || !expiry) {
    notFound();
  }

  return (
    <div>
      <Link href={`/strategy/${params.id}`} className="text-sm text-gray-400 hover:text-gray-200">
        &larr; {strategy.name} ({strategy.underlying})
      </Link>

      <h1 className="mt-1 text-2xl font-semibold text-gray-100">
        {expiry.date}
        {expiry.long_ce !== undefined && expiry.long_pe !== undefined
          ? ` — IC: PE${expiry.long_pe}/${expiry.pe_strike} × ${expiry.ce_strike}/${expiry.long_ce}CE`
          : expiry.ce_strike !== undefined && expiry.pe_strike !== undefined
            ? ` — CE ${expiry.ce_strike} / PE ${expiry.pe_strike}`
            : ` — Strike ${expiry.strike}`}
      </h1>

      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-sm text-gray-400">
        {expiry.net_credit !== undefined && (
          <span className="text-blue-300 font-medium">Net Credit: ₹{expiry.net_credit.toFixed(2)}/share</span>
        )}
        <span>
          {expiry.long_ce !== undefined ? "Call spread" : "CE"}: {expiry.ce_entry.toFixed(2)} &rarr; {expiry.ce_exit.toFixed(2)} @ {expiry.ce_exit_time} ({expiry.ce_exit_reason})
        </span>
        <span>
          {expiry.long_pe !== undefined ? "Put spread" : "PE"}: {expiry.pe_entry.toFixed(2)} &rarr; {expiry.pe_exit.toFixed(2)} @ {expiry.pe_exit_time} ({expiry.pe_exit_reason})
        </span>
      </div>

      <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        <SummaryCard
          label="Total Net PnL"
          value={fmtCurrency(expiry.total_net_pnl)}
          positive={expiry.total_net_pnl >= 0}
          negative={expiry.total_net_pnl < 0}
        />
        {expiry.long_ce !== undefined && expiry.long_pe !== undefined ? (
          <>
            <SummaryCard label="Short Strikes" value={`PE ${expiry.pe_strike} / CE ${expiry.ce_strike}`} />
            <SummaryCard label="Wing Strikes" value={`PE ${expiry.long_pe} / CE ${expiry.long_ce}`} />
          </>
        ) : expiry.ce_strike !== undefined && expiry.pe_strike !== undefined ? (
          <SummaryCard label="CE / PE Strike" value={`${expiry.ce_strike} / ${expiry.pe_strike}`} />
        ) : (
          <SummaryCard label="ATM Strike" value={`${expiry.strike}`} />
        )}
        <SummaryCard label="Candles" value={`${expiry.candles.length}`} />
      </div>

      <div className="mt-6 grid grid-cols-1 gap-4">
        <PayoffChart
          ceStrike={expiry.ce_strike ?? expiry.strike}
          peStrike={expiry.pe_strike ?? expiry.strike}
          ceEntry={expiry.ce_entry}
          peEntry={expiry.pe_entry}
          lotSize={expiry.lot_size}
          totalCosts={expiry.ce_costs + expiry.pe_costs}
          spotEntry={expiry.spot_entry}
          spotExit={expiry.candles[expiry.candles.length - 1]?.spot}
          longCeStrike={expiry.long_ce}
          longPeStrike={expiry.long_pe}
        />

        {(expiry.ce_iv !== undefined || expiry.pe_iv !== undefined || expiry.realized_vol_10d !== undefined) && (
          <VolatilityChart ceIv={expiry.ce_iv} peIv={expiry.pe_iv} realizedVol10d={expiry.realized_vol_10d} />
        )}

        <TimeSeriesChart
          title={`${strategy.underlying} Spot`}
          data={expiry.candles}
          lines={[{ dataKey: "spot", name: "Spot", color: "#60a5fa" }]}
        />
        <TimeSeriesChart
          title="CE / PE Premium"
          data={expiry.candles}
          lines={[
            { dataKey: "ce", name: "CE Premium", color: "#f87171" },
            { dataKey: "pe", name: "PE Premium", color: "#34d399" },
          ]}
        />
        <TimeSeriesChart
          title="Strategy PnL"
          data={expiry.candles}
          lines={[{ dataKey: "pnl", name: "PnL", color: "#facc15" }]}
        />
      </div>
    </div>
  );
}
