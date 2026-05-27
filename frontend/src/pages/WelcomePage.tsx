import { useEffect, useState } from 'react';

import { getMessage, redirectToLogin, UnauthorizedError } from '../lib/api';

type State =
  | { kind: 'loading' }
  | { kind: 'ok'; message: string }
  | { kind: 'error'; error: string };

export function WelcomePage() {
  const [state, setState] = useState<State>({ kind: 'loading' });

  useEffect(() => {
    let cancelled = false;
    getMessage()
      .then((res) => {
        if (!cancelled) setState({ kind: 'ok', message: res.message });
      })
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof UnauthorizedError) {
          redirectToLogin();
          return;
        }
        setState({ kind: 'error', error: String(err.message ?? err) });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">Welcome to project-neptune</h1>
        <p className="mt-2 text-slate-400">
          Authenticated through ara. Calls run client → BFF → API.
        </p>
      </div>

      <div className="rounded-xl border border-white/5 bg-ink-800/60 p-6">
        <div className="text-xs uppercase tracking-wide text-slate-500">Message from API</div>
        <div className="mt-2 min-h-[2rem] font-mono text-lg">
          {state.kind === 'loading' && <span className="text-slate-500">Loading…</span>}
          {state.kind === 'ok' && <span className="text-emerald-300">{state.message}</span>}
          {state.kind === 'error' && <span className="text-rose-300">{state.error}</span>}
        </div>
      </div>
    </div>
  );
}
