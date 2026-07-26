import { useEffect, useState } from 'react';
import { api } from '../api/client';

export type BackendWakeStatus = 'waking' | 'ready' | 'slow';

const DEADLINE_MS = 90_000;
const RETRY_MS = 3_000;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

/**
 * Ping /health on mount so a sleeping Render free dyno starts booting
 * while the user is still on the login page.
 */
export function useBackendWake(): BackendWakeStatus {
  const [status, setStatus] = useState<BackendWakeStatus>('waking');

  useEffect(() => {
    let cancelled = false;
    const startedAt = Date.now();

    async function wake() {
      while (!cancelled) {
        const remaining = DEADLINE_MS - (Date.now() - startedAt);
        if (remaining <= 0) {
          setStatus('slow');
          return;
        }

        try {
          await Promise.race([
            api.health(),
            sleep(remaining).then(() => {
              throw new Error('wake-deadline');
            }),
          ]);
          if (!cancelled) setStatus('ready');
          return;
        } catch {
          if (cancelled) return;
          if (Date.now() - startedAt >= DEADLINE_MS) {
            setStatus('slow');
            return;
          }
          await sleep(RETRY_MS);
        }
      }
    }

    void wake();
    return () => {
      cancelled = true;
    };
  }, []);

  return status;
}
