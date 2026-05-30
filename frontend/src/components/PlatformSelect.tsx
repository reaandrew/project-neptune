import { PLATFORMS } from '../lib/adDimensions';

/**
 * Single-input version of the creative-brief drawer — only exposes
 * platform/placement (which also drives the rendered image aspect ratio).
 * The other dimensions (objective / layout / angle / elements) are
 * intentionally hidden for now and auto-picked by the worker.
 */
export function PlatformSelect({
  value,
  onChange,
}: {
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <label className="block space-y-1.5">
      <span className="label">Platform / placement</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-md border border-white/10 bg-ink-900/70 px-3 py-2.5 text-sm text-slate-100 focus:border-brand/70 focus:outline-none focus:ring-1 focus:ring-brand/30"
      >
        <option value="">Auto (random)</option>
        {PLATFORMS.map(([id, lbl]) => (
          <option key={id} value={id}>
            {lbl}
          </option>
        ))}
      </select>
      <span className="block text-[11px] text-slate-500">
        Sets the image aspect ratio: square for feed posts, 9:16 for stories, 16:9 for banners.
      </span>
    </label>
  );
}
