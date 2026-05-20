import { apiFetch, clearSessionToken, storeSessionToken } from '../../shared/api/apiClient';
import type { AuthState, PairingResponse } from './types';

export async function loadAuthState(): Promise<AuthState> {
  return apiFetch<AuthState>('/api/auth/state');
}

export async function pairWithCode(code: string): Promise<PairingResponse> {
  const response = await apiFetch<PairingResponse>('/api/auth/pair', {
    method: 'POST',
    body: JSON.stringify({ code }),
  });
  storeSessionToken(response.token);
  return response;
}

export async function logout(): Promise<void> {
  try {
    await apiFetch<void>('/api/auth/logout', { method: 'POST' });
  } finally {
    clearSessionToken();
  }
}
