import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { ApiNetworkError } from '../../services/api/apiClient';
import { overviewApi } from '../../services/api/overviewApi';
import type { Overview } from '../../types';
import { OverviewContext, type OverviewContextValue } from './overview-context';

/** How often the dashboard re-reads the backend while the tab is visible. */
const POLL_INTERVAL_MS = 10_000;

function messageFor(error: unknown): string {
  if (error instanceof Error) return error.message;
  return 'No se pudo cargar el estado del sistema.';
}

/**
 * Polls `GET /api/v1/overview` and shares the result with the whole shell.
 *
 * A single poll feeds the top bar (connection, model, uptime) and the dashboard
 * body (runs, authorizations, trust), so those panels can never disagree about
 * what the backend last said. Polling pauses while the tab is hidden and resumes
 * with an immediate refresh on return, which keeps a backgrounded dashboard from
 * spending requests it cannot show.
 */
export function OverviewProvider({ children }: { children: ReactNode }) {
  const [data, setData] = useState<Overview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<number | null>(null);

  // Guards a fetch that resolves after unmount, and stops overlapping requests
  // if a poll is still in flight when the next interval fires.
  const alive = useRef(true);
  const inFlight = useRef(false);

  const load = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    try {
      const next = await overviewApi.get();
      if (!alive.current) return;
      setData(next);
      setError(null);
      setConnected(true);
      setLastUpdated(Date.now());
    } catch (caught) {
      if (!alive.current) return;
      setConnected(caught instanceof ApiNetworkError ? false : true);
      setError(messageFor(caught));
    } finally {
      inFlight.current = false;
      if (alive.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    alive.current = true;
    // Fetching the dashboard is exactly the "synchronize with an external
    // system" case an effect is for; the state updates land after the await.
    // oxlint-disable-next-line react/set-state-in-effect
    void load();

    const tick = () => {
      if (document.visibilityState === 'visible') void load();
    };
    const interval = window.setInterval(tick, POLL_INTERVAL_MS);
    const onVisible = () => {
      if (document.visibilityState === 'visible') void load();
    };
    document.addEventListener('visibilitychange', onVisible);

    return () => {
      alive.current = false;
      window.clearInterval(interval);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [load]);

  const value: OverviewContextValue = {
    data,
    loading,
    error,
    connected,
    lastUpdated,
    refresh: () => void load(),
  };

  return <OverviewContext.Provider value={value}>{children}</OverviewContext.Provider>;
}
