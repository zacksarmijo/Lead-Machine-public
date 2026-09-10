"""Tests for lead_vault_website_generator."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from inspiration_library import InspirationLibrary, InspirationProfile, LayoutPattern, Palette
import lead_vault_website_generator as gen_mod
from lead_vault_website_generator import (
    MAX_SCRAPED_TEXT_CHARS,
    MOTION_RUNTIME_CSS_FILE,
    MOTION_RUNTIME_JS_FILE,
    MULTI_PAGE_EXPORT_DIR,
    POLLINATIONS_FALLBACK_COUNT,
    POLLINATIONS_PROMPT_BANK,
    SITE_DESIGN_BRIEF_FILE,
    SITE_PLAN_FILE,
    WebsiteGenerator,
    WebsiteGeneratorError,
    _build_pollinations_image_specs,
    build_prompt_design_brief,
    build_runtime_attribute_contract,
    build_site_design_brief,
    build_site_generation_plan,
    ensure_alpine_csp_compatibility,
    inject_motion_runtime,
    prepare_site_design_brief,
    strip_custom_runtime_motion_css,
    _cap,
    _filter_photo_urls,
    _replace_photo_refs,
    _safe_key,
    _trim_text,
    load_site_design_brief,
    load_scraped_assets,
    repair_common_alpine_state,
    sanitize_error,
    write_site_design_brief,
    write_motion_runtime_assets,
)


SAMPLE_SCRAPE = {
    "source_url": "http://example.com/",
    "final_url": "http://example.com/",
    "business_name": "Example Dental",
    "title": "Example Dental | Littleton",
    "meta_description": "Caring dentistry in Littleton.",
    "phones": ["(720) 555-0100"],
    "emails": ["hello@example.com"],
    "services": ["Cleanings", "Invisalign", "Emergency"],
    "headings": ["Welcome", "Our Team"],
    "photos": ["http://example.com/hero.jpg"],
    "colors": ["#0E7490"],
    "fonts": ["Inter"],
    "social_links": {"facebook": "http://facebook.com/example"},
    "main_text": "Example Dental is a family practice in Littleton.",
}


def _make_profile(category: str = "dentist") -> InspirationProfile:
    return InspirationProfile(
        category=category,
        matched_from="dental",
        fallback=False,
        palette=Palette(name=category, primary="#0E7490", text="#0F172A"),
        layouts=[],
        tone="calm, clean",
        must_include=["booking link"],
        avoid=["fear-based messaging"],
    )


def _make_lead(**overrides) -> dict:
    lead = {
        "lead_key": "test-lead-01",
        "business_name": "Example Dental",
        "city_area": "Littleton, CO",
        "data": {"Business Type": "Dentist"},
    }
    lead.update(overrides)
    return lead


class SafeKeyTests(unittest.TestCase):
    def test_replaces_unsafe_chars(self) -> None:
        self.assertEqual(_safe_key("a b/c?d"), "a_b_c_d")

    def test_empty_defaults_to_unknown(self) -> None:
        self.assertEqual(_safe_key(""), "unknown")
        self.assertEqual(_safe_key(None), "unknown")  # type: ignore[arg-type]

    def test_caps_length(self) -> None:
        self.assertEqual(len(_safe_key("x" * 500)), 120)


class TrimTextTests(unittest.TestCase):
    def test_short_text_unchanged(self) -> None:
        self.assertEqual(_trim_text("hello", 100), "hello")

    def test_empty_returns_empty(self) -> None:
        self.assertEqual(_trim_text("", 100), "")

    def test_long_text_truncates_with_ellipsis(self) -> None:
        long_text = "x" * (MAX_SCRAPED_TEXT_CHARS + 10)
        trimmed = _trim_text(long_text, MAX_SCRAPED_TEXT_CHARS)
        self.assertTrue(trimmed.endswith("…"))
        self.assertLess(len(trimmed), len(long_text))


class CapTests(unittest.TestCase):
    def test_short_value_unchanged(self) -> None:
        self.assertEqual(_cap("hello", 10), "hello")

    def test_long_value_truncated(self) -> None:
        result = _cap("x" * 500, 10)
        self.assertTrue(result.endswith("…"))
        self.assertLessEqual(len(result), 11)

    def test_none_returns_empty(self) -> None:
        self.assertEqual(_cap(None, 10), "")

    def test_strips_whitespace(self) -> None:
        self.assertEqual(_cap("  hi  ", 10), "hi")


class SanitizeErrorTests(unittest.TestCase):
    def test_redacts_openai_key(self) -> None:
        text = "boom sk-proj-abcdef1234567890 broke"
        self.assertNotIn("sk-proj-abcdef", sanitize_error(text))
        self.assertIn("[redacted]", sanitize_error(text))

    def test_redacts_anthropic_key(self) -> None:
        text = "Auth failed with sk-ant-api03-ABCDEFG12345"
        self.assertNotIn("sk-ant-api03-ABCDEFG12345", sanitize_error(text))

    def test_redacts_bearer_token(self) -> None:
        text = "Authorization: Bearer abc123xyz456secret"
        self.assertNotIn("abc123xyz456secret", sanitize_error(text))

    def test_passes_through_safe_text(self) -> None:
        self.assertEqual(
            sanitize_error("network timeout"), "network timeout"
        )

    def test_handles_none(self) -> None:
        self.assertEqual(sanitize_error(None), "")


class FilterPhotoUrlsTests(unittest.TestCase):
    def test_keeps_http_and_https(self) -> None:
        urls = [
            "http://example.com/a.jpg",
            "https://example.com/b.jpg",
        ]
        self.assertEqual(_filter_photo_urls(urls), urls)

    def test_rejects_javascript_uri(self) -> None:
        urls = ["javascript:alert(1)"]
        self.assertEqual(_filter_photo_urls(urls), [])

    def test_rejects_data_uri(self) -> None:
        urls = ["data:image/svg+xml;base64,PHN2Zy8+"]
        self.assertEqual(_filter_photo_urls(urls), [])

    def test_rejects_file_uri(self) -> None:
        urls = ["file:///etc/passwd"]
        self.assertEqual(_filter_photo_urls(urls), [])

    def test_rejects_oversized_url(self) -> None:
        huge = "https://example.com/" + ("a" * 3000)
        self.assertEqual(_filter_photo_urls([huge]), [])

    def test_dedupes_preserving_order(self) -> None:
        urls = [
            "http://example.com/a.jpg",
            "http://example.com/a.jpg",
            "http://example.com/b.jpg",
        ]
        self.assertEqual(
            _filter_photo_urls(urls),
            ["http://example.com/a.jpg", "http://example.com/b.jpg"],
        )

    def test_respects_limit(self) -> None:
        urls = [f"http://example.com/{i}.jpg" for i in range(10)]
        self.assertEqual(len(_filter_photo_urls(urls, limit=3)), 3)

    def test_non_list_returns_empty(self) -> None:
        self.assertEqual(_filter_photo_urls("not a list"), [])
        self.assertEqual(_filter_photo_urls(None), [])


class LoadScrapedAssetsTests(unittest.TestCase):
    def test_missing_file_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(WebsiteGeneratorError):
                load_scraped_assets("nope", base_dir=Path(tmp))

    def test_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "lead_x" / "scrape.json"
            target.parent.mkdir(parents=True)
            target.write_text(json.dumps(SAMPLE_SCRAPE), encoding="utf-8")
            result = load_scraped_assets("lead_x", base_dir=root)
            self.assertEqual(result["business_name"], "Example Dental")

    def test_malformed_json_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "lead_y" / "scrape.json"
            target.parent.mkdir(parents=True)
            target.write_text("{ not json", encoding="utf-8")
            with self.assertRaises(WebsiteGeneratorError):
                load_scraped_assets("lead_y", base_dir=root)


class PromptBuildingTests(unittest.TestCase):
    def test_scraped_phone_and_service_present(self) -> None:
        gen = WebsiteGenerator(api_key="x", model="claude-sonnet-4-5")
        prompt = gen._build_user_prompt(_make_lead(), SAMPLE_SCRAPE, _make_profile())
        self.assertIn("(720) 555-0100", prompt)
        self.assertIn("Invisalign", prompt)
        self.assertIn("summit-image://image_1", prompt)
        self.assertNotIn("http://example.com/hero.jpg", prompt)

    def test_reference_urls_never_in_prompt(self) -> None:
        """The AI must never see a third-party inspiration URL."""
        gen = WebsiteGenerator(api_key="x", model="claude-sonnet-4-5")
        lib = InspirationLibrary()
        profile = lib.load("real estate agent")
        prompt = gen._build_user_prompt(_make_lead(), SAMPLE_SCRAPE, profile)
        self.assertNotIn("compass.com", prompt.lower())
        self.assertNotIn("sothebysrealty", prompt.lower())

    def test_palette_fields_present(self) -> None:
        gen = WebsiteGenerator(api_key="x", model="claude-sonnet-4-5")
        prompt = gen._build_user_prompt(_make_lead(), SAMPLE_SCRAPE, _make_profile())
        self.assertIn("#0E7490", prompt)

    def test_empty_scrape_does_not_crash(self) -> None:
        gen = WebsiteGenerator(api_key="x", model="claude-sonnet-4-5")
        prompt = gen._build_user_prompt(_make_lead(), {}, _make_profile())
        self.assertIn("Example Dental", prompt)

    def test_prompt_wraps_scraped_content_in_delimiters(self) -> None:
        gen = WebsiteGenerator(api_key="x", model="claude-sonnet-4-5")
        prompt = gen._build_user_prompt(_make_lead(), SAMPLE_SCRAPE, _make_profile())
        self.assertIn("<scraped_data>", prompt)
        self.assertIn("</scraped_data>", prompt)

    def test_prompt_includes_site_generation_plan(self) -> None:
        gen = WebsiteGenerator(api_key="x", model="claude-sonnet-4-5")
        scrape = dict(SAMPLE_SCRAPE)
        scrape["site_blueprint"] = {
            "generator_fit": "multi_page_blueprint_needed",
            "multi_page_detected": True,
            "auth_detected": True,
            "recommended_pages": [
                {"role": "home", "title": "Home", "reason": "Entry point"},
                {"role": "services", "title": "Services", "reason": "Service detail"},
                {"role": "contact", "title": "Contact", "reason": "Contact flow"},
            ],
            "risk_flags": ["auth_or_portal_detected"],
        }
        prompt = gen._build_user_prompt(_make_lead(), scrape, _make_profile())
        self.assertIn("<site_generation_plan>", prompt)
        self.assertIn("multi_page_plan", prompt)
        self.assertIn("auth_or_portal_detected", prompt)

    def test_prompt_includes_site_design_brief(self) -> None:
        gen = WebsiteGenerator(api_key="x", model="claude-sonnet-4-5")
        prompt = gen._build_user_prompt(_make_lead(), SAMPLE_SCRAPE, _make_profile())

        self.assertIn("<site_design_brief>", prompt)
        self.assertIn("</site_design_brief>", prompt)
        self.assertIn('"site_dna"', prompt)
        self.assertIn('"experience_dna"', prompt)
        self.assertIn('"archetype_key": "luxury_calm"', prompt)
        self.assertIn('"primitive_contracts"', prompt)
        self.assertIn("SITE DESIGN BRIEF - trusted app-generated", prompt)

    def test_enhanced_prompt_includes_strategy_blocks(self) -> None:
        gen = WebsiteGenerator(api_key="x", model="claude-sonnet-4-5")
        prompt = gen._build_user_prompt(
            _make_lead(),
            SAMPLE_SCRAPE,
            _make_profile(),
            enhanced_design=True,
            marketing_brief_payload={
                "primary_conversion_goal": "appointment requests",
                "copy_strategy": {"cta_labels": ["Book an Appointment"]},
            },
            design_kit_payload={
                "kit_key": "healthcare-trust",
                "label": "Healthcare Trust",
            },
            section_grammar_payload=[
                {"key": "professional_authority_intro", "section_type": "hero"}
            ],
        )

        self.assertIn("<marketing_brief>", prompt)
        self.assertIn("<design_kit>", prompt)
        self.assertIn("<section_grammar>", prompt)
        self.assertIn("healthcare-trust", prompt)
        self.assertNotIn("https://github.com", prompt)

    def test_prompt_includes_runtime_attribute_contract(self) -> None:
        gen = WebsiteGenerator(api_key="x", model="claude-sonnet-4-5")
        prompt = gen._build_user_prompt(_make_lead(), SAMPLE_SCRAPE, _make_profile())

        self.assertIn("RUNTIME ATTRIBUTE CONTRACT - mandatory", prompt)
        self.assertIn('data-motion="reveal-up"', prompt)
        self.assertIn('data-hover="lift"', prompt)
        self.assertIn("Do not write custom CSS keyframes", prompt)
        self.assertIn("Do not write IntersectionObserver reveal code", prompt)
        self.assertIn("Blocked primitives for this lead", prompt)

    def test_prompt_demotes_layout_patterns_to_optional_ingredients(self) -> None:
        gen = WebsiteGenerator(api_key="x", model="claude-sonnet-4-5")
        profile = _make_profile()
        profile.layouts = [
            LayoutPattern(
                name="hero_split",
                body="Hero Split\n" + ("Use a two-column pattern.\n" * 500),
                documented=True,
            )
        ]
        prompt = gen._build_user_prompt(_make_lead(), SAMPLE_SCRAPE, profile)

        self.assertIn("LAYOUT PATTERN INGREDIENTS - optional", prompt)
        self.assertIn("## Layout ingredient: hero_split", prompt)
        self.assertNotIn("compose the page from these in the order listed", prompt)
        self.assertNotIn("Use a two-column pattern.\n" * 400, prompt)

    def test_prompt_excludes_malicious_photo_urls(self) -> None:
        gen = WebsiteGenerator(api_key="x", model="claude-sonnet-4-5")
        evil_scrape = dict(SAMPLE_SCRAPE)
        evil_scrape["photos"] = [
            "javascript:alert(1)",
            "data:image/svg+xml;base64,PHN2Zy8+",
            "https://example.com/real.jpg",
        ]
        prompt = gen._build_user_prompt(_make_lead(), evil_scrape, _make_profile())
        self.assertNotIn("javascript:", prompt)
        self.assertNotIn("data:image", prompt)
        self.assertIn("summit-image://image_1", prompt)
        self.assertNotIn("https://example.com/real.jpg", prompt)

    def test_prompt_truncates_long_business_name(self) -> None:
        gen = WebsiteGenerator(api_key="x", model="claude-sonnet-4-5")
        lead = _make_lead(business_name="A" * 5000)
        empty_scrape = {k: v for k, v in SAMPLE_SCRAPE.items() if k != "business_name"}
        prompt = gen._build_user_prompt(lead, empty_scrape, _make_profile())
        self.assertNotIn("A" * 1000, prompt)

    def test_generated_image_guidance_is_included_in_prompt(self) -> None:
        gen = WebsiteGenerator(api_key="x", model="claude-sonnet-4-5")
        lead = _make_lead(
            business_name="Example Backflow and Fire",
            city_area="Colorado Front Range",
            data={"Business Type": "Fire protection and backflow"},
        )
        scrape = dict(SAMPLE_SCRAPE)
        scrape["business_name"] = "Example Backflow and Fire"
        scrape["services"] = [
            "Fire Protection",
            "Fire Sprinkler Services",
            "Backflow Certification",
        ]
        specs = _build_pollinations_image_specs(
            business_name="Example Backflow and Fire",
            category="generic",
            tone="clean, professional",
            lead=lead,
            scraped=scrape,
            count=3,
        )
        scrape["photos"] = [spec["url"] for spec in specs]
        scrape["photos_source"] = "pollinations_fallback"
        scrape["generated_photo_specs"] = specs

        prompt = gen._build_user_prompt(lead, scrape, _make_profile("generic"))

        self.assertIn("Generated image guidance", prompt)
        self.assertIn("placement-specific fallback images", prompt)
        self.assertIn("Example Backflow and Fire", prompt)
        self.assertIn("backflow preventer", prompt)
        self.assertIn("matching placement", prompt)
        self.assertIn("summit-image://image_1", prompt)
        self.assertNotIn(specs[0]["url"], prompt)

    def test_photo_refs_are_resolved_before_html_is_saved(self) -> None:
        urls = [
            "https://example.com/very-long-generated-image-one.jpg",
            "https://example.com/very-long-generated-image-two.jpg",
        ]
        html = (
            '<img src="summit-image://image_1">'
            '<section style="background-image:url({{image_2}})"></section>'
        )

        resolved = _replace_photo_refs(html, urls)

        self.assertIn(urls[0], resolved)
        self.assertIn(urls[1], resolved)
        self.assertNotIn("summit-image://image_1", resolved)
        self.assertNotIn("{{image_2}}", resolved)


class PollinationsFallbackPromptTests(unittest.TestCase):
    def test_prompt_bank_has_at_least_50_templates(self) -> None:
        self.assertGreaterEqual(len(POLLINATIONS_PROMPT_BANK), 50)
        placements = {template.placement for template in POLLINATIONS_PROMPT_BANK}
        self.assertGreaterEqual(len(placements), 50)

    def test_prompts_are_site_specific_placement_specific_and_not_generic(self) -> None:
        lead = _make_lead(
            business_name="Example Backflow and Fire",
            city_area="Colorado Front Range",
            data={"Business Type": "Fire protection and backflow"},
        )
        scrape = dict(SAMPLE_SCRAPE)
        scrape["business_name"] = "Example Backflow and Fire"
        scrape["services"] = [
            "Fire Protection",
            "Fire Sprinkler Services",
            "Backflow Certification",
            "Fire Alarm Services",
        ]
        specs = _build_pollinations_image_specs(
            business_name="Example Backflow and Fire",
            category="generic",
            tone="clean, professional, confident without stock-photo energy",
            lead=lead,
            scraped=scrape,
        )

        self.assertEqual(len(specs), POLLINATIONS_FALLBACK_COUNT)
        self.assertEqual(len({spec["prompt"] for spec in specs}), len(specs))
        self.assertEqual(len({spec["placement"] for spec in specs}), len(specs))

        combined = " ".join(spec["prompt"] for spec in specs).lower()
        self.assertIn("example backflow and fire", combined)
        self.assertIn("backflow preventer", combined)
        self.assertIn("fire sprinkler", combined)
        self.assertIn("no faces", combined)
        self.assertIn("no headshots", combined)
        self.assertNotIn("generic business", combined)
        self.assertNotIn("without stock", combined)


class SystemPromptTests(unittest.TestCase):
    def test_system_prompt_mentions_csp(self) -> None:
        gen = WebsiteGenerator(api_key="x", model="claude-sonnet-4-5")
        system = gen._system_prompt()
        self.assertIn("Content-Security-Policy", system)

    def test_system_prompt_mentions_injection_defense(self) -> None:
        gen = WebsiteGenerator(api_key="x", model="claude-sonnet-4-5")
        system = gen._system_prompt()
        self.assertIn("<scraped_data>", system)
        self.assertIn("IGNORE", system)

    def test_system_prompt_uses_experience_dna_for_motion_and_nav(self) -> None:
        gen = WebsiteGenerator(api_key="x", model="claude-sonnet-4-5")
        system = gen._system_prompt()
        self.assertIn("Experience DNA", system)
        self.assertIn("follow the Experience DNA nav system", system)
        self.assertIn("summit-motion.css", system)
        self.assertIn("data-motion", system)
        self.assertIn("Do not write custom reveal observers", system)
        self.assertIn("Do not write IntersectionObserver reveal code", system)
        self.assertNotIn("blurred blob", system.lower())


class ExtractHtmlTests(unittest.TestCase):
    def test_strips_code_fence(self) -> None:
        gen = WebsiteGenerator(api_key="x")
        raw = "```html\n<!doctype html><html></html>\n```"
        self.assertTrue(gen._extract_html(raw).startswith("<!doctype"))

    def test_strips_leading_commentary(self) -> None:
        gen = WebsiteGenerator(api_key="x")
        raw = "Here is your page:\n<!DOCTYPE html><html></html>"
        self.assertTrue(gen._extract_html(raw).startswith("<!DOCTYPE"))

    def test_accepts_plain_html(self) -> None:
        gen = WebsiteGenerator(api_key="x")
        raw = "<!doctype html>\n<html></html>"
        self.assertEqual(gen._extract_html(raw), raw)


class MotionRuntimeTests(unittest.TestCase):
    def test_inject_motion_runtime_adds_local_assets_once(self) -> None:
        html = "<!doctype html><html><head><title>x</title></head><body></body></html>"
        injected = inject_motion_runtime(html)
        self.assertIn(f'href="{MOTION_RUNTIME_CSS_FILE}"', injected)
        self.assertIn(f'src="{MOTION_RUNTIME_JS_FILE}"', injected)
        self.assertIn('data-summit-motion-runtime="css"', injected)
        self.assertEqual(inject_motion_runtime(injected), injected)

    def test_write_motion_runtime_assets_copies_css_and_js(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            assets = write_motion_runtime_assets(output_dir)
            self.assertEqual(assets["css"], MOTION_RUNTIME_CSS_FILE)
            self.assertEqual(assets["js"], MOTION_RUNTIME_JS_FILE)
            css = (output_dir / MOTION_RUNTIME_CSS_FILE).read_text(encoding="utf-8")
            js = (output_dir / MOTION_RUNTIME_JS_FILE).read_text(encoding="utf-8")
            self.assertIn('[data-motion="reveal-up"]', css)
            self.assertIn('[data-bg="gradient-mesh"]', css)
            self.assertIn('[data-bg="water-attractor"]', css)
            self.assertIn(".summit-water-canvas", css)
            self.assertIn("[data-parallax]", css)
            self.assertIn("SummitMotionRuntime", js)
            self.assertIn('data-motion="sticky-cta"', js)
            self.assertIn('data-bg="water-attractor"', js)

    def test_strip_custom_runtime_motion_css_keeps_reveal_content_visible(self) -> None:
        html = """<!doctype html><html><head><style>
