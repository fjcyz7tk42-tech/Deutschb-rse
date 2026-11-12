import { useEffect, useState } from 'react';

/**
 * Loads data for a request key. The result is tagged with its key, so a response that belongs to an
 * older key is never shown: while the new request runs, `data` is null (loading).
 * Pass key = null to load nothing.
 */
export function useFetch<T>(key: string | null, load: () => Promise<T>) {
  const [state, setState] = useState<{ key: string; data: T | null; error: string | null } | null>(null);

  useEffect(() => {
    if (key === null) return;
    let live = true;
    load()
      .then((data) => live && setState({ key, data, error: null }))
      .catch((e) => live && setState({ key, data: null, error: String(e?.message ?? e) }));
    return () => {
      live = false;
    };
    // `load` is recreated every render; the key captures everything it depends on.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const current = state && state.key === key ? state : null;
  return { data: current?.data ?? null, error: current?.error ?? null, loading: key !== null && !current };
}
