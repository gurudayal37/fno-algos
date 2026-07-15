import IndexStatsClient from "@/components/IndexStatsClient";

export const metadata = {
  title: "SENSEX Market Statistics",
  description: "Daily, weekly, and monthly return distribution, volatility analysis for BSE SENSEX",
};

export default function SensexStatsPage() {
  return <IndexStatsClient symbol="SENSEX" label="SENSEX" />;
}
