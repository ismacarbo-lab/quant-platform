import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Job } from "./api";

export type AsyncState<T> = {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
};

export function useAsync<T>(loader: () => Promise<T>, deps: unknown[] = []): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((value) => value + 1), []);
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    loader()
      .then((result) => {
        if (!cancelled) {
          setData(result);
          setError(null);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  return { data, error, loading, reload };
}

/** Polls the job list while any job is active and notifies on completion. */
export function useJobs(onFinished?: (job: Job) => void): { jobs: Job[]; refresh: () => void } {
  const [jobs, setJobs] = useState<Job[]>([]);
  const seen = useRef<Record<string, string>>({});
  const callback = useRef(onFinished);
  callback.current = onFinished;

  const refresh = useCallback(() => {
    api
      .jobs()
      .then((payload) => {
        for (const job of payload.jobs) {
          const previous = seen.current[job.id];
          if (previous && previous !== job.status && (job.status === "succeeded" || job.status === "failed")) {
            callback.current?.(job);
          }
          seen.current[job.id] = job.status;
        }
        setJobs(payload.jobs);
      })
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    refresh();
    const active = jobs.some((job) => job.status === "queued" || job.status === "running");
    const interval = window.setInterval(refresh, active ? 2000 : 15000);
    return () => window.clearInterval(interval);
  }, [refresh, jobs.length, jobs.map((job) => job.status).join("|")]);

  return { jobs, refresh };
}
