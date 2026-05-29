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
      <div className="flex items-end justify-between gap-6 flex-wrap">
        <div>
          <div className="label">Studio</div>
          <h1 className="font-display text-5xl md:text-6xl tracking-tightest text-ink-900 mt-2">
            Your brands.
          </h1>
        </div>
        <Link to="/brands/new" className="btn-primary">
          Register a brand
        </Link>
      </div>

      {error && (
        <div className="rounded-xl border border-red-300/60 bg-red-50 p-4 text-sm text-red-700">
          {error}
        </div>
      )}

      {jobs === null && !error && (
        <div className="text-sm text-ink-500">Loading…</div>
      )}

      {jobs?.length === 0 && (
        <div className="panel p-12 text-center space-y-4">
          <div className="font-display text-3xl text-ink-900 tracking-tightest">
            No brands yet.
          </div>
          <p className="text-sm text-ink-500 max-w-md mx-auto">
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
              <Link to={`/brands/${j.jobId}`} className="panel p-6 block hover:bg-paper-dark transition group">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="label">{statusLabel(j.status)}</div>
                    <div className="font-display text-2xl tracking-tightest text-ink-900 mt-1 break-words">
                      {hostnameFromUrl(j.url) || j.jobId.slice(0, 12)}
                    </div>
                    {j.url && (
                      <div className="mt-1 text-xs text-ink-500 truncate">{j.url}</div>
                    )}
                  </div>
                  <StatusDot status={j.status} />
                </div>
                <div className="mt-4 flex items-center justify-between">
                  <span className="text-[11px] font-mono text-ink-500">
                    {j.jobId.slice(0, 8)}
                  </span>
                  <span className="text-xs text-ink-500 group-hover:text-ink-900 transition">
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
      ? 'bg-accent'
      : status === 'error'
        ? 'bg-red-500'
        : 'bg-ink-300';
  return <span className={`h-2 w-2 rounded-full ${cls} shrink-0 mt-2`} />;
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
