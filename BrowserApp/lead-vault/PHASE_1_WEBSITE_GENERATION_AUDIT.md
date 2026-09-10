# Phase 1 Website Generation Audit

Date: 2026-04-28

## Goal

Map the current website generation system before adding Site DNA, Experience DNA, motion primitives, and Studio controls.

This phase is intentionally diagnostic. It identifies what already makes sense, what creates same-looking output, and where the next phases should attach.

## Current Template Counts

- App UI Jinja templates: 9 files in `BrowserApp/summit-web/app/templates`.
- AI layout pattern docs: 25 files in `BrowserApp/lead-vault/inspiration/layouts`.
- Category inspiration profiles: 20 profiles in `BrowserApp/lead-vault/inspiration/categories.json`.
- Palette files: 20 files in `BrowserApp/lead-vault/inspiration/palettes`.
- Generated mockup files currently present: 9 `mockup.html` files under `generated`.

## Current Generation Flow

1. User clicks website generation from Lead Detail or Website Studio.
2. Frontend calls `POST /api/ai/generate-website-package`.
3. `BrowserApp/summit-web/app/routers/ai.py` resolves provider, model, API key, lead, and per-lead lock.
4. `WebsiteGenerator.generate()` in `BrowserApp/lead-vault/lead_vault_website_generator.py` loads scraped assets.
5. `inspiration_library.load_profile()` maps business type to a category profile.
6. `build_site_generation_plan()` creates a site plan from scraper blueprint and category profile.
7. `_build_user_prompt()` combines scraped facts, site plan, category profile, layout docs, and creative direction.
8. `_system_prompt()` provides global generation rules.
9. AI returns a complete single-file HTML document.
10. Generator extracts HTML, writes `mockup.html`, `site_plan.json`, `edit_manifest.json`, and `meta.json`.
11. FastAPI validates the mockup and writes `validation.json`.
12. UI loads status through `GET /api/ai/website-package/{lead_key}`.

## Inputs The Model Reads

- Lead fields: lead key, business name, city/area, business type, phone, email, score/context fields.
- Scraped site data: source URL, final URL, title, meta description, services/nav items, headings, colors, fonts, photos, phones, emails, social links, crawled pages, and main text excerpt.
- Site blueprint: observed page count, content page count, roles, recommended pages, auth/portal detection, legal pages, skipped pages, and forms.
- Category inspiration profile: palette, tone, must-include rules, avoid rules, interaction kit, and recommended layout docs.
- Deterministic creative direction: archetype, hero system, nav system, section rhythm, visual motif, CTA system, asset strategy, portal boundary, and guardrails.
- Global generation rules: accessibility, HTML-only output, section markers, content safety, no invented facts, responsive layout, and validation expectations.

## What Makes Sense

- The pipeline is properly staged: scrape first, plan, generate, validate, then edit.
- Real scraped assets are available to the model, including photos, colors, copy, and business contact details.
- Category profiles prevent every business type from starting from the same baseline.
- `site_plan.json`, `meta.json`, `validation.json`, and `edit_manifest.json` make generation inspectable.
- Provider/model routing is explicit enough to support both OpenAI and Anthropic.
- Per-lead locking prevents duplicate generation jobs for the same lead.
- Debug artifacts now exist for failed generation attempts.

## What Does Not Make Sense Yet

- Layout docs are section recipes, but category profiles use them like fixed sequences.
- The same layout blocks are reused across many categories, which pushes outputs toward sameness.
- The model still writes most interactive CSS/JS itself, so motion quality can vary and break.
- Site planning and interaction planning are not separate enough.
- Website Studio does not yet expose a pre-generation creative brief editor.
- There is no formal motion primitive registry or trusted runtime.
- Scraped services can include navigation labels or resource labels, so content can feel random without taxonomy cleanup.
- Multi-page detection currently influences the prompt, but the main output is still a single `mockup.html` preview.

## Highest-Reuse Layout Blocks

These blocks create the strongest same-looking pressure:

- `footer_standard`: used by 20 categories.
- `testimonial_block`: used by 15 categories.
- `contact_cta_band`: used by 12 categories.
- `hero_split`: used by 11 categories.
- `service_grid_3x`: used by 11 categories.
- `hero_full_bleed`: used by 9 categories.
- `trust_badge_row`: used by 8 categories.
- `team_bio_row`: used by 8 categories.

