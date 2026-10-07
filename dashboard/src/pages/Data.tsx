import { useState } from "react";
import { api, type Status } from "../api";
import { useAsync } from "../hooks";
import { Kpi } from "../components/Kpi";

export default function Data({ status, onChanged }: { status: Status | null; onChanged: () => void }) {
  const universe = useAsync(() => api.universe(), []);
  const jobs = useAsync(() => api.jobs(), []);
  const [message, setMessage] = useState<string | null>(null);
  const [includeCrypto, setIncludeCrypto] = useState(true);
  const [busy, setBusy] = useState(false);

  async function fetchData(fullRefresh = false) {
    setBusy(true);
    setMessage(null);
    try {
      const job = await api.fetchMarketData({ include_crypto: includeCrypto, full_refresh: fullRefresh });
      setMessage(`Descarga lanzada (job ${job.id.slice(0, 8)}). La primera carga completa tarda unos minutos.`);
      window.setTimeout(() => {
        universe.reload();
        jobs.reload();
        onChanged();
      }, 4000);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <h1>Datos</h1>
      <p className="subtitle">
        Fuente: Yahoo Finance vía yfinance (gratuita, sin cuenta). Cada barra se guarda con su hora de disponibilidad
        (point-in-time); las revisiones del proveedor se almacenan como correcciones, nunca se sobrescriben.
      </p>
      <div className="toolbar">
        <button onClick={() => void fetchData(false)} disabled={busy}>
          Descargar datos (incremental)
        </button>
        <button className="secondary" onClick={() => void fetchData(true)} disabled={busy}>
          Refresco completo
        </button>
        <label className="muted" style={{ fontSize: 13 }}>
          <input type="checkbox" checked={includeCrypto} onChange={(e) => setIncludeCrypto(e.target.checked)} /> incluir BTC-USD
        </label>
        <button
          className="secondary"
          onClick={() => {
            universe.reload();
            jobs.reload();
            onChanged();
          }}
        >
          Recargar
        </button>
        {message ? <span className="muted">{message}</span> : null}
      </div>
      <div className="grid kpis">
        <Kpi label="Base de datos" value={status?.database.reachable ? "OK" : "sin conexión"} className={status?.database.reachable ? "pos" : "neg"} hint={status?.alembic_head_expected} />
        <Kpi label="Fuente" value={status?.database.market_data_source ?? "—"} hint={status?.database.market_data_present ? "cargada" : "sin datos"} />
        <Kpi label="Barras" value={status?.database.bar_count?.toLocaleString("es-ES") ?? "0"} hint={`${status?.database.symbol_count ?? 0} símbolos`} />
        <Kpi label="Última sesión" value={status?.database.last_session ?? "—"} />
        <Kpi label="Modo" value={status?.mode ?? "—"} hint="live deshabilitado · sin dinero real" />
      </div>
      <div className="card" style={{ marginTop: 16 }}>
        <h2>Universo y cobertura</h2>
        <table>
          <thead>
            <tr>
              <th>Símbolo</th>
              <th style={{ textAlign: "left" }}>Nombre</th>
              <th>Clase</th>
              <th>Rol</th>
              <th>Primera sesión</th>
              <th>Última sesión</th>
              <th>Barras</th>
              <th>Dividendos</th>
            </tr>
          </thead>
          <tbody>
            {(universe.data?.instruments ?? []).map((item) => (
              <tr key={item.symbol}>
                <td>
                  {item.symbol} {item.optional ? <span className="badge">opcional</span> : null}
                </td>
                <td style={{ textAlign: "left" }}>{item.name}</td>
                <td>{item.asset_class}</td>
                <td>{item.role}</td>
                <td className="muted">{item.coverage?.first_session ?? "—"}</td>
                <td className="muted">{item.coverage?.last_session ?? "—"}</td>
                <td>{item.coverage?.bar_count?.toLocaleString("es-ES") ?? "—"}</td>
                <td>{item.coverage?.dividend_count ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="card" style={{ marginTop: 16 }}>
        <h2>Trabajos recientes</h2>
        <table>
          <thead>
            <tr>
              <th>Tipo</th>
              <th>Estado</th>
              <th>Creado</th>
              <th>Terminado</th>
              <th style={{ textAlign: "left" }}>Error</th>
            </tr>
          </thead>
          <tbody>
            {(jobs.data?.jobs ?? []).map((job) => (
              <tr key={job.id}>
                <td>{job.kind}</td>
                <td>
                  <span className={`badge ${job.status === "succeeded" ? "ok" : job.status === "failed" ? "no" : "info"}`}>{job.status}</span>
                </td>
                <td className="muted">{new Date(job.created_at).toLocaleString("es-ES")}</td>
                <td className="muted">{job.finished_at ? new Date(job.finished_at).toLocaleString("es-ES") : "—"}</td>
                <td style={{ textAlign: "left", whiteSpace: "normal" }} className="neg">
                  {job.error ?? ""}
                </td>
              </tr>
            ))}
            {(jobs.data?.jobs ?? []).length === 0 ? (
              <tr>
                <td colSpan={5} className="muted">
                  Sin trabajos en esta sesión del servidor.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
      <div className="card" style={{ marginTop: 16 }}>
        <h2>Capacidades deshabilitadas</h2>
        <div className="legend">
          {(status?.capabilities.disabled ?? []).map((item) => (
            <span className="badge no" key={item}>
              {item}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
