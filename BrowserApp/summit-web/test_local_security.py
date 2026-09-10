"""Offline tests: no production app, settings, databases, or providers are used."""
from __future__ import annotations

import unittest
import csv
import io
import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient

from app.security import LocalOnlyMiddleware


class LocalSecurityTests(unittest.TestCase):
    def setUp(self):
        self.calls = 0
        application = FastAPI()
        application.add_middleware(LocalOnlyMiddleware)

        @application.api_route("/api/data", methods=["GET", "POST", "PUT", "DELETE"])
        async def protected_data():
            self.calls += 1
            return {"private": "synthetic test data"}

        @application.get("/api/ai/website-package/demo/mockup")
        async def preview():
            return HTMLResponse("<script>fetch('/api/data')</script>")

        @application.get("/api/ai/website-package/demo/files/style.css")
        async def asset():
            return HTMLResponse("body { color: black; }")

        self.app = application

    def client(self, peer="127.0.0.1", base_url="http://127.0.0.1:8000"):
        return TestClient(self.app, base_url=base_url, client=(peer, 12345))

    def test_same_origin_browser_and_local_script_requests_work(self):
        with self.client() as client:
            self.assertEqual(client.get("/api/data").status_code, 200)
            for method in ("POST", "PUT", "DELETE"):
                response = client.request(method, "/api/data", json={}, headers={
                    "Origin": "http://127.0.0.1:8000", "Sec-Fetch-Site": "same-origin",
                })
                self.assertEqual(response.status_code, 200)
            self.assertEqual(client.post("/api/data", headers={"Content-Type": "application/json"}).status_code, 200)

    def test_non_loopback_peers_and_rebinding_hosts_never_reach_handlers(self):
        for peer in ("192.168.1.10", "203.0.113.10"):
            with self.client(peer) as client:
                self.assertEqual(client.get("/api/data").status_code, 403)
        for host in ("attacker.example", "127.0.0.1.attacker.example", "localhost.attacker.example", "0.0.0.0"):
            with self.client(base_url=f"http://{host}:8000") as client:
                self.assertEqual(client.get("/api/data").status_code, 403)
        self.assertEqual(self.calls, 0)

    def test_cross_origin_json_writes_and_reads_are_rejected(self):
        with self.client() as client:
            for origin in ("https://attacker.example", "http://127.0.0.1:8001", "http://localhost:8000", "null"):
                for method in ("GET", "POST", "PUT", "DELETE"):
                    response = client.request(method, "/api/data", json={}, headers={"Origin": origin})
                    self.assertEqual(response.status_code, 403)
        self.assertEqual(self.calls, 0)

    def test_cross_site_requests_without_origin_are_rejected(self):
        with self.client() as client:
            for site in ("cross-site", "same-site"):
                self.assertEqual(client.get("/api/data", headers={"Sec-Fetch-Site": site}).status_code, 403)
        self.assertEqual(self.calls, 0)

    def test_simple_forms_and_no_cors_posts_cannot_mutate(self):
        with self.client() as client:
            for content_type in (None, "text/plain", "application/x-www-form-urlencoded", "multipart/form-data; boundary=test"):
                headers = {"Content-Type": content_type} if content_type else {}
                self.assertEqual(client.post("/api/data", content='{"change":true}', headers=headers).status_code, 415)
        self.assertEqual(self.calls, 0)

    def test_null_preview_origin_can_only_read_preview_assets(self):
        headers = {"Origin": "null", "Sec-Fetch-Site": "cross-site"}
        with self.client() as client:
            self.assertEqual(client.get("/api/ai/website-package/demo/files/style.css", headers=headers).status_code, 200)
            self.assertEqual(client.get("/api/data", headers=headers).status_code, 403)
            self.assertEqual(client.post("/api/data", json={}, headers=headers).status_code, 403)
            self.assertEqual(client.get("/api/data", headers={**headers, "X-Forwarded-Host": "127.0.0.1"}).status_code, 403)
        self.assertEqual(self.calls, 0)

    def test_direct_preview_responses_have_opaque_origin_sandbox(self):
        with self.client() as client:
            for path in ("/api/ai/website-package/demo/mockup", "/api/ai/website-package/demo/files/style.css"):
                response = client.get(path)
                policy = response.headers["Content-Security-Policy"]
                self.assertIn("sandbox allow-scripts", policy)
                self.assertNotIn("allow-same-origin", policy)
                self.assertIn("form-action 'none'", policy)
                self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")

    def test_private_responses_cannot_be_embedded_or_cached(self):
        with self.client() as client:
            response = client.get("/api/data")
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")
            self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
            self.assertIn("connect-src 'self'", response.headers["Content-Security-Policy"])

    def test_ipv6_and_localhost_loopback_access(self):
        # Pass Host explicitly: older Starlette TestClient versions cannot parse
        # an IPv6 literal in their base_url, independently of the app middleware.
        for peer, host in (("::1", "[::1]:8000"), ("::ffff:127.0.0.1", "localhost:8000")):
            with self.client(peer) as client:
                self.assertEqual(client.get("/api/data", headers={"Host": host}).status_code, 200)

    def test_duplicate_security_headers_are_rejected(self):
        with self.client() as client:
            for headers in (
                [("Origin", "http://127.0.0.1:8000"), ("Origin", "https://attacker.example")],
                [("Host", "127.0.0.1:8000"), ("Host", "attacker.example")],
            ):
                self.assertEqual(client.get("/api/data", headers=headers).status_code, 403)
        self.assertEqual(self.calls, 0)


