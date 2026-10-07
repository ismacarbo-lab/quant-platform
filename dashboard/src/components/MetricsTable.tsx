import type { Metrics } from "../api";
import { num, pct, signClass } from "../format";

const ROWS: { key: keyof Metrics; label: string; kind: "pct" | "num" | "int" }[] = [
  { key: "cagr", label: "CAGR", kind: "pct" },
  { key: "annual_volatility", label: "Volatilidad anual", kind: "pct" },
  { key: "sharpe", label: "Sharpe", kind: "num" },
  { key: "sortino", label: "Sortino", kind: "num" },
  { key: "max_drawdown", label: "Máx. drawdown", kind: "pct" },
  { key: "calmar", label: "Calmar", kind: "num" },
  { key: "total_return", label: "Retorno total", kind: "pct" },
  { key: "positive_months", label: "Meses positivos", kind: "pct" },
  { key: "best_month", label: "Mejor mes", kind: "pct" },
  { key: "worst_month", label: "Peor mes", kind: "pct" },
  { key: "annual_turnover", label: "Rotación anual", kind: "num" },
  { key: "average_exposure", label: "Exposición media", kind: "pct" },
  { key: "sessions", label: "Sesiones", kind: "int" },
];

function render(value: unknown, kind: "pct" | "num" | "int"): string {
  if (typeof value !== "number") return "—";
  if (kind === "pct") return pct(value);
  if (kind === "int") return value.toString();
  return num(value);
}

export function MetricsTable({
  columns,
}: {
  columns: { title: string; metrics: Metrics | null | undefined }[];
}) {
  return (
    <table>
      <thead>
        <tr>
          <th>Métrica</th>
          {columns.map((column) => (
            <th key={column.title}>{column.title}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {ROWS.map((row) => (
          <tr key={row.key}>
            <td>{row.label}</td>
            {columns.map((column) => {
              const value = column.metrics ? column.metrics[row.key] : null;
              const cls = row.kind === "pct" && row.key !== "annual_volatility" ? signClass(value as number) : "";
              return (
                <td key={column.title} className={cls}>
                  {render(value, row.kind)}
                </td>
              );
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