The issue is not that these blocks exist. The issue is that they are often used as a linear recipe instead of a composable grammar.

## Current Template-Like Pressure Points

- `categories.json` assigns each category a fixed `recommended_layouts` array.
- `_build_user_prompt()` passes those layout docs to the model in order.
- `_system_prompt()` has strong global style rules that can overpower business-specific variation.
- Reused CTAs, proof strips, grids, and footers create familiar silhouettes.
- The model has no first-class pre-generation brief that the user can inspect and approve.

## Recommended Architecture Direction

Move from:

`category -> layout list -> generated HTML`

to:

`lead facts -> content taxonomy -> Site DNA -> Experience DNA -> allowed primitives -> generated HTML`

Where:

- Site DNA describes business purpose, audience, offer, content hierarchy, proof, conversion goal, and exclusions.
- Experience DNA describes motion level, background system, scroll behavior, nav behavior, microinteractions, and performance boundaries.
- Motion primitives are trusted reusable behaviors that generated HTML activates through attributes.

## Proposed Ten Phases

1. Audit current generator and document schematic. Complete in this file.
2. Add `motion_primitives.json` with a small safe primitive registry.
3. Add `experience_archetypes.json` for premium editorial, conversion, gallery-led, utility, luxury calm, and tech-launch styles.
4. Generate and persist `site_design_brief.json` per lead before HTML generation.
5. Feed Site DNA and Experience DNA into the prompt while demoting layout docs to optional ingredients.
6. Add Summit Motion Runtime CSS/JS that powers `data-motion`, `data-bg`, `data-parallax`, and `data-hover` attributes.
7. Update generator output rules to use runtime attributes instead of ad hoc animation JavaScript.
8. Add Website Studio controls to inspect/edit creative brief before generation.
9. Extend validation for motion attributes, runtime limits, reduced-motion support, file size, and unsupported primitives.
10. Add preview QA and iteration loop for desktop/mobile screenshots and motion sanity checks.

## Phase 2 Entry Criteria

- Keep the existing generation path working.
- Do not remove category profiles yet.
- Add motion primitives as data only first.
- Start with a small primitive set: `reveal_up`, `gradient_mesh`, `parallax_image`, `sticky_cta`, `cursor_spotlight`.
- Include performance and mobile fallback rules in each primitive.

## Phase 2 Completion Note

Added `BrowserApp/lead-vault/inspiration/motion_primitives.json` as a data-only registry. It defines the first five trusted primitives:

- `reveal_up`
- `gradient_mesh`
- `parallax_image`
- `sticky_cta`
- `cursor_spotlight`

Each primitive includes activation attributes, allowed contexts, avoid contexts, reduced-motion behavior, accessibility notes, performance limits, and implementation notes.

The registry is not wired into live generation yet. That is intentional. Phase 2 only establishes the contract that later phases can load into Site DNA, Experience DNA, the prompt, validator, and runtime.

## Phase 3 Entry Criteria

- Keep the existing generation path working.
- Do not wire archetypes into live generation yet.
- Define a small curated set of experience-level site behaviors.
- Require archetypes to reference only known motion primitives.
- Include performance, mobile, CTA, navigation, section rhythm, and prompt guidance rules.

## Phase 3 Completion Note

Added `BrowserApp/lead-vault/inspiration/experience_archetypes.json` as a data-only registry. It defines six first-pass experience archetypes:

- `premium_editorial`
- `tech_launch`
- `local_service_conversion`
- `gallery_led`
- `luxury_calm`
- `utility_dashboard`

Each archetype describes motion level, background system, scroll behavior, navigation behavior, section rhythm, CTA behavior, recommended primitives, primitives to avoid, best-fit categories, categories to avoid, performance limits, and prompt guidance.

The registry is validated against `motion_primitives.json` and `categories.json` so future edits cannot reference unsupported primitives or nonexistent category profiles.

## Phase 4 Entry Criteria

- Keep the existing website generation prompt behavior stable.
- Build a deterministic per-lead design brief before the paid model call.
- Persist the brief even if OpenAI or Anthropic generation later fails.
- Use the Phase 2 motion primitives and Phase 3 experience archetypes as planning inputs.
- Do not require Website Studio editing controls yet.