class SettingsSecretTests(unittest.TestCase):
    def test_secret_redaction_and_blank_updates_preserve_saved_values(self):
        from app import config
        from app.routers.settings import _redact_settings

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(config, "LEAD_MACHINE_SETTINGS", Path(directory) / "machine.json"), patch.object(
                config, "LEAD_VAULT_SETTINGS", Path(directory) / "vault.json"
            ):
                original = {key: "synthetic-fixture-value" for key in config.SECRET_SETTING_KEYS}
                config.save_settings(original)
                response = _redact_settings(config.load_settings())
                for key in original:
                    self.assertEqual(response[key], "")
                    self.assertTrue(response[f"{key}_set"])
                config.save_settings({key: "" for key in original})
                saved = config.load_settings()
                self.assertTrue(all(saved[key] == value for key, value in original.items()))

    def test_real_app_installs_boundary_without_reading_local_settings(self):
        from app import config
        from app.main import create_app

        with patch.object(config, "_read_json", side_effect=AssertionError("Real settings must not be read")):
            with patch("app.routers.settings.load_settings", return_value={"openai_api_key": "synthetic-value"}):
                with TestClient(create_app(), base_url="http://127.0.0.1:8000", client=("127.0.0.1", 12345)) as client:
                    self.assertEqual(client.get("/").status_code, 200)
                    response = client.get("/api/settings")
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json()["openai_api_key"], "")
                    self.assertEqual(client.get("/api/settings", headers={"Origin": "https://attacker.example"}).status_code, 403)
                    self.assertEqual(client.get("/openapi.json").status_code, 200)
                    self.assertEqual(client.get("/docs").status_code, 404)
                    self.assertEqual(client.get("/redoc").status_code, 404)


class CsvExportSecurityTests(unittest.TestCase):
    def test_untrusted_csv_cells_stay_literal_and_do_not_create_extra_columns(self):
        from app.routers import leads

        fixture = {
            "business_name": '=HYPERLINK("https://example.invalid", "example")',
            "city_area": 'City, "quoted"\nSecond line',
            "address": ' 	@SUM(1,2)',
            "data": {"Phone": "+1-555-0100", "Email": "example@example.invalid"},
        }

        class FakeStore:
            def list_queue_summaries(self, **kwargs):
                return [fixture]

        application = FastAPI()
        application.include_router(leads.router)
        with patch.object(leads, "get_store", return_value=FakeStore()):
            with TestClient(application) as client:
                response = client.get("/api/leads/export")
        self.assertEqual(response.status_code, 200)
        rows = list(csv.reader(io.StringIO(response.text)))
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(rows[0]), len(rows[1]))
        exported = dict(zip(rows[0], rows[1]))
        self.assertEqual(exported["business_name"], "'" + fixture["business_name"])
        self.assertEqual(exported["city_area"], fixture["city_area"])
        self.assertEqual(exported["address"], "'" + fixture["address"])
        self.assertEqual(exported["Phone"], "'+1-555-0100")


if __name__ == "__main__":
    unittest.main()
