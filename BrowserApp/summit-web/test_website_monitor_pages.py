"""Regression tests for the Website Monitor page and retired Studio routes."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.templating import Jinja2Templates


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from app.routers import pages as pages_router  # noqa: E402


def _make_app() -> FastAPI:
    app = FastAPI()
    app.state.templates = Jinja2Templates(directory=str(ROOT / "app" / "templates"))
    app.include_router(pages_router.router)
    return app


class WebsiteMonitorPageTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(_make_app())
        self.addCleanup(self.client.close)

    def test_website_monitor_renders_without_website_studio_navigation(self):
        response = self.client.get("/website-monitor")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Website Monitor", response.text)
        self.assertIn('href="/website-monitor"', response.text)
        self.assertNotIn('href="/website-studio"', response.text)
        self.assertNotIn(">Website Studio<", response.text)

    def test_retired_top_level_pages_redirect_to_website_monitor(self):
        for path in ("/manual-website", "/website-studio"):
            with self.subTest(path=path):
                response = self.client.get(path, follow_redirects=False)

                self.assertEqual(response.status_code, 307)
                self.assertEqual(response.headers["location"], "/website-monitor")

    def test_retired_studio_editor_redirects_to_lead_detail(self):
        response = self.client.get(
            "/website-studio/example",
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 307)
        self.assertEqual(response.headers["location"], "/leads/example")

    def test_base_template_uses_website_monitor_navigation(self):
        template = (ROOT / "app" / "templates" / "base.html").read_text(
            encoding="utf-8"
        )

        self.assertIn('href="/website-monitor"', template)
        self.assertIn(">Website Monitor<", template)
        self.assertNotIn('href="/website-studio"', template)
        self.assertNotIn(">Website Studio<", template)

    def test_lead_detail_removes_studio_controls_but_keeps_agent_review(self):
        response = self.client.get("/leads/example")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Website Generation", response.text)
        self.assertNotIn("Open Studio", response.text)
        self.assertIn("Agent Review", response.text)


if __name__ == "__main__":
    unittest.main()