## Phase 4 Completion Note

Added generation of `site_design_brief.json` under each generated lead package before HTML generation starts.

The brief now contains:

- Site DNA: category, business type, location, audience, primary conversion goal, content priorities, proof signals, exclusions, and asset strategy.
- Experience DNA: selected archetype, motion level, background system, scroll behavior, nav behavior, CTA behavior, allowed primitives, blocked primitives, primitive contracts, performance budget, and prompt guidance.
- Layout strategy: existing layout docs are explicitly marked as optional ingredients, not a fixed template order.
- Site plan summary: mode, generator fit, planned pages, multi-page export flag, and risk flags.
- Source summary: scraped URL details, matched category, asset counts, sample services, sample headings, and photo source.
- Creative variation: deterministic per-lead variation seed and composition choices.

`meta.json` now includes `site_design_brief_path`, `experience_archetype`, and `experience_archetype_label` so Website Studio and debug views can find the brief later.

Phase 4 still does not feed the full brief into the HTML prompt. That is reserved for Phase 5 so the live generation behavior changes in a controlled step.

## Phase 5 Entry Criteria

- Keep `site_design_brief.json` persisted before generation.
- Feed a compact prompt-safe view of Site DNA and Experience DNA into the HTML generation prompt.
- Make Site DNA and Experience DNA the primary design plan.
- Demote layout pattern docs from recipe/order to optional ingredients.
- Keep existing scraped-data prompt-injection boundaries intact.

## Phase 5 Completion Note

The website generation prompt now includes a trusted `<site_design_brief>` block with a compact version of the persisted design brief.

The prompt now prioritizes:

- Site DNA: audience, conversion goal, content priorities, proof signals, exclusions, and asset strategy.
- Experience DNA: selected archetype, motion level, background system, scroll system, nav system, CTA system, allowed primitives, blocked primitives, performance budget, and prompt guidance.
- Primitive contracts: activation attributes, max instances, mobile support, and reduced-motion requirements.
- Layout strategy: layout pattern docs are explicitly optional ingredients, not a fixed order.

The old user-prompt wording that told the model to compose the page from layout patterns "in the order listed" was removed.

This is the first phase that changes live generation behavior. It should reduce same-looking outputs because the model now sees a business-specific Site DNA/Experience DNA plan before it sees category layout pattern docs.

## Phase 6 Entry Criteria

- Keep generation working without a real paid API call during tests.
- Add trusted runtime assets for the Phase 2 primitive attributes.
- Inject runtime assets into generated packages automatically.
- Ensure the runtime works for `mockup.html` and multi-page export pages.
- Keep generated HTML editable by Summit section markers.

## Phase 6 Completion Note

Added Summit Motion Runtime assets:

- `BrowserApp/lead-vault/runtime/summit-motion.css`
- `BrowserApp/lead-vault/runtime/summit-motion.js`

The runtime powers:

- `data-motion="reveal-up"`
- `data-motion="sticky-cta"`
- `data-bg="gradient-mesh"`
- `data-bg="cursor-spotlight"`
- `data-parallax`
- `data-hover="lift"`
- `data-hover="glow"`
- `data-hover="underline"`

Generated packages now receive local `summit-motion.css` and `summit-motion.js` files automatically. `mockup.html` and multi-page export pages are injected with runtime `<link>` and `<script>` tags using `data-summit-motion-runtime` markers so injection is idempotent.

The runtime handles reduced-motion preferences, mobile parallax disablement, reveal observers, sticky CTA state, cursor spotlight variables, and scroll-throttled parallax updates.

This phase provides the runtime foundation. Phase 7 should tighten output rules further so generated HTML consistently uses runtime attributes instead of ad hoc animation code.

## Phase 7 Entry Criteria

- Keep the Summit Motion Runtime injection from Phase 6.
- Make runtime attributes the required mechanism for supported motion primitives.
- Preserve room for small inline JavaScript only for non-motion UI such as menus, tabs, filters, and accordions.
- Do not introduce paid API calls during validation.

## Phase 7 Completion Note

The generation prompt now includes a mandatory `RUNTIME ATTRIBUTE CONTRACT` section derived from the selected Site Design Brief.

