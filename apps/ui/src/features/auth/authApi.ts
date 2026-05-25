import { clearSessionToken, storeSessionToken } from '../../shared/api/apiClient';
import {
  getAuthState,
  logoutSession,
  pairWithCode as requestPairWithCode,
} from '../../shared/api/backendApi';
import type { AuthState, PairingResponse } from './types';

export async function loadAuthState(): Promise<AuthState> {
  return getAuthState();
}

export async function pairWithCode(code: string): Promise<PairingResponse> {
  const response = await requestPairWithCode(code);
  storeSessionToken(response.token);
  return response;
}

export async function logout(): Promise<void> {
  try {
    await logoutSession();
  } finally {
    clearSessionToken();
  }
}
