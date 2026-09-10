# Codex Implementation Plan: Design Agent Website Builder Upgrade

Date: 2026-05-05

## Mission

Upgrade the Lead Vault website builder with a design-agent workflow while preserving the current static HTML generator.

This is a Codex execution plan. Each phase is intentionally scoped so it can be implemented, tested, and reviewed independently.

## Guardrails

- Do not replace the existing website generator.
- Do not add React, Next.js, shadcn, or a template framework as a runtime dependency.
- Do not copy third-party template HTML into shipped output.
- Do not pass external source URLs or raw third-party code into generation prompts.
- Keep enhanced generation opt-in until all phases are stable.
- Preserve current `POST /api/ai/generate-website-package` behavior.
- Use `apply_patch` for edits.
- Avoid touching unrelated dirty worktree files.

## Current Attachment Points

Primary implementation files:

- `BrowserApp/lead-vault/lead_vault_website_generator.py`
- `BrowserApp/lead-vault/inspiration_library.py`
- `BrowserApp/lead-vault/lead_vault_website_validator.py`
- `BrowserApp/lead-vault/lead_vault_preview_qa.py`
- `BrowserApp/summit-web/app/routers/ai.py`
- `BrowserApp/summit-web/app/templates/website_studio.html`
- `BrowserApp/summit-web/app/templates/website_studio_editor.html`

Existing data folders:

- `BrowserApp/lead-vault/inspiration/layouts/`
- `BrowserApp/lead-vault/inspiration/palettes/`
- `BrowserApp/lead-vault/inspiration/categories.json`
- `BrowserApp/lead-vault/inspiration/experience_archetypes.json`
- `BrowserApp/lead-vault/inspiration/motion_primitives.json`

## Target Flow

```text
lead + scraped assets
  -> marketing_brief.json
  -> site_design_brief.json
  -> design kit
  -> section grammar
  -> generation prompt
  -> mockup.html
  -> validation.json
  -> preview_qa.json
  -> design_review.json
  -> optional regeneration_notes.json
```

## Phase 0: Baseline Safety Check

Goal: understand current behavior before edits.

Tasks:

- [ ] Run existing lead-vault website generator tests.
- [ ] Run existing website package endpoint tests.
- [ ] Note any existing failures before touching code.

Commands:

```powershell
python -m pytest BrowserApp\lead-vault\test_lead_vault_website_generator.py -q
python -m pytest BrowserApp\summit-web\test_website_package_endpoints.py -q
```

Acceptance:

- Existing failures, if any, are documented.
- No files changed.

Stop point:

- If baseline tests fail for unrelated reasons, record the failures and continue only with data-only Phase 1.

## Phase 1: Add Data Contracts Only

Goal: add design kits, section grammar, source registry, and review rules as data only. No generator behavior changes.

Files to add:

```text
BrowserApp/lead-vault/inspiration/design_sources/sources.json
BrowserApp/lead-vault/inspiration/design_sources/licenses.md
BrowserApp/lead-vault/inspiration/design_sources/imported_patterns/hyperui.json
BrowserApp/lead-vault/inspiration/design_sources/imported_patterns/tailark.json
BrowserApp/lead-vault/inspiration/design_sources/imported_patterns/page-ui.json
BrowserApp/lead-vault/inspiration/design_sources/imported_patterns/loopple.json
BrowserApp/lead-vault/inspiration/design_kits/local-service.json
BrowserApp/lead-vault/inspiration/design_kits/premium-local.json
BrowserApp/lead-vault/inspiration/design_kits/gallery-led.json
BrowserApp/lead-vault/inspiration/design_kits/healthcare-trust.json
BrowserApp/lead-vault/inspiration/design_kits/professional-services.json
BrowserApp/lead-vault/inspiration/design_kits/restaurant-hospitality.json
BrowserApp/lead-vault/inspiration/section_grammar/hero.json
BrowserApp/lead-vault/inspiration/section_grammar/trust.json
BrowserApp/lead-vault/inspiration/section_grammar/services.json
BrowserApp/lead-vault/inspiration/section_grammar/proof.json
BrowserApp/lead-vault/inspiration/section_grammar/gallery.json
BrowserApp/lead-vault/inspiration/section_grammar/pricing.json
BrowserApp/lead-vault/inspiration/section_grammar/location.json
BrowserApp/lead-vault/inspiration/section_grammar/conversion.json
BrowserApp/lead-vault/inspiration/section_grammar/footer.json
BrowserApp/lead-vault/inspiration/review_rules/design_quality_rules.json
BrowserApp/lead-vault/inspiration/review_rules/ai_design_antipatterns.json
BrowserApp/lead-vault/inspiration/review_rules/local_business_conversion_rules.json
```

