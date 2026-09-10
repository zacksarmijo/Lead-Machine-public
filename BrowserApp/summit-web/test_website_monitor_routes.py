"""API contract tests for the standalone Website Monitor router.

All persistence and scan coordination are replaced with fakes.  The suite
therefore verifies response compatibility and HTTP error handling without
touching the real database or making PageSpeed/DataForSEO/network requests.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("LEAD_VAULT_DB", str(ROOT / "_test_lead_vault.sqlite3"))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.routers import website_monitor as monitor_router  # noqa: E402


def _make_client(store, coordinator=None) -> TestClient:
    app = FastAPI()
    app.include_router(monitor_router.router)

    patches = [
        patch.object(monitor_router, "get_monitor_store", lambda: store),
    ]
    if coordinator is not None:
        patches.append(patch.object(monitor_router, "scan_coordinator", coordinator))
    for active_patch in patches:
        active_patch.start()
        app.state._website_monitor_test_patches = getattr(
            app.state, "_website_monitor_test_patches", []
        ) + [active_patch]

    client = TestClient(app)
    original_close = client.close

    def close_with_patches():
        try:
            original_close()
        finally:
            for active_patch in reversed(app.state._website_monitor_test_patches):
                active_patch.stop()

    client.close = close_with_patches
    return client


def _site(site_id=7, *, site_type="owned", name="Example Plumbing"):
    return {
        "id": site_id,
        "name": name,
        "url": "https://example.com/",
        "site_type": site_type,
        "active": True,
        "overall_score": 88,
        "open_issue_count": 2,
    }


class FakeStore:
    def __init__(self):
        self.sites = [
            _site(),
            _site(8, site_type="observed", name="Observed Competitor"),
        ]
        self.created_payload = None
        self.updated = None
        self.deleted = None
        self.failures = {}

    def _raise(self, operation):
        failure = self.failures.get(operation)
        if failure:
            raise failure

    def get_summary(self):
        self._raise("summary")
        return {
            "site_count": 2,
            "active_site_count": 2,
            "owned_site_count": 1,
            "observed_site_count": 1,
            "open_issue_count": 3,
            "critical_issue_count": 1,
            "average_health_score": 81,
            "sites": list(self.sites),
        }

    def list_sites(self):
        self._raise("list")
        return list(self.sites)

    def get_site_detail(self, site_id):
        self._raise("detail")
        site = next((item for item in self.sites if item["id"] == site_id), None)
        if site is None:
            raise ValueError("Website not found")
        # Store details are intentionally flat.  The router is responsible for
        # exposing the stable nested shape consumed by website_monitor.js.
        return {
            **site,
            "latest_run": {"id": 31, "overall_score": 88, "status": "complete"},
            "latest_rankings": [
                {"keyword": "denver plumber", "rank_absolute": 4}
            ],
            "open_issues": [
                {"id": 10, "severity": "warning", "title": "Improve title"}
            ],
            "history": [
                {"id": 31, "overall_score": 88, "completed_at": "2026-07-16T12:00:00Z"}
            ],
            "resolved_issues": [],
        }

    def get_site_summary(self, site_id):
        site = next((item for item in self.sites if item["id"] == site_id), None)
        if site is None:
            raise ValueError("Website not found")
        return dict(site)

    def create_site(self, payload):
        self._raise("create")
        self.created_payload = payload
        return {**_site(9, name=payload.get("name", "New site")), **payload}

    def update_site(self, site_id, payload):
        self._raise("update")
        if not any(item["id"] == site_id for item in self.sites):
            raise ValueError("Website not found")
        self.updated = (site_id, payload)
        return {**_site(site_id), **payload}

    def delete_site(self, site_id):
        self._raise("delete")
        if not any(item["id"] == site_id for item in self.sites):
            raise ValueError("Website not found")
        self.deleted = site_id
        return {"deleted": True, "site_id": site_id}

    def scan_site(self, *_args, **_kwargs):
        raise AssertionError("Route tests must never execute a real scan")


class FakeScanCoordinator:
    def __init__(self):
        self.running = False
        self.started_site_ids = []
        self.status = {
            "running": False,
            "site_id": None,
            "started_at": None,
            "finished_at": None,
            "error": "",
        }

    def is_running(self, site_id=None):
        if not self.running:
            return False
        return site_id is None or self.status["site_id"] == site_id

    def start(self, site_id):
        self.started_site_ids.append(site_id)
        self.running = True
        self.status.update(
            {
                "running": True,
                "site_id": site_id,
                "started_at": "2026-07-16T12:30:00Z",
                "finished_at": None,
                "error": "",
            }
        )
        return True

    def snapshot(self):
        return dict(self.status)


class WebsiteMonitorRouteTests(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.coordinator = FakeScanCoordinator()
        self.client = _make_client(self.store, self.coordinator)
        self.addCleanup(self.client.close)

    def test_summary_adds_provider_readiness_and_count_aliases(self):
        with patch.object(
            monitor_router,
            "load_settings",
            lambda: {
                "dataforseo_login": "seo-user",
                "dataforseo_password": "seo-password",
                "pagespeed_api_key": "pagespeed-key",
            },
        ):
            response = self.client.get("/api/website-monitor/summary")

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["owned_count"], 1)
        self.assertEqual(body["observed_count"], 1)
        self.assertEqual(body["average_health"], 81)
        self.assertTrue(body["providers"]["dataforseo_configured"])
        self.assertTrue(body["providers"]["pagespeed_configured"])

    def test_provider_readiness_requires_complete_credentials(self):
        with patch.object(
            monitor_router,
            "load_settings",
            lambda: {
                "dataforseo_login": "seo-user",
                "dataforseo_password": "",
                "pagespeed_api_key": "",
            },
        ):
            body = self.client.get("/api/website-monitor/summary").json()

        self.assertFalse(body["providers"]["dataforseo_configured"])
        self.assertFalse(body["providers"]["pagespeed_configured"])

    def test_list_and_detail_have_frontend_compatible_shapes(self):
        listed = self.client.get("/api/website-monitor/sites")
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual([site["id"] for site in listed.json()["sites"]], [7, 8])

        response = self.client.get("/api/website-monitor/sites/7")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["site"]["id"], 7)
        self.assertEqual(body["rankings"][0]["keyword"], "denver plumber")
        self.assertEqual(body["issues"][0]["title"], "Improve title")
        self.assertEqual(body["history"][0]["overall_score"], 88)
        self.assertEqual(body["latest_run"]["id"], 31)

    def test_crud_success_passes_payloads_to_store(self):
        create_payload = {
            "name": "New Site",
            "url": "https://new.example/",
            "site_type": "observed",
            "keywords": ["new keyword"],
        }
        created = self.client.post(
            "/api/website-monitor/sites", json=create_payload
        )
        self.assertIn(created.status_code, (200, 201), created.text)
        self.assertEqual(self.store.created_payload["name"], "New Site")

        updated = self.client.put(
            "/api/website-monitor/sites/7", json={"name": "Renamed"}
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(self.store.updated, (7, {"name": "Renamed"}))

        deleted = self.client.delete("/api/website-monitor/sites/7")
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertEqual(self.store.deleted, 7)

    def test_crud_value_errors_translate_to_400_or_404(self):
        self.store.failures["create"] = ValueError("URL must use http or https")
        bad_create = self.client.post(
            "/api/website-monitor/sites",
            json={"name": "Bad", "url": "javascript:alert(1)"},
        )
        self.assertEqual(bad_create.status_code, 400, bad_create.text)
        self.assertIn("http", bad_create.json()["detail"].lower())

        missing_detail = self.client.get("/api/website-monitor/sites/999")
        self.assertEqual(missing_detail.status_code, 404, missing_detail.text)

        missing_update = self.client.put(
            "/api/website-monitor/sites/999", json={"name": "Nope"}
        )
        self.assertEqual(missing_update.status_code, 404, missing_update.text)

        missing_delete = self.client.delete("/api/website-monitor/sites/999")
        self.assertEqual(missing_delete.status_code, 404, missing_delete.text)

    def test_scan_start_and_status_use_coordinator_without_network(self):
        response = self.client.post("/api/website-monitor/sites/7/scan")
        self.assertIn(response.status_code, (200, 202), response.text)
        body = response.json()
        self.assertTrue(body["accepted"])
        self.assertEqual(body["site_id"], 7)
        self.assertEqual(self.coordinator.started_site_ids, [7])

        status = self.client.get("/api/website-monitor/scans/status")
        self.assertEqual(status.status_code, 200, status.text)
        self.assertTrue(status.json()["running"])
        self.assertEqual(status.json()["site_id"], 7)

    def test_scan_conflict_and_unknown_site_are_http_errors(self):
        self.coordinator.running = True
        self.coordinator.status["site_id"] = 8
        conflict = self.client.post("/api/website-monitor/sites/7/scan")
        self.assertEqual(conflict.status_code, 409, conflict.text)
        self.assertEqual(self.coordinator.started_site_ids, [])

        self.coordinator.running = False
        missing = self.client.post("/api/website-monitor/sites/999/scan")
        self.assertEqual(missing.status_code, 404, missing.text)


if __name__ == "__main__":
    unittest.main()
