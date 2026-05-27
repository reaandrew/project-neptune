import { FormEvent, useEffect, useRef, useState } from 'react';

import {
  BrandJob,
  createBrandJob,
  getBrandJob,
  redirectToLogin,
  UnauthorizedError,
} from '../lib/api';

type FormState =
  | { kind: 'idle' }
  | { kind: 'submitting' }
  | { kind: 'tracking'; jobId: string; job: BrandJob | null }
  | { kind: 'error'; error: string };

const POLL_INTERVAL_MS = 5000;

export function BrandGuidelinesPage() {
  const [url, setUrl] = useState('');
  const [state, setState] = useState<FormState>({ kind: 'idle' });
  const timerRef = useRef<number | null>(null);

  const stopPolling = () => {
    if (timerRef.current !== null) {
      window.clearInterval(timerRef.current);
      timerRef.current = null;
    }
  };

  useEffect(() => () => stopPolling(), []);

  useEffect(() => {
    if (state.kind !== 'tracking') return;
    if (state.job?.status === 'done' || state.job?.status === 'error') {
      stopPolling();
      return;
    }
    const jobId = state.jobId;
    let cancelled = false;
    const tick = () => {
      getBrandJob(jobId)
        .then((job) => {
          if (cancelled) return;
          setState({ kind: 'tracking', jobId, job });
        })
        .catch((err) => {
          if (cancelled) return;
          if (err instanceof UnauthorizedError) {
            redirectToLogin();
            return;
          }
          setState({ kind: 'error', error: String(err.message ?? err) });
        });
    };
    tick();
    timerRef.current = window.setInterval(tick, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      stopPolling();
    };
  }, [state.kind === 'tracking' ? state.jobId : null]);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    const target = url.trim();
    if (!target) return;
    setState({ kind: 'submitting' });
    try {
      const { jobId } = await createBrandJob(target);
      setState({ kind: 'tracking', jobId, job: null });
    } catch (err) {
      if (err instanceof UnauthorizedError) {
        redirectToLogin();
        return;
      }
      setState({ kind: 'error', error: String((err as Error).message ?? err) });
    }
  };

  const reset = () => {
    stopPolling();
    setState({ kind: 'idle' });
    setUrl('');
  };

  return (
    <div className="space-y-6 max-w-2xl">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">Brand Guidelines</h1>
        <p className="mt-2 text-slate-400">
          Enter a website URL. We crawl it, run Bedrock vision passes over its
          screenshots, and render a brand-guidelines PDF.
        </p>
      </div>

      <form onSubmit={onSubmit} className="flex gap-2">
        <input
          type="url"
          placeholder="https://example.com"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          disabled={state.kind === 'submitting' || state.kind === 'tracking'}
          className="flex-1 rounded-md border border-white/10 bg-ink-800 px-3 py-2 text-sm placeholder:text-slate-600 focus:border-brand focus:outline-none disabled:opacity-50"
          required
        />
        <button
          type="submit"
          disabled={!url.trim() || state.kind === 'submitting' || state.kind === 'tracking'}
          className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-white hover:bg-brand-dim disabled:opacity-50"
        >
          {state.kind === 'submitting' ? 'Starting…' : 'Generate'}
        </button>
      </form>

      {state.kind === 'tracking' && (
        <JobCard jobId={state.jobId} job={state.job} onReset={reset} />
      )}

      {state.kind === 'error' && (
        <div className="rounded-md border border-rose-500/30 bg-rose-500/5 p-4 text-sm text-rose-300">
          <div>{state.error}</div>
          <button onClick={reset} className="mt-2 underline">
            Try again
          </button>
        </div>
      )}
    </div>
  );
}

function JobCard({
  jobId,
  job,
  onReset,
}: {
  jobId: string;
  job: BrandJob | null;
  onReset: () => void;
}) {
  const status = job?.status ?? 'pending';
  const shortLabel =
    status === 'pending'
      ? 'Queued'
      : status === 'running'
        ? 'Generating…'
        : status === 'done'
          ? 'Ready'
          : 'Failed';

  const accent =
    status === 'done'
      ? 'text-emerald-300 border-emerald-500/30 bg-emerald-500/5'
      : status === 'error'
        ? 'text-rose-300 border-rose-500/30 bg-rose-500/5'
        : 'text-slate-200 border-white/10 bg-ink-800/60';

  const pillBg =
    status === 'done'
      ? 'bg-emerald-500/15'
      : status === 'error'
        ? 'bg-rose-500/15'
        : 'bg-white/10';

  return (
    <div className={`rounded-xl border p-5 ${accent}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="text-xs uppercase tracking-wide text-slate-500">Job</div>
          <div className="font-mono text-xs sm:text-sm break-all">{jobId}</div>
        </div>
        <span
          className={`whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-medium ${pillBg}`}
        >
          {shortLabel}
        </span>
      </div>

      {status === 'running' && (
        <div className="mt-3 text-xs text-slate-400">
          Crawling, screenshotting, Bedrock vision passes, PDF render — up to ~5 min.
        </div>
      )}

      {job?.url && (
        <div className="mt-3 text-xs text-slate-400 break-all">{job.url}</div>
      )}

      {status === 'done' && job?.pdfUrl && (
        <a
          href={job.pdfUrl}
          target="_blank"
          rel="noreferrer"
          className="mt-4 inline-flex items-center gap-2 rounded-md bg-emerald-500 px-4 py-2 text-sm font-medium text-ink-900 hover:bg-emerald-400"
        >
          Download PDF
        </a>
      )}

      {status === 'error' && job?.error && (
        <div className="mt-3 text-sm">{job.error}</div>
      )}

      <div className="mt-4 flex items-center justify-between text-xs text-slate-500">
        {(status === 'pending' || status === 'running') && (
          <span className="inline-flex items-center gap-2">
            <span className="h-2 w-2 animate-pulse rounded-full bg-current" /> polling every 5s
          </span>
        )}
        <button onClick={onReset} className="underline">
          Start another
        </button>
      </div>
    </div>
  );
}
