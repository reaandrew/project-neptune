import { FormEvent, useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import {
  AdJob,
  BrandJob,
  createAdJob,
  getAdJob,
  getBrandJob,
  redirectToLogin,
  UnauthorizedError,
} from '../lib/api';

const POLL_MS = 5000;

export function BrandJobDetailPage() {
  const { jobId = '' } = useParams();
  const [job, setJob] = useState<BrandJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timerRef = useRef<number | null>(null);

  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    const tick = () => {
      getBrandJob(jobId)
        .then((j) => {
          if (cancelled) return;
          setJob(j);
          if (j.status === 'done' || j.status === 'error') {
            if (timerRef.current !== null) {
              window.clearInterval(timerRef.current);
              timerRef.current = null;
            }
          }
        })
        .catch((err) => {
          if (cancelled) return;
          if (err instanceof UnauthorizedError) {
            redirectToLogin();
            return;
          }
          setError(String((err as Error).message ?? err));
        });
    };
    tick();
    timerRef.current = window.setInterval(tick, POLL_MS);
    return () => {
      cancelled = true;
      if (timerRef.current !== null) {
        window.clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [jobId]);

  return (
    <div className="space-y-8 max-w-3xl">
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <div>
          <Link to="/brand" className="text-xs text-slate-500 hover:text-slate-300">
            ← All brand jobs
          </Link>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">Brand Job</h1>
          <div className="mt-1 font-mono text-xs text-slate-500 break-all">{jobId}</div>
        </div>
        {job && <StatusPill status={job.status} />}
      </div>

      {error && (
        <div className="rounded-md border border-rose-500/30 bg-rose-500/5 p-4 text-sm text-rose-300">
          {error}
        </div>
      )}

      {job?.status === 'running' && (
        <div className="text-sm text-slate-400">
          Crawling, screenshotting, Bedrock vision passes, PDF render — up to ~5 min.
        </div>
      )}

      {job?.url && (
        <div className="text-sm text-slate-400 break-all">{job.url}</div>
      )}

      {job?.status === 'done' && (
        <>
          <DownloadsCard job={job} />
          <AdsSection brandJobId={jobId} />
        </>
      )}

      {job?.status === 'error' && (
        <div className="rounded-md border border-rose-500/30 bg-rose-500/5 p-4 text-sm text-rose-300">
          {job.error || 'Generation failed.'}
        </div>
      )}
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
  const bg =
    status === 'done'
      ? 'bg-emerald-500/15 text-emerald-300'
      : status === 'error'
        ? 'bg-rose-500/15 text-rose-300'
        : 'bg-white/10 text-slate-200';
  const label =
    status === 'pending'
      ? 'Queued'
      : status === 'running'
        ? 'Generating…'
        : status === 'done'
          ? 'Ready'
          : 'Failed';
  return (
    <span className={`whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-medium ${bg}`}>
      {label}
    </span>
  );
}

function DownloadsCard({ job }: { job: BrandJob }) {
  return (
    <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-5">
      <div className="text-xs uppercase tracking-wide text-emerald-200/80">
        Brand Guidelines
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        {job.pdfUrl && (
          <a
            href={job.pdfUrl}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-2 rounded-md bg-emerald-500 px-4 py-2 text-sm font-medium text-ink-900 hover:bg-emerald-400"
          >
            Download PDF
          </a>
        )}
        {job.yamlUrl && (
          <a
            href={job.yamlUrl}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-2 rounded-md border border-emerald-500/40 px-4 py-2 text-sm font-medium text-emerald-200 hover:bg-emerald-500/10"
          >
            brand.yaml
          </a>
        )}
        {job.jsonUrl && (
          <a
            href={job.jsonUrl}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-2 rounded-md border border-emerald-500/40 px-4 py-2 text-sm font-medium text-emerald-200 hover:bg-emerald-500/10"
          >
            brand.json
          </a>
        )}
      </div>
      <div className="mt-3 text-xs text-slate-500">
        Download links expire after 15 minutes — refresh this page to regenerate.
      </div>
    </div>
  );
}

function AdsSection({ brandJobId }: { brandJobId: string }) {
  const [headline, setHeadline] = useState('');
  const [body, setBody] = useState('');
  const [cta, setCta] = useState('');
  const [sampleAdUrl, setSampleAdUrl] = useState('');
  const [adId, setAdId] = useState<string | null>(null);
  const [ad, setAd] = useState<AdJob | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const adTimer = useRef<number | null>(null);

  useEffect(() => {
    if (!adId) return;
    let cancelled = false;
    const tick = () => {
      getAdJob(adId)
        .then((j) => {
          if (cancelled) return;
          setAd(j);
          if (j.status === 'done' || j.status === 'error') {
            if (adTimer.current !== null) {
              window.clearInterval(adTimer.current);
              adTimer.current = null;
            }
          }
        })
        .catch((err) => {
          if (cancelled) return;
          if (err instanceof UnauthorizedError) {
            redirectToLogin();
            return;
          }
          setError(String((err as Error).message ?? err));
        });
    };
    tick();
    adTimer.current = window.setInterval(tick, POLL_MS);
    return () => {
      cancelled = true;
      if (adTimer.current !== null) {
        window.clearInterval(adTimer.current);
        adTimer.current = null;
      }
    };
  }, [adId]);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    setAd(null);
    setAdId(null);
    try {
      const { adId: newId } = await createAdJob({
        brandJobId,
        headline: headline.trim() || undefined,
        body: body.trim() || undefined,
        cta: cta.trim() || undefined,
        sampleAdUrl: sampleAdUrl.trim() || undefined,
      });
      setAdId(newId);
    } catch (err) {
      if (err instanceof UnauthorizedError) {
        redirectToLogin();
        return;
      }
      setError(String((err as Error).message ?? err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-xl font-semibold tracking-tight">Generate Facebook ad</h2>
        <p className="mt-1 text-sm text-slate-400">
          Uses your brand guidelines as the sole brand reference. GPT-4o drafts the
          image prompt; gpt-image-1 renders the final 1024×1024 advert.
        </p>
      </div>

      <form onSubmit={onSubmit} className="space-y-3">
        <Field
          label="Headline"
          placeholder="Skip Hire Made Simple"
          value={headline}
          onChange={setHeadline}
        />
        <Field
          label="Supporting copy"
          placeholder="Fast, reliable skip hire across St Helens, Liverpool & Manchester"
          value={body}
          onChange={setBody}
          multiline
        />
        <Field
          label="Call to action"
          placeholder="Get Your Free Quote Today"
          value={cta}
          onChange={setCta}
        />
        <Field
          label="Sample-ad reference URL (optional)"
          placeholder="https://… (publicly accessible image)"
          value={sampleAdUrl}
          onChange={setSampleAdUrl}
          hint="If provided, GPT-4o looks at this image as a style cue."
        />
        <button
          type="submit"
          disabled={submitting || (ad?.status === 'running' || ad?.status === 'pending')}
          className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-white hover:bg-brand-dim disabled:opacity-50"
        >
          {submitting ? 'Starting…' : 'Generate ad'}
        </button>
      </form>

      {error && (
        <div className="rounded-md border border-rose-500/30 bg-rose-500/5 p-3 text-sm text-rose-300">
          {error}
        </div>
      )}

      {ad && <AdResultCard ad={ad} />}
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  placeholder,
  multiline,
  hint,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  multiline?: boolean;
  hint?: string;
}) {
  const cls =
    'w-full rounded-md border border-white/10 bg-ink-800 px-3 py-2 text-sm placeholder:text-slate-600 focus:border-brand focus:outline-none';
  return (
    <label className="block space-y-1">
      <span className="text-xs uppercase tracking-wide text-slate-500">{label}</span>
      {multiline ? (
        <textarea
          rows={3}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className={cls}
        />
      ) : (
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className={cls}
        />
      )}
      {hint && <span className="block text-[11px] text-slate-500">{hint}</span>}
    </label>
  );
}

function AdResultCard({ ad }: { ad: AdJob }) {
  const accent =
    ad.status === 'done'
      ? 'border-emerald-500/30 bg-emerald-500/5'
      : ad.status === 'error'
        ? 'border-rose-500/30 bg-rose-500/5'
        : 'border-white/10 bg-ink-800/60';
  return (
    <div className={`rounded-xl border p-5 ${accent}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-xs uppercase tracking-wide text-slate-500">Ad job</div>
          <div className="font-mono text-xs sm:text-sm break-all">{ad.adId}</div>
        </div>
        <StatusPill status={ad.status} />
      </div>

      {ad.status === 'running' && (
        <div className="mt-3 text-sm text-slate-400">
          GPT-4o drafting prompt → gpt-image-1 rendering — about 30-90 seconds.
        </div>
      )}

      {ad.status === 'done' && ad.imageUrl && (
        <div className="mt-4 space-y-3">
          <img
            src={ad.imageUrl}
            alt="Generated advert"
            className="w-full rounded-lg border border-white/5"
          />
          <a
            href={ad.imageUrl}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-2 rounded-md bg-emerald-500 px-4 py-2 text-sm font-medium text-ink-900 hover:bg-emerald-400"
          >
            Download PNG
          </a>
        </div>
      )}

      {ad.status === 'error' && ad.error && (
        <div className="mt-3 text-sm text-rose-300 break-words">{ad.error}</div>
      )}
    </div>
  );
}
