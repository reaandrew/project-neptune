import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import {
  BrandJobSummary,
  listBrandJobs,
  redirectToLogin,
  UnauthorizedError,
} from '../lib/api';

export function BrandsListPage() {
  const [jobs, setJobs] = useState<BrandJobSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

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
        setError(String((err as Error).message ?? err));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="space-y-10">
      <div className="flex items-end justify-between gap-6 flex-wrap border-b border-white/5 pb-8">
        <div>
          <div className="label flex items-center gap-3">
            <span className="accent-rule" />
            Studio
          </div>
          <h1 className="mt-3 text-4xl md:text-5xl font-bold tracking-tight text-slate-100">
            Your <span className="text-brand">brands.</span>
          </h1>
          <p className="mt-3 text-sm text-slate-400 max-w-md">
            Every brand you've onboarded — guidelines, structured data, and
            generated ads in one place.
          </p>
        </div>
        <Link to="/brands/new" className="btn-primary">
          Register a brand
        </Link>
      </div>

      {error && (
        <div className="rounded-md border border-rose-500/30 bg-rose-500/5 p-4 text-sm text-rose-300">
          {error}
        </div>
      )}

      {jobs === null && !error && (
        <div className="text-sm text-slate-500">Loading…</div>
      )}

      {jobs?.length === 0 && (
        <div className="panel p-12 text-center space-y-4">
          <div className="text-2xl text-slate-100 font-semibold tracking-tight">
            No brands yet.
          </div>
          <p className="text-sm text-slate-400 max-w-md mx-auto">
            Register your first brand and we'll build a guidelines book + structured
            data you can feed to the ad generator.
          </p>
          <Link to="/brands/new" className="btn-primary inline-flex">
            Register your first brand
          </Link>
        </div>
      )}

      {jobs && jobs.length > 0 && (
        <ul className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {jobs.map((j) => (
            <li key={j.jobId}>
              <Link
                to={`/brands/${j.jobId}`}
                className="panel p-6 block hover:border-brand/30 hover:bg-ink-900/80 transition group"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="label flex items-center gap-2">
                      <StatusDot status={j.status} />
                      {statusLabel(j.status)}
                    </div>
                    <div className="text-xl font-semibold text-slate-100 tracking-tight mt-2 break-words">
                      {hostnameFromUrl(j.url) || j.jobId.slice(0, 12)}
                    </div>
                    {j.url && (
                      <div className="mt-1 text-xs text-slate-500 truncate">{j.url}</div>
                    )}
                  </div>
                </div>
                <div className="mt-5 flex items-center justify-between">
                  <span className="text-[10px] font-mono text-slate-600">
                    {j.jobId.slice(0, 8)}
                  </span>
                  <span className="text-xs text-slate-500 group-hover:text-brand transition">
                    Open →
                  </span>
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function StatusDot({ status }: { status: string }) {
  const cls =
    status === 'done'
      ? 'bg-emerald-400'
      : status === 'error'
        ? 'bg-rose-400'
        : 'bg-slate-500 animate-pulse';
  return <span className={`h-1.5 w-1.5 rounded-full ${cls} shrink-0`} />;
}

function statusLabel(status: string): string {
  if (status === 'done') return 'Ready';
  if (status === 'running') return 'Generating';
  if (status === 'pending') return 'Queued';
  if (status === 'error') return 'Failed';
  return status;
}

function hostnameFromUrl(url?: string): string | null {
  if (!url) return null;
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return null;
  }
}
