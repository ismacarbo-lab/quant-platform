import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { useAsync } from "../hooks";
import { Kpi } from "../components/Kpi";
import { LineChart } from "../components/LineChart";
import { DrawdownChart } from "../components/DrawdownChart";
import { WeightsBar } from "../components/Weights";
import { money, num, pct, shortDate, signClass, strategyLabel } from "../format";

export default function PaperAccount() {
  const { name } = useParams();
  const detail = useAsync(() => api.paperAccount(name ?? ""), [name]);
  const equity = useAsync(() => api.paperEquity(name ?? ""), [name]);
  const [message, setMessage] = useState<string | null>(null);
  const data = detail.data;
  if (detail.error) return <div className="notice error">{detail.error}</div>;
  if (!data) return <div className="empty">Cargando…</div>;
  const account = data.account;
  const points = equity.data?.equity ?? [];
  const series = [
    {
      name: strategyLabel(account.strategy_name),
      color: "#4cc9f0",
      data: points.map((p) => ({ date: p.date, value: p.equity })),
    },
    {
      name: `${account.benchmark_symbol} buy & hold`,
      color: "#8da0c9",
      dashed: true,
      data: points.filter((p) => p.benchmark !== null).map((p) => ({ date: p.date, value: p.benchmark as number })),
    },
  ];
  const replayedUntil = [...points].reverse().find((p) => p.replayed)?.date;

  async function toggle() {
    try {
      await api.setAccountStatus(account.name, account.status === "active" ? "paused" : "active");
      detail.reload();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <div>
      <p className="muted">
        <Link to="/paper">← Paper trading</Link>
      </p>
      <h1>{strategyLabel(account.strategy_name)}</h1>
      <p className="subtitle">
        cuenta <code>{account.name}</code> · {account.rebalance} · comisión {account.commission_bps} bps · slippage{" "}
        {account.slippage_bps} bps · parámetros {JSON.stringify(account.params)}
        {replayedUntil ? ` · replay hasta ${replayedUntil}` : ""}
      </p>
      <div className="toolbar">
        <button className={account.status === "active" ? "danger" : ""} onClick={() => void toggle()}>
          {account.status === "active" ? "Pausar cuenta" : "Reactivar cuenta"}
        </button>
        {message ? <span className="neg">{message}</span> : null}
      </div>
      <div className="grid kpis">
        <Kpi label="Equity" value={money(account.equity)} hint={`inicio ${money(account.initial_cash)}`} />
        <Kpi label="Retorno" value={pct(account.total_return)} className={signClass(account.total_return)} hint={`SPY ${pct(account.benchmark_return)}`} />
        <Kpi label="Máx. drawdown" value={pct(account.max_drawdown)} className="neg" />
        <Kpi label="Efectivo" value={money(account.cash)} hint={`posiciones ${money(account.positions_value)}`} />
        <Kpi label="Sesiones" value={String(account.snapshot_count)} hint={`${account.replayed_snapshots} replay · ${account.fill_count} fills`} />
      </div>
      <div className="card" style={{ marginTop: 16 }}>
        <h2>Equity vs {account.benchmark_symbol}</h2>
        {points.length ? <LineChart series={series} height={360} /> : <div className="empty">Sin snapshots.</div>}
      </div>
      <div className="grid equal" style={{ marginTop: 16 }}>
        <div className="card">
          <h2>Drawdown</h2>
          <DrawdownChart points={points} />
        </div>
        <div className="card">
          <h2>Asignación actual</h2>
          <WeightsBar weights={account.weights} />
          <h2 style={{ marginTop: 18 }}>Posiciones</h2>
          <table>
            <thead>
              <tr>
                <th>Símbolo</th>
                <th>Cantidad</th>
                <th>Coste medio</th>
              </tr>
            </thead>
            <tbody>
              {data.positions.map((row) => (
                <tr key={row.symbol}>
                  <td>{row.symbol}</td>
                  <td>{num(row.quantity, 4)}</td>
                  <td>{num(row.average_cost)}</td>
                </tr>
              ))}
              {data.positions.length === 0 ? (
                <tr>
                  <td colSpan={3} className="muted">
                    Sin posiciones abiertas (100% efectivo)
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </div>
      <div className="grid equal" style={{ marginTop: 16 }}>
        <div className="card">
          <h2>Órdenes recientes</h2>
          <table>
            <thead>
              <tr>
                <th>Decisión</th>
                <th>Símbolo</th>
                <th>Lado</th>
                <th>Cantidad</th>
                <th>Peso objetivo</th>
                <th>Estado</th>
              </tr>
            </thead>
            <tbody>
              {data.orders.slice(0, 25).map((row) => (
                <tr key={row.id}>
                  <td>{row.session_date}</td>
                  <td>{row.symbol}</td>
                  <td className={row.side === "buy" ? "pos" : "neg"}>{row.side}</td>
                  <td>{num(row.quantity, 4)}</td>
                  <td>{pct(row.target_weight)}</td>
                  <td>
                    <span className={`badge ${row.status === "filled" ? "ok" : row.status === "pending" ? "info" : "no"}`}>{row.status}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="card">
          <h2>Fills recientes</h2>
          <table>
            <thead>
              <tr>
                <th>Fecha</th>
                <th>Símbolo</th>
                <th>Lado</th>
                <th>Cantidad</th>
                <th>Precio</th>
                <th>Ref.</th>
                <th>Comisión</th>
                <th>Slippage</th>
              </tr>
            </thead>
            <tbody>
              {data.fills.slice(0, 25).map((row) => (
                <tr key={row.id}>
                  <td>{row.fill_date}</td>
                  <td>{row.symbol}</td>
                  <td className={row.side === "buy" ? "pos" : "neg"}>{row.side}</td>
                  <td>{num(row.quantity, 4)}</td>
                  <td>{num(row.price)}</td>
                  <td className="muted">{num(row.reference_price)}</td>
                  <td>{num(row.commission, 4)}</td>
                  <td>{num(row.slippage_cost, 4)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <div className="card" style={{ marginTop: 16 }}>
        <h2>Últimas ejecuciones del motor</h2>
        <table>
          <thead>
            <tr>
              <th>Sesión</th>
              <th>Estado</th>
              <th>Replay</th>
              <th>Rebalanceo</th>
              <th>Órdenes</th>
              <th>Fills</th>
              <th>Dividendos</th>
              <th>Ejecutado</th>
            </tr>
          </thead>
          <tbody>
            {data.runs.map((row) => (
              <tr key={row.session_date}>
                <td>{row.session_date}</td>
                <td>
                  <span className={`badge ${row.status === "ok" ? "ok" : "warn"}`}>{row.status}</span>
                </td>
                <td className="muted">{row.replayed ? "sí" : "no"}</td>
                <td>{row.rebalanced ? "sí" : "—"}</td>
                <td>{row.orders_created}</td>
                <td>{row.fills_executed}</td>
                <td>{row.dividends_credited ? money(row.dividends_credited, 2) : "—"}</td>
                <td className="muted">{shortDate(row.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
