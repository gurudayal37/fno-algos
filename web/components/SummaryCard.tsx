interface SummaryCardProps {
  label: string;
  value: string;
  positive?: boolean;
  negative?: boolean;
}

export default function SummaryCard({ label, value, positive, negative }: SummaryCardProps) {
  let valueColor = "text-gray-100";
  if (positive) valueColor = "text-emerald-400";
  if (negative) valueColor = "text-red-400";

  return (
    <div className="rounded-lg border border-gray-800 bg-gray-900 p-4">
      <div className="text-xs uppercase tracking-wide text-gray-400">{label}</div>
      <div className={`mt-1 text-xl font-semibold ${valueColor}`}>{value}</div>
    </div>
  );
}
