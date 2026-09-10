"""Endpoint tests for GET /api/ai/website-package/{lead_key}{,/mockup}.

Verifies the Phase 6 UI data-feed endpoints: status aggregation and
sandboxed mockup preview. Scrape and generate side-effects are NOT
exercised here (covered by test_scrape_endpoint.py and the generator
unit tests); these tests focus on file-read paths, path traversal
defense, and cache headers.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "lead-vault"))
os.environ.setdefault("LEAD_VAULT_DB", str(ROOT / "_test_lead_vault.sqlite3"))

from fastapi.testclient import TestClient

from app.routers import ai as ai_router


def _make_app():
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(ai_router.router)
    return app


class _FakeStore:
    def __init__(self, lead: dict | None):
        self._lead = lead

    def get_lead(self, lead_key: str):  # noqa: ARG002
        return self._lead

    def list_leads(self):
        return [self._lead] if self._lead else []


class WebsitePackageProviderResolverTests(unittest.TestCase):
    def test_gpt_model_routes_to_openai_even_with_anthropic_default(self):
        provider, model = ai_router._resolve_provider_model(
            {"ai_model": "gpt-5.5"},
            {"ai_provider": "Anthropic", "ai_model": "claude-sonnet-4-6"},
        )
        self.assertEqual(provider, "OpenAI")
        self.assertEqual(model, "gpt-5.5")

    def test_claude_model_routes_to_anthropic_even_with_openai_default(self):
        provider, model = ai_router._resolve_provider_model(
            {"ai_model": "claude-sonnet-4-6"},
            {"ai_provider": "OpenAI", "ai_model": "gpt-5.4"},
        )
        self.assertEqual(provider, "Anthropic")
        self.assertEqual(model, "claude-sonnet-4-6")

    def test_missing_model_defaults_to_openai_for_website_generation(self):
        provider, model = ai_router._resolve_provider_model({}, {})
        self.assertEqual(provider, "OpenAI")
        self.assertEqual(model, "gpt-5.4")


class WebsitePackageStatusTests(unittest.TestCase):
    def setUp(self):
        # Isolated generated/ and scraped/ roots for every test.
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.gen_root = Path(self._tmp.name) / "generated"
        self.scr_root = Path(self._tmp.name) / "scraped"
        self.gen_root.mkdir()
        self.scr_root.mkdir()

        import lead_vault_website_generator as gen_mod
        self._gen_patch = patch.object(
            gen_mod, "DEFAULT_GENERATED_DIR", self.gen_root
        )
        self._scr_patch = patch.object(
            gen_mod, "DEFAULT_SCRAPED_DIR", self.scr_root
        )
        self._gen_patch.start()
        self._scr_patch.start()
        self.addCleanup(self._gen_patch.stop)
        self.addCleanup(self._scr_patch.stop)

    def _client(self, lead):
        app = _make_app()
        patcher = patch.object(ai_router, "get_store", lambda: _FakeStore(lead))
        patcher.start()
        self.addCleanup(patcher.stop)
        return TestClient(app)

    def _write_scrape(self, safe_key: str, **overrides):
        payload = {
            "source_url": "https://example.com/",
            "final_url": "https://example.com/",
            "status_code": 200,
            "business_name": "Example Biz",
            "title": "Example",
            "photos": ["https://example.com/a.jpg"],
            "services": ["One", "Two"],
            "phones": ["555"],
            "emails": ["hello@example.com"],
            "headings": ["Welcome", "Services"],
            "tech_hints": ["WordPress"],
            "colors": ["#ffffff"],
            "fonts": ["Inter"],
            "social_links": {"facebook": "https://facebook.com/example"},
            "crawled_pages": [
                {
                    "url": "https://example.com/contact",
                    "status_code": 200,
                    "title": "Contact",
                    "text_chars": 123,
                }
            ],
            "main_text": "hello world",
        }
        payload.update(overrides)
        d = self.scr_root / safe_key
        d.mkdir(parents=True, exist_ok=True)
        (d / "scrape.json").write_text(json.dumps(payload), encoding="utf-8")

    def _write_generated(self, safe_key: str, html: str = "<!DOCTYPE html><html><body>hi</body></html>"):
        d = self.gen_root / safe_key
        d.mkdir(parents=True, exist_ok=True)
        (d / "mockup.html").write_text(html, encoding="utf-8")
        (d / "meta.json").write_text(
            json.dumps({
                "lead_key": "x",
                "business_name": "Example Biz",
                "model": "claude-sonnet-4-6",
                "category": "generic",
                "matched_from": "Generic",
                "fallback_category": False,
            }),
            encoding="utf-8",
        )
        (d / "validation.json").write_text(
            json.dumps({
                "passed": True,
                "error_count": 0,
                "warning_count": 1,
                "tool_runs": {"htmlhint": "ok", "structure": "ok", "a11y": "ok"},
                "issues": [
                    {"severity": "warning", "source": "security",
                     "rule": "external_script_no_sri",
                     "message": "Tailwind CDN has no SRI", "line": 0}
                ],
            }),
            encoding="utf-8",
        )

    def test_requires_known_lead(self):
        client = self._client(lead=None)
        r = client.get("/api/ai/website-package/unknown")
        self.assertEqual(r.status_code, 404)
        self.assertFalse(r.json()["ok"])

    def test_empty_state(self):
        lead = {"lead_key": "x", "data": {}}
        client = self._client(lead=lead)
        r = client.get("/api/ai/website-package/x")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["ok"])
        self.assertFalse(body["scraped"])
        self.assertFalse(body["generated"])
        self.assertIsNone(body["scrape"])
        self.assertIsNone(body["generated_info"])
        self.assertIsNone(body["validation"])

    def test_scrape_only(self):
        self._write_scrape("x")
        client = self._client(lead={"lead_key": "x", "data": {}})
        r = client.get("/api/ai/website-package/x")
        body = r.json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["scraped"])
        self.assertFalse(body["generated"])
        self.assertEqual(body["scrape"]["business_name"], "Example Biz")
        self.assertEqual(body["scrape"]["counts"]["services"], 2)
        self.assertEqual(body["scrape"]["counts"]["photos"], 1)
        self.assertEqual(body["scrape"]["services"], ["One", "Two"])
        self.assertEqual(body["scrape"]["emails"], ["hello@example.com"])
        self.assertEqual(body["scrape"]["tech_hints"], ["WordPress"])
        self.assertEqual(
            body["scrape"]["social_links"]["facebook"],
            "https://facebook.com/example",
        )
        self.assertEqual(body["scrape"]["crawled_pages"][0]["title"], "Contact")
        self.assertEqual(body["scrape"]["counts"]["crawled_pages"], 1)
        self.assertIn("main_text", body["scrape"]["missing_fields"])

    def test_scrape_and_generated(self):
        self._write_scrape("x")
        self._write_generated("x")
        client = self._client(lead={"lead_key": "x", "data": {}})
        r = client.get("/api/ai/website-package/x")
        body = r.json()
        self.assertTrue(body["scraped"])
        self.assertTrue(body["generated"])
        self.assertEqual(body["generated_info"]["meta"]["category"], "generic")
        self.assertTrue(body["validation"]["passed"])
        self.assertEqual(body["validation"]["warning_count"], 1)

    def test_orphaned_generated_package_still_lists_and_loads(self):
        self._write_generated("orphan")
        client = self._client(lead=None)

        listed = client.get("/api/ai/website-packages")
        self.assertEqual(listed.status_code, 200)
        packages = listed.json()["packages"]
        self.assertEqual(len(packages), 1)
        self.assertEqual(packages[0]["safe_key"], "orphan")
        self.assertTrue(packages[0]["orphaned_package"])
        self.assertFalse(packages[0]["lead_exists"])

        status = client.get("/api/ai/website-package/orphan")
        self.assertEqual(status.status_code, 200)
        body = status.json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["generated"])
        self.assertTrue(body["orphaned_package"])
        self.assertFalse(body["lead_exists"])

    def test_delete_generated_package_removes_files_without_deleting_lead(self):
        self._write_generated("x")
        export_dir = self.gen_root / "x" / "multi_page_export"
        export_dir.mkdir()
        (export_dir / "index.html").write_text("<html></html>", encoding="utf-8")
        client = self._client(lead={"lead_key": "x", "data": {}})

        r = client.delete("/api/ai/website-package/x")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["ok"], body)
        self.assertTrue(body["deleted"])
        self.assertFalse((self.gen_root / "x").exists())

        status = client.get("/api/ai/website-package/x")
        self.assertEqual(status.status_code, 200)
        status_body = status.json()
        self.assertTrue(status_body["ok"])
        self.assertTrue(status_body["lead_exists"])
        self.assertFalse(status_body["generated"])

    def test_delete_orphaned_generated_package(self):
        self._write_generated("orphan")
        client = self._client(lead=None)

        r = client.delete("/api/ai/website-package/orphan")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["ok"], body)
        self.assertEqual(body["safe_key"], "orphan")
        self.assertFalse((self.gen_root / "orphan").exists())

        missing = client.get("/api/ai/website-package/orphan")
        self.assertEqual(missing.status_code, 404)

    def test_delete_missing_generated_package_returns_404(self):
        client = self._client(lead={"lead_key": "x", "data": {}})
        r = client.delete("/api/ai/website-package/x")
        self.assertEqual(r.status_code, 404)
        self.assertFalse(r.json()["ok"])

    def test_enhanced_artifact_read_endpoints_and_status(self):
        self._write_generated("x")
        out = self.gen_root / "x"
        (out / "marketing_brief.json").write_text(
            json.dumps({
                "version": 1,
                "lead_key": "x",
                "business_name": "Example Biz",
                "primary_conversion_goal": "qualified contact requests",
            }),
            encoding="utf-8",
        )
        (out / "design_review.json").write_text(
            json.dumps({
                "version": 1,
                "passed": True,
                "score": 92,
                "summary": "Design review passed.",
                "issues": [],
            }),
            encoding="utf-8",
        )
        client = self._client(lead={"lead_key": "x", "data": {}})

        status = client.get("/api/ai/website-package/x").json()
        self.assertEqual(status["marketing_brief"]["business_name"], "Example Biz")
        self.assertTrue(status["design_review"]["passed"])

        brief = client.get("/api/ai/website-package/x/marketing-brief")
        self.assertEqual(brief.status_code, 200)
        self.assertTrue(brief.json()["ok"])
        self.assertEqual(brief.json()["brief"]["lead_key"], "x")

        review = client.get("/api/ai/website-package/x/design-review")
        self.assertEqual(review.status_code, 200)
        self.assertEqual(review.json()["review"]["score"], 92)

    def test_missing_enhanced_artifact_read_endpoints_404(self):
        self._write_generated("x")
        client = self._client(lead={"lead_key": "x", "data": {}})
        self.assertEqual(
            client.get("/api/ai/website-package/x/marketing-brief").status_code,
            404,
        )
        self.assertEqual(
            client.get("/api/ai/website-package/x/design-review").status_code,
            404,
        )

    def test_design_catalog_endpoints(self):
        client = self._client(lead={"lead_key": "x", "data": {}})
        kits = client.get("/api/ai/design-kits")
        self.assertEqual(kits.status_code, 200)
        self.assertTrue(kits.json()["ok"])
        self.assertIn("local-service", {kit["key"] for kit in kits.json()["kits"]})

        grammar = client.get("/api/ai/section-grammar")
        self.assertEqual(grammar.status_code, 200)
        self.assertTrue(grammar.json()["ok"])
        self.assertIn(
            "hero",
            {section["section_type"] for section in grammar.json()["sections"]},
        )

    def test_preview_qa_endpoint_runs_and_status_includes_report(self):
        self._write_generated("x")

        import lead_vault_preview_qa as qa_mod

        def fake_run_preview_qa(mockup_path, output_dir):
            self.assertEqual(Path(mockup_path), self.gen_root / "x" / "mockup.html")
            report = {
                "ok": True,
                "passed": True,
                "status": "completed",
                "version": 1,
                "created_at": "2026-04-27T10:00:00+00:00",
                "html_path": str(mockup_path),
                "tool_runs": {"playwright": "ok"},
                "viewports": [
                    {
                        "name": "desktop",
                        "width": 1440,
                        "height": 1000,
                        "screenshot": "preview_qa/desktop.png",
                        "metrics": {"horizontal_overflow_px": 0},
                        "issue_count": 0,
                    }
                ],
                "issues": [],
            }
            qa_dir = Path(output_dir) / "preview_qa"
            qa_dir.mkdir(parents=True, exist_ok=True)
            (qa_dir / "preview_qa.json").write_text(
                json.dumps(report),
                encoding="utf-8",
            )
            return report

        patcher = patch.object(qa_mod, "run_preview_qa", fake_run_preview_qa)
        patcher.start()
        self.addCleanup(patcher.stop)

        client = self._client(lead={"lead_key": "x", "data": {}})
        r = client.post("/api/ai/website-package/x/preview-qa")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["passed"])
        self.assertEqual(body["tool_runs"]["playwright"], "ok")

        status = client.get("/api/ai/website-package/x").json()
        self.assertEqual(status["preview_qa"]["status"], "completed")
        self.assertEqual(status["preview_qa"]["viewports"][0]["name"], "desktop")

    def test_generated_status_includes_edit_manifest(self):
        html = (
            '<!DOCTYPE html><html><body>'
            '<section data-summit-section="hero" data-summit-label="Hero">'
            '<h1>Hero title</h1></section>'
            '</body></html>'
        )
        self._write_generated("x", html=html)
        client = self._client(lead={"lead_key": "x", "data": {}})
        r = client.get("/api/ai/website-package/x")
        body = r.json()
        self.assertTrue(body["generated"])
        sections = body["edit_manifest"]["sections"]
        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0]["id"], "hero")
        self.assertEqual(sections[0]["label"], "Hero")

    def test_design_brief_preview_and_save_round_trip(self):
        self._write_scrape("x")
        lead = {"lead_key": "x", "data": {"Business Type": "Dentist"}}
        client = self._client(lead=lead)

        preview = client.get("/api/ai/website-package/x/design-brief")
        self.assertEqual(preview.status_code, 200)
        preview_body = preview.json()
        self.assertTrue(preview_body["ok"])
        self.assertFalse(preview_body["saved"])
        self.assertEqual(preview_body["source"], "preview_from_scrape")
        self.assertIn("site_dna", preview_body["brief"])
        self.assertIn("experience_dna", preview_body["brief"])

        brief = preview_body["brief"]
        brief["creative_variation"]["hero_system"] = "editorial proof wall"
        saved = client.post(
            "/api/ai/website-package/x/design-brief",
            json={"brief": brief},
        )
        self.assertEqual(saved.status_code, 200)
        saved_body = saved.json()
        self.assertTrue(saved_body["ok"])
        self.assertTrue(saved_body["saved"])
        self.assertEqual(saved_body["source"], "saved_user_approved")
        self.assertTrue(saved_body["brief"]["review_status"]["approved_by_user"])
        self.assertEqual(
            saved_body["brief"]["creative_variation"]["hero_system"],
            "editorial proof wall",
        )
        self.assertTrue((self.gen_root / "x" / "site_design_brief.json").exists())

        loaded = client.get("/api/ai/website-package/x/design-brief").json()
        self.assertTrue(loaded["saved"])
        self.assertEqual(loaded["source"], "saved_user_approved")
        self.assertEqual(
            loaded["brief"]["creative_variation"]["hero_system"],
            "editorial proof wall",
        )

        status = client.get("/api/ai/website-package/x").json()
        self.assertTrue(status["design_brief"]["approved_by_user"])
        self.assertEqual(status["design_brief"]["source"], "saved_user_approved")

    def test_design_brief_save_rejects_bad_shape(self):
        client = self._client(lead={"lead_key": "x", "data": {}})
        r = client.post(
            "/api/ai/website-package/x/design-brief",
            json={"brief": {"site_dna": {}}},
        )
        self.assertEqual(r.status_code, 400)
        self.assertFalse(r.json()["ok"])

    def test_safe_key_normalization(self):
        # Lead key contains punctuation; files live under the safe-key dir.
        self._write_scrape("weird_key_")
        client = self._client(lead={"lead_key": "weird/key:", "data": {}})
        r = client.get("/api/ai/website-package/weird/key:")
        # Slash makes this not match the route (FastAPI treats as nested
        # segment). Use encoded form instead.
        self.assertIn(r.status_code, (404, 405))

    def test_handles_unreadable_scrape_json(self):
        d = self.scr_root / "x"
        d.mkdir()
        (d / "scrape.json").write_text("not json", encoding="utf-8")
        client = self._client(lead={"lead_key": "x", "data": {}})
        r = client.get("/api/ai/website-package/x")
        body = r.json()
        # scrape.json exists -> scraped=True, but parsing returned None
        # so the summary defaults populate without crashing.
        self.assertTrue(body["ok"])
        self.assertTrue(body["scraped"])
        self.assertEqual(body["scrape"]["counts"]["services"], 0)


class WebsitePackageGenerateTests(unittest.TestCase):
    def setUp(self):
        ai_router._generation_cancel_events.clear()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.gen_root = Path(self._tmp.name) / "generated"
        self.gen_root.mkdir()

        import lead_vault_website_generator as gen_mod

        patcher = patch.object(gen_mod, "DEFAULT_GENERATED_DIR", self.gen_root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _client(self, lead):
        app = _make_app()
        patcher = patch.object(ai_router, "get_store", lambda: _FakeStore(lead))
        patcher.start()
        self.addCleanup(patcher.stop)
        settings_patch = patch.object(
            ai_router,
            "load_settings",
            lambda: {"openai_api_key": "test-key", "ai_provider": "OpenAI"},
        )
        settings_patch.start()
        self.addCleanup(settings_patch.stop)
        return TestClient(app)

    def test_generate_uses_default_multi_page_ai_export_count(self):
        import lead_vault_website_generator as gen_mod
        import lead_vault_website_validator as validator_mod

        captured = {}

        class FakeGenerator:
            def __init__(self, **kwargs):
                captured.update(kwargs)

            def generate(self, lead):
                out = self_gen_root / "x"
                out.mkdir(parents=True, exist_ok=True)
                mockup = out / "mockup.html"
                mockup.write_text(
                    "<!DOCTYPE html><html><body>hi</body></html>",
                    encoding="utf-8",
                )
                meta = out / "meta.json"
                meta.write_text("{}", encoding="utf-8")
                return type(
                    "Generated",
                    (),
                    {
                        "lead_key": lead["lead_key"],
                        "model": "gpt-5.4",
                        "category": "generic",
                        "output_dir": out,
                        "mockup_path": mockup,
                        "meta_path": meta,
                        "site_plan_path": None,
                        "site_design_brief_path": None,
                        "multi_page_export_dir": out / "multi_page_export",
                    },
                )()

        self_gen_root = self.gen_root
        gen_patch = patch.object(gen_mod, "WebsiteGenerator", FakeGenerator)
        val_patch = patch.object(
            validator_mod,
            "validate_html",
            lambda path: type(
                "Report",
                (),
                {"passed": True, "error_count": 0, "to_dict": lambda self: {"passed": True}},
            )(),
        )
        save_patch = patch.object(validator_mod, "save_report", lambda report, output_dir: None)
        gen_patch.start()
        val_patch.start()
        save_patch.start()
        self.addCleanup(gen_patch.stop)
        self.addCleanup(val_patch.stop)
        self.addCleanup(save_patch.stop)

        client = self._client(lead={"lead_key": "x", "data": {}})
        response = client.post("/api/ai/generate-website-package", json={"lead_key": "x"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertIsNotNone(captured.get("cancellation_event"))
        self.assertEqual(
            captured["multi_page_ai_pages"],
            gen_mod.MAX_MULTI_PAGE_AI_PAGES,
        )

    def test_cancel_generation_without_running_returns_clear_error(self):
        client = self._client(lead={"lead_key": "x", "data": {}})
        response = client.post(
            "/api/ai/cancel-website-generation",
            json={"lead_key": "x"},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["ok"])
        self.assertIn("No website generation", body["error"])

    def test_cancel_generation_endpoint_sets_active_event(self):
        event = ai_router._begin_generation_cancel_event("x")
        self.addCleanup(lambda: ai_router._finish_generation_cancel_event("x", event))
        client = self._client(lead={"lead_key": "x", "data": {}})

        response = client.post(
            "/api/ai/cancel-website-generation",
            json={"lead_key": "x"},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"], body)
        self.assertTrue(body["cancellation_requested"])
        self.assertTrue(event.is_set())

    def test_generate_returns_cancelled_when_generator_stops(self):
        import lead_vault_website_generator as gen_mod

        captured = {}
        test_case = self

        class FakeGenerator:
            def __init__(self, **kwargs):
                captured.update(kwargs)

            def generate(self, lead):  # noqa: ARG002
                event = captured.get("cancellation_event")
                test_case.assertIsNotNone(event)
                event.set()
                raise gen_mod.WebsiteGenerationCancelled("Website generation cancelled.")

        gen_patch = patch.object(gen_mod, "WebsiteGenerator", FakeGenerator)
        gen_patch.start()
        self.addCleanup(gen_patch.stop)

        client = self._client(lead={"lead_key": "x", "data": {}})
        response = client.post(
            "/api/ai/generate-website-package",
            json={"lead_key": "x"},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["ok"])
        self.assertTrue(body["cancelled"])
        self.assertIsNone(ai_router._get_generation_cancel_event("x"))

    def test_generate_passes_enhanced_design_options_and_returns_artifacts(self):
        import lead_vault_website_generator as gen_mod
        import lead_vault_website_validator as validator_mod

        captured = {}

        class FakeGenerator:
            def __init__(self, **kwargs):
                captured["init"] = kwargs

            def generate(self, lead, **kwargs):
                captured["generate"] = kwargs
                out = self_gen_root / "x"
                out.mkdir(parents=True, exist_ok=True)
                mockup = out / "mockup.html"
                mockup.write_text(
                    "<!DOCTYPE html><html><body>hi</body></html>",
                    encoding="utf-8",
                )
                meta = out / "meta.json"
                meta.write_text(
                    json.dumps({
                        "enhanced_design": True,
                        "design_kit": "local-service",
                        "section_grammar_keys": ["local_service_call_first"],
                        "marketing_brief_path": "marketing_brief.json",
                        "design_review_path": "design_review.json",
                        "design_review_summary": {"passed": True, "score": 90},
                    }),
                    encoding="utf-8",
                )
                return type(
                    "Generated",
                    (),
                    {
                        "lead_key": lead["lead_key"],
                        "model": "gpt-5.4",
                        "category": "generic",
                        "output_dir": out,
                        "mockup_path": mockup,
                        "meta_path": meta,
                        "site_plan_path": None,
                        "site_design_brief_path": None,
                        "multi_page_export_dir": out / "multi_page_export",
                    },
                )()

        self_gen_root = self.gen_root
        gen_patch = patch.object(gen_mod, "WebsiteGenerator", FakeGenerator)
        val_patch = patch.object(
            validator_mod,
            "validate_html",
            lambda path: type(
                "Report",
                (),
                {"passed": True, "error_count": 0, "to_dict": lambda self: {"passed": True}},
            )(),
        )
        save_patch = patch.object(validator_mod, "save_report", lambda report, output_dir: None)
        gen_patch.start()
        val_patch.start()
        save_patch.start()
        self.addCleanup(gen_patch.stop)
        self.addCleanup(val_patch.stop)
        self.addCleanup(save_patch.stop)

        client = self._client(lead={"lead_key": "x", "data": {}})
        response = client.post(
            "/api/ai/generate-website-package",
            json={
                "lead_key": "x",
                "enhanced_design": True,
                "design_kit": "auto",
                "section_preferences": ["hero", "conversion"],
                "blocked_sections": ["pricing"],
                "run_design_review": True,
            },
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["enhanced_design"])
        self.assertEqual(body["design_kit"], "local-service")
        self.assertEqual(body["marketing_brief_path"], "marketing_brief.json")
        self.assertEqual(captured["generate"]["section_preferences"], ["hero", "conversion"])
        self.assertEqual(captured["generate"]["blocked_sections"], ["pricing"])
        self.assertTrue(captured["generate"]["run_design_review"])


class WebsitePackageMockupTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.gen_root = Path(self._tmp.name) / "generated"
        self.gen_root.mkdir()

        import lead_vault_website_generator as gen_mod
        patcher = patch.object(gen_mod, "DEFAULT_GENERATED_DIR", self.gen_root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _client(self, lead):
        app = _make_app()
        patcher = patch.object(ai_router, "get_store", lambda: _FakeStore(lead))
        patcher.start()
        self.addCleanup(patcher.stop)
        return TestClient(app)

    def test_404_when_no_mockup(self):
        client = self._client(lead={"lead_key": "x", "data": {}})
        r = client.get("/api/ai/website-package/x/mockup")
        self.assertEqual(r.status_code, 404)

    def test_serves_mockup_with_hardened_headers(self):
        d = self.gen_root / "x"
        d.mkdir()
        (d / "mockup.html").write_text(
            "<!DOCTYPE html><html><body>hi</body></html>",
            encoding="utf-8",
        )
        client = self._client(lead={"lead_key": "x", "data": {}})
        r = client.get("/api/ai/website-package/x/mockup")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/html", r.headers.get("content-type", ""))
        self.assertEqual(r.headers.get("cache-control"), "no-store, max-age=0")
        self.assertEqual(r.headers.get("x-content-type-options"), "nosniff")
        self.assertEqual(r.headers.get("referrer-policy"), "no-referrer")
        self.assertIn("sandbox allow-scripts", r.headers.get("content-security-policy", ""))
        self.assertNotIn("allow-same-origin", r.headers.get("content-security-policy", ""))
        self.assertIn("hi", r.text)

    def test_serves_mockup_with_section_highlight(self):
        d = self.gen_root / "x"
        d.mkdir()
        (d / "mockup.html").write_text(
            '<!DOCTYPE html><html><head></head><body>'
            '<section data-summit-section="hero" data-summit-label="Hero">hi</section>'
            '</body></html>',
            encoding="utf-8",
        )
        client = self._client(lead={"lead_key": "x", "data": {}})
        r = client.get("/api/ai/website-package/x/mockup?highlight=hero")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/html", r.headers.get("content-type", ""))
        self.assertEqual(r.headers.get("cache-control"), "no-store, max-age=0")
        self.assertIn("summit-preview-highlight-style", r.text)
        self.assertIn("sandbox allow-scripts", r.headers.get("content-security-policy", ""))
        self.assertIn("summit-edit-highlight", r.text)
        self.assertIn('"hero"', r.text)

    def test_invalid_section_highlight_is_ignored(self):
        d = self.gen_root / "x"
        d.mkdir()
        (d / "mockup.html").write_text(
            "<!DOCTYPE html><html><body>hi</body></html>",
            encoding="utf-8",
        )
        client = self._client(lead={"lead_key": "x", "data": {}})
        r = client.get("/api/ai/website-package/x/mockup?highlight=../hero")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("summit-preview-highlight-style", r.text)

    def test_unknown_lead_404(self):
        client = self._client(lead=None)
        r = client.get("/api/ai/website-package/x/mockup")
        self.assertEqual(r.status_code, 404)

    def test_serves_orphaned_mockup_when_lead_row_is_missing(self):
        d = self.gen_root / "orphan"
        d.mkdir()
        (d / "mockup.html").write_text(
            "<!DOCTYPE html><html><body>saved site</body></html>",
            encoding="utf-8",
        )
        client = self._client(lead=None)
        r = client.get("/api/ai/website-package/orphan/mockup")
        self.assertEqual(r.status_code, 200)
        self.assertIn("saved site", r.text)

    def test_path_traversal_attempt_does_not_escape(self):
        """A lead_key with traversal metacharacters must not leave the tree.

        ``_safe_lead_key`` collapses `..` and `/` to `_`, so the resolved
        path stays inside generated/. Combined with the lead-existence
        check this is defense-in-depth; either layer alone stops the
        attack.
        """
        # Even with a matching store, the sanitized key maps to "_"
        # which has no file in our tmp tree -> 404.
        client = self._client(lead={"lead_key": "../../etc/passwd", "data": {}})
        r = client.get("/api/ai/website-package/..%2F..%2Fetc%2Fpasswd/mockup")
        # FastAPI decodes the path param; the safe_key logic collapses
        # it so no real file is reachable.
        self.assertIn(r.status_code, (404, 400))


class WebsitePackageGeneratedFileTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.gen_root = Path(self._tmp.name) / "generated"
        self.gen_root.mkdir()

        import lead_vault_website_generator as gen_mod
        patcher = patch.object(gen_mod, "DEFAULT_GENERATED_DIR", self.gen_root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _client(self, lead):
        app = _make_app()
        patcher = patch.object(ai_router, "get_store", lambda: _FakeStore(lead))
        patcher.start()
        self.addCleanup(patcher.stop)
        return TestClient(app)

    def test_serves_secondary_generated_html_file(self):
        d = self.gen_root / "x"
        d.mkdir()
        (d / "transition-playbook.html").write_text(
            "<!DOCTYPE html><html><body>second page</body></html>",
            encoding="utf-8",
        )
        client = self._client(lead={"lead_key": "x", "data": {}})
        r = client.get("/api/ai/website-package/x/files/transition-playbook.html")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/html", r.headers.get("content-type", ""))
        self.assertEqual(r.headers.get("cache-control"), "no-store, max-age=0")
        self.assertIn("second page", r.text)
        self.assertIn("sandbox allow-scripts", r.headers.get("content-security-policy", ""))

    def test_serves_orphaned_generated_file_when_lead_row_is_missing(self):
        d = self.gen_root / "orphan"
        d.mkdir()
        (d / "index.html").write_text(
            "<!DOCTYPE html><html><body>orphan secondary page</body></html>",
            encoding="utf-8",
        )
        client = self._client(lead=None)
        r = client.get("/api/ai/website-package/orphan/files/index.html")
        self.assertEqual(r.status_code, 200)
        self.assertIn("orphan secondary page", r.text)

    def test_missing_generated_file_returns_404(self):
        client = self._client(lead={"lead_key": "x", "data": {}})
        r = client.get("/api/ai/website-package/x/files/transition-playbook.html")
        self.assertEqual(r.status_code, 404)

    def test_rejects_unsupported_extension(self):
        d = self.gen_root / "x"
        d.mkdir()
        (d / "meta.json").write_text("{}", encoding="utf-8")
        client = self._client(lead={"lead_key": "x", "data": {}})
        r = client.get("/api/ai/website-package/x/files/meta.json")
        self.assertEqual(r.status_code, 404)

    def test_path_traversal_attempt_does_not_escape(self):
        client = self._client(lead={"lead_key": "x", "data": {}})
        r = client.get("/api/ai/website-package/x/files/..%2F..%2Fsecret.html")
        self.assertIn(r.status_code, (400, 404))


class WebsitePackageSectionEditTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.gen_root = Path(self._tmp.name) / "generated"
        self.scr_root = Path(self._tmp.name) / "scraped"
        self.gen_root.mkdir()
        self.scr_root.mkdir()

        import lead_vault_website_generator as gen_mod
        self.gen_mod = gen_mod
        gen_patch = patch.object(gen_mod, "DEFAULT_GENERATED_DIR", self.gen_root)
        scr_patch = patch.object(gen_mod, "DEFAULT_SCRAPED_DIR", self.scr_root)
        gen_patch.start()
        scr_patch.start()
        self.addCleanup(gen_patch.stop)
        self.addCleanup(scr_patch.stop)

    def _client(self, lead):
        app = _make_app()
        patcher = patch.object(ai_router, "get_store", lambda: _FakeStore(lead))
        patcher.start()
        self.addCleanup(patcher.stop)
        return TestClient(app)

    def _write_generated(self, safe_key: str):
        d = self.gen_root / safe_key
        d.mkdir(parents=True, exist_ok=True)
        html = (
            '<!DOCTYPE html><html lang="en"><head>'
            '<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>Example</title><meta name="description" content="Example">'
            '</head><body>'
            '<section data-summit-section="hero" data-summit-label="Hero"><h1>Old hero</h1></section>'
            '<section data-summit-section="contact" data-summit-label="Contact"><p>Call us</p></section>'
            '</body></html>'
        )
        (d / "mockup.html").write_text(html, encoding="utf-8")
        (d / "meta.json").write_text(
            json.dumps({"category": "generic", "model": "claude-sonnet-4-6"}),
            encoding="utf-8",
        )

    def test_ai_section_edit_replaces_only_target_section_and_backs_up(self):
        self._write_generated("x")
        gen_mod = self.gen_mod
        calls = []

        class FakeEditor:
            def __init__(self, api_key, model):  # noqa: ARG002
                self.model = model

            def edit_section(self, **kwargs):
                calls.append(kwargs)
                return gen_mod.SectionEditResult(
                    section_id=kwargs["section_id"],
                    replacement_html=(
                        '<section data-summit-section="hero" data-summit-label="Hero">'
                        '<h1>Edited hero</h1></section>'
                    ),
                    model=self.model,
                )

        patcher = patch.object(self.gen_mod, "WebsiteSectionEditor", FakeEditor)
        patcher.start()
        self.addCleanup(patcher.stop)

        client = self._client(lead={
            "lead_key": "x",
            "business_name": "Example Biz",
            "city_area": "Denver, CO",
            "data": {},
        })
        r = client.post("/api/ai/edit-website-section", json={
            "lead_key": "x",
            "section_id": "hero",
            "instruction": "Make it clearer.",
            "color_mode": "darker",
            "ai_provider": "Anthropic",
            "ai_api_key": "test-key",
            "ai_model": "claude-test",
        })
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["ok"], body)
        mockup = (self.gen_root / "x" / "mockup.html").read_text(encoding="utf-8")
        self.assertIn("Edited hero", mockup)
        self.assertIn("Call us", mockup)
        self.assertNotIn("Old hero", mockup)
        backups = list((self.gen_root / "x" / "versions").glob("mockup_v*.html"))
        self.assertEqual(len(backups), 1)
        self.assertIn("Old hero", backups[0].read_text(encoding="utf-8"))
        self.assertEqual(body["edit_manifest"]["sections"][0]["id"], "hero")
        self.assertEqual(calls[0]["color_mode"], "darker")

    def test_ai_section_edit_can_target_exported_page(self):
        self._write_generated("x")
        export_dir = self.gen_root / "x" / "multi_page_export"
        export_dir.mkdir()
        export_page = export_dir / "services.html"
        export_page.write_text(
            '<!DOCTYPE html><html lang="en"><head>'
            '<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>Services</title><meta name="description" content="Services">'
            '</head><body>'
            '<section data-summit-section="services" data-summit-label="Services"><h1>Old services</h1></section>'
            '</body></html>',
            encoding="utf-8",
        )
        gen_mod = self.gen_mod

        class FakeEditor:
            def __init__(self, api_key, model):  # noqa: ARG002
                self.model = model

            def edit_section(self, **kwargs):
                return gen_mod.SectionEditResult(
                    section_id=kwargs["section_id"],
                    replacement_html=(
                        '<section data-summit-section="services" data-summit-label="Services">'
                        '<h1>Edited services</h1></section>'
                    ),
                    model=self.model,
                )

        patcher = patch.object(self.gen_mod, "WebsiteSectionEditor", FakeEditor)
        patcher.start()
        self.addCleanup(patcher.stop)

        client = self._client(lead={"lead_key": "x", "data": {}})
        r = client.post("/api/ai/edit-website-section", json={
            "lead_key": "x",
            "section_id": "services",
            "instruction": "Tighten services.",
            "target_path": "multi_page_export/services.html",
            "ai_provider": "Anthropic",
            "ai_api_key": "test-key",
            "ai_model": "claude-test",
        })
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["ok"], body)
        self.assertEqual(body["target_path"], "multi_page_export/services.html")
        self.assertIn("Edited services", export_page.read_text(encoding="utf-8"))
        self.assertIn(
            "Old hero",
            (self.gen_root / "x" / "mockup.html").read_text(encoding="utf-8"),
        )
        backups = list((self.gen_root / "x" / "versions" / "pages").glob("services_v*.html"))
        self.assertEqual(len(backups), 1)
        self.assertIn("Old services", backups[0].read_text(encoding="utf-8"))

    def test_restore_previous_color_requires_backup(self):
        self._write_generated("x")
        client = self._client(lead={"lead_key": "x", "data": {}})
        r = client.post("/api/ai/edit-website-section", json={
            "lead_key": "x",
            "section_id": "hero",
            "instruction": "Restore colors.",
            "color_mode": "restore_previous",
            "ai_provider": "Anthropic",
            "ai_api_key": "test-key",
        })
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertFalse(body["ok"])
        self.assertIn("No previous backup", body["error"])

    def test_restore_website_backup_restores_latest_saved_mockup(self):
        self._write_generated("x")
        out = self.gen_root / "x"
        original = (out / "mockup.html").read_text(encoding="utf-8")
        backup_path = self.gen_mod.backup_mockup_version(
            out,
            original,
            reason="Before edit",
            section_id="hero",
        )
        (out / "mockup.html").write_text(
            original.replace("Old hero", "Changed hero"),
            encoding="utf-8",
        )

        client = self._client(lead={"lead_key": "x", "data": {}})
        r = client.post("/api/ai/restore-website-backup", json={"lead_key": "x"})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["ok"], body)
        self.assertEqual(body["restored_file"], backup_path.name)
        restored = (out / "mockup.html").read_text(encoding="utf-8")
        self.assertIn("Old hero", restored)
        self.assertNotIn("Changed hero", restored)

    def test_restore_website_backup_can_restore_selected_version(self):
        self._write_generated("x")
        out = self.gen_root / "x"
        original = (out / "mockup.html").read_text(encoding="utf-8")
        first = self.gen_mod.backup_mockup_version(
            out,
            original.replace("Old hero", "First backup hero"),
            reason="First",
        )
        self.gen_mod.backup_mockup_version(
            out,
            original.replace("Old hero", "Second backup hero"),
            reason="Second",
        )
        (out / "mockup.html").write_text(
            original.replace("Old hero", "Current hero"),
            encoding="utf-8",
        )

        client = self._client(lead={"lead_key": "x", "data": {}})
        r = client.post("/api/ai/restore-website-backup", json={
            "lead_key": "x",
            "version_file": first.name,
        })
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["ok"], body)
        self.assertEqual(body["restored_file"], first.name)
        restored = (out / "mockup.html").read_text(encoding="utf-8")
        self.assertIn("First backup hero", restored)
        self.assertNotIn("Second backup hero", restored)

    def test_restore_website_backup_rejects_invalid_version_file(self):
        self._write_generated("x")
        client = self._client(lead={"lead_key": "x", "data": {}})
        r = client.post("/api/ai/restore-website-backup", json={
            "lead_key": "x",
            "version_file": "../mockup_v001.html",
        })
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertFalse(body["ok"])
        self.assertIn("Invalid backup", body["error"])


class WebsitePackageManualSaveTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.gen_root = Path(self._tmp.name) / "generated"
        self.gen_root.mkdir()

        import lead_vault_website_generator as gen_mod
        self.gen_mod = gen_mod
        patcher = patch.object(gen_mod, "DEFAULT_GENERATED_DIR", self.gen_root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _client(self, lead):
        app = _make_app()
        patcher = patch.object(ai_router, "get_store", lambda: _FakeStore(lead))
        patcher.start()
        self.addCleanup(patcher.stop)
        return TestClient(app)

    def _write_generated(self, safe_key: str):
        d = self.gen_root / safe_key
        d.mkdir(parents=True, exist_ok=True)
        html = (
            '<!DOCTYPE html><html lang="en"><head>'
            '<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>Example</title><meta name="description" content="Example">'
            '</head><body>'
            '<section data-summit-section="hero" data-summit-label="Hero"><h1>Old hero</h1></section>'
            '</body></html>'
        )
        (d / "mockup.html").write_text(html, encoding="utf-8")
        (d / "meta.json").write_text(
            json.dumps({"category": "generic", "model": "claude-sonnet-4-6"}),
            encoding="utf-8",
        )
        return d

    def test_manual_save_overwrites_mockup_backs_up_and_rebuilds_manifest(self):
        out = self._write_generated("x")
        new_html = (
            '<!DOCTYPE html><html lang="en"><head>'
            '<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>Edited</title><meta name="description" content="Edited">'
            '</head><body>'
            '<section data-summit-section="hero" data-summit-label="Hero"><h1>Manual edit</h1></section>'
            '<section data-summit-section="contact" data-summit-label="Contact"><p>Call us</p></section>'
            '</body></html>'
        )
        client = self._client(lead={"lead_key": "x", "data": {}})
        r = client.post("/api/ai/save-website-mockup", json={
            "lead_key": "x",
            "html": new_html,
        })
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["ok"], body)
        saved = (out / "mockup.html").read_text(encoding="utf-8")
        self.assertIn("Manual edit", saved)
        self.assertNotIn("Old hero", saved)
        backups = list((out / "versions").glob("mockup_v*.html"))
        self.assertEqual(len(backups), 1)
        self.assertIn("Old hero", backups[0].read_text(encoding="utf-8"))
        sections = body["edit_manifest"]["sections"]
        self.assertEqual([s["id"] for s in sections], ["hero", "contact"])
        self.assertTrue((out / "edit_manifest.json").exists())
        self.assertTrue((out / "validation.json").exists())

    def test_manual_save_warns_when_section_markers_are_removed(self):
        out = self._write_generated("x")
        new_html = (
            '<!DOCTYPE html><html lang="en"><head>'
            '<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>Edited</title><meta name="description" content="Edited">'
            '</head><body><main><h1>No markers</h1></main></body></html>'
        )
        client = self._client(lead={"lead_key": "x", "data": {}})
        r = client.post("/api/ai/save-website-mockup", json={
            "lead_key": "x",
            "html": new_html,
        })
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["ok"], body)
        self.assertIn("markers were removed", body["marker_warning"])
        self.assertEqual(body["edit_manifest"]["sections"], [])
        self.assertIn("No markers", (out / "mockup.html").read_text(encoding="utf-8"))

    def test_manual_save_can_target_selected_export_page(self):
        out = self._write_generated("x")
        export_dir = out / "multi_page_export"
        export_dir.mkdir()
        service_path = export_dir / "services.html"
        service_path.write_text(
            '<!DOCTYPE html><html lang="en"><head>'
            '<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>Services</title><meta name="description" content="Services">'
            '</head><body>'
            '<section data-summit-section="hero" data-summit-label="Hero"><h1>Old services</h1></section>'
            '</body></html>',
            encoding="utf-8",
        )
        new_html = (
            '<!DOCTYPE html><html lang="en"><head>'
            '<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>Services Edited</title><meta name="description" content="Services">'
            '</head><body>'
            '<section data-summit-section="hero" data-summit-label="Hero"><h1>Edited services</h1></section>'
            '</body></html>'
        )
        client = self._client(lead={"lead_key": "x", "data": {}})
        r = client.post("/api/ai/save-website-mockup", json={
            "lead_key": "x",
            "target_path": "multi_page_export/services.html",
            "html": new_html,
        })
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["ok"], body)
        self.assertEqual(body["target_path"], "multi_page_export/services.html")
        self.assertIn("Edited services", service_path.read_text(encoding="utf-8"))
        self.assertIn("Old hero", (out / "mockup.html").read_text(encoding="utf-8"))
        backups = list((out / "versions" / "pages").glob("services_v*.html"))
        self.assertEqual(len(backups), 1)
        self.assertIn("Old services", backups[0].read_text(encoding="utf-8"))
        self.assertEqual(body["edit_manifest"], {})


if __name__ == "__main__":
    unittest.main()
