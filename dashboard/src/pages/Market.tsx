import { useState } from "react";
import { api } from "../api";
import { useAsync } from "../hooks";
import { CandleChart } from "../components/CandleChart";
import { Kpi } from "../components/Kpi";
import { num, pct, signClass } from "../format";

export default function Market() {
  const universe = useAsync(() => api.universe(), []);
  const [symbol, setSymbol] = useState("SPY");
  const [limit, setLimit] = useState(750);
  const bars = useAsync(() => api.bars(symbol, limit), [symbol, limit]);
  const data = bars.data?.bars ?? [];
  const last = data[data.length - 1];
  const first = data[0];
  const change = last && first ? last.close / first.close - 1 : null;
  const dayChange = data.length > 1 ? last.close / data[data.length - 2].close - 1 : null;
  const instrument = universe.data?.instruments.find((item) => item.symbol === symbol);
  return (
    <div>
      <h1>Mercado</h1>
      <p className="subtitle">Barras diarias almacenadas point-in-time (Yahoo Finance). Línea azul: cierre ajustado por dividendos.</p>
      <div className="toolbar">
        <select value={symbol} onChange={(e) => setSymbol(e.target.value)}>
          {(universe.data?.instruments ?? []).map((item) => (
            <option key={item.symbol} value={item.symbol}>
              {item.symbol} · {item.name}
            </option>
          ))}
        </select>
        <select value={limit} onChange={(e) => setLimit(Number(e.target.value))}>
          <option value={250}>1 año</option>
          <option value={750}>3 años</option>
          <option value={1500}>6 años</option>
          <option value={2600}>10 años</option>
          <option value={6000}>Todo</option>
        </select>
        {bars.error ? <span className="neg">{bars.error}</span> : null}
      </div>
      <div className="grid kpis">
        <Kpi label="Último cierre" value={last ? num(last.close) : "—"} hint={last?.date ?? ""} />
        <Kpi label="Variación diaria" value={pct(dayChange, 2)} className={signClass(dayChange)} />
        <Kpi label="Variación periodo" value={pct(change)} className={signClass(change)} hint={first ? `desde ${first.date}` : ""} />
        <Kpi label="Clase / rol" value={instrument ? `${instrument.asset_class} · ${instrument.role}` : "—"} hint={instrument?.category ?? ""} />
        <Kpi
          label="Cobertura"
          value={instrument?.coverage?.bar_count?.toLocaleString("es-ES") ?? "—"}
          hint={instrument?.coverage ? `${instrument.coverage.first_session} → ${instrument.coverage.last_session}` : ""}
        />
      </div>
      <div className="card" style={{ marginTop: 16 }}>
        <h2>
          {symbol} · {instrument?.name ?? ""}
        </h2>
        {data.length ? <CandleChart bars={data} /> : <div className="empty">{bars.loading ? "Cargando…" : "Sin datos para este símbolo."}</div>}
      </div>
    </div>
  );
}
