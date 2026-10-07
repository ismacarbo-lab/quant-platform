import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { useAsync } from "../hooks";
import { Kpi } from "../components/Kpi";
import { LineChart } from "../components/LineChart";
import { DrawdownChart } from "../components/DrawdownChart";
import { MonthlyHeatmap } from "../components/MonthlyHeatmap";
import { MetricsTable } from "../components/MetricsTable";
import { WeightsBar } from "../components/Weights";
import { num, pct, signClass, strategyLabel } from "../format";

export default function BacktestDetail() {
  const { id } = useParams();
  const detail = useAsync(() => api.backtest(id ?? ""), [id]);
  const data = detail.data;
  if (detail.error) return <div className="notice error">{detail.error}</div>;
  if (!data) return <div className="empty">Cargando…</div>;
  const strategySeries = {
    name: strategyLabel(data.strategy_name),
    color: "#4cc9f0",
    data: data.equity_curve.map((point) => ({ date: point.date, value: point.equity })),
  };
  const benchmarkSeries = {
    name: `Benchmark (${strategyLabel(data.benchmark_name)})`,
    color: "#8da0c9",
    dashed: true,
    data: data.equity_curve
      .filter((point) => point.benchmark !== null)
      .map((point) => ({ date: point.date, value: point.benchmark as number })),
  };
  const wf = data.walk_forward;
  return (
    <div>
      <p className="muted">
        <Link to="/strategies">← Estrategias</Link>
      </p>
      <h1>{strategyLabel(data.strategy_name)}</h1>
      <p className="subtitle">
        {data.start_date} → {data.end_date} · rebalanceo {data.rebalance} · comisión {data.commission_bps} bps · slippage{" "}
        {data.slippage_bps} bps · parámetros {JSON.stringify(data.params)}
      </p>
      <div className="grid kpis">
        <Kpi label="CAGR" value={pct(data.metrics.cagr)} className={signClass(data.metrics.cagr)} hint={`benchmark ${pct(data.benchmark_metrics.cagr)}`} />
        <Kpi label="Sharpe" value={num(data.metrics.sharpe)} hint={`benchmark ${num(data.benchmark_metrics.sharpe)}`} />
        <Kpi label="Máx. drawdown" value={pct(data.metrics.max_drawdown)} className="neg" hint={`benchmark ${pct(data.benchmark_metrics.max_drawdown)}`} />
        <Kpi label="Sharpe OOS" value={num(wf?.oos_metrics.sharpe)} hint={wf ? `${wf.oos_start} → ${wf.oos_end}` : "sin walk-forward"} />
        <Kpi
          label="Apto para paper"
          value={data.promotion ? (data.promotion.eligible ? "Sí" : "No") : "—"}
          className={data.promotion ? (data.promotion.eligible ? "pos" : "neg") : ""}
          hint={data.promotion?.reasons.join(", ") || "OOS bate al benchmark"}
        />
      </div>
      <div className="card" style={{ marginTop: 16 }}>
        <h2>Equity vs benchmark (escala log)</h2>
        <LineChart series={[strategySeries, benchmarkSeries]} height={380} logScale />
      </div>
      <div className="grid equal" style={{ marginTop: 16 }}>
        <div className="card">
          <h2>Drawdown</h2>
          <DrawdownChart points={data.equity_curve} />
        </div>
        <div className="card">
          <h2>Pesos actuales</h2>
          <WeightsBar weights={data.latest_weights} />
          <h2 style={{ marginTop: 18 }}>Relativo al benchmark</h2>
          <dl className="facts">
            <dt>Beta</dt>
            <dd>{num(data.relative_metrics.beta)}</dd>
            <dt>Correlación</dt>
            <dd>{num(data.relative_metrics.correlation)}</dd>
            <dt>Exceso de CAGR</dt>
            <dd className={signClass(data.relative_metrics.excess_cagr)}>{pct(data.relative_metrics.excess_cagr)}</dd>
            <dt>Rebalanceos</dt>
            <dd>{data.rebalance_count}</dd>
            <dt>Costes totales</dt>
            <dd>{num(data.metrics.total_costs, 0)} USD</dd>
          </dl>
        </div>
      </div>
      <div className="card" style={{ marginTop: 16 }}>
        <h2>Retornos mensuales</h2>
        <MonthlyHeatmap rows={data.monthly_returns} />
      </div>
      <div className="card" style={{ marginTop: 16 }}>
        <h2>Métricas</h2>
        <MetricsTable
          columns={[
            { title: "Estrategia (todo el periodo)", metrics: data.metrics },
            { title: "Benchmark", metrics: data.benchmark_metrics },
            { title: "Estrategia OOS (walk-forward)", metrics: wf?.oos_metrics },
            { title: "Parámetros fijos OOS", metrics: wf?.default_params_oos_metrics },
          ]}
        />
      </div>
      {wf ? (
        <div className="card" style={{ marginTop: 16 }}>
          <h2>Walk-forward: {wf.fold_count} bloques anuales</h2>
          <p className="muted" style={{ fontSize: 13 }}>
            En cada bloque se eligen los parámetros con mejor Sharpe in-sample (datos anteriores) y se evalúan fuera de
            muestra. Estabilidad de parámetros:{" "}
            {Object.entries(wf.param_stability)
              .map(([key, value]) => `${key}=${value.most_common} (${pct(value.most_common_share, 0)})`)
              .join(" · ")}
          </p>
          <table>
            <thead>
              <tr>
                <th>In-sample</th>
                <th>Out-of-sample</th>
                <th>Parámetros elegidos</th>
                <th>Sharpe IS</th>
                <th>CAGR OOS</th>
                <th>Sharpe OOS</th>
                <th>MaxDD OOS</th>
              </tr>
            </thead>
            <tbody>
              {wf.folds.map((fold) => (
                <tr key={fold.oos_start}>
                  <td className="muted">
                    {fold.is_start} → {fold.is_end}
                  </td>
                  <td>
                    {fold.oos_start} → {fold.oos_end}
                  </td>
                  <td className="params">{JSON.stringify(fold.chosen_params)}</td>
                  <td>{num(fold.is_metric)}</td>
                  <td className={signClass(fold.oos_metrics.cagr)}>{pct(fold.oos_metrics.cagr)}</td>
                  <td>{num(fold.oos_metrics.sharpe)}</td>
                  <td className="neg">{pct(fold.oos_metrics.max_drawdown)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
