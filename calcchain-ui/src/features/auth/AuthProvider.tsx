import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { clearSessionToken } from '../../shared/api/apiClient';
import { loadAuthState, logout as requestLogout, pairWithCode } from './authApi';

type AuthContextValue = {
  loading: boolean;
  authRequired: boolean;
  authenticated: boolean;
  error: string | null;
  pair: (code: string) => Promise<void>;
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [loading, setLoading] = useState(true);
  const [authRequired, setAuthRequired] = useState(true);
  const [authenticated, setAuthenticated] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const state = await loadAuthState();
      setAuthRequired(state.auth_required);
      setAuthenticated(state.authenticated);
      if (state.auth_required && !state.authenticated) {
        clearSessionToken();
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Cannot reach CalcChain backend');
      setAuthRequired(true);
      setAuthenticated(false);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const pair = useCallback(async (code: string) => {
    setError(null);
    await pairWithCode(code);
    const state = await loadAuthState();
    setAuthRequired(state.auth_required);
    setAuthenticated(state.authenticated);
  }, []);

  const logout = useCallback(async () => {
    await requestLogout();
    await refresh();
  }, [refresh]);

  const value = useMemo<AuthContextValue>(
    () => ({ loading, authRequired, authenticated, error, pair, refresh, logout }),
    [loading, authRequired, authenticated, error, pair, refresh, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (context === null) {
    throw new Error('useAuth must be used inside AuthProvider');
  }
  return context;
}
