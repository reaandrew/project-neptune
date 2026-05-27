import { FormEvent, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import {
  createBrandJob,
  listRecentBrandJobs,
  redirectToLogin,
  rememberBrandJob,
  UnauthorizedError,
} from '../lib/api';

type FormState =
  | { kind: 'idle' }
  | { kind: 'submitting' }
  | { kind: 'error'; error: string };

export function BrandGuidelinesPage() {
  const navigate = useNavigate();
  const [url, setUrl] = useState('');
  const [state, setState] = useState<FormState>({ kind: 'idle' });
  const [recent, setRecent] = useState(listRecentBrandJobs());

  useEffect(() => {
    setRecent(listRecentBrandJobs());
  }, []);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    const target = url.trim();
    if (!target) return;
    setState({ kind: 'submitting' });
    try {
      const { jobId } = await createBrandJob(target);
      rememberBrandJob({
        jobId,
        url: target,
        createdAt: new Date().toISOString(),
      });
      navigate(`/brand/${jobId}`);
    } catch (err) {
      if (err instanceof UnauthorizedError) {
        redirectToLogin();
        return;
      }
      setState({ kind: 'error', error: String((err as Error).message ?? err) });
    }
  };

  return (
    <div className="space-y-8 max-w-2xl">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">Brand Guidelines</h1>
        <p className="mt-2 text-slate-400">
          Enter a website URL. We crawl it, run Bedrock vision passes over its
          screenshots, and render a brand-guidelines PDF (plus a structured YAML/JSON
          summary you can feed to other tools).
        </p>
      </div>

      <form onSubmit={onSubmit} className="flex gap-2">
        <input
          type="url"
          placeholder="https://example.com"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          disabled={state.kind === 'submitting'}
          className="flex-1 rounded-md border border-white/10 bg-ink-800 px-3 py-2 text-sm placeholder:text-slate-600 focus:border-brand focus:outline-none disabled:opacity-50"
          required
        />
        <button
          type="submit"
          disabled={!url.trim() || state.kind === 'submitting'}
          className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-white hover:bg-brand-dim disabled:opacity-50"
        >
          {state.kind === 'submitting' ? 'Starting…' : 'Generate'}
        </button>
      </form>

      {state.kind === 'error' && (
        <div className="rounded-md border border-rose-500/30 bg-rose-500/5 p-4 text-sm text-rose-300">
          {state.error}
        </div>
      )}

      {recent.length > 0 && (
        <div className="space-y-2">
          <div className="text-xs uppercase tracking-wide text-slate-500">Recent</div>
          <ul className="space-y-1">
            {recent.map((r) => (
              <li key={r.jobId}>
                <Link
                  to={`/brand/${r.jobId}`}
                  className="flex items-center justify-between gap-3 rounded-md border border-white/5 bg-ink-800/40 px-3 py-2 text-sm hover:bg-ink-800/80"
                >
                  <span className="truncate text-slate-300">{r.url}</span>
                  <span className="font-mono text-[10px] text-slate-500 shrink-0">
                    {r.jobId.slice(0, 8)}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
