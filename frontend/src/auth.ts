const STORAGE_KEY = 'desk_admin_key';
const ROLE_KEY = 'desk_auth_role';

export type AuthRole = 'admin' | 'guest';

export function getAuthToken(): string | null {
  try {
    return sessionStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function getAuthRole(): AuthRole {
  try {
    if (sessionStorage.getItem(ROLE_KEY) === 'guest') return 'guest';
  } catch {
    /* ignore quota / private mode */
  }
  return 'admin';
}

export function isGuest(): boolean {
  return getAuthRole() === 'guest';
}

export function setAuthSession(token: string, role: AuthRole): void {
  sessionStorage.setItem(STORAGE_KEY, token);
  sessionStorage.setItem(ROLE_KEY, role);
}

export function setAuthToken(key: string): void {
  setAuthSession(key, 'admin');
}

export function clearAuthToken(): void {
  sessionStorage.removeItem(STORAGE_KEY);
  try {
    sessionStorage.removeItem(ROLE_KEY);
  } catch {
    /* ignore */
  }
}

export function isLoggedIn(): boolean {
  return Boolean(getAuthToken());
}
