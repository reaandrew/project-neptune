import { FormEvent, useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';

import {
  AdSummary,
  BrandJob,
  createAdJob,
  createBrandJob,
  getBrandJob,
  listAds,
  redirectToLogin,
  UnauthorizedError,
} from '../lib/api';
import {
  CreativeBrief,
  RefineDrawer,
  briefToPayload,
  makeDefaultBrief,
} from '../components/RefineDrawer';

const POLL_MS = 5000;

export function BrandDetailPage() {
  const { jobId = '' } = useParams();
  const navigate = useNavigate();
  const [job, setJob] = useState<BrandJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ads, setAds] = useState<AdSummary[] | null>(null);
  const [regenerating, setRegenerating] = useState(false);
  const timerRef = useRef<number | null>(null);

  // Poll brand-job until done.
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

  // Load ads for this brand.
  const loadAds = () => {
    listAds(jobId)
      .then((res) => setAds(res.ads))
      .catch((err) => {
        if (err instanceof UnauthorizedError) {
          redirectToLogin();
          return;
        }
        // Soft failure — ads section just shows nothing.
      });
  };
  useEffect(() => {
    if (job?.status === 'done') loadAds();
  }, [job?.status, jobId]);

  const onRegenerate = async () => {
    if (!job?.url) return;
    setRegenerating(true);
    try {
      const { jobId: newId } = await createBrandJob(job.url, { force: true });
      navigate(`/brands/${newId}`);
    } catch (err) {
      if (err instanceof UnauthorizedError) {
        redirectToLogin();
        return;
      }
      setError(String((err as Error).message ?? err));
    } finally {
      setRegenerating(false);
    }
  };

  const brandName = hostnameFromUrl(job?.url) || jobId.slice(0, 12);

  return (
    <div className="space-y-12">
      <div>
        <Link to="/brands" className="text-xs text-ink-500 hover:text-ink-900">
          ← Brands
        </Link>
        <div className="mt-2 flex items-end justify-between gap-6 flex-wrap">
          <div>
            <div className="label">{job ? statusLabel(job.status) : 'Loading'}</div>
            <h1 className="font-display text-5xl md:text-6xl tracking-tightest text-ink-900 mt-2 break-words">
              {brandName}
            </h1>
            {job?.url && (
              <a
                href={job.url}
                target="_blank"
                rel="noreferrer"
                className="mt-2 inline-block text-sm text-ink-500 underline hover:text-ink-900 break-all"
              >
                {job.url}
              </a>
            )}
          </div>
        </div>
      </div>

      {error && (
        <div className="rounded-xl border border-red-300/60 bg-red-50 p-4 text-sm text-red-700">
          {error}
        </div>
      )}

      {job?.status === 'pending' && (
        <RunningCard label="Queued. Spinning up the worker." />
      )}
      {job?.status === 'running' && (
        <RunningCard label="Crawling, screenshotting, Bedrock vision passes, PDF render. Up to ~5 minutes." />
      )}

      {job?.status === 'error' && (
        <div className="panel p-6 border-red-300/60 bg-red-50">
          <div className="label text-red-700">Generation failed</div>
          <div className="mt-2 text-sm text-red-700">{job.error || 'Unknown error'}</div>
        </div>
      )}

      {job?.status === 'done' && (
        <>
          <DownloadsPanel job={job} onRegenerate={onRegenerate} regenerating={regenerating} />
          <AdsSection brandJobId={jobId} ads={ads} onRefresh={loadAds} />
        </>
      )}
    </div>
  );
}

function RunningCard({ label }: { label: string }) {
  return (
    <div className="panel p-8 flex items-center gap-4">
      <span className="h-3 w-3 rounded-full bg-accent animate-pulse" />
      <span className="text-sm text-ink-700">{label}</span>
    </div>
  );
}

function DownloadsPanel({
  job,
  onRegenerate,
  regenerating,
}: {
  job: BrandJob;
  onRegenerate: () => void;
  regenerating: boolean;
}) {
  return (
    <section className="space-y-4">
      <div className="flex items-end justify-between gap-3">
        <div>
          <div className="label">Guidelines</div>
          <h2 className="font-display text-3xl tracking-tightest text-ink-900 mt-1">
            Downloads.
          </h2>
        </div>
        <button
          onClick={onRegenerate}
          disabled={regenerating}
          className="btn-ghost text-xs"
          title="Re-runs the full pipeline (~$3)"
        >
          {regenerating ? 'Starting…' : 'Regenerate'}
        </button>
      </div>
      <div className="panel p-6 space-y-3">
        <div className="flex flex-wrap gap-2">
          {job.pdfUrl && (
            <a href={job.pdfUrl} target="_blank" rel="noreferrer" className="btn-primary">
              brand_guidelines.pdf
            </a>
          )}
          {job.yamlUrl && (
            <a href={job.yamlUrl} target="_blank" rel="noreferrer" className="btn-ghost">
              brand.yaml
            </a>
          )}
          {job.jsonUrl && (
            <a href={job.jsonUrl} target="_blank" rel="noreferrer" className="btn-ghost">
              brand.json
            </a>
          )}
        </div>
        <div className="text-xs text-ink-500">
          Download links expire after 15 minutes — refresh this page to regenerate them.
        </div>
      </div>
    </section>
  );
}

