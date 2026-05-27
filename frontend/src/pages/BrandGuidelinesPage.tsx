import { FormEvent, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import {
  BrandJobSummary,
  createBrandJob,
  listBrandJobs,
  redirectToLogin,
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
  const [jobs, setJobs] = useState<BrandJobSummary[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    listBrandJobs()
      .then((res) => {
        if (!cancelled) setJobs(res.jobs);
      })
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof UnauthorizedError) {
          redirectToLogin();
          return;
        }
        setListError(String((err as Error).message ?? err));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    const target = url.trim();
    if (!target) return;
    setState({ kind: 'submitting' });
    try {
      const { jobId } = await createBrandJob(target);
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
          screenshots, and render a brand-guidelines PDF (plus a structured
          YAML/JSON summary). Jobs are cached by URL — re-entering the same site
          opens the existing guidelines instead of regenerating.
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

      <div className="space-y-2">
        <div className="text-xs uppercase tracking-wide text-slate-500">
          Your brand jobs
        </div>
        {listError ? (
          <div className="rounded-md border border-rose-500/30 bg-rose-500/5 p-3 text-xs text-rose-300">
            {listError}
          </div>
        ) : jobs === null ? (
          <div className="text-sm text-slate-500">Loading…</div>
        ) : jobs.length === 0 ? (
          <div className="text-sm text-slate-500">No jobs yet.</div>
        ) : (
          <ul className="space-y-1">
            {jobs.map((j) => (
              <li key={j.jobId}>
                <Link
                  to={`/brand/${j.jobId}`}
                  className="flex items-center justify-between gap-3 rounded-md border border-white/5 bg-ink-800/40 px-3 py-2 text-sm hover:bg-ink-800/80"
                >
                  <span className="truncate text-slate-300">
                    {j.url || j.jobId}
                  </span>
                  <span className="flex items-center gap-2 shrink-0">
                    <StatusBadge status={j.status} />
                    <span className="font-mono text-[10px] text-slate-500">
                      {j.jobId.slice(0, 8)}
                    </span>
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const cls =
    status === 'done'
      ? 'bg-emerald-500/15 text-emerald-300'
      : status === 'error'
        ? 'bg-rose-500/15 text-rose-300'
        : 'bg-white/10 text-slate-300';
  return (
    <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${cls}`}>
      {status}
    </span>
  );
}
