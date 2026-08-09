import { useEffect, useState } from 'react';
import { isUsRegularSession } from '../lib/usMarketHours';

const CHECK_MS = 30_000;

/** Reactive US regular-session flag; re-checks every 30s so polling can resume at open. */
export function useUsRegularSession(): boolean {
  const [open, setOpen] = useState(() => isUsRegularSession());

  useEffect(() => {
    const sync = () => setOpen(isUsRegularSession());
    sync();
    const id = window.setInterval(sync, CHECK_MS);
    return () => window.clearInterval(id);
  }, []);

  return open;
}