function AdsSection({
  brandJobId,
  ads,
  onRefresh,
}: {
  brandJobId: string;
  ads: AdSummary[] | null;
  onRefresh: () => void;
}) {
  const navigate = useNavigate();
  const [headline, setHeadline] = useState('');
  const [body, setBody] = useState('');
  const [cta, setCta] = useState('');
  const [sampleAdUrl, setSampleAdUrl] = useState('');
  const [brief, setBrief] = useState<CreativeBrief>(() => makeDefaultBrief());
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const { adId } = await createAdJob({
        brandJobId,
        headline: headline.trim() || undefined,
        body: body.trim() || undefined,
        cta: cta.trim() || undefined,
        sampleAdUrl: sampleAdUrl.trim() || undefined,
        ...briefToPayload(brief),
      });
      navigate(`/brands/${brandJobId}/ads/${adId}`);
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
    <section className="space-y-4">
      <div className="flex items-end justify-between gap-3">
        <div>
          <div className="label">Studio</div>
          <h2 className="font-display text-3xl tracking-tightest text-ink-900 mt-1">
            Ads.
          </h2>
        </div>
        {ads && (
          <button onClick={onRefresh} className="text-xs text-ink-500 hover:text-ink-900">
            Refresh
          </button>
        )}
      </div>

      {ads && ads.length > 0 && (
        <ul className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
          {ads.map((a) => (
            <li key={a.adId}>
              <Link
                to={`/brands/${brandJobId}/ads/${a.adId}`}
                className="panel-flush p-4 bg-white block hover:bg-paper-dark transition"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="label">{adStatusLabel(a.status)}</div>
                    <div className="font-display text-lg tracking-tightest text-ink-900 mt-1 line-clamp-2">
                      {a.headline || '(awaiting copy)'}
                    </div>
                  </div>
                  <AdStatusDot status={a.status} />
                </div>
                <div className="mt-3 flex items-center justify-between text-[11px] text-ink-500">
                  <span className="font-mono">{a.adId.slice(0, 8)}</span>
                  <span>Open →</span>
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}

      <div className="panel p-6 space-y-4">
        <div>
          <div className="label">New ad</div>
          <h3 className="font-display text-2xl tracking-tightest text-ink-900 mt-1">
            Generate from this brand.
          </h3>
          <p className="text-sm text-ink-500 mt-1 max-w-xl">
            All four fields below are optional — leave them blank and GPT-5 writes
            the copy from the brand's tone, mission and services. Then gpt-image-1
            renders a 1024×1024 Facebook square using the brand's logo + a real
            site photo as reference.
          </p>
        </div>
        <form onSubmit={onSubmit} className="space-y-4">
          <RefineDrawer brief={brief} onChange={setBrief} />
          <details className="border border-ink-300/40 rounded-2xl bg-paper-dark/50">
            <summary className="px-5 py-3 cursor-pointer text-sm text-ink-700 list-none flex items-center justify-between">
              <span className="label">Lock the copy too (optional)</span>
              <span className="text-xs text-ink-500">Open ▾</span>
            </summary>
            <div className="px-5 pb-5 pt-1 space-y-3">
              <Field label="Headline" value={headline} onChange={setHeadline} placeholder="Leave blank to auto-generate" />
              <Field label="Supporting copy" value={body} onChange={setBody} multiline placeholder="Leave blank to auto-generate" />
              <Field label="Call to action" value={cta} onChange={setCta} placeholder="Leave blank to auto-generate" />
              <Field label="Sample-ad URL" value={sampleAdUrl} onChange={setSampleAdUrl} placeholder="https://… layout style cue" />
            </div>
          </details>
          <div className="flex items-center justify-end">
            <button type="submit" disabled={submitting} className="btn-primary">
              {submitting ? 'Starting…' : 'Generate ad'}
            </button>
          </div>
        </form>
        {error && (
          <div className="rounded-xl border border-red-300/60 bg-red-50 p-3 text-sm text-red-700">
            {error}
          </div>
        )}
      </div>
    </section>
  );
}

function Field({
  label,
  value,
  onChange,
  placeholder,
  multiline,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  multiline?: boolean;
}) {
  return (
    <label className="block space-y-2">
      <span className="label">{label}</span>
      {multiline ? (
        <textarea
          rows={3}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className="input"
        />
      ) : (
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className="input"
        />
      )}
    </label>
  );
}

function AdStatusDot({ status }: { status: string }) {
  const cls =
    status === 'done'
      ? 'bg-accent'
      : status === 'error'
        ? 'bg-red-500'
        : 'bg-ink-300 animate-pulse';
  return <span className={`h-2 w-2 rounded-full ${cls} shrink-0 mt-2`} />;
}

function statusLabel(status: string): string {
  if (status === 'done') return 'Ready';
  if (status === 'running') return 'Generating';
  if (status === 'pending') return 'Queued';
  if (status === 'error') return 'Failed';
  return status;
}

function adStatusLabel(status: string): string {
  if (status === 'done') return 'Ready';
  if (status === 'running') return 'Rendering';
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
