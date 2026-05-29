import { FormEvent, useState } from 'react';
import { useNavigate } from 'react-router-dom';

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
      <div>
        <div className="label">Step one</div>
        <h1 className="font-display text-5xl md:text-6xl tracking-tightest text-ink-900 mt-2">
          Register a brand.
        </h1>
        <p className="mt-4 text-base text-ink-500 max-w-xl leading-relaxed">
          Drop in a website URL. We crawl the apex, run Bedrock vision over the
          screenshots, classify the marketing imagery, and render a complete
          A4-landscape brand-guidelines book — plus a structured YAML/JSON your
          downstream tools can read directly.
        </p>
      </div>

      <form onSubmit={onSubmit} className="panel p-6 space-y-4">
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
        <div className="flex items-center justify-between">
          <span className="text-xs text-ink-500">
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
        <div className="rounded-xl border border-red-300/60 bg-red-50 p-4 text-sm text-red-700">
          {error}
        </div>
      )}
    </div>
  );
}
