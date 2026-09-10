# Design Agent + Template Integration Plan

Date: 2026-05-05

## Goal

Upgrade the Lead Vault website builder from "AI writes a single static mockup from scraped lead data" into a repeatable website creation pipeline with:

- marketing strategy from agent skills
- design kits and section grammars
- safer template inspiration imports
- stronger design review and visual QA
- better Website Studio controls before and after generation

This plan preserves the current static HTML package generator. It does not replace the builder with React, Next.js, or a hosted design agent.

## Current Builder Hooks

Existing pieces worth keeping:

- `lead_vault_website_generator.py`
  - `build_site_generation_plan()`
  - `build_site_design_brief()`
  - `build_prompt_design_brief()`
  - `build_runtime_attribute_contract()`
  - `WebsiteGenerator.generate()`
  - `WebsiteSectionEditor`
- `inspiration_library.py`
  - category matching
  - palettes
  - layout docs
  - AI-safe payload stripping
- `inspiration/`
  - `categories.json`
  - `palettes/*.json`
  - `layouts/*.md`
  - `experience_archetypes.json`
  - `motion_primitives.json`
- `runtime/`
  - `summit-motion.css`
  - `summit-motion.js`
- `lead_vault_website_validator.py`
  - HTML structure checks
  - a11y/security checks
  - motion/runtime checks
  - optional pa11y/Lighthouse hooks
- `lead_vault_preview_qa.py`
  - Playwright screenshot pass
  - desktop/mobile metrics
  - runtime sanity checks
- `summit-web/app/routers/ai.py`
  - `POST /api/ai/generate-website-package`
  - `GET/POST /api/ai/website-package/{lead_key}/design-brief`
  - `POST /api/ai/website-package/{lead_key}/preview-qa`
  - package status and preview endpoints

## External Sources To Use

Use these as inspiration/data sources, not as runtime dependencies unless explicitly noted.

| Source | Role | License / Caution | Use |
|---|---|---|---|
| `coreyhaines31/marketingskills` | marketing skills | MIT | Strategy, copy, CRO, SEO, schema, analytics |
| `markmead/hyperui` | HTML/Tailwind section patterns | MIT | Convert selected sections into our own section grammar notes |
| `tailark/blocks` | modern marketing blocks | MIT | Convert layout ideas into static HTML prompt patterns |
| `PageAI-Pro/page-ui` | landing page components | MIT | Use as reference for conversion-focused section patterns |
| `loopple/Landings` | business landing templates | MIT | Reference local-business page structures |
| `themesberg/flowbite` | UI components | MIT/commercial mix by product area | Reference forms, nav, accordions, FAQ, cards |
| `microsoft/skills/frontend-design-review` | design review skill | MIT | Post-generation design critique workflow |
| `pbakaus/impeccable` | AI design quality rules | Apache-2.0 | DESIGN.md style checks and anti-pattern detection |
| `superdesigndev/superdesign` | design-agent architecture | AGPL/commercial mixed | Architecture reference only; do not import code |
| `opendesigner` / `open-codesign` | artifact workflow reference | verify before code use | Reference only unless license is reviewed |

## New Repository Structure

Add these files/directories under `BrowserApp/lead-vault/inspiration/`:

```text
inspiration/
  design_sources/
    sources.json
    licenses.md
    imported_patterns/
      hyperui.json
      tailark.json
      page-ui.json
      loopple.json
  design_kits/
    local-service.json
    premium-local.json
    gallery-led.json
    healthcare-trust.json
    professional-services.json
    restaurant-hospitality.json
  section_grammar/
    hero.json
    trust.json
    services.json
    proof.json
    gallery.json
    pricing.json
    location.json
    conversion.json
    footer.json
  review_rules/
    design_quality_rules.json
    ai_design_antipatterns.json
    local_business_conversion_rules.json
```

Add these Python modules under `BrowserApp/lead-vault/`:

```text
design_source_library.py
design_kit_library.py
section_grammar_library.py
marketing_skill_bridge.py
design_review_agent.py
website_generation_orchestrator.py
```

Add tests:

```text
test_design_source_library.py
test_design_kit_library.py
test_section_grammar_library.py
test_marketing_skill_bridge.py
test_design_review_agent.py
test_website_generation_orchestrator.py
```

## Python Imports To Add

Keep dependencies light. Prefer standard library and existing packages.

### `design_source_library.py`

```python
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
```

Purpose:

- load curated source metadata
- strip source URLs before prompts
- expose only license-safe summaries and pattern metadata
- prevent raw third-party HTML from being passed directly to the model

### `design_kit_library.py`

```python
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from inspiration_library import InspirationProfile
from section_grammar_library import SectionGrammarLibrary
```

