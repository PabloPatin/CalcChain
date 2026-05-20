export class ApiError extends Error {
  public readonly status: number;
  public readonly responseBody?: unknown;

  constructor(message: string, status: number, responseBody?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.responseBody = responseBody;
  }
}

const API_BASE_URL = import.meta.env.VITE_CALCCHAIN_API_BASE_URL ?? '';
const SESSION_STORAGE_KEY = 'calcchain.session_token';

export function getStoredSessionToken(): string | null {
  return sessionStorage.getItem(SESSION_STORAGE_KEY);
}

export function storeSessionToken(token: string): void {
  sessionStorage.setItem(SESSION_STORAGE_KEY, token);
}

export function clearSessionToken(): void {
  sessionStorage.removeItem(SESSION_STORAGE_KEY);
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getStoredSessionToken();
  const headers = new Headers(init.headers);

  if (!headers.has('Content-Type') && init.body !== undefined) {
    headers.set('Content-Type', 'application/json');
  }

  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers,
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const payload = await response.json();
      detail = payload.detail ?? detail;
    } catch {
      // Keep status text when the response is not JSON.
    }
    throw new ApiError(detail, response.status);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}