Data rules:

- `sources.json` stores source name, repo/url, license, usage notes, and whether direct code import is allowed.
- `imported_patterns/*.json` stores abstract pattern summaries only.
- `design_kits/*.json` stores visual principles, typography, spacing, imagery, CTA rules, rhythm, and avoid rules.
- `section_grammar/*.json` stores section moves, content slots, requirements, and layout notes.
- `review_rules/*.json` stores static review rules and severity.

Tests to add:

```text
BrowserApp/lead-vault/test_design_data_contracts.py
```

Test expectations:

- All JSON files load.
- Every design kit has `version`, `key`, `label`, `best_for`, `visual_principles`, `section_rhythm`, `avoid`.
- Every section grammar has `version`, `section_type`, `moves`.
- Every move has `key`, `content_slots`, `layout_notes`, `conversion_notes`.
- Design source imported patterns do not include raw HTML fields.
- External source URLs are present in source metadata, not in prompt payload examples.

Commands:

```powershell
python -m pytest BrowserApp\lead-vault\test_design_data_contracts.py -q
```

Acceptance:

- Data files exist and tests pass.
- No generator behavior changes.

## Phase 2: Section Grammar Loader

Goal: load and select section grammar safely.

Files to add:

```text
BrowserApp/lead-vault/section_grammar_library.py
BrowserApp/lead-vault/test_section_grammar_library.py
```

Imports:

```python
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
```

Required API:

```python
DEFAULT_SECTION_GRAMMAR_DIR = Path(__file__).resolve().parent / "inspiration" / "section_grammar"

@dataclass
class SectionMove:
    key: str
    section_type: str
    best_for: list[str] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)
    works_with_assets: list[str] = field(default_factory=list)
    content_slots: list[str] = field(default_factory=list)
    layout_notes: list[str] = field(default_factory=list)
    conversion_notes: list[str] = field(default_factory=list)
    avoid: list[str] = field(default_factory=list)

class SectionGrammarLibrary:
    def list_section_types(self) -> list[str]: ...
    def load_section_type(self, section_type: str) -> list[SectionMove]: ...
    def select_moves(
        self,
        *,
        category: str,
        available_assets: list[str],
        conversion_goal: str,
        preferred_sections: list[str] | None = None,
        blocked_sections: list[str] | None = None,
        limit_per_type: int = 3,
    ) -> list[SectionMove]: ...
    def to_prompt_payload(self, moves: list[SectionMove]) -> list[dict[str, Any]]: ...
```

Tests:

- Loads all grammar files.
- Selects local-service moves for `plumber`, `roofer`, `hvac`, `electrician`.
- Respects `blocked_sections`.
- Respects `limit_per_type`.
- Prompt payload contains no source URLs and stays compact.

Commands:

```powershell
python -m pytest BrowserApp\lead-vault\test_section_grammar_library.py -q
```

Acceptance:

- Library works independently.
- No generator behavior changes.

## Phase 3: Design Kit Loader

Goal: map lead/category/archetype to a design kit.

Files to add:

```text
BrowserApp/lead-vault/design_kit_library.py
BrowserApp/lead-vault/test_design_kit_library.py
```

Imports:

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

Required API:

```python
DEFAULT_DESIGN_KIT_DIR = Path(__file__).resolve().parent / "inspiration" / "design_kits"

@dataclass
class DesignKit:
    key: str
    label: str
    best_for: list[str] = field(default_factory=list)
    visual_principles: list[str] = field(default_factory=list)
    typography: dict[str, Any] = field(default_factory=dict)
    spacing: dict[str, Any] = field(default_factory=dict)
    imagery: dict[str, Any] = field(default_factory=dict)
    cta_rules: list[str] = field(default_factory=list)
    section_rhythm: list[str] = field(default_factory=list)
    avoid: list[str] = field(default_factory=list)

class DesignKitLibrary:
    def list_kits(self) -> list[str]: ...
    def load(self, key: str) -> DesignKit: ...
    def select_for(
        self,
        *,
        category: str,
        business_type: str = "",
        experience_archetype: str = "",
        requested_key: str = "auto",
    ) -> DesignKit: ...
    def to_prompt_payload(self, kit: DesignKit, selected_moves: list[dict[str, Any]]) -> dict[str, Any]: ...
```

