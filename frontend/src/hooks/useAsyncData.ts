import { useCallback, useEffect, useRef, useState } from 'react';

export interface AsyncState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

function messageFor(error: unknown): string {
  if (error instanceof Error) return error.message;
  return 'La petición al backend ha fallado.';
}

/**
 * A small read hook for list/detail pages.
 *
 * It resolves the two failures that page code keeps re-implementing: a response
 * that arrives after unmount, and a duplicate request when the dependency tuple
 * changes while one is still in flight. `reload` is stable, so it is safe to use
 * as an effect dependency or a button handler.
 */
export function useAsyncData<T>(
  load: () => Promise<T>,
  deps: unknown[] = [],
): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const alive = useRef(true);
  const requestId = useRef(0);
  const loadRef = useRef(load);
  loadRef.current = load;

  const run = useCallback(() => {
    const id = ++requestId.current;
    setLoading(true);
    void (async () => {
      try {
        const next = await loadRef.current();
        if (!alive.current || id !== requestId.current) return;
        setData(next);
        setError(null);
      } catch (caught) {
        if (!alive.current || id !== requestId.current) return;
        setError(messageFor(caught));
      } finally {
        if (alive.current && id === requestId.current) setLoading(false);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    alive.current = true;
    run();
    return () => {
      alive.current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, loading, error, reload: run };
}
