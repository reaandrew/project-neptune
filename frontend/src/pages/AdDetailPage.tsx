import { FormEvent, useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';

import {
  AdJob,
  createAdJob,
  getAdJob,
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
  const timerRef = useRef<number | null>(null);

  // Polling
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
        <Link to={`/brands/${jobId}`} className="text-xs text-ink-500 hover:text-ink-900">
          ← Brand
        </Link>
        <div className="mt-2">
          <div className="label">{ad ? statusLabel(ad.status) : 'Loading'}</div>
          <h1 className="font-display text-5xl md:text-6xl tracking-tightest text-ink-900 mt-2 break-words">
            {ad?.headline || 'Ad'}
          </h1>
          <div className="mt-1 text-xs font-mono text-ink-500 break-all">
            {adId}
          </div>
        </div>
      </div>

      {error && (
        <div className="rounded-xl border border-red-300/60 bg-red-50 p-4 text-sm text-red-700">
          {error}
        </div>
      )}

      {ad?.status === 'pending' && (
        <RunningCard label="Queued. Spinning up the worker." />
      )}
      {ad?.status === 'running' && (
        <RunningCard label="GPT-5 drafting prompt → gpt-image-1 rendering. ~30-90s." />
      )}

      {ad?.status === 'error' && (
        <div className="panel p-6 border-red-300/60 bg-red-50">
          <div className="label text-red-700">Generation failed</div>
          <div className="mt-2 text-sm text-red-700 break-words">{ad.error}</div>
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
      <span className="h-3 w-3 rounded-full bg-accent animate-pulse" />
      <span className="text-sm text-ink-700">{label}</span>
    </div>
  );
}

function ResultCard({ ad }: { ad: AdJob }) {
  return (
    <section className="grid grid-cols-1 lg:grid-cols-5 gap-6">
      <div className="lg:col-span-3 panel-flush bg-white p-4">
        {ad.imageUrl ? (
          <img
            src={ad.imageUrl}
            alt={ad.headline || 'Generated ad'}
            className="w-full rounded-xl"
          />
        ) : (
          <div className="aspect-square bg-paper-dark rounded-xl" />
        )}
      </div>
      <div className="lg:col-span-2 space-y-4">
        <div className="panel p-5 space-y-3">
          <div className="label">Copy used</div>
          {ad.headline && (
            <div>
              <div className="text-[11px] text-ink-500">Headline</div>
              <div className="font-display text-2xl tracking-tightest text-ink-900 mt-1">
                {ad.headline}
              </div>
            </div>
          )}
          {ad.body && (
            <div>
              <div className="text-[11px] text-ink-500">Body</div>
              <div className="text-sm text-ink-700 mt-1">{ad.body}</div>
            </div>
          )}
          {ad.cta && (
            <div>
              <div className="text-[11px] text-ink-500">CTA</div>
              <div className="text-sm text-ink-900 font-medium mt-1">{ad.cta}</div>
            </div>
          )}
        </div>
        {(ad.resolvedPlatform || ad.resolvedObjective || ad.resolvedLayout || ad.resolvedAngle) && (
          <div className="panel p-5 space-y-2">
            <div className="label">Creative brief</div>
            <dl className="text-xs space-y-1.5 text-ink-700">
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

  // Reset form when navigating to a new ad.
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
    <section className="space-y-4">
      <div>
        <div className="label">Revise</div>
        <h2 className="font-display text-3xl tracking-tightest text-ink-900 mt-1">
          Tweak and regenerate.
        </h2>
        <p className="text-sm text-ink-500 mt-1 max-w-xl">
          Edit the copy and submit — produces a new ad off the same brand. The
          original stays put in the ad list.
        </p>
      </div>
      <form onSubmit={onSubmit} className="panel p-6 space-y-4">
        <RefineDrawer brief={brief} onChange={setBrief} />
        <div className="space-y-3">
          <Field label="Headline" value={headline} onChange={setHeadline} />
          <Field label="Supporting copy" value={body} onChange={setBody} multiline />
          <Field label="Call to action" value={cta} onChange={setCta} />
          <Field label="Sample-ad URL (optional)" value={sampleAdUrl} onChange={setSampleAdUrl} placeholder="https://… layout style cue" />
        </div>
        <div className="flex items-center justify-end">
          <button type="submit" disabled={submitting} className="btn-primary">
            {submitting ? 'Starting…' : 'Revise & regenerate'}
          </button>
        </div>
      </form>
      {error && (
        <div className="rounded-xl border border-red-300/60 bg-red-50 p-3 text-sm text-red-700">
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
    <label className="block space-y-2">
      <span className="label">{label}</span>
      {multiline ? (
        <textarea rows={3} value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} className="input" />
      ) : (
        <input type="text" value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} className="input" />
      )}
    </label>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex items-baseline gap-3">
      <dt className="text-ink-500 w-20 shrink-0">{k}</dt>
      <dd className="text-ink-900">{v}</dd>
    </div>
  );
}

function statusLabel(status: string): string {
  if (status === 'done') return 'Ready';
  if (status === 'running') return 'Rendering';
  if (status === 'pending') return 'Queued';
  if (status === 'error') return 'Failed';
  return status;
}