Tests:

- Selects `local-service` for trades.
- Selects `gallery-led` for landscaper/restaurant/salon-style categories.
- Honors explicit `requested_key`.
- Falls back safely to `local-service` or `premium-local`.
- Prompt payload is compact and URL-free.

Commands:

```powershell
python -m pytest BrowserApp\lead-vault\test_design_kit_library.py -q
```

Acceptance:

- Design kit selection works independently.
- No generator behavior changes.

## Phase 4: Feed Design Kit + Section Grammar Into Prompt

Goal: enhance generation prompt behind an opt-in flag.

Files to modify:

```text
BrowserApp/lead-vault/lead_vault_website_generator.py
BrowserApp/lead-vault/test_lead_vault_website_generator.py
```

Imports to add:

```python
from design_kit_library import DesignKitLibrary
from section_grammar_library import SectionGrammarLibrary
```

Implementation tasks:

- Add optional `enhanced_design: bool = False` to `WebsiteGenerator.generate()`.
- Add optional `design_kit_key: str = "auto"`.
- Add optional `section_preferences: list[str] | None = None`.
- Add optional `blocked_sections: list[str] | None = None`.
- When `enhanced_design` is false, preserve existing prompt exactly as much as practical.
- When true:
  - load selected section moves
  - select design kit
  - build compact payload
  - insert `<design_kit>` prompt block after `<site_design_brief>`
  - insert `<section_grammar>` prompt block after `<design_kit>`
- Write selected kit/moves into `meta.json`.

Prompt block shape:

```text
<design_kit>
{...compact JSON...}
</design_kit>

<section_grammar>
{...compact JSON...}
</section_grammar>
```

Tests:

- Existing generator tests still pass without `enhanced_design`.
- Enhanced prompt includes design kit and section grammar.
- Enhanced prompt does not include source URLs.
- Meta includes `enhanced_design`, `design_kit`, and `section_grammar_keys`.

Commands:

```powershell
python -m pytest BrowserApp\lead-vault\test_lead_vault_website_generator.py -q
```

Acceptance:

- Enhanced prompt path is available.
- Default behavior remains stable.

## Phase 5: Marketing Brief Builder

Goal: persist a marketing strategy artifact before generation.

Files to add:

```text
BrowserApp/lead-vault/marketing_skill_bridge.py
BrowserApp/lead-vault/test_marketing_skill_bridge.py
```

Imports:

```python
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
```

Required API:

```python
MARKETING_BRIEF_FILE = "marketing_brief.json"

@dataclass
class MarketingBrief:
    version: int
    lead_key: str
    business_name: str
    business_type: str
    location: str
    primary_audience: str
    primary_conversion_goal: str
    positioning: dict[str, Any] = field(default_factory=dict)
    page_strategy: dict[str, Any] = field(default_factory=dict)
    copy_strategy: dict[str, Any] = field(default_factory=dict)
    seo_strategy: dict[str, Any] = field(default_factory=dict)
    analytics_strategy: dict[str, Any] = field(default_factory=dict)

def build_marketing_brief(lead: dict[str, Any], scraped: dict[str, Any], site_plan: dict[str, Any]) -> MarketingBrief: ...
def write_marketing_brief(brief: MarketingBrief, output_dir: Path) -> Path: ...
def load_marketing_brief(output_dir: Path, lead_key: str = "") -> dict[str, Any] | None: ...
def build_prompt_marketing_brief(brief: MarketingBrief | dict[str, Any]) -> dict[str, Any]: ...
```

Implementation tasks:

- Use marketingskills concepts, but do not require installed skills at runtime.
- Build deterministic brief from existing lead/scrape/site plan.
- Include page strategy, copy strategy, SEO, schema suggestions, analytics events.
- Write `marketing_brief.json` before model call.
- Add optional prompt block when `enhanced_design` is true.

Tests:

- Brief contains required top-level keys.
- Local service leads get call/quote conversion goals.
- SEO strategy includes local keywords when city/area exists.
- Analytics strategy includes CTA/form events.
- Prompt payload is capped and compact.

Commands:

```powershell
python -m pytest BrowserApp\lead-vault\test_marketing_skill_bridge.py -q
```

Acceptance:

- Marketing brief can be generated independently.
- No API/UI changes yet.