Purpose:

- map lead category + experience archetype to a design kit
- define typography, density, spacing, imagery, CTA behavior, and section rhythm
- produce compact prompt-safe design-kit payload

### `section_grammar_library.py`

```python
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
```

Purpose:

- load section grammar JSON files
- select section candidates by category, conversion goal, asset availability, and risk flags
- return "allowed section moves" instead of fixed templates

### `marketing_skill_bridge.py`

```python
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
```

Purpose:

- convert lead + scrape + audit data into marketing-brief objects
- persist `marketing_brief.json`
- prepare prompt blocks inspired by `marketingskills`
- avoid direct runtime dependency on another agent system

### `design_review_agent.py`

```python
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None  # type: ignore
```

Purpose:

- static design-quality pass over generated HTML
- detect common AI page patterns
- check CTA clarity, section rhythm, text density, generic copy, image use, over-carded layouts, contrast flags, and local-business conversion gaps
- write `design_review.json`

### `website_generation_orchestrator.py`

```python
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from design_kit_library import DesignKitLibrary
from design_review_agent import review_generated_website
from inspiration_library import load_profile
from lead_vault_preview_qa import run_preview_qa
from lead_vault_website_generator import WebsiteGenerator
from lead_vault_website_validator import save_report, validate_html
from marketing_skill_bridge import build_marketing_brief
from section_grammar_library import SectionGrammarLibrary
```

Purpose:

- one optional higher-level entrypoint for the full generation loop
- keep current API working while allowing a new "enhanced generation" path

## Data Models

### `marketing_brief.json`

```json
{
  "version": 1,
  "lead_key": "",
  "business_name": "",
  "business_type": "",
  "location": "",
  "primary_audience": "",
  "primary_conversion_goal": "",
  "positioning": {
    "one_liner": "",
    "value_proposition": "",
    "differentiators": [],
    "objections": []
  },
  "page_strategy": {
    "recommended_pages": [],
    "primary_page_goal": "",
    "internal_linking_notes": []
  },
  "copy_strategy": {
    "headline_angles": [],
    "cta_labels": [],
    "proof_points": [],
    "words_to_use": [],
    "words_to_avoid": []
  },
  "seo_strategy": {
    "title_template": "",
    "meta_description_template": "",
    "local_keywords": [],
    "schema_types": []
  },
  "analytics_strategy": {
    "conversion_events": [],
    "cta_events": [],
    "form_events": []
  }
}
```

### `design_kit_payload`

```json
{
  "kit_key": "local-service",
  "label": "Local Service",
  "best_for": ["plumber", "roofer", "hvac", "electrician"],
  "visual_principles": [],
  "typography": {},
  "spacing": {},
  "imagery": {},
  "cta_rules": [],
  "section_rhythm": [],
  "avoid": [],
  "selected_section_grammar": []
}
```

### `section_grammar`

Each section grammar file should define reusable "moves," not full copied HTML.

```json
{
  "version": 1,
  "section_type": "hero",
  "moves": [
    {
      "key": "local_service_call_first",
      "best_for": ["plumber", "roofer", "hvac", "electrician"],
      "requires": ["phone"],
      "works_with_assets": ["photo", "no_photo"],
      "content_slots": ["eyebrow", "h1", "subhead", "primary_cta", "secondary_cta", "trust_line"],
      "layout_notes": [],
      "conversion_notes": [],
      "avoid": []
    }
  ]
}
```

### `design_review.json`

```json
{
  "version": 1,
  "passed": true,
  "score": 0,
  "summary": "",
  "issues": [
    {
      "severity": "warning",
      "rule": "generic_headline",
      "message": "",
      "section_id": "",
      "recommendation": ""
    }
  ],
  "suggested_regeneration_notes": []
}
```

## Added Features

### 1. Marketing Brief Generation

Add `marketing_brief.json` before HTML generation.

Inputs:

- lead fields
- scraped source data
- website audit data if present
- category profile
- marketingskills-inspired rules

Outputs:

- positioning
- page strategy
- copy strategy
- local SEO strategy
- schema suggestions
- analytics events

Builder impact:

- generation prompt gets clearer copy direction
- package contains a reusable sales/SEO artifact
- Studio can expose editable headline/CTA/SEO fields before generation

### 2. Design Kits

Add high-level design kits that sit between category and experience archetype.

Initial kits:

- `local-service`
- `premium-local`
- `gallery-led`
- `healthcare-trust`
- `professional-services`
- `restaurant-hospitality`

Builder impact:

- less same-looking output
- stronger typography/spacing/CTA rules by business type
- easier UI controls: users choose a kit instead of editing raw prompt text

