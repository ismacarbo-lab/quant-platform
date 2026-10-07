import { NavLink, Route, Routes } from "react-router-dom";
import { api } from "./api";
import { useAsync, useJobs } from "./hooks";
import { JobsPanel } from "./components/JobsPanel";
import Overview from "./pages/Overview";
import Strategies from "./pages/Strategies";
import BacktestDetail from "./pages/BacktestDetail";
import Paper from "./pages/Paper";
import PaperAccount from "./pages/PaperAccount";
import Market from "./pages/Market";
import Data from "./pages/Data";

export default function App() {
  const status = useAsync(() => api.status(), []);
  const { jobs } = useJobs(() => status.reload());
  const mode = status.data?.mode ?? "…";
  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="brand">
          quant_platform
          <small>
            modo <strong>{mode}</strong> · dinero ficticio
          </small>
        </div>
        <nav className="nav">
          <NavLink to="/" end>
            Resumen
          </NavLink>
          <NavLink to="/strategies">Estrategias</NavLink>
          <NavLink to="/paper">Paper trading</NavLink>
          <NavLink to="/market">Mercado</NavLink>
          <NavLink to="/data">Datos</NavLink>
        </nav>
        <div className="footer">
          Sin dinero real. Sin broker real. <br />
          Backtests y paper trading no garantizan resultados futuros.
          <br />
          <br />
          v{status.data?.version ?? "?"} · {status.data?.alembic_head_expected ?? ""}
        </div>
      </aside>
      <main className="main">
        <Routes>
          <Route path="/" element={<Overview status={status.data} />} />
          <Route path="/strategies" element={<Strategies />} />
          <Route path="/backtests/:id" element={<BacktestDetail />} />
          <Route path="/paper" element={<Paper paperEnabled={status.data?.paper_enabled ?? false} />} />
          <Route path="/paper/:name" element={<PaperAccount />} />
          <Route path="/market" element={<Market />} />
          <Route path="/data" element={<Data status={status.data} onChanged={status.reload} />} />
        </Routes>
      </main>
      <JobsPanel jobs={jobs} />
    </div>
  );
}
