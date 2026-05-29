import { FormEvent, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import {
  createBrandJob,
  redirectToLogin,
  UnauthorizedError,
} from '../lib/api';

export function BrandRegisterPage() {
  const navigate = useNavigate();
  const [url, setUrl] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    const target = url.trim();
    if (!target) return;
    setError(null);
    setSubmitting(true);
    try {
      const { jobId } = await createBrandJob(target);
      navigate(`/brands/${jobId}`);
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
    <div className="space-y-10 max-w-3xl">
      <Link to="/brands" className="text-xs text-slate-500 hover:text-slate-200 inline-flex items-center gap-1">
        ← Brands
      </Link>

      <div className="border-b border-white/5 pb-8">
        <div className="label flex items-center gap-3">
          <span className="accent-rule" />
          Step one
        </div>
        <h1 className="mt-3 text-4xl md:text-5xl font-bold tracking-tight text-slate-100">
          Register a <span className="text-brand">brand.</span>
        </h1>
        <p className="mt-3 text-sm text-slate-400 max-w-xl leading-relaxed">
          Drop in a website URL. We crawl the apex, run Bedrock vision over the
          screenshots, classify the marketing imagery, and render a complete
          A4-landscape brand-guidelines book plus a structured YAML/JSON your
          downstream tools can read directly.
        </p>
      </div>

      <form onSubmit={onSubmit} className="panel p-6 space-y-5">
        <label className="block space-y-2">
          <span className="label">Website URL</span>
          <input
            type="url"
            placeholder="https://example.com"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            disabled={submitting}
            className="input"
            required
          />
        </label>
        <div className="flex items-center justify-between flex-wrap gap-3 pt-2 border-t border-white/5">
          <span className="text-xs text-slate-500">
            Same URL twice returns the cached guidelines instantly — no double charge.
          </span>
          <button
            type="submit"
            disabled={!url.trim() || submitting}
            className="btn-primary"
          >
            {submitting ? 'Starting…' : 'Generate guidelines'}
          </button>
        </div>
      </form>

      {error && (
        <div className="rounded-md border border-rose-500/30 bg-rose-500/5 p-4 text-sm text-rose-300">
          {error}
        </div>
      )}
    </div>
  );
}
