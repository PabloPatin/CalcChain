import { AppShell } from './app/AppShell';
import { AuthProvider } from './features/auth/AuthProvider';
import { RequireAuth } from './features/auth/RequireAuth';

export default function App() {
  return (
    <AuthProvider>
      <RequireAuth>
        <AppShell />
      </RequireAuth>
    </AuthProvider>
  );
}