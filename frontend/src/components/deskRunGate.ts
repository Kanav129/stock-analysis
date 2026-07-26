import type { DailyRunSummary } from '../api/types';

function formatHkt(iso: string, timezone = 'Asia/Hong_Kong') {
  return `${new Date(iso).toLocaleTimeString('en-HK', {
    timeZone: timezone,
    hour: '2-digit',
    minute: '2-digit',
  })} HKT`;
}

export type DeskRunGateTone = 'done' | 'resume';

export type DeskRunGate = {
  tone: DeskRunGateTone | null;
  /** Compact status shown inside the pill button. */
  badge: string | null;
};

/** Derive in-button Done / Resume badge from the daily-gate summary. */
export function getDeskRunGate(
  kind: 'sync' | 'analysis',
  daily: DailyRunSummary | null | undefined,
  busy: boolean,
): DeskRunGate {
  if (busy || !daily) return { tone: null, badge: null };

  if (daily.already_completed_today) {
    const time = daily.finished_at
      ? formatHkt(daily.finished_at, daily.timezone || 'Asia/Hong_Kong')
      : null;
    return { tone: 'done', badge: time ? `Done · ${time}` : 'Done' };
  }

  if (!daily.can_resume) return { tone: null, badge: null };

  const total = daily.universe_count;
  if (kind === 'sync') {
    const news = daily.news_done_count ?? 0;
    const prices = daily.prices_done_count ?? 0;
    const done = Math.min(news, prices);
    return {
      tone: 'resume',
      badge: total && total > 0 ? `Resume · ${done}/${total}` : 'Resume',
    };
  }

  const completed = daily.completed_count ?? 0;
  return {
    tone: 'resume',
    badge: total && total > 0 ? `Resume · ${completed}/${total}` : 'Resume',
  };
}
