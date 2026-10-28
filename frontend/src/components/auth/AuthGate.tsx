import { useEffect, useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import { apiClient, setAccessToken } from '../../services/api/apiClient';

/** Keep the access key in memory only; reloading the page signs out. */
export function AuthGate({ children }: { children: ReactNode }) {
  const [authenticated, setAuthenticated] = useState(false);
  const [token, setToken] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    const signOut = () => {
      setAccessToken('');
      setAuthenticated(false);
    };
    window.addEventListener('nexus:unauthorized', signOut);
    return () => window.removeEventListener('nexus:unauthorized', signOut);
  }, []);

  async function signIn(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setError('');
    setAccessToken(token.trim());
    try {
      await apiClient.get('/api/v1/auth/me');
      setToken('');
      setAuthenticated(true);
    } catch (caught) {
      setAccessToken('');
      setError(caught instanceof Error ? caught.message : 'No se pudo iniciar sesión.');
    } finally {
      setPending(false);
    }
  }

  if (authenticated) return <>{children}</>;
  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-950 px-6 text-slate-100">
      <form onSubmit={signIn} className="w-full max-w-sm space-y-5 rounded-2xl border border-slate-700 bg-slate-900 p-8">
        <h1 className="text-2xl font-semibold">NEXUS</h1>
        <p className="text-sm text-slate-300">Introduce tu clave de acceso para abrir tu espacio personal.</p>
        <label className="block text-sm">
          Clave de acceso
          <input type="password" autoComplete="current-password" required value={token}
            onChange={(event) => setToken(event.target.value)}
            className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-950 p-3" />
        </label>
        {error && <p role="alert" className="text-sm text-red-300">{error}</p>}
        <button type="submit" disabled={pending} className="w-full rounded-lg bg-cyan-600 p-3 font-medium disabled:opacity-50">
          {pending ? 'Verificando…' : 'Entrar'}
        </button>
      </form>
    </main>
  );
}
