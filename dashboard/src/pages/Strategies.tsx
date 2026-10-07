import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAsync } from "../hooks";
import { LineChart } from "../components/LineChart";
import { colorFor, num, pct, signClass, strategyLabel } from "../format";

export default function Strategies() {
  const specs = useAsync(() => api.strategies(), []);
  const ranking = useAsync(() => api.ranking(), []);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [walkForward, setWalkForward] = useState(true);

  const curves = useAsync(
    async () => {
      const rows = ranking.data?.ranking ?? [];
      const details = await Promise.all(rows.map((row) => api.backtest(row.id)));
      return details;
    },
    [ranking.data?.ranking.map((row) => row.id).join(",")],
  );

  const series =
    curves.data?.map((detail, index) => ({
      name: strategyLabel(detail.strategy_name),
      color: colorFor(index),
      data: detail.equity_curve.map((point) => ({ date: point.date, value: point.equity })),
    })) ?? [];

  async function runAll(strategies?: string[]) {
    setBusy(true);
    setMessage(null);
    try {
      const job = await api.runBacktests({ strategies: strategies ?? null, walk_forward: walkForward });
      setMessage(`Backtest lanzado (job ${job.id.slice(0, 8)}). Tarda unos minutos con walk-forward; la tabla se actualizará al recargar.`);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <h1>Estrategias</h1>
      <p className="subtitle">
        Reglas con evidencia académica, evaluadas con costes y validación walk-forward (selección in-sample, juicio
        out-of-sample). Promoción a paper solo si el OOS bate al benchmark en Sharpe sin peor drawdown.
      </p>
      <div className="toolbar">
        <button onClick={() => void runAll()} disabled={busy}>
          Lanzar backtest de todas
        </button>
        <label className="muted" style={{ fontSize: 13 }}>
          <input type="checkbox" checked={walkForward} onChange={(e) => setWalkForward(e.target.checked)} /> walk-forward
        </label>
        <button className="secondary" onClick={() => ranking.reload()}>
          Recargar resultados
        </button>
        {message ? <span className="muted">{message}</span> : null}
      </div>
      <div className="card">
        <h2>Curvas de equity de los últimos backtests (escala log)</h2>
        {series.length ? <LineChart series={series} height={380} logScale /> : <div className="empty">Sin backtests todavía.</div>}
      </div>
      <div className="card" style={{ marginTop: 16 }}>
        <h2>Comparativa</h2>
        <table>
          <thead>
            <tr>
              <th>Estrategia</th>
              <th>Periodo</th>
              <th>CAGR</th>
              <th>Vol</th>
              <th>Sharpe</th>
              <th>Sortino</th>
              <th>MaxDD</th>
              <th>Calmar</th>
              <th>Rotación</th>
              <th>OOS Sharpe</th>
              <th>OOS MaxDD</th>
              <th>Apto paper</th>
            </tr>
          </thead>
          <tbody>
            {(ranking.data?.ranking ?? []).map((row) => (
              <tr key={row.id} className="clickable">
                <td>
                  <Link to={`/backtests/${row.id}`}>{strategyLabel(row.strategy_name)}</Link>
                  <div className="params">{JSON.stringify(row.params)}</div>
                </td>
                <td className="muted">
                  {row.start_date} → {row.end_date}
                </td>
                <td className={signClass(row.metrics.cagr)}>{pct(row.metrics.cagr)}</td>
                <td>{pct(row.metrics.annual_volatility)}</td>
                <td>{num(row.metrics.sharpe)}</td>
                <td>{num(row.metrics.sortino)}</td>
                <td className="neg">{pct(row.metrics.max_drawdown)}</td>
                <td>{num(row.metrics.calmar)}</td>
                <td>{num(row.metrics.annual_turnover, 1)}</td>
                <td>{num(row.walk_forward_oos_metrics?.sharpe)}</td>
                <td className="neg">{pct(row.walk_forward_oos_metrics?.max_drawdown)}</td>
                <td>
                  {row.promotion_eligible === null ? (
                    <span className="badge">benchmark</span>
                  ) : row.promotion_eligible ? (
                    <span className="badge ok">sí</span>
                  ) : (
                    <span className="badge no" title={row.promotion?.reasons.join(", ")}>
                      no
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="card" style={{ marginTop: 16 }}>
        <h2>Catálogo</h2>
        <table>
          <thead>
            <tr>
              <th>Estrategia</th>
              <th style={{ textAlign: "left" }}>Qué hace</th>
              <th style={{ textAlign: "left" }}>Evidencia</th>
              <th>Parámetros por defecto</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {(specs.data?.strategies ?? []).map((spec) => (
              <tr key={spec.name}>
                <td>
                  {spec.title} {spec.is_benchmark ? <span className="badge">benchmark</span> : null}
                </td>
                <td style={{ textAlign: "left", whiteSpace: "normal" }}>{spec.description}</td>
                <td style={{ textAlign: "left", whiteSpace: "normal" }} className="muted">
                  {spec.evidence}
                </td>
                <td className="params">{JSON.stringify(spec.default_params)}</td>
                <td>
                  <button className="secondary" onClick={() => void runAll([spec.name])} disabled={busy}>
                    Backtest
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