### 3. Section Grammar Library

Replace "fixed recommended layout list" pressure with composable section choices.

Initial section families:

- hero
- trust
- services
- proof/reviews
- gallery
- pricing/menu
- location/service area
- conversion/contact
- footer

Builder impact:

- generator receives allowed section moves
- templates become a grammar, not a recipe
- easier to add external inspiration safely

### 4. Design Source Import Registry

Add source metadata for HyperUI, Tailark, Page UI, Loopple, Flowbite, and others.

Rules:

- never pass source URLs to the generation model unless for human review
- never import raw third-party HTML without license review
- convert useful patterns into abstract section grammar notes
- record license/source in `design_sources/licenses.md`

Builder impact:

- safer ongoing design research
- repeatable process for adding new inspiration
- no accidental code/license contamination

### 5. Post-Generation Design Review

Add `design_review_agent.py`.

Checks:

- generic headline patterns
- weak CTAs
- hidden phone/contact actions
- too many same-shaped cards
- card-inside-card layouts
- overly monochrome palettes
- missing local signal
- missing trust/proof
- text overflow risk
- weak mobile conversion path
- fake claims or invented metrics
- AI-ish filler phrases

Builder impact:

- generation can pass HTML validation but still fail design quality
- review output can feed a retry prompt
- Studio can show human-readable issues

### 6. Enhanced Generation Mode

Keep current `generate-website-package` path stable. Add an optional body flag:

```json
{
  "enhanced_design": true,
  "design_kit": "auto",
  "run_design_review": true,
  "run_preview_qa": true,
  "auto_retry_on_design_review": false
}
```

Builder impact:

- safe rollout
- can compare old vs enhanced output
- lets us turn features on one at a time

### 7. Studio Brief Editor Upgrade

Extend Website Studio to edit:

- marketing brief
- selected design kit
- section grammar preferences
- allowed/blocked sections
- motion level
- primary CTA
- SEO title/meta
- schema type
- review issues

Builder impact:

- user can steer before spending model tokens
- better regeneration control
- easier to make each business site feel custom

### 8. Review-Informed Regeneration

After validation + design review + preview QA, create:

```text
regeneration_notes.json
```

Then allow:

- regenerate whole mockup with notes
- regenerate a section using notes
- accept warnings and ship

Builder impact:

- closes the loop from critique to improved output
- makes the builder feel like an agentic workflow rather than a one-shot generator

### 9. Local Business Website Packs

Add bundled page/section presets by industry:

- emergency trades
- appointment-based healthcare
- professional services
- portfolio/project businesses
- restaurants/hospitality
- real estate/agent sites

Builder impact:

- better defaults by category
- faster generation
- simpler QA expectations per industry

### 10. Analytics + Schema Output

Generated packages should include:

- JSON-LD schema block
- `analytics_plan.json`
- recommended event names
- optional `data-analytics-event` attributes on CTAs/forms

Builder impact:

- each website package becomes launch-ready
- future integrations can wire GA4/GTM/PostHog without rewriting pages

## Prompt Pipeline

Current simplified flow:

```text
lead + scraped data + category profile + site design brief
  -> prompt
  -> mockup.html
```

Target flow:

```text
lead + scraped data
  -> marketing_brief.json
  -> category profile
  -> site_design_brief.json
  -> design_kit payload
  -> section_grammar payload
  -> runtime attribute contract
  -> HTML generation prompt
  -> mockup.html
  -> validator
  -> preview QA
  -> design review
  -> optional regeneration notes
```

## API Changes

### Existing Endpoint Enhancement

Update:

```text
POST /api/ai/generate-website-package
```

New optional request fields:

```json
{
  "enhanced_design": false,
  "design_kit": "auto",
  "section_preferences": [],
  "blocked_sections": [],
  "run_design_review": true,
  "run_preview_qa": false,
  "auto_retry_on_design_review": false
}
```

Response additions:

```json
{
  "marketing_brief_path": "marketing_brief.json",
  "design_review_path": "design_review.json",
  "design_kit": "local-service",
  "section_grammar_keys": [],
  "enhanced_design": true
}
```

### New Read Endpoints

```text
GET /api/ai/website-package/{lead_key}/marketing-brief
GET /api/ai/website-package/{lead_key}/design-review
GET /api/ai/design-kits
GET /api/ai/section-grammar
```

### New Save Endpoints

```text
POST /api/ai/website-package/{lead_key}/marketing-brief
POST /api/ai/website-package/{lead_key}/design-review/regenerate-notes
```

## UI Changes

In Website Studio:

