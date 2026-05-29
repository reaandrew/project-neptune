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

  const loadAds = () => {
    listAds(jobId)
      .then((res) => setAds(res.ads))
      .catch((err) => {
        if (err instanceof UnauthorizedError) {
          redirectToLogin();
        }
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

  const brandName = job?.brandName || hostnameFromUrl(job?.url) || jobId.slice(0, 12);
  const accent = job?.primaryColor || '#0891b2';

  return (
    <div className="space-y-12">
      <div>
        <Link to="/brands" className="text-xs text-slate-500 hover:text-slate-200 inline-flex items-center gap-1">
          ← Brands
        </Link>

        {/* Hero: screenshot + brand colour accent + logo chip. */}
        {job?.status === 'done' && (job.screenshotUrl || job.logoUrl) && (
          <div className="mt-4 panel-flush overflow-hidden">
            <div
              className="relative aspect-[16/6] w-full bg-ink-900"
              style={job.screenshotUrl ? undefined : { backgroundColor: accent }}
            >
              {job.screenshotUrl && (
                <img
                  src={job.screenshotUrl}
                  alt=""
                  className="absolute inset-0 w-full h-full object-cover object-top opacity-70"
                />
              )}
              <div className="absolute inset-x-0 bottom-0 h-32 bg-gradient-to-t from-ink-950/95 to-transparent" />
              <div
                className="absolute left-0 right-0 bottom-0 h-[4px]"
                style={{ backgroundColor: accent }}
              />
              {job.logoUrl && (
                <div className="absolute left-5 bottom-5 h-14 px-3 py-2 rounded-md bg-white/95 shadow-lg flex items-center">
                  <img
                    src={job.logoUrl}
                    alt={brandName}
                    className="max-h-10 max-w-[200px] object-contain"
                    referrerPolicy="no-referrer"
                  />
                </div>
              )}
            </div>
          </div>
        )}

        <div className="mt-6 flex items-end justify-between gap-6 flex-wrap border-b border-white/5 pb-8">
          <div>
            <div className="label flex items-center gap-3">
              <span className="accent-rule" style={{ backgroundColor: accent }} />
              {job ? statusLabel(job.status) : 'Loading'}
            </div>
            <h1 className="mt-3 text-4xl md:text-5xl font-bold tracking-tight text-slate-100 break-words">
              {brandName}
            </h1>
            {job?.url && (
              <a
                href={job.url}
                target="_blank"
                rel="noreferrer"
                className="mt-2 inline-block text-sm text-slate-500 hover:text-brand transition break-all"
              >
                {job.url}
              </a>
            )}
          </div>
        </div>
      </div>

      {error && (
        <div className="rounded-md border border-rose-500/30 bg-rose-500/5 p-4 text-sm text-rose-300">
          {error}
        </div>
      )}

      {job?.status === 'pending' && (
        <RunningCard label="Queued. Spinning up the worker." />
      )}
      {job?.status === 'running' && (
        <RunningCard label="Crawling, screenshotting, Bedrock vision passes, PDF render — up to ~5 minutes." />
      )}

      {job?.status === 'error' && (
        <div className="panel border-rose-500/30 bg-rose-500/5 p-6">
          <div className="label text-rose-300">Generation failed</div>
          <div className="mt-2 text-sm text-rose-200">{job.error || 'Unknown error'}</div>
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
      <span className="h-2.5 w-2.5 rounded-full bg-brand animate-pulse shadow-[0_0_12px_rgba(34,211,238,0.7)]" />
      <span className="text-sm text-slate-300">{label}</span>
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
    <section className="space-y-5">
      <div className="flex items-end justify-between gap-3 flex-wrap">
        <div>
          <div className="label flex items-center gap-3">
            <span className="accent-rule" />
            Guidelines
          </div>
          <h2 className="mt-2 text-2xl font-semibold tracking-tight text-slate-100">
            Downloads.
          </h2>
        </div>
        <button
          onClick={onRegenerate}
          disabled={regenerating}
          className="text-[11px] uppercase tracking-widest2 text-slate-500 hover:text-slate-200 disabled:opacity-40"
          title="Re-runs the full pipeline (~$3)"
        >
          {regenerating ? 'Starting…' : 'Regenerate ↻'}
        </button>
      </div>
      <div className="panel p-6 space-y-4">
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
        <div className="text-xs text-slate-500 pt-2 border-t border-white/5">
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
  const [formOpen, setFormOpen] = useState(false);

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
    <section className="space-y-5">
      <div className="grid gap-8 md:grid-cols-[1.6fr,1fr] md:items-end border-t border-white/5 pt-10">
        <div>
          <div className="label flex items-center gap-3">
            <span className="accent-rule" />
            Studio
          </div>
          <h2 className="mt-3 text-3xl md:text-4xl font-bold tracking-tight text-slate-100">
            Generate an ad <span className="text-brand">brief.</span>
          </h2>
          <p className="mt-3 text-sm text-slate-400 max-w-xl">
            Every generation is built straight from{' '}
            <strong className="text-slate-200">your brand guidelines</strong> — logo,
            colour palette, tone, and a real site photo. Leave the refine drawer
            closed for fully automatic.
          </p>
        </div>
        <div className="flex md:justify-end items-center gap-3 flex-wrap">
          {ads && ads.length > 0 && (
            <button onClick={onRefresh} className="text-[11px] uppercase tracking-widest2 text-slate-500 hover:text-slate-200">
              Refresh ↻
            </button>
          )}
          <button
            onClick={() => setFormOpen((v) => !v)}
            className="btn-primary"
          >
            {formOpen ? 'Hide form' : 'Generate ad'}
          </button>
        </div>
      </div>

      {formOpen && (
        <form onSubmit={onSubmit} className="panel-elevated p-6 space-y-5">
          <RefineDrawer brief={brief} onChange={setBrief} />
          <details className="border border-white/10 rounded-md bg-ink-900/40">
            <summary className="px-4 py-3 cursor-pointer text-sm text-slate-300 list-none flex items-center justify-between">
              <span className="label">Lock the copy too (optional)</span>
              <span className="text-xs text-slate-500">Open ▾</span>
            </summary>
            <div className="px-4 pb-4 pt-1 space-y-3">
              <Field label="Headline" value={headline} onChange={setHeadline} placeholder="Leave blank to auto-generate" />
              <Field label="Supporting copy" value={body} onChange={setBody} multiline placeholder="Leave blank to auto-generate" />
              <Field label="Call to action" value={cta} onChange={setCta} placeholder="Leave blank to auto-generate" />
              <Field label="Sample-ad URL" value={sampleAdUrl} onChange={setSampleAdUrl} placeholder="https://… layout style cue" />
            </div>
          </details>
          <div className="flex items-center justify-end pt-2 border-t border-white/5">
            <button type="submit" disabled={submitting} className="btn-primary">
              {submitting ? 'Starting…' : 'Generate ad →'}
            </button>
          </div>
          {error && (
            <div className="rounded-md border border-rose-500/30 bg-rose-500/5 p-3 text-sm text-rose-300">
              {error}
            </div>
          )}
        </form>
      )}

      {ads && ads.length > 0 && (
        <div className="space-y-3">
          <div className="label">{ads.length} {ads.length === 1 ? 'ad' : 'ads'}</div>
          <ul className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {ads.map((a) => (
              <li key={a.adId}>
                <Link
                  to={`/brands/${brandJobId}/ads/${a.adId}`}
                  className="panel p-4 block hover:border-brand/30 hover:bg-ink-900/80 transition"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="label flex items-center gap-2">
                        <AdStatusDot status={a.status} />
                        {adStatusLabel(a.status)}
                      </div>
                      <div className="text-base font-semibold text-slate-100 tracking-tight mt-1.5 line-clamp-2">
                        {a.headline || '(awaiting copy)'}
                      </div>
                    </div>
                  </div>
                  <div className="mt-3 flex items-center justify-between text-[10px] text-slate-600">
                    <span className="font-mono">{a.adId.slice(0, 8)}</span>
                    <span>Open →</span>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}

      {ads && ads.length === 0 && (
        <div className="panel p-8 text-center text-sm text-slate-500">
          No ads yet. Open the form above to generate your first.
        </div>
      )}
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
    <label className="block space-y-1.5">
      <span className="label">{label}</span>
      {multiline ? (
        <textarea rows={3} value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} className="input" />
      ) : (
        <input type="text" value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} className="input" />
      )}
    </label>
  );
}

function AdStatusDot({ status }: { status: string }) {
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
