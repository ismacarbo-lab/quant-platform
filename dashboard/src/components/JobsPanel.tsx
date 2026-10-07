import type { Job } from "../api";

const LABELS: Record<string, string> = {
  market_fetch: "Descarga de datos",
  backtest: "Backtest",
  paper_run: "Paper trading",
};

export function JobsPanel({ jobs }: { jobs: Job[] }) {
  const recent = jobs
    .filter((job) => {
      if (job.status === "queued" || job.status === "running") return true;
      if (!job.finished_at) return false;
      return Date.now() - new Date(job.finished_at).getTime() < 60_000;
    })
    .slice(0, 4);
  if (recent.length === 0) return null;
  return (
    <div className="jobs">
      {recent.map((job) => (
        <div className="job" key={job.id}>
          <div className="title">
            <span>{LABELS[job.kind] ?? job.kind}</span>
            <span>
              {job.status === "running" || job.status === "queued" ? (
                <span className="spinner" />
              ) : job.status === "succeeded" ? (
                <span className="pos">listo</span>
              ) : (
                <span className="neg">error</span>
              )}
            </span>
          </div>
          {job.error ? <div className="neg">{job.error}</div> : null}
          <div className="muted">{new Date(job.created_at).toLocaleTimeString("es-ES")}</div>
        </div>
      ))}
    </div>
  );
}
