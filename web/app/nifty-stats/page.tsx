import IndexStatsClient from "@/components/IndexStatsClient";

export const metadata = {
  title: "NIFTY 50 Market Statistics",
  description: "Daily, weekly, and monthly return distribution, volatility analysis for NIFTY 50",
};

export default function NiftyStatsPage() {
  return <IndexStatsClient symbol="^NSEI" label="NIFTY 50" />;
}