## Phase 6: Design Review Agent

Goal: add post-generation design quality checks.

Files to add:

```text
BrowserApp/lead-vault/design_review_agent.py
BrowserApp/lead-vault/test_design_review_agent.py
```

Imports:

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

Required API:

```python
DESIGN_REVIEW_FILE = "design_review.json"

@dataclass
class DesignReviewIssue:
    severity: str
    rule: str
    message: str
    section_id: str = ""
    recommendation: str = ""

@dataclass
class DesignReviewReport:
    version: int
    passed: bool
    score: int
    summary: str
    issues: list[DesignReviewIssue] = field(default_factory=list)
    suggested_regeneration_notes: list[str] = field(default_factory=list)

def review_generated_website(
    html_path: Path,
    *,
    lead: dict[str, Any] | None = None,
    marketing_brief: dict[str, Any] | None = None,
    site_design_brief: dict[str, Any] | None = None,
) -> DesignReviewReport: ...
def save_design_review(report: DesignReviewReport, output_dir: Path) -> Path: ...
```

Checks:

- generic headlines
- weak CTAs
- missing visible phone for local service businesses
- missing local/location signal
- too many repeated cards
- nested cards
- too many generic icons with no proof
- missing trust/proof section
- monochrome palette warning
- likely placeholder/filler copy
- invented metrics warning patterns

Tests:

- Flags weak sample HTML.
- Passes strong local-service sample HTML.
- Flags missing phone CTA when lead has phone.
- Flags too many repeated cards.
- Saves valid `design_review.json`.

Commands:

```powershell
python -m pytest BrowserApp\lead-vault\test_design_review_agent.py -q
```

Acceptance:

- Design review works independently.
- No generation endpoint behavior changes yet.

## Phase 7: API Enhanced Generation Flags

Goal: expose enhanced design mode through the existing endpoint.

Files to modify:

```text
BrowserApp/summit-web/app/routers/ai.py
BrowserApp/summit-web/test_website_package_endpoints.py
```

Request fields:

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

Implementation tasks:

- Parse fields in `generate_website_package`.
- Pass fields to `WebsiteGenerator.generate()`.
- If `run_design_review` is true, run `design_review_agent` after validation.
- Include design-review path and summary in response.
- Do not auto-retry yet.
- Keep all new behavior optional.

Response additions:

```json
{
  "enhanced_design": true,
  "design_kit": "local-service",
  "section_grammar_keys": [],
  "marketing_brief_path": "marketing_brief.json",
  "design_review_path": "design_review.json"
}
```

Tests:

- Existing request body still passes.
- Enhanced request writes expected artifacts.
- Missing design review dependency degrades with a clean error or skipped status.
- Design review warnings do not fail endpoint by default.

Commands:

```powershell
python -m pytest BrowserApp\summit-web\test_website_package_endpoints.py -q
```

Acceptance:

- API can run enhanced mode.
- Default mode remains unchanged.

## Phase 8: Package Status + Read Endpoints

Goal: make generated artifacts visible to Studio.

Files to modify:

```text
BrowserApp/summit-web/app/routers/ai.py
BrowserApp/summit-web/test_website_package_endpoints.py
```

Endpoints to add:

```text
GET /api/ai/website-package/{lead_key}/marketing-brief
POST /api/ai/website-package/{lead_key}/marketing-brief
GET /api/ai/website-package/{lead_key}/design-review
GET /api/ai/design-kits
GET /api/ai/section-grammar
```

Implementation tasks:

- Reuse `_resolve_inside()` and `_safe_lead_key()`.
- Validate JSON shape on save.
- Return summaries in `GET /website-package/{lead_key}`.
- Keep paths under `generated/{lead_key}`.

Tests:

- Read endpoints return 404-style JSON when artifact missing.
- Save marketing brief validates shape.
- Design kits endpoint lists available kits.
- Section grammar endpoint lists section types/moves.

Commands:

```powershell
python -m pytest BrowserApp\summit-web\test_website_package_endpoints.py -q
```

Acceptance:

- Studio can read all enhanced artifacts.

## Phase 9: Website Studio UI

Goal: expose enhanced generation controls.

Files to inspect/modify:

```text
BrowserApp/summit-web/app/templates/website_studio.html
BrowserApp/summit-web/app/templates/website_studio_editor.html
BrowserApp/summit-web/app/static/js/*.js
BrowserApp/summit-web/app/static/css/*.css
```

