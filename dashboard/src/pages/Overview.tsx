import { Link } from "react-router-dom";
import { api, type Status } from "../api";
import { useAsync } from "../hooks";
import { Kpi } from "../components/Kpi";
import { LineChart } from "../components/LineChart";
import { colorFor, money, pct, shortDate, signClass, strategyLabel } from "../format";

export default function Overview({ status }: { status: Status | null }) {
  const accounts = useAsync(() => api.paperAccounts(), []);
  const ranking = useAsync(() => api.ranking(), []);
  const list = accounts.data?.accounts ?? [];
  const best = [...list].sort((a, b) => (b.total_return ?? -1) - (a.total_return ?? -1))[0];
  const benchmark = list.find((item) => item.strategy_name === "buy_and_hold") ?? list[0];
  const curves = useAsync(
    async () => {
      const names = list.slice(0, 8).map((item) => item.name);
      const results = await Promise.all(names.map((name) => api.paperEquity(name)));
      return results;
    },
    [list.map((item) => item.name).join(",")],
  );
  const series =
    curves.data?.map((item, index) => ({
      name: strategyLabel(item.name),
      color: colorFor(index),
      data: item.equity.map((point) => ({ date: point.date, value: point.equity })),
    })) ?? [];

  return (
    <div>
      <h1>Resumen</h1>
      <p className="subtitle">
        Cuentas de paper trading (dinero ficticio) comparadas entre sí y con comprar y mantener SPY.
      </p>
      {status && !status.database.reachable ? (
        <div className="notice error">PostgreSQL no está accesible. Arranca `docker compose up -d` y recarga.</div>
      ) : null}
      {status && status.database.reachable && !status.database.market_data_present ? (
        <div className="notice">
          Aún no hay datos de mercado. Ve a <Link to="/data">Datos</Link> y pulsa “Descargar datos”.
        </div>
      ) : null}
      {status && !status.paper_enabled ? (
        <div className="notice info">
          El servidor está en modo <strong>{status.mode}</strong>: el paper trading es de solo lectura. Arranca con
          <code> APP_MODE=paper</code> para ejecutar el motor.
        </div>
      ) : null}
      <div className="grid kpis">
        <Kpi
          label="Mejor cuenta paper"
          value={best ? strategyLabel(best.strategy_name) : "—"}
          hint={best ? `${pct(best.total_return)} desde ${shortDate(best.first_session)}` : "sin cuentas"}
        />
        <Kpi
          label="Equity mejor cuenta"
          value={money(best?.equity ?? null)}
          className={signClass(best?.total_return ?? null)}
          hint={best ? `inicio ${money(best.initial_cash)}` : ""}
        />
        <Kpi
          label="Benchmark (SPY)"
          value={pct(benchmark?.benchmark_return ?? null)}
          className={signClass(benchmark?.benchmark_return ?? null)}
          hint="mismo periodo que las cuentas"
        />
        <Kpi
          label="Último dato"
          value={status?.database.last_session ?? "—"}
          hint={`${status?.database.bar_count?.toLocaleString("es-ES") ?? 0} barras · ${status?.database.symbol_count ?? 0} símbolos`}
        />
        <Kpi label="Backtests guardados" value={String(status?.database.backtest_count ?? 0)} hint="ver Estrategias" />
      </div>
      <div className="grid two" style={{ marginTop: 16 }}>
        <div className="card">
          <h2>Equity paper por cuenta</h2>
          {series.length ? (
            <LineChart series={series} height={360} />
          ) : (
            <div className="empty">Sin cuentas paper todavía. Ejecuta el motor desde “Paper trading”.</div>
          )}
        </div>
        <div className="card">
          <h2>Cuentas</h2>
          {list.length ? (
            <table>
              <thead>
                <tr>
                  <th>Cuenta</th>
                  <th>Equity</th>
                  <th>Ret.</th>
                  <th>MaxDD</th>
                </tr>
              </thead>
              <tbody>
                {list.map((item) => (
                  <tr key={item.name}>
                    <td>
                      <Link to={`/paper/${encodeURIComponent(item.name)}`}>{strategyLabel(item.strategy_name)}</Link>
                    </td>
                    <td>{money(item.equity)}</td>
                    <td className={signClass(item.total_return)}>{pct(item.total_return)}</td>
                    <td className="neg">{pct(item.max_drawdown)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="empty">—</div>
          )}
        </div>
      </div>
      <div className="card" style={{ marginTop: 16 }}>
        <h2>Ranking de backtests (último por estrategia, costes incluidos)</h2>
        {ranking.data?.ranking.length ? (
          <table>
            <thead>
              <tr>
                <th>Estrategia</th>
                <th>CAGR</th>
                <th>Vol</th>
                <th>Sharpe</th>
                <th>MaxDD</th>
                <th>Sharpe OOS</th>
                <th>Benchmark CAGR</th>
                <th>Apto paper</th>
              </tr>
            </thead>
            <tbody>
              {ranking.data.ranking.map((row) => (
                <tr key={row.id}>
                  <td>
                    <Link to={`/backtests/${row.id}`}>{strategyLabel(row.strategy_name)}</Link>
                  </td>
                  <td className={signClass(row.metrics.cagr)}>{pct(row.metrics.cagr)}</td>
                  <td>{pct(row.metrics.annual_volatility)}</td>
                  <td>{row.metrics.sharpe?.toFixed(2) ?? "—"}</td>
                  <td className="neg">{pct(row.metrics.max_drawdown)}</td>
                  <td>{row.walk_forward_oos_metrics?.sharpe?.toFixed(2) ?? "—"}</td>
                  <td>{pct(row.benchmark_metrics.cagr)}</td>
                  <td>
                    {row.promotion_eligible === null ? (
                      <span className="badge">benchmark</span>
                    ) : row.promotion_eligible ? (
                      <span className="badge ok">sí</span>
                    ) : (
                      <span className="badge no">no</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="empty">Sin backtests. Lánzalos desde “Estrategias”.</div>
        )}
      </div>
    </div>
  );
}
