import { useState } from 'react';

import {
  ANGLES,
  DEFAULT_ELEMENT_SET,
  ELEMENTS,
  LAYOUTS,
  OBJECTIVES,
  PLATFORMS,
} from '../lib/adDimensions';

export interface CreativeBrief {
  platform: string;
  objective: string;
  layout: string;
  angle: string;
  elements: Set<string>;
}

export function makeDefaultBrief(): CreativeBrief {
  return {
    platform: '',
    objective: '',
    layout: '',
    angle: '',
    elements: new Set(DEFAULT_ELEMENT_SET),
  };
}

export function briefToPayload(brief: CreativeBrief) {
  const elementsArray = ELEMENTS
    .map(([id]) => id)
    .filter((id) => brief.elements.has(id));
  return {
    platform: brief.platform || undefined,
    objective: brief.objective || undefined,
    layout: brief.layout || undefined,
    angle: brief.angle || undefined,
    elements: elementsArray.length ? elementsArray : undefined,
  };
}

/**
 * Collapsible refinement panel. Closed by default — auto-mode is the
 * "happy path". Opening it lets the operator lock specific dimensions.
 */
export function RefineDrawer({
  brief,
  onChange,
  defaultOpen,
}: {
  brief: CreativeBrief;
  onChange: (next: CreativeBrief) => void;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(!!defaultOpen);

  const lockedCount =
    (brief.platform ? 1 : 0) +
    (brief.objective ? 1 : 0) +
    (brief.layout ? 1 : 0) +
    (brief.angle ? 1 : 0);

  return (
    <div className="border border-ink-300/40 rounded-2xl bg-paper-dark/50">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full px-5 py-3 flex items-center justify-between text-left"
      >
        <span className="label">Refine the brief (optional)</span>
        <span className="text-xs text-ink-500">
          {lockedCount > 0 ? `${lockedCount} locked` : 'Auto'} {open ? '▴' : '▾'}
        </span>
      </button>
      {open && (
        <div className="px-5 pb-5 pt-1 space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <Select
              label="01 · Platform / placement"
              value={brief.platform}
              onChange={(v) => onChange({ ...brief, platform: v })}
              options={PLATFORMS}
            />
            <Select
              label="02 · Advert objective"
              value={brief.objective}
              onChange={(v) => onChange({ ...brief, objective: v })}
              options={OBJECTIVES}
            />
            <Select
              label="03 · Layout / structure"
              value={brief.layout}
              onChange={(v) => onChange({ ...brief, layout: v })}
              options={LAYOUTS}
            />
            <Select
              label="04 · Message angle"
              value={brief.angle}
              onChange={(v) => onChange({ ...brief, angle: v })}
              options={ANGLES}
            />
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="label">05 · Content elements</span>
              <button
                type="button"
                onClick={() => onChange({ ...brief, elements: new Set(DEFAULT_ELEMENT_SET) })}
                className="text-[11px] text-ink-500 hover:text-ink-900"
              >
                Reset
              </button>
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-1.5">
              {ELEMENTS.map(([id, label]) => {
                const on = brief.elements.has(id);
                return (
                  <label
                    key={id}
                    className={`flex items-center gap-2 rounded-full px-3 py-1.5 text-xs cursor-pointer border transition ${
                      on
                        ? 'border-ink-900 bg-ink-900 text-paper'
                        : 'border-ink-300/60 bg-white hover:bg-paper-dark text-ink-700'
                    }`}
                  >
                    <input
                      type="checkbox"
                      className="sr-only"
                      checked={on}
                      onChange={() => {
                        const next = new Set(brief.elements);
                        if (next.has(id)) next.delete(id);
                        else next.add(id);
                        onChange({ ...brief, elements: next });
                      }}
                    />
                    {label}
                  </label>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function Select({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: Array<[string, string]>;
}) {
  return (
    <label className="block space-y-1.5">
      <span className="label">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-xl border border-ink-300/60 bg-white px-3 py-2 text-sm text-ink-900 focus:border-ink-900 focus:outline-none"
      >
        <option value="">Auto (random)</option>
        {options.map(([id, lbl]) => (
          <option key={id} value={id}>
            {lbl}
          </option>
        ))}
      </select>
    </label>
  );
}