- add "Marketing Brief" tab
- add "Design Kit" picker
- add "Sections" tab with include/avoid toggles
- add "Review" tab showing validator, preview QA, and design review together
- add "Regenerate with Review Notes" button
- show selected experience archetype and motion primitives in plain language

In Lead Detail:

- add "Generate Enhanced Website" action
- show package quality badges:
  - HTML valid
  - Mobile screenshot checked
  - Design review passed
  - SEO/schema included

## Validation Additions

Extend `lead_vault_website_validator.py` or add a companion pass for:

- one visible H1
- primary CTA above fold signal
- visible phone/email if known
- local business name/location present
- schema JSON-LD exists when requested
- `data-analytics-event` on primary CTAs
- no more than a configured number of repeated same-shaped card grids
- no nested UI cards
- no source/license comments copied from external templates

Extend `lead_vault_preview_qa.py` with:

- screenshot path included in package response
- basic text overlap checks where possible
- above-the-fold CTA check by viewport
- mobile sticky CTA presence when expected

## Dependency Plan

Avoid new required dependencies at first.

Already useful:

- `beautifulsoup4`
- `lxml`
- `openai`
- `anthropic`
- local Node validator packages

Optional future additions:

- `playwright` for preview QA screenshots
- `Pillow` for screenshot nonblank checks
- `pa11y` for WCAG checks
- `lighthouse` for performance/SEO checks

Do not add:

- React/Next.js just for templates
- shadcn CLI as a runtime dependency
- external design-agent server dependency
- SuperDesign code because of AGPL/commercial licensing concerns

## Rollout Phases

### Phase 1: Data Contracts Only

Add:

- design source registry
- design kit JSON files
- section grammar JSON files
- review rules JSON files

Tests:

- JSON loads
- required keys exist
- source URLs stripped from AI payloads
- known categories map to a design kit

### Phase 2: Marketing Brief

Add:

- `marketing_skill_bridge.py`
- `marketing_brief.json` persistence
- API read/save endpoints

Tests:

- generated brief contains positioning, copy, SEO, schema, analytics
- no scraped prompt-injection content treated as instructions
- brief can be edited and reused

### Phase 3: Design Kit + Section Grammar Prompting

Add:

- `design_kit_library.py`
- `section_grammar_library.py`
- compact payload inside `_build_user_prompt()`

Tests:

- selected kit is deterministic
- prompt payload stays under size limits
- external source URLs do not enter prompt
- old generation path still works

### Phase 4: Design Review Agent

Add:

- `design_review_agent.py`
- `design_review.json`
- package status summary

Tests:

- detects generic CTAs/headlines
- detects missing phone CTA for service businesses
- detects nested cards or excessive card grids
- passes strong sample HTML

### Phase 5: Enhanced Generation Mode

Add:

- request flags to generation endpoint
- orchestrated optional run of marketing brief, design kit, validator, preview QA, design review

Tests:

- old request body still works
- enhanced mode writes all artifacts
- failures degrade gracefully
- design review warnings do not block unless configured

### Phase 6: Studio Controls

Add UI:

- brief tab
- design kit picker
- section include/block controls
- review dashboard
- regenerate with notes

Tests:

- endpoint responses render
- edits persist
- regenerated output uses approved brief

### Phase 7: Review-Informed Regeneration

Add:

- `regeneration_notes.json`
- retry prompt block from design review and preview QA
- whole-page and section-level retry controls

Tests:

- notes are capped and safe
- retry prompt references issues without copying untrusted HTML instructions
- backup versions are created before edits

### Phase 8: Analytics + Schema Launch Pack

Add:

- schema plan in marketing brief
- JSON-LD generation requirements
- `analytics_plan.json`
- optional CTA/form event attributes

Tests:

- LocalBusiness schema validates structurally
- CTA events exist
- package includes launch notes

## Risk Controls

- Keep external templates as inspiration summaries, not direct code imports.
- Store source/license metadata next to any imported pattern summary.
- Make enhanced generation opt-in until tests prove stable.
- Keep current static HTML output.
- Cap all new prompt payloads.
- Strip raw scraped text and source URLs from design-source payloads.
- Continue writing debug prompts for failed generation.
- Do not let design review auto-retry infinitely.

## Recommended First Implementation Slice

Build the smallest useful version:

1. Add `section_grammar/hero.json`, `trust.json`, `services.json`, `conversion.json`.
2. Add `design_kits/local-service.json`, `premium-local.json`, `gallery-led.json`.
3. Add `section_grammar_library.py` and tests.
4. Add `design_kit_library.py` and tests.
5. Feed compact design kit + section grammar into the existing prompt.
6. Generate one known lead before/after and compare screenshots.

This gives immediate design variety without touching the API/UI yet.