The contract tells the model to use runtime attributes for supported primitives:

- `data-motion="reveal-up"`
- `data-motion="sticky-cta"`
- `data-bg="gradient-mesh"`
- `data-bg="cursor-spotlight"`
- `data-parallax`
- `data-hover="lift"`, `data-hover="glow"`, or `data-hover="underline"`

The system prompt now explicitly forbids custom reveal observers, custom parallax scroll listeners, sticky CTA scripts, cursor spotlight scripts, duplicate keyframe systems, and competing motion runtimes for supported primitives.

Inline JavaScript remains allowed for non-motion UI only, such as menus, accordions, tabs, or filters.

This phase should make generated sites more consistent and less buggy because the AI is now asked to activate trusted runtime behavior instead of building animation systems from scratch in every output.

## Phase 8 Entry Criteria

- Keep generation free of extra paid API calls during design brief review.
- Let Website Studio inspect and edit the creative brief before generation.
- Persist user-approved brief edits in `site_design_brief.json`.
- Ensure generation uses approved Studio edits and ignores stale unapproved generated briefs.
- Keep provider/model routing unchanged for website generation.

## Phase 8 Completion Note

Website Studio now includes a Design Brief panel before validation, section editing, preview, and report tools.

The panel can:

- Load the saved design brief.
- Rebuild a preview brief from the latest scrape without spending API credits.
- Edit the JSON brief directly.
- Save the brief as user-approved.

The generator now checks for an approved saved `site_design_brief.json` before building a new brief. Approved Studio briefs are reused for paid generation; old auto-generated briefs that were never approved are ignored so a fresh scrape can still produce a fresh plan.

The website package status endpoint now reports design brief summary metadata, and new design brief endpoints cover preview/save round trips.

Validation did not make a real paid API call.

## Phase 10 Entry Criteria

- Keep the Phase 9 deterministic validation intact.
- Add a preview QA loop for generated `mockup.html` without making paid API calls.
- Capture desktop and mobile screenshots when Playwright is available.
- Surface layout, blank-page, console-error, and Summit Motion Runtime sanity checks in Website Studio.
- Keep generated-file serving path-safe for screenshots.

## Phase 10 Completion Note

Added `lead_vault_preview_qa.py`, an optional Playwright-backed QA runner that writes `preview_qa/preview_qa.json` beside each generated mockup.

Preview QA checks:

- Desktop and mobile render passes.
- Screenshot existence and non-blank image detection when Pillow is available.
- Body height, visible content density, and horizontal overflow.
- Console/page errors during preview.
- Summit Motion Runtime CSS/JS presence, runtime boot state, reveal visibility, sticky CTA state, and parallax activation.

Website Studio now has a `Run Preview QA` action in the mockup preview panel. The result card shows pass/fail status, Playwright status, screenshot thumbnails, viewport metrics, and issues. Reports are persisted and included in `/api/ai/website-package/{lead_key}` status payloads.

This phase does not make a real paid API call. If Playwright or browser binaries are unavailable, preview QA records a skipped or failed local-tool report instead of spending generation credits.

## Phase 9 Entry Criteria

- Keep the Phase 8 design brief save/reuse flow intact.
- Add deterministic validation for the generated site against the saved brief.
- Surface contract failures inside Website Studio's existing validation report.
- Do not make any extra paid API calls.

## Phase 9 Completion Note

The website validator now includes a `design_contract` pass. It automatically reads `site_design_brief.json` beside `mockup.html` and checks whether the generated output follows the brief and Summit Motion Runtime rules.

The new pass flags:

- Missing `summit-motion.css` / `summit-motion.js` when runtime attributes or a design brief are present.
- Recommended motion primitives that were not activated with runtime attributes.
- Blocked primitives that appear in generated HTML.
- Primitive instance counts that exceed the brief's performance budget.
- Missing business name in page text.
- Custom motion code such as inline scroll listeners, `IntersectionObserver`, `requestAnimationFrame`, or overlapping motion keyframes.
- Obvious placeholder copy.

Website Studio's Validation Report now shows the Design Contract tool status alongside htmlhint, structure, and a11y. Findings appear in the same issues list, with `design_contract/...` source labels.

Validation did not make a real paid API call.