[data-motion="reveal-up"] { opacity: 0; transform: translateY(20px); transition: opacity .7s; }
.card { color: red; }
@media (prefers-reduced-motion: reduce) {
  [data-motion] { opacity: 1 !important; transform: none !important; }
}
</style></head><body><section data-motion="reveal-up">Visible copy</section></body></html>"""
        cleaned = strip_custom_runtime_motion_css(html)
        self.assertIn(".card { color: red; }", cleaned)
        self.assertIn("Visible copy", cleaned)
        self.assertNotIn('[data-motion="reveal-up"] { opacity: 0', cleaned)
        self.assertNotIn("[data-motion] { opacity: 1", cleaned)

    def test_ensure_alpine_csp_compatibility_adds_unsafe_eval(self) -> None:
        html = """<!doctype html><html><head>
<meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://unpkg.com; style-src 'self' 'unsafe-inline'">
<script defer src="https://unpkg.com/alpinejs"></script>
</head><body><nav x-data="{open:false}"><button @click="open=!open">Menu</button></nav></body></html>"""
        cleaned = ensure_alpine_csp_compatibility(html)
        self.assertIn("script-src 'self' 'unsafe-inline' 'unsafe-eval'", cleaned)
        self.assertEqual(ensure_alpine_csp_compatibility(cleaned), cleaned)

    def test_ensure_alpine_csp_compatibility_leaves_static_html_alone(self) -> None:
        html = """<!doctype html><html><head>
<meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self' 'unsafe-inline'">
</head><body><h1>No Alpine</h1></body></html>"""
        self.assertEqual(ensure_alpine_csp_compatibility(html), html)

    def test_repair_common_alpine_state_initializes_slider_dragging(self) -> None:
        html = (
            '<div x-data="{pos:50, drag(e){this.pos=50}}" '
            '@mousedown="dragging=true" '
            '@mousemove.window="if(dragging)drag($event)">'
            "</div>"
        )
        repaired = repair_common_alpine_state(html)
        self.assertIn("x-data=\"{dragging:false, pos:50", repaired)
        self.assertEqual(repair_common_alpine_state(repaired), repaired)


class SiteGenerationPlanTests(unittest.TestCase):
    def test_multi_page_blueprint_creates_multi_page_plan(self) -> None:
        scrape = dict(SAMPLE_SCRAPE)
        scrape["site_blueprint"] = {
            "generator_fit": "multi_page_blueprint_needed",
            "multi_page_detected": True,
            "auth_detected": True,
            "recommended_pages": [
                {"role": "home", "title": "Home", "reason": "Entry point"},
                {"role": "services", "title": "Fire Alarm Services", "reason": "Observed page"},
                {"role": "contact", "title": "Contact", "reason": "Conversion"},
            ],
            "risk_flags": ["multi_page_site_detected"],
        }
        plan = build_site_generation_plan(_make_lead(), scrape, _make_profile())
        self.assertEqual(plan["mode"], "multi_page_plan")
        self.assertTrue(plan["multi_page_export_enabled"])
        self.assertTrue(plan["auth_detected"])
        self.assertIn("auth_or_portal_detected", plan["risk_flags"])
        filenames = {page["filename"] for page in plan["pages"]}
        self.assertIn("index.html", filenames)
        self.assertIn("fire-alarm-services.html", filenames)

    def test_simple_scrape_remains_single_page_mockup(self) -> None:
        plan = build_site_generation_plan(_make_lead(), SAMPLE_SCRAPE, _make_profile())
        self.assertEqual(plan["mode"], "single_page_mockup")
        self.assertFalse(plan["multi_page_export_enabled"])


class SiteDesignBriefTests(unittest.TestCase):
    def test_brief_contains_site_and_experience_dna(self) -> None:
        profile = _make_profile("dentist")
        plan = build_site_generation_plan(_make_lead(), SAMPLE_SCRAPE, profile)
        brief = build_site_design_brief(_make_lead(), SAMPLE_SCRAPE, profile, plan)

        self.assertEqual(brief["version"], 1)
        self.assertEqual(brief["phase"], 4)
        self.assertEqual(brief["lead_key"], "test-lead-01")
        self.assertEqual(brief["site_dna"]["category"], "dentist")
        self.assertIn("patients", brief["site_dna"]["audience"])
        self.assertIn("appointment", brief["site_dna"]["primary_conversion_goal"])
        self.assertEqual(brief["experience_dna"]["archetype_key"], "luxury_calm")
        self.assertIn("reveal_up", brief["experience_dna"]["recommended_primitives"])
        self.assertIn("reveal_up", brief["experience_dna"]["primitive_contracts"])
        self.assertEqual(brief["site_plan_summary"]["mode"], "single_page_mockup")
        self.assertFalse(brief["review_status"]["approved_by_user"])

    def test_brief_prefers_conversion_for_urgent_trade(self) -> None:
        profile = _make_profile("plumber")
        lead = _make_lead(data={"Business Type": "Plumber"})
        scrape = dict(SAMPLE_SCRAPE)
        scrape["services"] = ["Emergency Plumbing", "Drain Cleaning", "Water Heaters"]
        plan = build_site_generation_plan(lead, scrape, profile)
        brief = build_site_design_brief(lead, scrape, profile, plan)

        self.assertEqual(
            brief["experience_dna"]["archetype_key"],
            "local_service_conversion",
        )
        self.assertIn("phone", brief["site_dna"]["primary_conversion_goal"].lower())
        self.assertIn("sticky_cta", brief["experience_dna"]["recommended_primitives"])

    def test_runtime_attribute_contract_uses_brief_primitives(self) -> None:
        profile = _make_profile("plumber")
        lead = _make_lead(data={"Business Type": "Plumber"})
        plan = build_site_generation_plan(lead, SAMPLE_SCRAPE, profile)
        brief = build_site_design_brief(lead, SAMPLE_SCRAPE, profile, plan)
        prompt_brief = build_prompt_design_brief(brief)
        contract = build_runtime_attribute_contract(prompt_brief)

        self.assertIn("reveal_up", contract)
        self.assertIn("sticky_cta", contract)
        self.assertIn('data-motion="sticky-cta"', contract)
        self.assertIn('data-bg="water-attractor"', contract)
        self.assertIn("custom parallax scroll listeners", contract)
        self.assertIn("Allowed primitive attributes", contract)

    def test_prepare_uses_user_approved_saved_brief(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            profile = _make_profile("dentist")
            plan = build_site_generation_plan(_make_lead(), SAMPLE_SCRAPE, profile)
            saved = build_site_design_brief(_make_lead(), SAMPLE_SCRAPE, profile, plan)
            saved["experience_dna"]["archetype_key"] = "tech_launch"
            saved["review_status"]["approved_by_user"] = True
            saved["review_status"]["saved_in_website_studio"] = True
            write_site_design_brief(saved, output_dir)

            brief, source = prepare_site_design_brief(
                _make_lead(),
                SAMPLE_SCRAPE,
                profile,
                plan,
                output_dir,
            )

            self.assertEqual(source, "saved_user_approved")
            self.assertEqual(brief["experience_dna"]["archetype_key"], "tech_launch")
            loaded = load_site_design_brief(
                output_dir,
                lead_key="test-lead-01",
                require_user_approved=True,
            )
            self.assertIsNotNone(loaded)

    def test_prepare_ignores_unapproved_saved_brief(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            profile = _make_profile("dentist")
            plan = build_site_generation_plan(_make_lead(), SAMPLE_SCRAPE, profile)
            saved = build_site_design_brief(_make_lead(), SAMPLE_SCRAPE, profile, plan)
            saved["experience_dna"]["archetype_key"] = "tech_launch"
            write_site_design_brief(saved, output_dir)

            brief, source = prepare_site_design_brief(
                _make_lead(),
                SAMPLE_SCRAPE,
                profile,
                plan,
                output_dir,
            )

            self.assertEqual(source, "generated")
            self.assertEqual(brief["experience_dna"]["archetype_key"], "luxury_calm")


class _FakeStreamContext:
    """Mimics the Anthropic SDK's streaming context manager."""

    def __init__(self, chunks, stop_reason: str = "end_turn"):
        self._chunks = list(chunks)
        self._stop_reason = stop_reason

    def __enter__(self):
        stop = self._stop_reason

        class _Stream:
            text_stream = iter(self._chunks)

            def get_final_message(_self):  # noqa: N805
                return SimpleNamespace(stop_reason=stop)

        return _Stream()

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeAnthropicClient:
    def __init__(self, *_args, **_kwargs):
        self.messages = SimpleNamespace(stream=self._stream)
        self._html_to_return: str = (
            '<!doctype html><html lang="en"><head><title>t</title></head>'
            "<body><h1>h</h1></body></html>"
        )
        self._stop_reason: str = "end_turn"

    def _stream(self, **kwargs):
        messages = kwargs.get("messages") or []
        prompt = ""
        if messages and isinstance(messages[0], dict):
            prompt = str(messages[0].get("content") or "")
        if "PAGE EXPORT GENERATION" in prompt:
            html = (
                '<!doctype html><html lang="en"><head><title>AI Page</title></head>'
                '<body data-summit-page="test"><section data-summit-section="page-hero">'
                '<h1>AI Generated Page</h1><p>Cleanings and (720) 555-0100</p>'
                '</section></body></html>'
            )
        else:
            html = self._html_to_return
        mid = max(1, len(html) // 2)
        return _FakeStreamContext(
            [html[:mid], html[mid:]],
            stop_reason=self._stop_reason,
        )


class FakeCanonicalMockupClient(FakeAnthropicClient):
    def __init__(self, *_args, **_kwargs):
        super().__init__(*_args, **_kwargs)
        self._html_to_return = (
            '<!doctype html><html lang="en"><head><title>Canonical</title>'
            '<script src="https://cdn.tailwindcss.com"></script>'
            '<style>.canonical-token{color:#123456}.cta-button{border-radius:8px}</style>'
            '</head><body class="canonical-body">'
            '<header class="canonical-header"><a href="#work">Work</a>'
            '<a href="#services">Services</a><a href="#showroom">Showroom</a>'
            '<a href="#testimonials">Reviews</a><a href="#contact">Contact</a></header>'
            '<main class="canonical-main"><section data-summit-section="hero" '
            'data-summit-label="Hero"><h1>Canonical Hero</h1></section></main>'
            '<footer class="canonical-footer">Canonical Footer</footer>'
            '<script>window.__canonicalNav=true;</script>'
            '</body></html>'
        )


class FakeCanonicalTruncatedExportClient(FakeCanonicalMockupClient):
    def _stream(self, **kwargs):
        messages = kwargs.get("messages") or []
        prompt = ""
        if messages and isinstance(messages[0], dict):
            prompt = str(messages[0].get("content") or "")
        if "PAGE EXPORT GENERATION" in prompt:
            html = (
                '<!doctype html><html lang="en"><head><title>Too Long</title></head>'
                '<body data-summit-page="test"><section data-summit-section="page-hero">'
                '<h1>This output truncates</h1></section></body></html>'
            )
            mid = max(1, len(html) // 2)
            return _FakeStreamContext([html[:mid], html[mid:]], stop_reason="max_tokens")
        return super()._stream(**kwargs)


class GenerateIntegrationTests(unittest.TestCase):
    def _setup_dirs(self, tmp: Path) -> tuple[Path, Path]:
        scraped = tmp / "scraped_assets"
        generated = tmp / "generated"
        scraped.mkdir()
        generated.mkdir()
        target = scraped / "test-lead-01" / "scrape.json"
        target.parent.mkdir(parents=True)
        target.write_text(json.dumps(SAMPLE_SCRAPE), encoding="utf-8")
        return scraped, generated

    def test_generate_writes_mockup_and_meta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scraped_dir, generated_dir = self._setup_dirs(Path(tmp))
            gen = WebsiteGenerator(
                api_key="fake",
                model="claude-sonnet-4-5",
                generated_dir=generated_dir,
                scraped_dir=scraped_dir,
            )
            with patch.object(
                gen_mod,
                "_anthropic",
                SimpleNamespace(
                    Anthropic=FakeAnthropicClient,
                    AuthenticationError=Exception,
                ),
            ):
                result = gen.generate(lead=_make_lead(), inspiration=_make_profile())

            self.assertTrue(result.mockup_path.exists())
            self.assertTrue(result.meta_path.exists())
            meta = json.loads(result.meta_path.read_text(encoding="utf-8"))
            self.assertEqual(meta["lead_key"], "test-lead-01")
            self.assertEqual(meta["category"], "dentist")
            self.assertTrue((result.output_dir / SITE_PLAN_FILE).exists())
            self.assertTrue((result.output_dir / SITE_DESIGN_BRIEF_FILE).exists())
            self.assertTrue(result.site_design_brief_path.exists())
            self.assertTrue((result.output_dir / MOTION_RUNTIME_CSS_FILE).exists())
            self.assertTrue((result.output_dir / MOTION_RUNTIME_JS_FILE).exists())
            self.assertEqual(meta["site_design_brief_path"], SITE_DESIGN_BRIEF_FILE)
            self.assertEqual(meta["motion_runtime"]["css"], MOTION_RUNTIME_CSS_FILE)
            self.assertEqual(meta["motion_runtime"]["js"], MOTION_RUNTIME_JS_FILE)
            self.assertEqual(meta["experience_archetype"], "luxury_calm")
            self.assertEqual(meta["site_design_brief_source"], "generated")
            self.assertEqual(meta["generation_mode"], "single_page_mockup")
            mockup = result.mockup_path.read_text(encoding="utf-8")
            self.assertIn(f'href="{MOTION_RUNTIME_CSS_FILE}"', mockup)
            self.assertIn(f'src="{MOTION_RUNTIME_JS_FILE}"', mockup)

    def test_enhanced_generate_writes_foundation_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scraped_dir, generated_dir = self._setup_dirs(Path(tmp))
            gen = WebsiteGenerator(
                api_key="fake",
                model="claude-sonnet-4-5",
                generated_dir=generated_dir,
                scraped_dir=scraped_dir,
            )
            with patch.object(
                gen_mod,
                "_anthropic",
                SimpleNamespace(
                    Anthropic=FakeAnthropicClient,
                    AuthenticationError=Exception,
                ),
            ):
                result = gen.generate(
                    lead=_make_lead(),
                    inspiration=_make_profile(),
                    enhanced_design=True,
                    section_preferences=["hero", "services", "conversion"],
                    run_design_review=True,
                )

            meta = json.loads(result.meta_path.read_text(encoding="utf-8"))
            self.assertTrue(meta["enhanced_design"])
            self.assertEqual(meta["design_kit"], "healthcare-trust")
            self.assertIn("professional_authority_intro", meta["section_grammar_keys"])
            self.assertEqual(meta["marketing_brief_path"], "marketing_brief.json")
            self.assertEqual(meta["design_review_path"], "design_review.json")
            self.assertTrue((result.output_dir / "marketing_brief.json").exists())
            self.assertTrue((result.output_dir / "design_review.json").exists())
            prompt = (
                result.output_dir
                / "_debug"
                / "website_generation.prompt.txt"
            ).read_text(encoding="utf-8")
            self.assertIn("<marketing_brief>", prompt)
            self.assertIn("<design_kit>", prompt)
            self.assertIn("<section_grammar>", prompt)
            self.assertNotIn("https://github.com", prompt)

    def test_generate_uses_user_approved_design_brief(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scraped_dir, generated_dir = self._setup_dirs(Path(tmp))
            output_dir = generated_dir / "test-lead-01"
            profile = _make_profile("dentist")
            plan = build_site_generation_plan(_make_lead(), SAMPLE_SCRAPE, profile)
            brief = build_site_design_brief(_make_lead(), SAMPLE_SCRAPE, profile, plan)
            brief["experience_dna"]["archetype_key"] = "tech_launch"
            brief["experience_dna"]["archetype_label"] = "Tech Launch"
            brief["review_status"]["approved_by_user"] = True
            brief["review_status"]["saved_in_website_studio"] = True
            write_site_design_brief(brief, output_dir)
            gen = WebsiteGenerator(
                api_key="fake",
                model="claude-sonnet-4-5",
                generated_dir=generated_dir,
                scraped_dir=scraped_dir,
            )

            with patch.object(
                gen_mod,
                "_anthropic",
                SimpleNamespace(
                    Anthropic=FakeAnthropicClient,
                    AuthenticationError=Exception,
                ),
            ):
                result = gen.generate(lead=_make_lead(), inspiration=profile)

            meta = json.loads(result.meta_path.read_text(encoding="utf-8"))
            self.assertEqual(meta["site_design_brief_source"], "saved_user_approved")
            self.assertEqual(meta["experience_archetype"], "tech_launch")
            self.assertEqual(meta["experience_archetype_label"], "Tech Launch")

    def test_generate_writes_multi_page_plan_and_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scraped_dir, generated_dir = self._setup_dirs(Path(tmp))
            multi_scrape = dict(SAMPLE_SCRAPE)
            multi_scrape["site_blueprint"] = {
                "generator_fit": "multi_page_blueprint_needed",
                "multi_page_detected": True,
                "auth_detected": True,
                "recommended_pages": [
                    {"role": "home", "title": "Home", "reason": "Entry"},
                    {"role": "services", "title": "Backflow Certification", "reason": "Observed service page"},
                    {"role": "contact", "title": "Contact", "reason": "Contact flow"},
                ],
                "risk_flags": ["multi_page_site_detected"],
            }
            target = scraped_dir / "test-lead-01" / "scrape.json"
            target.write_text(json.dumps(multi_scrape), encoding="utf-8")
            gen = WebsiteGenerator(
                api_key="fake",
                model="claude-sonnet-4-5",
                generated_dir=generated_dir,
                scraped_dir=scraped_dir,
            )
            with patch.object(
                gen_mod,
                "_anthropic",
                SimpleNamespace(
                    Anthropic=FakeAnthropicClient,
                    AuthenticationError=Exception,
                ),
            ):
                result = gen.generate(lead=_make_lead(), inspiration=_make_profile())

            self.assertTrue(result.site_plan_path.exists())
            self.assertTrue(result.multi_page_export_dir.exists())
            self.assertTrue((result.multi_page_export_dir / "index.html").exists())
            self.assertTrue(
                (result.multi_page_export_dir / "backflow-certification.html").exists()
            )
            self.assertTrue(
                (result.multi_page_export_dir / MOTION_RUNTIME_CSS_FILE).exists()
            )
            self.assertTrue(
                (result.multi_page_export_dir / MOTION_RUNTIME_JS_FILE).exists()
            )
            service_page = (
                result.multi_page_export_dir / "backflow-certification.html"
            ).read_text(encoding="utf-8")
            self.assertIn("Cleanings", service_page)
            self.assertIn("(720) 555-0100", service_page)
            self.assertNotIn("Replace this planning copy", service_page)
            self.assertIn("data-summit-page", service_page)
            self.assertIn(f'href="{MOTION_RUNTIME_CSS_FILE}"', service_page)
            self.assertIn(f'src="{MOTION_RUNTIME_JS_FILE}"', service_page)
            export_manifest = json.loads(
                (result.multi_page_export_dir / "export_manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(export_manifest["version"], 3)
            self.assertEqual(export_manifest["kind"], "ai_multi_page_export")
            self.assertGreaterEqual(export_manifest["ai_generated_count"], 1)
            self.assertTrue(
                (result.multi_page_export_dir / "_debug_prompts" / "backflow-certification.prompt.txt").exists()
            )
            meta = json.loads(result.meta_path.read_text(encoding="utf-8"))
            self.assertEqual(meta["generation_mode"], "multi_page_plan")
            self.assertTrue(meta["multi_page_export_enabled"])
            self.assertGreaterEqual(meta["multi_page_ai_page_count"], 1)

    def test_multi_page_export_uses_mockup_as_canonical_design_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scraped_dir, generated_dir = self._setup_dirs(Path(tmp))
            multi_scrape = dict(SAMPLE_SCRAPE)
            multi_scrape["site_blueprint"] = {
                "generator_fit": "multi_page_blueprint_needed",
                "multi_page_detected": True,
                "recommended_pages": [
                    {"role": "home", "title": "Home", "reason": "Entry"},
                    {"role": "about", "title": "About", "reason": "Company proof"},
                    {"role": "services", "title": "Backflow Certification", "reason": "Observed service page"},
                    {"role": "contact", "title": "Contact", "reason": "Contact flow"},
                ],
            }
            target = scraped_dir / "test-lead-01" / "scrape.json"
            target.write_text(json.dumps(multi_scrape), encoding="utf-8")
            gen = WebsiteGenerator(
                api_key="fake",
                model="claude-sonnet-4-5",
                generated_dir=generated_dir,
                scraped_dir=scraped_dir,
            )
            with patch.object(
                gen_mod,
                "_anthropic",
                SimpleNamespace(
                    Anthropic=FakeCanonicalMockupClient,
                    AuthenticationError=Exception,
                ),
            ):
                result = gen.generate(lead=_make_lead(), inspiration=_make_profile())

            index_page = (result.multi_page_export_dir / "index.html").read_text(
                encoding="utf-8"
            )
            self.assertIn("Canonical Hero", index_page)
            self.assertIn("canonical-token", index_page)
            self.assertIn('href="about.html"', index_page)
            self.assertIn(">About</a>", index_page)
            self.assertIn('href="backflow-certification.html"', index_page)
            self.assertIn('href="contact.html"', index_page)
            self.assertNotIn('href="#work"', index_page)
            self.assertNotIn('href="#services"', index_page)
            self.assertNotIn('href="#showroom"', index_page)
            self.assertNotIn('href="#testimonials"', index_page)
            self.assertNotIn('href="#contact"', index_page)
            self.assertEqual(index_page.lower().count("<header"), 1)
            self.assertNotIn("AI Generated Page", index_page)

            service_page = (
                result.multi_page_export_dir / "backflow-certification.html"
            ).read_text(encoding="utf-8")
            self.assertIn("canonical-token", service_page)
            self.assertIn('class="canonical-body"', service_page)
            self.assertIn("canonical-header", service_page)
            self.assertIn("canonical-footer", service_page)
            self.assertIn("AI Generated Page", service_page)
            self.assertIn("Cleanings and (720) 555-0100", service_page)
            self.assertIn('data-summit-page="backflow-certification"', service_page)
            self.assertIn('href="about.html"', service_page)
            self.assertIn('href="backflow-certification.html"', service_page)
            self.assertIn('href="contact.html"', service_page)
            self.assertNotIn('href="#work"', service_page)
            self.assertNotIn('href="#services"', service_page)
            self.assertNotIn('href="#showroom"', service_page)
            self.assertNotIn('href="#testimonials"', service_page)
            self.assertNotIn('href="#contact"', service_page)
            self.assertEqual(service_page.lower().count("<header"), 1)
            self.assertNotIn("<title>AI Page</title>", service_page)

            export_manifest = json.loads(
                (result.multi_page_export_dir / "export_manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(export_manifest["design_source"], "mockup.html")
            self.assertTrue(export_manifest["canonical_homepage"])
            self.assertEqual(export_manifest["page_shell_source"], "mockup.html")
            home_statuses = [
                page for page in export_manifest["pages"]
                if page["filename"] == "index.html"
            ]
            self.assertEqual(home_statuses[0]["status"], "canonical_mockup")

    def test_multi_page_static_fallback_also_uses_mockup_design_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scraped_dir, generated_dir = self._setup_dirs(Path(tmp))
            multi_scrape = dict(SAMPLE_SCRAPE)
            multi_scrape["site_blueprint"] = {
                "generator_fit": "multi_page_blueprint_needed",
                "multi_page_detected": True,
                "recommended_pages": [
                    {"role": "home", "title": "Home", "reason": "Entry"},
                    {"role": "services", "title": "Backflow Certification", "reason": "Observed service page"},
                ],
            }
            target = scraped_dir / "test-lead-01" / "scrape.json"
            target.write_text(json.dumps(multi_scrape), encoding="utf-8")
            gen = WebsiteGenerator(
                api_key="fake",
                model="claude-sonnet-4-5",
                generated_dir=generated_dir,
                scraped_dir=scraped_dir,
            )
            with patch.object(
                gen_mod,
                "_anthropic",
                SimpleNamespace(
                    Anthropic=FakeCanonicalTruncatedExportClient,
                    AuthenticationError=Exception,
                ),
            ):
                result = gen.generate(lead=_make_lead(), inspiration=_make_profile())

            service_page = (
                result.multi_page_export_dir / "backflow-certification.html"
            ).read_text(encoding="utf-8")
            self.assertIn("canonical-token", service_page)
            self.assertIn('class="canonical-body"', service_page)
            self.assertIn("canonical-header", service_page)
            self.assertIn("canonical-footer", service_page)
            self.assertIn("Cleanings", service_page)
            self.assertIn('data-summit-section="service-focus"', service_page)
            self.assertIn('data-summit-section="page-cta"', service_page)
            self.assertNotIn("Public Site Summary", service_page)
            self.assertIn('data-summit-page="backflow-certification"', service_page)
            self.assertNotIn("This output truncates", service_page)
            export_manifest = json.loads(
                (result.multi_page_export_dir / "export_manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            service_statuses = [
                page for page in export_manifest["pages"]
                if page["filename"] == "backflow-certification.html"
            ]
            self.assertEqual(service_statuses[0]["status"], "static_fallback_error")
            self.assertEqual(export_manifest["design_source"], "mockup.html")

    def test_generate_requires_api_key(self) -> None:
        gen = WebsiteGenerator(api_key="   ", model="claude-sonnet-4-5")
        with self.assertRaises(WebsiteGeneratorError):
            gen.generate(lead=_make_lead(), scraped=SAMPLE_SCRAPE, inspiration=_make_profile())

    def test_generate_requires_lead_key(self) -> None:
        gen = WebsiteGenerator(api_key="fake", model="claude-sonnet-4-5")
        bad = _make_lead()
        bad["lead_key"] = ""
        with self.assertRaises(WebsiteGeneratorError):
            gen.generate(lead=bad, scraped=SAMPLE_SCRAPE, inspiration=_make_profile())

    def test_generate_rejects_non_html_response(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scraped_dir, generated_dir = self._setup_dirs(Path(tmp))
            gen = WebsiteGenerator(
                api_key="fake",
                model="claude-sonnet-4-5",
                generated_dir=generated_dir,
                scraped_dir=scraped_dir,
            )

            class EmptyClient(FakeAnthropicClient):
                def __init__(self, *args, **kwargs) -> None:
                    super().__init__(*args, **kwargs)
                    self._html_to_return = "sorry, nothing to generate"

            with patch.object(
                gen_mod,
                "_anthropic",
                SimpleNamespace(
                    Anthropic=EmptyClient,
                    AuthenticationError=Exception,
                ),
            ):
                with self.assertRaises(WebsiteGeneratorError):
                    gen.generate(lead=_make_lead(), inspiration=_make_profile())

    def test_generate_sanitizes_sdk_errors(self) -> None:
        """An SDK error containing an API key must not surface to the caller."""
        with tempfile.TemporaryDirectory() as tmp:
            scraped_dir, generated_dir = self._setup_dirs(Path(tmp))
            gen = WebsiteGenerator(
                api_key="fake",
                model="claude-sonnet-4-5",
                generated_dir=generated_dir,
                scraped_dir=scraped_dir,
            )

            class LeakyClient(FakeAnthropicClient):
                def _stream(self, **kwargs):  # noqa: ARG002
                    raise RuntimeError(
                        "bad call with sk-ant-api03-ABCDEFGHIJ12345 inside"
                    )

            with patch.object(
                gen_mod,
                "_anthropic",
                SimpleNamespace(
                    Anthropic=LeakyClient,
                    AuthenticationError=Exception,
                ),
            ):
                with self.assertRaises(WebsiteGeneratorError) as ctx:
                    gen.generate(lead=_make_lead(), inspiration=_make_profile())
            self.assertNotIn("sk-ant-api03-ABCDEFGHIJ12345", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
