import { useAuth } from './useAuth';
import { PairingPage } from './PairingPage';

export function RequireAuth({ children }: { children: React.ReactNode }) {
  const { loading, authRequired, authenticated, error } = useAuth();

  if (loading) {
    return (
      <main className="min-h-screen bg-slate-950 text-slate-100 flex items-center justify-center">
        <p>Подключаюсь к CalcChain backend…</p>
      </main>
    );
  }

  if (error && !authenticated) {
    return <PairingPage />;
  }

  if (authRequired && !authenticated) {
    return <PairingPage />;
  }

  return <>{children}</>;
}
