/** US regular equity session helpers (America/New_York). */

const NY = 'America/New_York';

function nyParts(date: Date): { weekday: string; hour: number; minute: number } {
  const fmt = new Intl.DateTimeFormat('en-US', {
    timeZone: NY,
    weekday: 'short',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  });
  const map: Record<string, string> = {};
  for (const p of fmt.formatToParts(date)) {
    if (p.type !== 'literal') map[p.type] = p.value;
  }
  return {
    weekday: map.weekday ?? '',
    hour: Number(map.hour),
    minute: Number(map.minute),
  };
}

/** True Mon–Fri 09:30–16:00 America/New_York (regular session). */
export function isUsRegularSession(now: Date = new Date()): boolean {
  const { weekday, hour, minute } = nyParts(now);
  if (weekday === 'Sat' || weekday === 'Sun') return false;
  const mins = hour * 60 + minute;
  return mins >= 9 * 60 + 30 && mins < 16 * 60;
}
