import { useState } from 'react';
import type { FormEvent } from 'react';
import { useAuth } from './useAuth';

export function PairingPage() {
  const { pair, error, refresh } = useAuth();
  const [code, setCode] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedCode = code.trim();

    if (!/^\d{8}$/.test(normalizedCode)) {
      setLocalError('Введите 8 цифр из консоли сервера.');
      return;
    }

    setSubmitting(true);
    setLocalError(null);
    try {
      await pair(normalizedCode);
    } catch (caught) {
      setLocalError(caught instanceof Error ? caught.message : 'Не удалось выполнить pairing.');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="min-h-screen bg-slate-950 text-slate-100 flex items-center justify-center p-6">
      <section className="w-full max-w-md rounded-2xl border border-slate-800 bg-slate-900 p-6 shadow-xl">
        <h1 className="text-2xl font-semibold">Подключение к CalcChain</h1>
        <p className="mt-3 text-sm leading-6 text-slate-300">
          Backend запущен в LAN-режиме. Введите одноразовый pairing code,
          который был напечатан в доверенной консоли сервера.
        </p>

        <form className="mt-6 space-y-4" onSubmit={handleSubmit}>
          <label className="block text-sm font-medium text-slate-200" htmlFor="pairing-code">
            Pairing code
          </label>
          <input
            id="pairing-code"
            inputMode="numeric"
            autoComplete="one-time-code"
            pattern="\d{8}"
            maxLength={8}
            value={code}
            onChange={(event) => setCode(event.target.value.replace(/\D/g, '').slice(0, 8))}
            className="w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-lg tracking-[0.35em] outline-none focus:border-sky-400"
            placeholder="00000000"
          />

          {(localError || error) && (
            <p className="rounded-xl border border-red-900 bg-red-950/50 p-3 text-sm text-red-200">
              {localError || error}
            </p>
          )}

          <button
            type="submit"
            disabled={submitting || code.length !== 8}
            className="w-full rounded-xl bg-sky-500 px-4 py-3 font-semibold text-slate-950 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {submitting ? 'Проверяю…' : 'Подключиться'}
          </button>

          <button
            type="button"
            onClick={() => void refresh()}
            className="w-full rounded-xl border border-slate-700 px-4 py-3 text-sm text-slate-200"
          >
            Проверить подключение заново
          </button>
        </form>
      </section>
    </main>
  );
}
