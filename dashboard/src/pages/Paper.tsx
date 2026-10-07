import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAsync } from "../hooks";
import { LineChart } from "../components/LineChart";
import { WeightsBar } from "../components/Weights";
import { colorFor, money, pct, shortDate, signClass, strategyLabel } from "../format";

export default function Paper({ paperEnabled }: { paperEnabled: boolean }) {
  const accounts = useAsync(() => api.paperAccounts(), []);
  const [message, setMessage] = useState<string | null>(null);
  const [replayFrom, setReplayFrom] = useState("");
  const [busy, setBusy] = useState(false);
  const list = accounts.data?.accounts ?? [];
  const curves = useAsync(
    async () => Promise.all(list.map((item) => api.paperEquity(item.name))),
    [list.map((item) => item.name).join(",")],
  );
  const relative =
    curves.data?.map((item, index) => {
      const base = item.equity[0]?.equity ?? 1;
      return {
        name: strategyLabel(item.name),
        color: colorFor(index),
        data: item.equity.map((point) => ({ date: point.date, value: point.equity / base - 1 })),
      };
    }) ?? [];
  const benchmarkCurve = curves.data?.find((item) => item.equity.some((p) => p.benchmark !== null));
  if (benchmarkCurve) {
    const base = benchmarkCurve.equity.find((p) => p.benchmark !== null)?.benchmark ?? 1;
    relative.push({
      name: "SPY (benchmark)",
      color: "#8da0c9",
      data: benchmarkCurve.equity
        .filter((p) => p.benchmark !== null)
        .map((p) => ({ date: p.date, value: (p.benchmark as number) / base - 1 })),
    });
  }

  async function run(options: { fetch?: boolean; replay?: boolean }) {
    setBusy(true);
    setMessage(null);
    try {
      const job = await api.runPaper({
        fetch: options.fetch ?? false,
        replay_from: options.replay && replayFrom ? replayFrom : null,
      });
      setMessage(`Motor paper lanzado (job ${job.id.slice(0, 8)}). Recarga cuando termine.`);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <h1>Paper trading</h1>
      <p className="subtitle">
        Una cuenta de 100.000 USD ficticios por estrategia. Cada día tras el cierre: se ejecutan al open las órdenes
        decididas la sesión anterior (con slippage y comisión), se cobran dividendos, se valora la cartera y se decide
        el siguiente rebalanceo. Las sesiones marcadas como “replay” se simularon sobre histórico para construir el
        track record inicial.
      </p>
      {!paperEnabled ? (
        <div className="notice info">
          Servidor en modo solo lectura. Para ejecutar el motor arranca la API con <code>APP_MODE=paper</code> o usa{" "}
          <code>make paper-run</code>.
        </div>
      ) : (
        <div className="toolbar">
          <button onClick={() => void run({ fetch: true })} disabled={busy}>
            Descargar datos y ejecutar hoy
          </button>
          <button className="secondary" onClick={() => void run({})} disabled={busy}>
            Ejecutar con datos actuales
          </button>
          <input type="date" value={replayFrom} onChange={(e) => setReplayFrom(e.target.value)} />
          <button className="secondary" onClick={() => void run({ replay: true })} disabled={busy || !replayFrom}>
            Replay desde fecha
          </button>
          <button className="secondary" onClick={() => accounts.reload()}>
            Recargar
          </button>
          {message ? <span className="muted">{message}</span> : null}
        </div>
      )}
      <div className="card">
        <h2>Rentabilidad acumulada por cuenta vs SPY</h2>
        {relative.length ? <LineChart series={relative} height={380} percentAxis /> : <div className="empty">Sin cuentas todavía.</div>}
      </div>
      <div className="card" style={{ marginTop: 16 }}>
        <h2>Cuentas</h2>
        <table>
          <thead>
            <tr>
              <th>Cuenta</th>
              <th>Estado</th>
              <th>Equity</th>
              <th>Retorno</th>
              <th>SPY mismo periodo</th>
              <th>MaxDD</th>
              <th>Efectivo</th>
              <th>Desde</th>
              <th>Último run</th>
              <th>Fills</th>
              <th style={{ minWidth: 220 }}>Pesos</th>
            </tr>
          </thead>
          <tbody>
            {list.map((item) => (
              <tr key={item.name}>
                <td>
                  <Link to={`/paper/${encodeURIComponent(item.name)}`}>{strategyLabel(item.strategy_name)}</Link>
                  <div className="params">{item.rebalance} · {item.commission_bps}+{item.slippage_bps} bps</div>
                </td>
                <td>
                  <span className={`badge ${item.status === "active" ? "ok" : "warn"}`}>{item.status}</span>
                </td>
                <td>{money(item.equity)}</td>
                <td className={signClass(item.total_return)}>{pct(item.total_return)}</td>
                <td className={signClass(item.benchmark_return)}>{pct(item.benchmark_return)}</td>
                <td className="neg">{pct(item.max_drawdown)}</td>
                <td>{money(item.cash)}</td>
                <td className="muted">{shortDate(item.first_session)}</td>
                <td className="muted">{shortDate(item.last_run_date)}</td>
                <td>{item.fill_count}</td>
                <td style={{ textAlign: "left" }}>
                  <WeightsBar weights={item.weights} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
