import { createContext } from 'react';

export type AuthContextValue = {
  loading: boolean;
  authRequired: boolean;
  authenticated: boolean;
  error: string | null;
  pair: (code: string) => Promise<void>;
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
};

export const AuthContext = createContext<AuthContextValue | null>(null);
