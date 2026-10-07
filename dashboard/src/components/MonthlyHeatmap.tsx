const MONTHS = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"];

function color(value: number | null): string {
  if (value === null) return "transparent";
  const capped = Math.max(-0.1, Math.min(0.1, value));
  const intensity = Math.abs(capped) / 0.1;
  if (capped >= 0) return `rgba(82, 210, 115, ${0.15 + intensity * 0.75})`;
  return `rgba(255, 93, 108, ${0.15 + intensity * 0.75})`;
}

export function MonthlyHeatmap({ rows }: { rows: { year: number; month: number; return: number | null }[] }) {
  const years = Array.from(new Set(rows.map((row) => row.year))).sort();
  const lookup = new Map(rows.map((row) => [`${row.year}-${row.month}`, row.return]));
  return (
    <div className="heatmap">
      <div className="head" />
      {MONTHS.map((month) => (
        <div className="head" key={month}>
          {month}
        </div>
      ))}
      <div className="head">Año</div>
      {years.map((year) => {
        let compounded = 1;
        let any = false;
        const cells = MONTHS.map((_, index) => {
          const value = lookup.get(`${year}-${index + 1}`) ?? null;
          if (value !== null) {
            compounded *= 1 + value;
            any = true;
          }
          return (
            <div
              className="cell"
              key={`${year}-${index}`}
              style={{ background: color(value), color: value === null ? "transparent" : "#06121f" }}
              title={value === null ? "" : `${(value * 100).toFixed(2)}%`}
            >
              {value === null ? "·" : `${(value * 100).toFixed(1)}`}
            </div>
          );
        });
        const annual = any ? compounded - 1 : null;
        return (
          <div style={{ display: "contents" }} key={year}>
            <div className="year">{year}</div>
            {cells}
            <div className={`cell ${annual !== null && annual < 0 ? "" : ""}`} style={{ background: color(annual) }}>
              {annual === null ? "" : `${(annual * 100).toFixed(1)}%`}
            </div>
          </div>
        );
      })}
    </div>
  );
}
