import { useCallback, useEffect, useRef, useState } from "react";
import { errorMessage } from "../api/client";

export interface AsyncState<T> {
  data: T | undefined;
  error: string | null;
  loading: boolean;
  /** Fetch again. Keeps showing the current data while the request is in flight. */
  reload: () => Promise<void>;
  setData: (data: T) => void;
}

/** Load data on mount and whenever `deps` change. */
export function useAsync<T>(load: () => Promise<T>, deps: unknown[]): AsyncState<T> {
  const [data, setData] = useState<T | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const generation = useRef(0);
  const loadRef = useRef(load);
  loadRef.current = load;

  const run = useCallback(async () => {
    const current = ++generation.current;
    try {
      const result = await loadRef.current();
      if (current !== generation.current) return;
      setData(result);
      setError(null);
    } catch (cause) {
      if (current !== generation.current) return;
      setError(errorMessage(cause));
    } finally {
      if (current === generation.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    setData(undefined);
    void run();
    return () => {
      generation.current++;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, error, loading, reload: run, setData };
}

/** Call `tick` every `intervalMs` while `active` is true. */
export function usePolling(tick: () => void | Promise<void>, active: boolean, intervalMs = 2500) {
  const tickRef = useRef(tick);
  tickRef.current = tick;

  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => void tickRef.current(), intervalMs);
    return () => clearInterval(timer);
  }, [active, intervalMs]);
}
