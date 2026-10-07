import { colorFor, pct } from "../format";

export function WeightsBar({ weights }: { weights: Record<string, number | string> }) {
  const entries = Object.entries(weights)
    .map(([symbol, value]) => [symbol, Number(value)] as const)
    .filter(([, value]) => value > 0.0005)
    .sort((a, b) => b[1] - a[1]);
  const total = entries.reduce((sum, [, value]) => sum + value, 0);
  if (entries.length === 0) return <span className="muted">100% efectivo</span>;
  return (
    <div>
      <div className="weights-bar" title={entries.map(([s, v]) => `${s} ${pct(v)}`).join(" · ")}>
        {entries.map(([symbol, value], index) => (
          <span key={symbol} style={{ width: `${value * 100}%`, background: colorFor(index) }} />
        ))}
        {total < 0.999 ? <span style={{ width: `${(1 - total) * 100}%`, background: "transparent" }} /> : null}
      </div>
      <div className="legend">
        {entries.map(([symbol, value], index) => (
          <span key={symbol}>
            <span className="dot" style={{ background: colorFor(index) }} />
            {symbol} {pct(value)}
          </span>
        ))}
        {total < 0.999 ? <span className="muted">efectivo {pct(1 - total)}</span> : null}
      </div>
    </div>
  );
}
