/** Session cache so Desk remounts paint instantly while network refreshes. */

/** Bump when cached payload shape changes (e.g. new summary fields). */
const KEY = 'desk_session_cache_v3';
const MAX_AGE_MS = 15 * 60_000;

export type DeskSessionCache = {
  at: number;
  holdings?: unknown;
  ratings?: unknown;
  ratingsDeskKey?: string;
  watchlist?: unknown;
  marketQuotes?: unknown;
  heatQuotes?: unknown;
  heatQuoteKey?: string;
  holdingsRestQuotes?: unknown;
  holdingsRestQuoteKey?: string;
};

export function readDeskCache(): DeskSessionCache | null {
  try {
    const raw = sessionStorage.getItem(KEY);
    if (!raw) return null;
    const data = JSON.parse(raw) as DeskSessionCache;
    if (!data?.at || Date.now() - data.at > MAX_AGE_MS) return null;
    return data;
  } catch {
    return null;
  }
}

export function patchDeskCache(partial: Partial<DeskSessionCache>): void {
  try {
    const prev = readDeskCache() ?? { at: 0 };
    const next: DeskSessionCache = { ...prev, ...partial, at: Date.now() };
    sessionStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    /* private mode / quota — ignore */
  }
}

export function clearDeskCache(): void {
  try {
    sessionStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
}
