# Brand-book roadmap — what a real agency includes

A working roadmap for sections to add to the generated brand-guidelines book
so it sits closer to what a senior brand-strategy firm would deliver.

Ranked by **impact-for-effort** with a feasibility filter: each item must be
derivable from the website crawl (no human input) and shippable through
ReportLab + Bedrock + the existing pipeline.

---

## Already shipping

- Cover (with homepage screenshot + ARA consultancy mark)
- About / brand story
- Contact details
- Mission statement
- Core services
- Key strengths
- Brand palette (primary, secondary, accent, surface, text)
- Colour gradients (tonal ramps)
- Supporting colours
- **Design DNA** — archetype, density, typographic voice, photographic treatment, layout preference, reference marks, voice-to-design rules, do-nots
- Typography
- Logos & marks (primary, light + dark companion)
- Supporting marks (trust badges, accreditations)
- **Photography** — Bedrock-classified marketing imagery, paginated
- Favicons
- Consultancy credits

---

## Tier 1 — high value, derivable, also improves ads

Implementing now.

| # | Section | Source | Also feeds ads? |
|---|---|---|---|
| 1 | **Tone of voice guide** — concrete do/don't pairs with example phrasings | Bedrock pass on extracted paragraphs + tone words | Yes — gpt-5 ad copy |
| 2 | **Voice spectrum sliders** — formal↔casual, serious↔playful, premium↔accessible, technical↔plainspoken (4 × 5-point scales) | Same Bedrock pass | Yes — guides headline register |
| 3 | **Messaging framework** — pitches at 10 / 30 / 60 / 150 words, tagline candidates, press boilerplate | Same Bedrock pass | Yes — body copy fallbacks |
| 4 | **Audience personas** — 2-4 archetypes inferred from page titles + services (parent paying tuition vs. prospective student; builder vs. homeowner) | Same Bedrock pass | Yes — persona-targeted ad variants |
| 5 | **Vocabulary** — preferred terms the site already uses (n-gram extraction) vs. industry jargon and dated phrases to avoid | Same Bedrock pass | Yes — direct copy input |
| 6 | **Photography do/don't** — side-by-side: a real site photo we'd use vs. an archetypal photo to avoid | Existing `marketing_imagery` + `design_dna.do_not` | Yes — already feeds image-prompt |
| 7 | **UI component samples** — buttons (primary/ghost/secondary), badges, cards, form fields, alerts — all in brand colours + fonts | Pure ReportLab, no AI | No (design system) |

**Cost**: single ~$0.05 Bedrock call for items 1-5; items 6-7 are free.
**Effort**: ~2 days. **Net result**: brand book reads as agency-grade.

---

## Tier 2 — valuable PDF additions, less direct ad impact

Defer until Tier 1 has shipped + been validated by customers.

| # | Section | Source |
|---|---|---|
| 8 | **Logo misuse page** — generated examples of NEVER (squished, recoloured, on busy photo, distorted) | Pillow renders of the real logo |
| 9 | **Logo clear space + minimum size** | Geometric diagrams |
| 10 | **Email signature template** — rendered example | ReportLab |
| 11 | **Social media profile pack** — pre-rendered profile (square) + cover (banner) for FB / LinkedIn / IG / X | Pillow composites |
| 12 | **Iconography style** — characteristics inferred from existing icons | Bedrock pass over icon-classified images |
| 13 | **Pattern / background library** — tints, gradients, brand-colour washes as repeatable assets | ReportLab generation |

---

## Tier 3 — powerful but expensive / human-in-the-loop

Future / paid tiers.

| # | Section | Source | Why deferred |
|---|---|---|---|
| 14 | **Competitive landscape** — top 3-5 competitors + how this brand differs | Web search + Bedrock comparison | ~$1/brand + multi-minute crawl |
| 15 | **Application mockups** — business card, letterhead, vehicle livery, tote, mug, signage | Pillow composites onto stock product templates | Magazine-quality wow factor |
| 16 | **Brand pillars / values** — 3-5 named values with descriptions | Bedrock essence pass | Borders on invention without human input |
| 17 | **Trademark / legal notes** — registered marks, ® placement, disclaimers | Human review | Liability exposure |
| 18 | **Brand audit checklist** — quarterly review template | Generic template | Not brand-specific |

---

## Implementation order (Tier 1)

1. New Bedrock function `extract_voice_and_messaging()` returning items 1-5 in one JSON.
2. Wire into `build_brand_guidelines.main()`, persist under `content.voice`.
3. Five new ReportLab page renderers:
   - `voice_page` — do/don't pairs
   - `voice_spectrum_page` — 4 slider rows
   - `messaging_page` — 10/30/60/150-word pitches + tagline candidates
   - `personas_page` — card grid (2 per row)
   - `vocabulary_page` — two-column preferred/avoid
4. `photography_dos_donts_page` from existing data.
5. `ui_components_page` — pure rendering.
6. Update ads-worker to consume `content.voice` in `_brand_summary` and add a "VOICE & PERSONA" section to the gpt-5 prompt.

---

## Pricing implication

Tier 1 adds ~$0.05 to each brand-job (one Bedrock call), unchanged per-ad cost. At £49/mo unlimited (or £10/ad), margin is unaffected.

Tier 2 adds nothing per-job (free / one-off).

Tier 3 adds ~$1-2 per brand-job and 1-3 minutes wall-clock. Right size for an "Enterprise" tier at £499/mo.
