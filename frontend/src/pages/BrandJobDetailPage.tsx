import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';

import {
  AdJob,
  BrandJob,
  createAdJob,
  createBrandJob,
  getAdJob,
  getBrandJob,
  redirectToLogin,
  UnauthorizedError,
} from '../lib/api';

const POLL_MS = 5000;

export function BrandJobDetailPage() {
  const { jobId = '' } = useParams();
  const navigate = useNavigate();
  const [job, setJob] = useState<BrandJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [regenerating, setRegenerating] = useState(false);
  const timerRef = useRef<number | null>(null);

  const onRegenerate = async () => {
    if (!job?.url) return;
    setRegenerating(true);
    try {
      const { jobId: newId } = await createBrandJob(job.url, { force: true });
      navigate(`/brand/${newId}`);
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
    <div className="space-y-10">
      {/* Job header / summary — narrower, reads as an info block. */}
      <div className="space-y-6 max-w-3xl">
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
            <div className="flex items-center gap-3 text-xs text-slate-500">
              <span>Regenerating costs ~$3 — only do this if the site has changed.</span>
              <button
                onClick={onRegenerate}
                disabled={regenerating}
                className="rounded-md border border-white/10 px-3 py-1 text-xs text-slate-300 hover:bg-white/5 disabled:opacity-50"
              >
                {regenerating ? 'Starting…' : 'Regenerate'}
              </button>
            </div>
          </>
        )}

        {job?.status === 'error' && (
          <div className="rounded-md border border-rose-500/30 bg-rose-500/5 p-4 text-sm text-rose-300">
            {job.error || 'Generation failed.'}
          </div>
        )}
      </div>

      {/* Ads section breaks out to full container width so the
          refine-brief form has room to breathe. */}
      {job?.status === 'done' && <AdsSection brandJobId={jobId} />}
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

/* ───────────────────────────────────────────────────────────────
   Creative-brief option sets. Slug → human label. Slugs match the
   ads-worker handler.py lookup tables and the ads-create Go lambda
   so the three layers stay in sync.
   ─────────────────────────────────────────────────────────────── */
const PLATFORMS: Array<[string, string]> = [
  ['facebook-feed', 'Facebook feed'],
  ['instagram-feed', 'Instagram feed'],
  ['instagram-story', 'Instagram story'],
  ['linkedin-post', 'LinkedIn post'],
  ['tiktok-reel', 'TikTok / Reel cover'],
  ['google-display', 'Google display ad'],
  ['website-banner', 'Website banner'],
  ['email-header', 'Email header'],
  ['print-flyer', 'Print flyer'],
  ['multi-platform', 'Multi-platform pack'],
];
const OBJECTIVES: Array<[string, string]> = [
  ['brand-awareness', 'Brand awareness'],
  ['get-leads', 'Get leads'],
  ['promote-service', 'Promote a service'],
  ['promote-product', 'Promote a product'],
  ['promote-offer', 'Promote an offer'],
  ['drive-traffic', 'Drive website traffic'],
  ['book-appointments', 'Book appointments'],
  ['promote-event', 'Promote an event'],
  ['build-trust', 'Build trust / social proof'],
  ['recruitment', 'Recruitment'],
];
const LAYOUTS: Array<[string, string]> = [
  ['single-hero', 'Single hero image'],
  ['full-image-overlay', 'Full image with text overlay'],
  ['split-image-text', 'Split image and text'],
  ['grid-collage', 'Grid / collage'],
  ['product-card', 'Product card'],
  ['service-card', 'Service card'],
  ['offer-card', 'Offer card'],
  ['testimonial-card', 'Testimonial card'],
  ['before-after', 'Before-and-after'],
  ['carousel-sequence', 'Carousel sequence'],
];
const ANGLES: Array<[string, string]> = [
  ['benefit-led', 'Benefit-led'],
  ['problem-solution', 'Problem / solution'],
  ['trust-led', 'Trust-led'],
  ['local-expertise', 'Local expertise'],
  ['offer-led', 'Offer-led'],
  ['seasonal', 'Seasonal'],
  ['educational', 'Educational'],
  ['testimonial-led', 'Testimonial-led'],
  ['premium-quality', 'Premium quality'],
  ['urgency-limited', 'Urgency / limited time'],
];
const ELEMENTS: Array<[string, string, boolean]> = [
  ['logo', 'Logo', true],
  ['headline', 'Headline', true],
  ['subheadline', 'Subheadline', false],
  ['body', 'Body copy', false],
  ['cta', 'CTA button', true],
  ['website', 'Website', true],
  ['phone', 'Phone number', false],
  ['email', 'Email', false],
  ['social', 'Social handle', false],
  ['offer-badge', 'Offer badge', false],
  ['star-rating', 'Star rating', false],
  ['testimonial', 'Testimonial', false],
  ['price', 'Price', false],
  ['qr-code', 'QR code', false],
  ['location', 'Location', false],
  ['legal', 'Legal disclaimer', false],
];
const DEFAULT_ELEMENT_SET = new Set(
  ELEMENTS.filter(([, , d]) => d).map(([id]) => id),
);

function AdsSection({ brandJobId }: { brandJobId: string }) {
  // Refine drawer state — closed by default. Per the user's UX call:
  // "every generation should be based on the content from their brand
  // guidelines and core services" — refinement is opt-in.
  const [refineOpen, setRefineOpen] = useState(false);

  // Creative brief — empty string = "auto" (worker picks at random).
  const [platform, setPlatform] = useState('');
  const [objective, setObjective] = useState('');
  const [layout, setLayout] = useState('');
  const [angle, setAngle] = useState('');
  const [elementsSet, setElementsSet] = useState<Set<string>>(
    () => new Set(DEFAULT_ELEMENT_SET),
  );

  // Existing copy/style overrides — kept inside the refine drawer.
  const [headline, setHeadline] = useState('');
  const [body, setBody] = useState('');
  const [cta, setCta] = useState('');
  const [sampleAdUrl, setSampleAdUrl] = useState('');

  // Generation state
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

  const onGenerate = async () => {
    setError(null);
    setSubmitting(true);
    setAd(null);
    setAdId(null);
    try {
      const elements = ELEMENTS
        .map(([id]) => id)
        .filter((id) => elementsSet.has(id));
      const { adId: newId } = await createAdJob({
        brandJobId,
        headline: headline.trim() || undefined,
        body: body.trim() || undefined,
        cta: cta.trim() || undefined,
        sampleAdUrl: sampleAdUrl.trim() || undefined,
        platform: platform || undefined,
        objective: objective || undefined,
        layout: layout || undefined,
        angle: angle || undefined,
        elements: elements.length ? elements : undefined,
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

  const generating = submitting || ad?.status === 'pending' || ad?.status === 'running';
  const toggleElement = (id: string) => {
    setElementsSet((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <section className="space-y-8">
      {/* Hero — primary action + tagline. Full container width. */}
      <div className="grid gap-8 md:grid-cols-[1.6fr,1fr] md:items-end border-t border-white/5 pt-10">
        <div>
          <p className="text-[11px] uppercase tracking-[0.18em] text-slate-500 mb-3">
            Brand-compliant advert generation
          </p>
          <h2 className="text-3xl md:text-4xl font-semibold tracking-tight">
            Generate an ad <span className="text-brand">brief.</span>
          </h2>
          <div className="mt-3 h-[3px] w-12 bg-brand" aria-hidden />
          <p className="mt-4 text-sm text-slate-400 max-w-xl">
            Built straight from <strong className="text-slate-200">your brand
            guidelines and core services</strong>. Every generation is
            different, always on-brand — GPT-5 reads your guidelines PDF,
            gpt-image-1 renders the final advert with your real logo.
            Press Generate and a fresh advert is ready in about a minute.
          </p>
        </div>
        <div className="flex flex-col gap-3 md:items-end">
          <button
            type="button"
            onClick={onGenerate}
            disabled={generating}
            className="w-full md:w-auto rounded-md bg-brand px-8 py-4 text-base font-semibold text-white hover:bg-brand-dim disabled:opacity-50 transition"
          >
            {generating ? 'Generating…' : 'Generate ad'}
          </button>
          <button
            type="button"
            onClick={() => setRefineOpen((v) => !v)}
            className="text-xs text-slate-500 hover:text-slate-200 inline-flex items-center gap-1.5 self-start md:self-end"
            aria-expanded={refineOpen}
          >
            <span
              className={`inline-block transition-transform ${refineOpen ? 'rotate-90' : ''}`}
              aria-hidden
            >
              ›
            </span>
            <span>{refineOpen ? 'Hide refinement' : 'Refine the brief (optional)'}</span>
          </button>
        </div>
      </div>

      {/* Refine drawer */}
      {refineOpen && (
        <div className="rounded-xl border border-white/10 bg-ink-800/40 p-6 space-y-6">
          <div>
            <h3 className="text-[11px] uppercase tracking-[0.16em] text-slate-500 flex items-center gap-3 mb-2">
              <span className="block h-[2px] w-5 bg-brand" />
              Refine the brief
            </h3>
            <p className="text-sm text-slate-400 max-w-3xl">
              Leave anything on <strong className="text-slate-200">Auto
              (random)</strong> and the generator picks a sensible value
              for that dimension. Lock a dimension when you want a
              specific kind of ad — e.g. a LinkedIn lead-gen post with an
              offer angle.
            </p>
          </div>

          <div className="grid gap-5 md:grid-cols-2">
            <SelectField
              numeral="01"
              label="Where is this advert going?"
              hint="size, layout rules, safe zones"
              value={platform}
              onChange={setPlatform}
              options={PLATFORMS}
            />
            <SelectField
              numeral="02"
              label="What is the goal of the advert?"
              hint="controls the structure"
              value={objective}
              onChange={setObjective}
              options={OBJECTIVES}
            />
            <SelectField
              numeral="03"
              label="What layout should it use?"
              hint="visible variety, still on-brand"
              value={layout}
              onChange={setLayout}
              options={LAYOUTS}
            />
            <SelectField
              numeral="04"
              label="What message angle should it take?"
              hint="copy direction and emotional hook"
              value={angle}
              onChange={setAngle}
              options={ANGLES}
            />
          </div>

          {/* Content elements */}
          <div className="space-y-2">
            <div className="text-[11px] uppercase tracking-[0.14em] text-slate-500 flex items-center gap-3">
              <span className="text-brand text-base">05</span>
              What details should be shown?
              <span className="italic text-slate-500 text-xs ml-auto normal-case tracking-normal">
                leave defaults for a sensible mix
              </span>
            </div>
            <div className="grid gap-2 grid-cols-[repeat(auto-fill,minmax(180px,1fr))]">
              {ELEMENTS.map(([id, label]) => {
                const checked = elementsSet.has(id);
                return (
                  <label
                    key={id}
                    className={`flex items-center gap-2.5 px-3 py-2.5 rounded-md border text-sm cursor-pointer transition ${
                      checked
                        ? 'border-brand/60 bg-brand/10 text-slate-100'
                        : 'border-white/10 bg-ink-800/60 text-slate-300 hover:border-white/30'
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggleElement(id)}
                      className="sr-only"
                    />
                    <span
                      aria-hidden
                      className={`block w-4 h-4 rounded-sm flex-shrink-0 grid place-items-center text-[10px] ${
                        checked
                          ? 'bg-brand text-ink-900'
                          : 'border border-white/20 bg-ink-900/60'
                      }`}
                    >
                      {checked ? '✓' : ''}
                    </span>
                    <span>{label}</span>
                  </label>
                );
              })}
            </div>
          </div>

          {/* Copy/style overrides — secondary, dashed-rule below the
              dimensions so they read as 'additionally, if you want
              specifics…' rather than required fields. */}
          <div className="space-y-3 pt-6 border-t border-dashed border-white/10">
            <p className="text-xs text-slate-500">
              Lock the copy too — leave blank to let GPT-5 write it from
              your brand mission, services, and tone.
            </p>
            <div className="grid gap-3 md:grid-cols-2">
              <Field
                label="Headline"
                placeholder="Leave blank to auto-generate"
                value={headline}
                onChange={setHeadline}
              />
              <Field
                label="Call to action"
                placeholder="Leave blank to auto-generate"
                value={cta}
                onChange={setCta}
              />
            </div>
            <Field
              label="Supporting copy"
              placeholder="Leave blank to auto-generate"
              value={body}
              onChange={setBody}
              multiline
            />
            <Field
              label="Sample-ad reference URL"
              placeholder="https://… (publicly accessible image)"
              value={sampleAdUrl}
              onChange={setSampleAdUrl}
              hint="GPT-5 uses this as a layout style cue."
            />
          </div>
        </div>
      )}

      {error && (
        <div className="rounded-md border border-rose-500/30 bg-rose-500/5 p-3 text-sm text-rose-300">
          {error}
        </div>
      )}

      {ad && <AdResultCard ad={ad} />}
    </section>
  );
}

function SelectField({
  numeral,
  label,
  hint,
  value,
  onChange,
  options,
}: {
  numeral: string;
  label: string;
  hint: string;
  value: string;
  onChange: (v: string) => void;
  options: Array<[string, string]>;
}) {
  return (
    <label className="block space-y-2">
      <div className="text-[11px] uppercase tracking-[0.14em] text-slate-500 flex items-center gap-3">
        <span className="text-brand text-base">{numeral}</span>
        <span>{label}</span>
        <span className="italic text-slate-500 ml-auto normal-case tracking-normal">
          {hint}
        </span>
      </div>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-md border border-white/10 bg-ink-800 px-3 py-2.5 text-sm text-slate-200 focus:border-brand focus:outline-none"
      >
        <option value="" className="text-brand">Auto (random)</option>
        {options.map(([k, lbl]) => (
          <option key={k} value={k}>
            {lbl}
          </option>
        ))}
      </select>
    </label>
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
          GPT-5 drafting prompt → gpt-image-1 rendering — about 30-90 seconds.
        </div>
      )}

      {(ad.resolvedPlatform || ad.resolvedObjective || ad.resolvedLayout || ad.resolvedAngle) && (
        <div className="mt-3 text-xs text-slate-400 flex flex-wrap gap-x-3 gap-y-1">
          {ad.resolvedPlatform && (
            <span><span className="text-slate-500">Platform · </span>{ad.resolvedPlatform}</span>
          )}
          {ad.resolvedObjective && (
            <span><span className="text-slate-500">Objective · </span>{ad.resolvedObjective}</span>
          )}
          {ad.resolvedLayout && (
            <span><span className="text-slate-500">Layout · </span>{ad.resolvedLayout}</span>
          )}
          {ad.resolvedAngle && (
            <span><span className="text-slate-500">Angle · </span>{ad.resolvedAngle}</span>
          )}
        </div>
      )}

      {ad.status === 'done' && ad.imageUrl && (
        <div className="mt-4 space-y-3">
          <img
            src={ad.imageUrl}
            alt="Generated advert"
            className="w-full rounded-lg border border-white/5"
          />
          {(ad.headline || ad.body || ad.cta) && (
            <div className="space-y-2 rounded-md border border-white/5 bg-ink-900/50 p-3 text-sm">
              <div className="text-xs uppercase tracking-wide text-slate-500">
                Copy used
              </div>
              {ad.headline && (
                <div>
                  <span className="text-slate-500 text-xs">Headline · </span>
                  <span className="text-slate-200">{ad.headline}</span>
                </div>
              )}
              {ad.body && (
                <div>
                  <span className="text-slate-500 text-xs">Body · </span>
                  <span className="text-slate-300">{ad.body}</span>
                </div>
              )}
              {ad.cta && (
                <div>
                  <span className="text-slate-500 text-xs">CTA · </span>
                  <span className="text-slate-200">{ad.cta}</span>
                </div>
              )}
            </div>
          )}
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
