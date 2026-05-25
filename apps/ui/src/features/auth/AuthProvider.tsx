import type { ReactNode } from 'react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { clearSessionToken } from '../../shared/api/apiClient';
import { AuthContext, type AuthContextValue } from './authContext';
import { loadAuthState, logout as requestLogout, pairWithCode } from './authApi';

export function AuthProvider({ children }: { children: ReactNode }) {
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
    let cancelled = false;

    async function loadInitialAuthState() {
      try {
        const state = await loadAuthState();
        if (cancelled) {
          return;
        }
        setAuthRequired(state.auth_required);
        setAuthenticated(state.authenticated);
        if (state.auth_required && !state.authenticated) {
          clearSessionToken();
        }
      } catch (caught) {
        if (cancelled) {
          return;
        }
        setError(caught instanceof Error ? caught.message : 'Cannot reach CalcChain backend');
        setAuthRequired(true);
        setAuthenticated(false);
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void loadInitialAuthState();

    return () => {
      cancelled = true;
    };
  }, []);

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
