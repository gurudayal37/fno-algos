import { notFound } from "next/navigation";
import { getMarketStats } from "@/lib/marketStats";
import StatsClient from "./StatsClient";

export default function StatsPage() {
  const data = getMarketStats();
  if (!data) notFound();

  return (
    <div>
      <h1 className="text-2xl font-semibold text-gray-100">Market Return Analysis</h1>
      <p className="mt-1 text-sm text-gray-400">
        Empirical return distributions for NIFTY and SENSEX — the statistical foundation for designing and sizing option strategies.
      </p>

      <div className="mt-6">
        <StatsClient data={data} />
      </div>
    </div>
  );
}
