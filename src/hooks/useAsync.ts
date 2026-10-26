import { useCallback, useEffect, useRef, useState } from "react";

/** Fetch on mount / when deps change; ignores responses that arrive after a
 * re-run or unmount. Same helper as the TW-Labs dashboard. */
export function useAsync<T>(fetchFn: () => Promise<T>, deps: React.DependencyList, initialValue: T) {
  const [data, setData] = useState<T>(initialValue);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadTick, setReloadTick] = useState(0);
  const fetchFnRef = useRef(fetchFn);
  fetchFnRef.current = fetchFn;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchFnRef
      .current()
      .then(result => {
        if (cancelled) return;
        setData(result);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Something went wrong — please try again.");
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, reloadTick]);

  const reload = useCallback(() => setReloadTick(t => t + 1), []);
  return { data, setData, loading, error, reload } as const;
}