Implementation tasks:

- Add enhanced generation toggle.
- Add design kit picker.
- Add section preference/block controls.
- Add Marketing Brief tab.
- Add Design Review tab.
- Add "Run Design Review" button.
- Add "Run Preview QA" button if not already visible.
- Add status badges:
  - HTML valid
  - Preview QA checked
  - Design review passed
  - Schema/analytics included

Tests:

- Existing template smoke tests pass.
- Manual browser check: Studio loads, controls do not overlap, package preview still works.

Commands:

```powershell
python -m pytest BrowserApp\summit-web -q
```

Manual check:

```powershell
python BrowserApp\summit-web\run.py
```

Acceptance:

- UI can trigger enhanced generation and display artifacts.

## Phase 10: Review-Informed Regeneration

Goal: use review/QA output to improve generated pages.

Files to modify:

```text
BrowserApp/lead-vault/lead_vault_website_generator.py
BrowserApp/lead-vault/design_review_agent.py
BrowserApp/summit-web/app/routers/ai.py
```

Files to add:

```text
BrowserApp/lead-vault/test_review_informed_regeneration.py
```

Artifact:

```text
generated/{lead_key}/regeneration_notes.json
```

Implementation tasks:

- Build regeneration notes from design review and preview QA.
- Cap notes length.
- Add prompt block for whole-page retry.
- Add prompt block for section edit retry.
- Backup existing HTML before retry.
- Do not auto-run more than one retry per request.

Tests:

- Notes are generated from warnings/errors.
- Notes exclude raw untrusted HTML instructions.
- Retry creates a backup version.
- Retry prompt includes review notes.

Acceptance:

- User can regenerate from review notes.
- No infinite retry loop.

## Phase 11: Schema + Analytics Launch Pack

Goal: make generated website packages more launch-ready.

Files to modify:

```text
BrowserApp/lead-vault/marketing_skill_bridge.py
BrowserApp/lead-vault/lead_vault_website_generator.py
BrowserApp/lead-vault/lead_vault_website_validator.py
```

Artifacts:

```text
generated/{lead_key}/analytics_plan.json
generated/{lead_key}/schema_plan.json
```

Implementation tasks:

- Add schema plan to marketing brief.
- Prompt model to include JSON-LD when safe.
- Add `data-analytics-event` to primary CTA/form elements.
- Persist analytics plan separately.
- Validator checks for schema when requested.
- Validator checks CTA analytics attributes when requested.

Tests:

- LocalBusiness schema plan generated for local businesses.
- CTA event names generated.
- HTML with requested schema passes validator.
- Missing requested schema creates warning, not hard failure at first.

Acceptance:

- Generated package includes SEO/schema/analytics launch notes.

## Phase 12: Optional External Import Tooling

Goal: later automate pattern imports from approved open-source repos.

Do not implement until Phases 1-11 are stable.

Possible file:

```text
BrowserApp/lead-vault/design_pattern_importer.py
```

Rules:

- Only import from allowlisted sources.
- Store license metadata.
- Convert HTML/components into abstract notes manually or semi-automatically.
- Never pipe raw imported template code into generated customer pages.

Acceptance:

- Import tool produces pattern summaries only.

## First Codex Task To Run

Recommended first implementation request:

```text
Implement Phase 1 from BrowserApp/lead-vault/CODEX_DESIGN_AGENT_IMPLEMENTATION_PLAN.md.
Only add the data contract files and tests. Do not modify generator behavior.
Run the Phase 1 pytest command and report results.
```

## Second Codex Task To Run

```text
Implement Phase 2 from BrowserApp/lead-vault/CODEX_DESIGN_AGENT_IMPLEMENTATION_PLAN.md.
Add section_grammar_library.py and tests only.
Run Phase 1 and Phase 2 tests.
```

## Third Codex Task To Run

```text
Implement Phase 3 from BrowserApp/lead-vault/CODEX_DESIGN_AGENT_IMPLEMENTATION_PLAN.md.
Add design_kit_library.py and tests only.
Run Phase 1-3 tests.
```

## Done Definition

The full upgrade is done when:

- enhanced generation is opt-in and stable
- marketing brief, design kit, section grammar, design review, validation, and preview QA artifacts are all visible in Website Studio
- default generation still works
- generated packages include schema/analytics plans
- review-informed regeneration creates visibly better output without looping
- tests cover the new data loaders, prompt payloads, API paths, review agent, and regeneration notes

