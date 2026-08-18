import { useEffect, useState } from 'react';
import { smoothedProgressPercent } from '../lib/smoothedProgress';

export function useSmoothedProgress({
  active,
  startedAt,
  estimatedSeconds,
  complete = false,
}: {
  active: boolean;
  startedAt: string | null | undefined;
  estimatedSeconds: number;
  complete?: boolean;
}): number {
  const [percent, setPercent] = useState(0);

  useEffect(() => {
    if (complete) {
      setPercent(100);
      return;
    }
    if (!active || !startedAt) {
      setPercent(0);
      return;
    }
    const started = new Date(startedAt).getTime();
    if (!Number.isFinite(started)) {
      setPercent(0);
      return;
    }
    const estimatedMs = Math.max(1, estimatedSeconds) * 1000;
    const tick = () => {
      setPercent(
        smoothedProgressPercent({
          elapsedMs: Date.now() - started,
          estimatedMs,
          complete: false,
        }),
      );
    };
    tick();
    const id = window.setInterval(tick, 150);
    return () => window.clearInterval(id);
  }, [active, startedAt, estimatedSeconds, complete]);

  return percent;
}
