const STORAGE_KEY = 'desk_admin_key';

export function getAuthToken(): string | null {
  try {
    return sessionStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setAuthToken(key: string): void {
  sessionStorage.setItem(STORAGE_KEY, key);
}

export function clearAuthToken(): void {
  sessionStorage.removeItem(STORAGE_KEY);
}

export function isLoggedIn(): boolean {
  return Boolean(getAuthToken());
}
