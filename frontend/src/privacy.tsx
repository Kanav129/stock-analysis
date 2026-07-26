import {
  createContext,
  useCallback,
  useContext,
  useState,
  type ReactNode,
} from 'react';

const STORAGE_KEY = 'desk_privacy_mode';

type PrivacyContextValue = {
  privacyMode: boolean;
  setPrivacyMode: (on: boolean) => void;
  togglePrivacyMode: () => void;
};

const PrivacyContext = createContext<PrivacyContextValue | null>(null);

function readStored(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === '1';
  } catch {
    return false;
  }
}

export function PrivacyModeProvider({ children }: { children: ReactNode }) {
  const [privacyMode, setPrivacyModeState] = useState(() => readStored());

  const setPrivacyMode = useCallback((on: boolean) => {
    setPrivacyModeState(on);
    try {
      localStorage.setItem(STORAGE_KEY, on ? '1' : '0');
    } catch {
      /* ignore quota / private mode */
    }
  }, []);

  const togglePrivacyMode = useCallback(() => {
    setPrivacyModeState((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(STORAGE_KEY, next ? '1' : '0');
      } catch {
        /* ignore */
      }
      return next;
    });
  }, []);

  return (
    <PrivacyContext.Provider value={{ privacyMode, setPrivacyMode, togglePrivacyMode }}>
      {children}
    </PrivacyContext.Provider>
  );
}

export function usePrivacyMode(): PrivacyContextValue {
  const ctx = useContext(PrivacyContext);
  if (!ctx) {
    throw new Error('usePrivacyMode must be used within PrivacyModeProvider');
  }
  return ctx;
}
