"""Endpoint tests for POST /api/ai/scrape-website.

Exercises the route with FastAPI's TestClient; scraper and store are
patched so no real network calls or DB access happen.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "lead-vault"))
os.environ.setdefault("LEAD_VAULT_DB", str(ROOT / "_test_lead_vault.sqlite3"))

from fastapi.testclient import TestClient

from app.routers import ai as ai_router
from app.routers import leads as leads_router
from app.routers import settings as settings_router
from app import config as app_config


def _make_app():
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(ai_router.router)
    return app


def _make_leads_app():
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(leads_router.router)
    return app


def _make_settings_app():
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(settings_router.router)
    return app


class _FakeStore:
    def __init__(self, lead: dict | None):
        self._lead = lead

    def get_lead(self, lead_key: str):  # noqa: ARG002
        return self._lead


class _FakeManualCreateStore:
    def __init__(self):
        self.created = None

    def create_manual_website_lead(self, scrape, *, manual_key=""):
        self.created = {"scrape": scrape, "manual_key": manual_key}
        return {"lead_key": "manual_example", "business_name": "Example Biz"}


def _fake_scraped(ok: bool = True, **overrides):
    base = {
        "source_url": "https://example.com/",
        "final_url": "https://example.com/",
        "status_code": 200,
        "ok": ok,
        "error": "" if ok else "boom",
        "title": "Example",
        "business_name": "Example Biz",
        "services": ["One"],
        "phones": ["(555) 555-5555"],
        "emails": [],
        "photos": ["https://example.com/a.jpg"],
        "headings": ["Welcome"],
        "tech_hints": ["WordPress"],
        "colors": ["#ffffff"],
        "fonts": ["Inter"],
        "social_links": {"facebook": "https://facebook.com/example"},
        "main_text": "hello",
        "has_https": True,
        "robots_allowed": True,
    }
    base.update(overrides)
    scraped = SimpleNamespace(**base)
    scraped.to_dict = lambda: dict(base)
    return scraped


class ScrapeWebsiteEndpointTests(unittest.TestCase):
    def setUp(self):
        # Reset the in-memory lock dict between tests
        ai_router._lead_locks.clear()

    def _client(self, lead):
        app = _make_app()
        self._store_patch = patch.object(
            ai_router, "get_store", lambda: _FakeStore(lead)
        )
        self._store_patch.start()
        self.addCleanup(self._store_patch.stop)
        return TestClient(app)

    def test_requires_lead_key(self):
        client = self._client(lead={"lead_key": "x", "data": {}})
        r = client.post("/api/ai/scrape-website", json={})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["ok"])
        self.assertIn("lead_key", r.json()["error"])

    def test_rejects_unknown_mode(self):
        client = self._client(lead={"lead_key": "x", "data": {}})
        r = client.post(
            "/api/ai/scrape-website",
            json={"lead_key": "x", "mode": "telepathic"},
        )
        self.assertFalse(r.json()["ok"])
        self.assertIn("mode", r.json()["error"])

    def test_rejects_non_http_url_override(self):
        client = self._client(lead={"lead_key": "x", "data": {}})
        r = client.post(
            "/api/ai/scrape-website",
            json={"lead_key": "x", "url": "javascript:alert(1)"},
        )
        self.assertFalse(r.json()["ok"])
        self.assertIn("http", r.json()["error"])

    def test_rejects_private_url_override(self):
        client = self._client(lead={"lead_key": "x", "data": {}})
        r = client.post(
            "/api/ai/scrape-website",
            json={"lead_key": "x", "url": "http://127.0.0.1:8000"},
        )
        self.assertFalse(r.json()["ok"])
        self.assertIn("blocked", r.json()["error"].lower())

    def test_missing_lead(self):
        client = self._client(lead=None)
        r = client.post("/api/ai/scrape-website", json={"lead_key": "nope"})
        self.assertFalse(r.json()["ok"])
        self.assertEqual(r.json()["error"], "Lead not found")

    def test_missing_url_on_lead(self):
        client = self._client(lead={"lead_key": "x", "data": {}})
        r = client.post("/api/ai/scrape-website", json={"lead_key": "x"})
        self.assertFalse(r.json()["ok"])
        self.assertIn("No website URL", r.json()["error"])

    def test_happy_path_uses_lead_url(self):
        lead = {
            "lead_key": "x",
            "data": {"Resolved Website URL": "https://example.com/"},
        }
        client = self._client(lead=lead)

        captured = {}

        def fake_scrape_site(url, timeout, mode):  # noqa: ARG001
            captured["url"] = url
            captured["mode"] = mode
            return _fake_scraped()

        def fake_save(lead_key, scraped, base_dir):  # noqa: ARG001
            return Path("/tmp") / lead_key

        import lead_vault_scraper

        with patch.object(lead_vault_scraper, "scrape_site", fake_scrape_site), \
                patch.object(lead_vault_scraper, "save_scraped_assets", fake_save):
            r = client.post(
                "/api/ai/scrape-website", json={"lead_key": "x"}
            )

        self.assertTrue(r.json()["ok"], r.json())
        self.assertEqual(captured["url"], "https://example.com/")
        self.assertEqual(captured["mode"], "auto")
        self.assertEqual(r.json()["counts"]["photos"], 1)
        self.assertEqual(r.json()["business_name"], "Example Biz")

    def test_body_url_overrides_lead_url(self):
        lead = {
            "lead_key": "x",
            "data": {"Resolved Website URL": "https://lead.example/"},
        }
        client = self._client(lead=lead)
        captured = {}

        def fake_scrape_site(url, timeout, mode):  # noqa: ARG001
            captured["url"] = url
            return _fake_scraped()

        def fake_save(lead_key, scraped, base_dir):  # noqa: ARG001
            return Path("/tmp") / lead_key

        import lead_vault_scraper
        with patch.object(lead_vault_scraper, "scrape_site", fake_scrape_site), \
                patch.object(lead_vault_scraper, "save_scraped_assets", fake_save):
            r = client.post(
                "/api/ai/scrape-website",
                json={"lead_key": "x", "url": "https://override.example/"},
            )

        self.assertTrue(r.json()["ok"])
        self.assertEqual(captured["url"], "https://override.example/")

    def test_scraper_failure_surfaces_error(self):
        lead = {
            "lead_key": "x",
            "data": {"Resolved Website URL": "https://example.com/"},
        }
        client = self._client(lead=lead)

        def fake_scrape_site(url, timeout, mode):  # noqa: ARG001
            return _fake_scraped(ok=False, error="Blocked by robots.txt")

        import lead_vault_scraper
        with patch.object(lead_vault_scraper, "scrape_site", fake_scrape_site):
            r = client.post(
                "/api/ai/scrape-website", json={"lead_key": "x"}
            )
        self.assertFalse(r.json()["ok"])
        self.assertIn("robots", r.json()["error"])

    def test_scraper_exception_is_sanitized(self):
        lead = {
            "lead_key": "x",
            "data": {"Resolved Website URL": "https://example.com/"},
        }
        client = self._client(lead=lead)

        def fake_scrape_site(url, timeout, mode):  # noqa: ARG001
            raise RuntimeError(
                "boom sk-ant-api03-SUPERSECRETKEY12345 leaked"
            )

        import lead_vault_scraper
        with patch.object(lead_vault_scraper, "scrape_site", fake_scrape_site):
            r = client.post(
                "/api/ai/scrape-website", json={"lead_key": "x"}
            )
        self.assertFalse(r.json()["ok"])
        self.assertNotIn("SUPERSECRETKEY12345", r.json()["error"])

    def test_concurrent_second_call_rejected(self):
        """If the lock is held, a second call must return an error."""
        import asyncio

        lead = {
            "lead_key": "x",
            "data": {"Resolved Website URL": "https://example.com/"},
        }
        client = self._client(lead=lead)

        # Pre-acquire the lock so the endpoint sees it as locked.
        loop = asyncio.new_event_loop()
        try:
            lock = loop.run_until_complete(ai_router._lock_for_lead("x"))
            loop.run_until_complete(lock.acquire())
        finally:
            loop.close()

        r = client.post("/api/ai/scrape-website", json={"lead_key": "x"})
        self.assertFalse(r.json()["ok"])
        self.assertIn("Another operation", r.json()["error"])


class ManualScrapeWebsiteEndpointTests(unittest.TestCase):
    def setUp(self):
        ai_router._lead_locks.clear()

    def _client(self):
        app = _make_app()
        return TestClient(app)

    def test_manual_scrape_requires_url(self):
        client = self._client()
        r = client.post("/api/ai/manual-scrape-website", json={})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["ok"])
        self.assertIn("URL", r.json()["error"])

    def test_manual_scrape_rejects_non_http_url(self):
        client = self._client()
        r = client.post(
            "/api/ai/manual-scrape-website",
            json={"url": "javascript:alert(1)"},
        )
        self.assertFalse(r.json()["ok"])
        self.assertIn("http", r.json()["error"])

    def test_manual_scrape_rejects_localhost_url(self):
        client = self._client()
        r = client.post(
            "/api/ai/manual-scrape-website",
            json={"url": "http://localhost:5173"},
        )
        self.assertFalse(r.json()["ok"])
        self.assertIn("localhost", r.json()["error"].lower())

    def test_manual_scrape_happy_path_saves_under_manual_key(self):
        client = self._client()
        captured = {}

        def fake_scrape_site(url, timeout, mode):  # noqa: ARG001
            captured["url"] = url
            captured["mode"] = mode
            return _fake_scraped()

        def fake_save(lead_key, scraped, base_dir):  # noqa: ARG001
            captured["lead_key"] = lead_key
            return Path("/tmp") / lead_key

        import lead_vault_scraper
        with patch.object(lead_vault_scraper, "scrape_site", fake_scrape_site), \
                patch.object(lead_vault_scraper, "save_scraped_assets", fake_save):
            r = client.post(
                "/api/ai/manual-scrape-website",
                json={"url": "example.com", "mode": "static"},
            )

        body = r.json()
        self.assertTrue(body["ok"], body)
        self.assertEqual(captured["url"], "example.com")
        self.assertEqual(captured["mode"], "static")
        self.assertTrue(captured["lead_key"].startswith("manual_example_com_"))
        self.assertEqual(body["manual_key"], captured["lead_key"])
        self.assertEqual(body["counts"]["photos"], 1)
        self.assertEqual(body["scrape"]["tech_hints"], ["WordPress"])


class CreateLeadFromManualScrapeEndpointTests(unittest.TestCase):
    def test_create_lead_from_manual_scrape_payload(self):
        app = _make_leads_app()
        fake_store = _FakeManualCreateStore()
        patcher = patch.object(leads_router, "get_store", lambda: fake_store)
        patcher.start()
        self.addCleanup(patcher.stop)
        client = TestClient(app)

        r = client.post("/api/leads/from-manual-scrape", json={
            "manual_key": "",
            "scrape": {
                "business_name": "Example Biz",
                "final_url": "https://example.com/",
                "phones": ["(303) 444-1212"],
            },
        })

        body = r.json()
        self.assertTrue(body["ok"], body)
        self.assertEqual(body["lead_key"], "manual_example")
        self.assertEqual(body["lead_url"], "/leads/manual_example")
        self.assertEqual(fake_store.created["scrape"]["business_name"], "Example Biz")

    def test_create_lead_requires_scrape(self):
        app = _make_leads_app()
        client = TestClient(app)
        r = client.post("/api/leads/from-manual-scrape", json={})
        body = r.json()
        self.assertFalse(body["ok"])
        self.assertIn("manual scrape", body["error"])


class SettingsEndpointSecurityTests(unittest.TestCase):
    def test_get_redacts_saved_api_keys_and_blank_save_preserves_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            lm_path = tmp_path / "lead_machine_settings.json"
            lv_path = tmp_path / "lead_vault_settings.json"
            lm_path.write_text(
                '{"google_maps_api_key": "AIzaREAL", "hunter_api_key": "hunter-real"}',
                encoding="utf-8",
            )
            lv_path.write_text(
                '{"openai_api_key": "sk-real", "anthropic_api_key": "sk-ant-real"}',
                encoding="utf-8",
            )

            with patch.object(app_config, "LEAD_MACHINE_SETTINGS", lm_path), \
                    patch.object(app_config, "LEAD_VAULT_SETTINGS", lv_path):
                client = TestClient(_make_settings_app())
                body = client.get("/api/settings").json()
                self.assertEqual(body["google_maps_api_key"], "")
                self.assertEqual(body["hunter_api_key"], "")
                self.assertEqual(body["openai_api_key"], "")
                self.assertTrue(body["google_maps_api_key_set"])
                self.assertTrue(body["hunter_api_key_set"])
                self.assertTrue(body["openai_api_key_set"])

                r = client.put("/api/settings", json={
                    "google_maps_api_key": "",
                    "hunter_api_key": "",
                    "openai_api_key": "",
                    "agency_name": "Summit",
                })
                self.assertTrue(r.json()["ok"])
                self.assertIn("AIzaREAL", lm_path.read_text(encoding="utf-8"))
                self.assertIn("hunter-real", lm_path.read_text(encoding="utf-8"))
                self.assertIn("sk-real", lv_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
