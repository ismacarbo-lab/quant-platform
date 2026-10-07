export function Kpi({
  label,
  value,
  hint,
  className,
}: {
  label: string;
  value: string;
  hint?: string;
  className?: string;
}) {
  return (
    <div className="card kpi">
      <div className="label">{label}</div>
      <div className={`value ${className ?? ""}`}>{value}</div>
      {hint ? <div className="hint">{hint}</div> : null}
    </div>
  );
}
