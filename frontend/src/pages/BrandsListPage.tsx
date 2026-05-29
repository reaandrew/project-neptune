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
        <ul className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
          {jobs.map((j) => (
            <li key={j.jobId}>
              <BrandCard job={j} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function BrandCard({ job }: { job: BrandJobSummary }) {
  const accent = job.primaryColor || '#0891b2';
  const displayName =
    job.brandName ||
    hostnameFromUrl(job.url) ||
    job.jobId.slice(0, 12);

  return (
    <Link
      to={`/brands/${job.jobId}`}
      className="block panel-flush group overflow-hidden hover:border-brand/30 transition"
    >
      {/* Hero: screenshot tinted with the brand colour. */}
      <div
        className="relative aspect-[16/10] w-full overflow-hidden bg-ink-900"
        style={
          job.screenshotUrl
            ? undefined
            : {
                background: `linear-gradient(135deg, ${accent} 0%, ${accent}77 100%)`,
              }
        }
      >
        {job.screenshotUrl ? (
          <img
            src={job.screenshotUrl}
            alt=""
            className="absolute inset-0 w-full h-full object-cover object-top opacity-70 group-hover:opacity-100 group-hover:scale-[1.02] transition duration-500"
          />
        ) : (
          <div className="absolute inset-0 grid place-items-center text-white/60 text-xs uppercase tracking-widest2">
            {job.status === 'running' || job.status === 'pending'
              ? 'Generating…'
              : 'No screenshot'}
          </div>
        )}

        {/* Bottom gradient + brand colour accent rule. */}
        <div className="absolute inset-x-0 bottom-0 h-24 bg-gradient-to-t from-ink-950/95 to-transparent" />
        <div className="absolute left-0 right-0 bottom-0 h-[3px]" style={{ backgroundColor: accent }} />

        {/* Logo chip bottom-left over the gradient. */}
        {job.logoUrl && (
          <div className="absolute left-4 bottom-4 h-10 px-2.5 py-1.5 rounded-md bg-white/95 shadow-lg flex items-center">
            <img
              src={job.logoUrl}
              alt={displayName}
              className="max-h-7 max-w-[140px] object-contain"
              referrerPolicy="no-referrer"
            />
          </div>
        )}

        {/* Status pill top-right. */}
        <div className="absolute top-3 right-3 flex items-center gap-2 rounded-full bg-ink-950/80 backdrop-blur px-2.5 py-1 text-[10px] uppercase tracking-widest2 text-slate-200">
          <StatusDot status={job.status} />
          {statusLabel(job.status)}
        </div>
      </div>

      {/* Footer: name + hostname + open. */}
      <div className="p-5 bg-ink-900/60">
        <div className="text-lg font-semibold text-slate-100 tracking-tight truncate">
          {displayName}
        </div>
        {job.url && (
          <div className="mt-1 text-xs text-slate-500 truncate">{job.url}</div>
        )}
        <div className="mt-3 flex items-center justify-between text-[10px] text-slate-600">
          <span className="font-mono">{job.jobId.slice(0, 8)}</span>
          <span className="group-hover:text-brand transition">Open →</span>
        </div>
      </div>
    </Link>
  );
}

function StatusDot({ status }: { status: string }) {
  const cls =
    status === 'done'
      ? 'bg-emerald-400'
      : status === 'error'
        ? 'bg-rose-400'
        : 'bg-amber-400 animate-pulse';
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
