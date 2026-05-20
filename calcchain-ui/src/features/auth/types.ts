export type AuthState = {
  auth_required: boolean;
  authenticated: boolean;
};

export type PairingResponse = {
  token: string;
  token_type: 'bearer';
  expires_in_seconds: number;
};
