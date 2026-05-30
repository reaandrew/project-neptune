import { FormEvent, useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';

import {
  AdJob,
  AdSummary,
  createAdJob,
  getAdJob,
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

export function AdDetailPage() {
  const { jobId = '', adId = '' } = useParams();
  const navigate = useNavigate();
  const [ad, setAd] = useState<AdJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [versions, setVersions] = useState<AdSummary[] | null>(null);
  const timerRef = useRef<number | null>(null);

  // Poll sibling ads (all ads for this brand) so the version strip
  // stays current as new revisions land.
  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    const tick = () => {
      listAds(jobId)
        .then((res) => {
          if (!cancelled) setVersions(res.ads);
        })
        .catch((err) => {
          if (cancelled) return;
          if (err instanceof UnauthorizedError) {
            redirectToLogin();
          }
        });
    };
    tick();
    const id = window.setInterval(tick, 5000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [jobId]);

  useEffect(() => {
    if (!adId) return;
    let cancelled = false;
    const tick = () => {
      getAdJob(adId)
        .then((j) => {
          if (cancelled) return;
          setAd(j);
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
  }, [adId]);

  return (
    <div className="space-y-10">
      <div>
        <Link to={`/brands/${jobId}`} className="text-xs text-slate-500 hover:text-slate-200 inline-flex items-center gap-1">
          ← Brand
        </Link>
        <div className="mt-3 border-b border-white/5 pb-8">
          <div className="label flex items-center gap-3">
            <span className="accent-rule" />
            {ad ? statusLabel(ad.status) : 'Loading'}
          </div>
          <h1 className="mt-3 text-4xl md:text-5xl font-bold tracking-tight text-slate-100 break-words">
            {ad?.headline || 'Ad'}
          </h1>
          <div className="mt-2 text-xs font-mono text-slate-600 break-all">
            {adId}
          </div>
        </div>
      </div>

      {versions && versions.length > 1 && (
        <VersionsStrip
          brandJobId={jobId}
          currentAdId={adId}
          versions={versions}
        />
      )}

      {error && (
        <div className="rounded-md border border-rose-500/30 bg-rose-500/5 p-4 text-sm text-rose-300">
          {error}
        </div>
      )}

      {ad?.status === 'pending' && (
        <RunningCard label="Queued. Spinning up the worker." />
      )}
      {ad?.status === 'running' && (
        <RunningCard label="GPT-5 drafting prompt → gpt-image-1 rendering — ~30-90s." />
      )}

      {ad?.status === 'error' && (
        <div className="panel border-rose-500/30 bg-rose-500/5 p-6">
          <div className="label text-rose-300">Generation failed</div>
          <div className="mt-2 text-sm text-rose-200 break-words">{ad.error}</div>
        </div>
      )}

      {ad?.status === 'done' && (
        <>
          <ResultCard ad={ad} />
          <ReviseSection
            brandJobId={jobId}
            currentAd={ad}
            onReviseStarted={(newAdId) => navigate(`/brands/${jobId}/ads/${newAdId}`)}
          />
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

function ResultCard({ ad }: { ad: AdJob }) {
  return (
    <section className="grid grid-cols-1 lg:grid-cols-5 gap-5">
      <div className="lg:col-span-3 panel p-3">
        {ad.imageUrl ? (
          <img
            src={ad.imageUrl}
            alt={ad.headline || 'Generated ad'}
            className="w-full rounded-lg"
          />
        ) : (
          <div className="aspect-square bg-ink-900 rounded-lg" />
        )}
      </div>
      <div className="lg:col-span-2 space-y-3">
        <div className="panel p-5 space-y-3">
          <div className="label flex items-center gap-3">
            <span className="accent-rule" />
            Copy used
          </div>
          {ad.headline && (
            <div>
              <div className="text-[11px] text-slate-500">Headline</div>
              <div className="text-xl font-semibold text-slate-100 tracking-tight mt-1">
                {ad.headline}
              </div>
            </div>
          )}
          {ad.body && (
            <div>
              <div className="text-[11px] text-slate-500">Body</div>
              <div className="text-sm text-slate-300 mt-1">{ad.body}</div>
            </div>
          )}
          {ad.cta && (
            <div>
              <div className="text-[11px] text-slate-500">CTA</div>
              <div className="text-sm text-brand font-medium mt-1">{ad.cta}</div>
            </div>
          )}
        </div>
        {(ad.resolvedPlatform || ad.resolvedObjective || ad.resolvedLayout || ad.resolvedAngle) && (
          <div className="panel p-5 space-y-3">
            <div className="label flex items-center gap-3">
              <span className="accent-rule" />
              Creative brief
            </div>
            <dl className="text-xs space-y-1.5 text-slate-300">
              {ad.resolvedPlatform && <Row k="Platform" v={ad.resolvedPlatform} />}
              {ad.resolvedObjective && <Row k="Objective" v={ad.resolvedObjective} />}
              {ad.resolvedLayout && <Row k="Layout" v={ad.resolvedLayout} />}
              {ad.resolvedAngle && <Row k="Angle" v={ad.resolvedAngle} />}
            </dl>
          </div>
        )}
        {ad.imageUrl && (
          <a href={ad.imageUrl} target="_blank" rel="noreferrer" className="btn-primary w-full">
            Download PNG
          </a>
        )}
      </div>
    </section>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex items-baseline gap-3">
      <dt className="text-slate-500 w-20 shrink-0">{k}</dt>
      <dd className="text-slate-200">{v}</dd>
    </div>
  );
}

function ReviseSection({
  brandJobId,
  currentAd,
  onReviseStarted,
}: {
  brandJobId: string;
  currentAd: AdJob;
  onReviseStarted: (adId: string) => void;
}) {
  const [headline, setHeadline] = useState(currentAd.headline ?? '');
  const [body, setBody] = useState(currentAd.body ?? '');
  const [cta, setCta] = useState(currentAd.cta ?? '');
  const [sampleAdUrl, setSampleAdUrl] = useState('');
  const [brief, setBrief] = useState<CreativeBrief>(() => makeDefaultBrief());
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setHeadline(currentAd.headline ?? '');
    setBody(currentAd.body ?? '');
    setCta(currentAd.cta ?? '');
  }, [currentAd.adId]);

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
      onReviseStarted(adId);
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
    <section className="space-y-5 border-t border-white/5 pt-10">
      <div>
        <div className="label flex items-center gap-3">
          <span className="accent-rule" />
          Revise
        </div>
        <h2 className="mt-3 text-3xl font-bold tracking-tight text-slate-100">
          Tweak and <span className="text-brand">regenerate.</span>
        </h2>
        <p className="text-sm text-slate-400 mt-2 max-w-xl">
          Edit the copy and submit — produces a new ad off the same brand. The
          original stays put in the ads list.
        </p>
      </div>
      <form onSubmit={onSubmit} className="panel-elevated p-6 space-y-5">
        <RefineDrawer brief={brief} onChange={setBrief} />
        <div className="space-y-3">
          <Field label="Headline" value={headline} onChange={setHeadline} />
          <Field label="Supporting copy" value={body} onChange={setBody} multiline />
          <Field label="Call to action" value={cta} onChange={setCta} />
          <Field label="Sample-ad URL (optional)" value={sampleAdUrl} onChange={setSampleAdUrl} placeholder="https://… layout style cue" />
        </div>
        <div className="flex items-center justify-end pt-2 border-t border-white/5">
          <button type="submit" disabled={submitting} className="btn-primary">
            {submitting ? 'Starting…' : 'Revise & regenerate →'}
          </button>
        </div>
      </form>
      {error && (
        <div className="rounded-md border border-rose-500/30 bg-rose-500/5 p-3 text-sm text-rose-300">
          {error}
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

function statusLabel(status: string): string {
  if (status === 'done') return 'Ready';
  if (status === 'running') return 'Rendering';
  if (status === 'pending') return 'Queued';
  if (status === 'error') return 'Failed';
  return status;
}

function VersionsStrip({
  brandJobId,
  currentAdId,
  versions,
}: {
  brandJobId: string;
  currentAdId: string;
  versions: AdSummary[];
}) {
  // Most recent first — matches the order returned by the API.
  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="label flex items-center gap-3">
          <span className="accent-rule" />
          Versions ({versions.length})
        </div>
        <Link
          to={`/brands/${brandJobId}`}
          className="text-[11px] uppercase tracking-widest2 text-slate-500 hover:text-slate-200"
        >
          All on brand →
        </Link>
      </div>
      <div className="flex gap-3 overflow-x-auto pb-2 -mx-1 px-1">
        {versions.map((v) => {
          const isCurrent = v.adId === currentAdId;
          return (
            <Link
              key={v.adId}
              to={`/brands/${brandJobId}/ads/${v.adId}`}
              className={`shrink-0 w-32 panel-flush overflow-hidden transition group ${
                isCurrent
                  ? 'border-brand/70 shadow-[0_0_0_2px_rgba(34,211,238,0.25)]'
                  : 'hover:border-brand/30'
              }`}
              aria-current={isCurrent ? 'page' : undefined}
            >
              <div className="relative aspect-square bg-ink-900">
                {v.imageUrl ? (
                  <img
                    src={v.imageUrl}
                    alt={v.headline ?? ''}
                    className="absolute inset-0 w-full h-full object-cover"
                    loading="lazy"
                  />
                ) : (
                  <div className="absolute inset-0 grid place-items-center text-[9px] uppercase tracking-widest2 text-slate-600">
                    {v.status === 'pending' && 'Queued…'}
                    {v.status === 'running' && 'Rendering…'}
                    {v.status === 'error' && 'Failed'}
                    {!['pending', 'running', 'error'].includes(v.status) && '—'}
                  </div>
                )}
                {isCurrent && (
                  <div className="absolute top-1.5 left-1.5 rounded-full bg-brand text-ink-950 px-2 py-0.5 text-[9px] uppercase tracking-widest2 font-semibold">
                    Now
                  </div>
                )}
              </div>
              <div className="p-2 bg-ink-900/60">
                <div className="text-[10px] line-clamp-2 text-slate-200 min-h-[2rem]">
                  {v.headline || <span className="text-slate-600">(no copy)</span>}
                </div>
                <div className="mt-1 text-[9px] font-mono text-slate-600">
                  {v.adId.slice(0, 6)}
                </div>
              </div>
            </Link>
          );
        })}
      </div>
    </section>
  );
}
