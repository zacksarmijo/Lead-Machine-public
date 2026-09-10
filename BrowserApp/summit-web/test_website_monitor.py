from __future__ import annotations

from contextlib import closing
from datetime import timedelta
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest


SUMMIT_ROOT = Path(__file__).resolve().parent
if str(SUMMIT_ROOT) not in sys.path:
    sys.path.insert(0, str(SUMMIT_ROOT))

from app.website_monitor import (  # noqa: E402
    DATAFORSEO_ENDPOINT,
    PAGESPEED_ENDPOINT,
    WebsiteMonitorStore,
)


class FakeResponse:
    def __init__(self, status_code=200, text="", *, headers=None, payload=None, elapsed_ms=50):
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = headers or {}
        self._payload = payload
        self.elapsed = timedelta(milliseconds=elapsed_ms)
        self.encoding = "utf-8"

    def json(self):
        if self._payload is None:
            return json.loads(self.text)
        return self._payload


def safe_resolver(_hostname):
    return ["93.184.216.34"]


def healthy_html(title="Excellent Plumbing Services in Denver"):
    words = " ".join(["trusted plumbing repair installation service Denver experts"] * 45)
    return f"""
    <!doctype html><html><head>
      <title>{title}</title>
      <meta name="description" content="Trusted Denver plumbing repair, installation, and emergency service from experienced local professionals. Request straightforward help today.">
      <link rel="canonical" href="https://example.com/">
      <script type="application/ld+json">{{"@context":"https://schema.org","@type":"Plumber"}}</script>
    </head><body><h1>Denver Plumbing Services</h1>
      <a href="/services">Services</a><a href="/contact">Contact</a>
      <img src="team.jpg" alt="Denver plumbing team"><p>{words}</p>
    </body></html>
    """


def pagespeed_payload(performance=91):
    return {
        "id": "https://example.com/",
        "analysisUTCTimestamp": "2026-07-16T12:00:00Z",
        "lighthouseResult": {
            "finalUrl": "https://example.com/",
            "categories": {
                "performance": {"score": performance / 100},
                "accessibility": {"score": 0.94},
                "best-practices": {"score": 0.96},
                "seo": {"score": 1.0},
            },
            "audits": {
                "first-contentful-paint": {"numericValue": 700},
                "largest-contentful-paint": {"numericValue": 1300},
                "speed-index": {"numericValue": 900},
                "total-blocking-time": {"numericValue": 40},
                "cumulative-layout-shift": {"numericValue": 0.02},
            },
        },
        "loadingExperience": {
            "overall_category": "FAST",
            "metrics": {"INTERACTION_TO_NEXT_PAINT": {"percentile": 120}},
        },
    }


def serp_payload(rank=4, keyword="denver plumber"):
    return {
        "tasks": [
            {
                "status_code": 20000,
                "status_message": "Ok.",
                "data": {"keyword": keyword},
                "result": [
                    {
                        "items": [
                            {
                                "type": "organic",
                                "rank_group": 1,
                                "rank_absolute": 1,
                                "domain": "competitor.com",
                                "url": "https://competitor.com/denver",
                                "title": "Competitor",
                            },
                            {
                                "type": "organic",
                                "rank_group": rank,
                                "rank_absolute": rank,
                                "domain": "www.example.com",
                                "url": "https://www.example.com/plumbing",
                                "title": "Example Plumbing",
                            },
                        ]
                    }
                ],
            }
        ]
    }


class ScenarioRequester:
    def __init__(self):
        self.calls = []
        self.html = healthy_html()
        self.rank = 4
        self.performance = 91
        self.robots_status = 200
        self.sitemap_status = 200

    def __call__(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if url == PAGESPEED_ENDPOINT:
            return FakeResponse(payload=pagespeed_payload(self.performance))
        if url == DATAFORSEO_ENDPOINT:
            keyword = kwargs["json"][0]["keyword"]
            return FakeResponse(payload=serp_payload(self.rank, keyword))
        if url.endswith("/robots.txt"):
            return FakeResponse(self.robots_status, "User-agent: *\nAllow: /" if self.robots_status == 200 else "")
        if url.endswith("/sitemap.xml"):
            body = "<urlset><url><loc>https://example.com/</loc></url></urlset>" if self.sitemap_status == 200 else ""
            return FakeResponse(self.sitemap_status, body, headers={"Content-Type": "application/xml"})
        return FakeResponse(200, self.html, headers={"Content-Type": "text/html; charset=utf-8"}, elapsed_ms=320)


class WebsiteMonitorStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "monitor.db"
        self.requester = ScenarioRequester()
        self.store = WebsiteMonitorStore(self.db, request_func=self.requester, resolver=safe_resolver)

    def create_site(self, **overrides):
        payload = {
            "name": "Example Plumbing",
            "url": "example.com",
            "site_type": "owned",
            "location": "Denver, Colorado, United States",
            "device": "mobile",
            "active": True,
            "notes": "Primary company site",
            "keywords": ["denver plumber", "emergency plumber denver"],
        }
        payload.update(overrides)
        return self.store.create_site(payload)

    @property
    def settings(self):
        return {
            "pagespeed_api_key": "page-key",
            "dataforseo_login": "login",
            "dataforseo_password": "password",
        }

    def test_schema_is_isolated_and_preserves_existing_data(self):
        with closing(sqlite3.connect(self.db)) as conn:
            conn.execute("CREATE TABLE existing_user_data(value TEXT)")
            conn.execute("INSERT INTO existing_user_data VALUES ('keep me')")
            conn.commit()
        self.store.ensure_ready()
        with closing(sqlite3.connect(self.db)) as conn:
            tables = {
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
            self.assertEqual(conn.execute("SELECT value FROM existing_user_data").fetchone()[0], "keep me")
        expected = {
            "website_monitor_sites",
            "website_monitor_keywords",
            "website_monitor_runs",
            "website_monitor_rank_snapshots",
            "website_monitor_page_snapshots",
            "website_monitor_issues",
        }
        self.assertTrue(expected.issubset(tables))
        self.assertNotIn("lead_history", tables)

    def test_site_crud_validates_and_reuses_keyword_rows(self):
        created = self.create_site(keywords=["Denver Plumber", "denver plumber", "Boiler repair"])
        self.assertEqual(created["url"], "https://example.com/")
        self.assertEqual(created["site_type"], "owned")
        self.assertEqual(created["keywords"], ["Denver Plumber", "Boiler repair"])
        keyword_id = created["keyword_records"][0]["id"]

        updated = self.store.update_site(
            created["id"],
            {"device": "desktop", "site_type": "observed", "keywords": ["denver plumber", "new keyword"]},
        )
        self.assertEqual(updated["device"], "desktop")
        self.assertEqual(updated["site_type"], "observed")
        self.assertEqual(updated["keyword_records"][0]["id"], keyword_id)
        self.assertEqual(len(self.store.list_sites()), 1)

        with self.assertRaisesRegex(ValueError, "site_type"):
            self.store.update_site(created["id"], {"site_type": "lead"})
        deleted = self.store.delete_site(created["id"])
        self.assertTrue(deleted["deleted"])
        self.assertEqual(self.store.list_sites(), [])
        with self.assertRaisesRegex(ValueError, "not found"):
            self.store.get_site_detail(created["id"])

    def test_full_scan_captures_page_pagespeed_rank_and_competitors(self):
        site = self.create_site()
        result = self.store.scan_site(site["id"], self.settings)
        run = result["latest_run"]
        self.assertEqual(run["status"], "completed")
        self.assertGreaterEqual(run["overall_score"], 80)
        self.assertGreaterEqual(run["seo_score"], 90)
        self.assertEqual(run["performance_score"], 91)
        self.assertEqual(run["visibility_score"], 85)

        page = result["latest_page"]
        self.assertEqual(page["status_code"], 200)
        self.assertEqual(page["title"], "Excellent Plumbing Services in Denver")
        self.assertEqual(page["h1"], ["Denver Plumbing Services"])
        self.assertTrue(page["robots_txt_present"])
        self.assertTrue(page["sitemap_present"])
        self.assertEqual(page["schema"]["types"], ["Plumber"])
        self.assertEqual(page["pagespeed"]["lcp_ms"], 1300)

        rankings = result["latest_rankings"]
        self.assertEqual(len(rankings), 2)
        self.assertEqual(rankings[0]["rank_absolute"], 4)
        self.assertEqual(rankings[0]["ranking_url"], "https://www.example.com/plumbing")
        self.assertEqual(rankings[0]["top_competitors"][0]["domain"], "competitor.com")
        serp_call = next(call for call in self.requester.calls if call[1] == DATAFORSEO_ENDPOINT)
        self.assertEqual(serp_call[2]["json"][0]["location_name"], "Denver, Colorado, United States")
        self.assertEqual(serp_call[2]["json"][0]["device"], "mobile")
        json.dumps(result)  # the complete API payload must be JSON serializable

    def test_second_scan_compares_ranks_and_resolves_fixed_issues(self):
        self.requester.html = "<html><head><meta name='robots' content='noindex'></head><body><p>thin</p></body></html>"
        self.requester.robots_status = 404
        self.requester.sitemap_status = 404
        self.requester.rank = 12
        site = self.create_site(keywords=["denver plumber"])
        first = self.store.scan_site(site["id"], self.settings)
        first_score = first["latest_run"]["overall_score"]
        first_codes = {issue["code"] for issue in first["open_issues"]}
        self.assertIn("missing_title", first_codes)
        self.assertIn("noindex", first_codes)

        self.requester.html = healthy_html("Improved Denver Plumbing and Emergency Repair")
        self.requester.robots_status = 200
        self.requester.sitemap_status = 200
        self.requester.rank = 5
        second = self.store.scan_site(site["id"], self.settings)
        self.assertGreater(second["latest_run"]["overall_score"], first_score)
        rank = second["latest_rankings"][0]
        self.assertEqual(rank["previous_rank_absolute"], 12)
        self.assertEqual(rank["rank_change"], 7)
        comparison = second["latest_run"]["summary"]["comparison"]
        self.assertTrue(comparison["has_previous"])
        self.assertEqual(comparison["rank_changes"][0]["change"], 7)
        title_change = next(row for row in comparison["page_changes"] if row["field"] == "title")
        self.assertEqual(title_change["before"], "")
        self.assertEqual(title_change["after"], "Improved Denver Plumbing and Emergency Repair")
        resolved_codes = {issue["code"] for issue in second["resolved_issues"]}
        self.assertIn("missing_title", resolved_codes)
        self.assertIn("noindex", resolved_codes)
        self.assertEqual(len(second["history"]), 2)

    def test_unsafe_dns_is_blocked_before_any_http_request(self):
        calls = []

        def request(*args, **kwargs):
            calls.append((args, kwargs))
            raise AssertionError("HTTP must not be called")

        store = WebsiteMonitorStore(self.db, request_func=request, resolver=lambda _host: ["127.0.0.1"])
        site = store.create_site({"name": "Unsafe resolution", "url": "https://example.com", "keywords": []})
        result = store.scan_site(site["id"], {"pagespeed_api_key": "must-not-be-used"})
        self.assertEqual(result["latest_run"]["status"], "completed_with_errors")
        self.assertEqual(result["latest_run"]["overall_score"], 0)
        self.assertEqual(calls, [])
        self.assertIn("private or reserved", result["latest_page"]["fetch_error"])

    def test_provider_error_is_recorded_without_losing_page_audit(self):
        class ProviderFailure(ScenarioRequester):
            def __call__(self, method, url, **kwargs):
                if url in {PAGESPEED_ENDPOINT, DATAFORSEO_ENDPOINT}:
                    return FakeResponse(503, "temporarily unavailable")
                return super().__call__(method, url, **kwargs)

        requester = ProviderFailure()
        store = WebsiteMonitorStore(self.db, request_func=requester, resolver=safe_resolver)
        site = store.create_site({
            "name": "Example", "url": "https://example.com", "location": "United States",
            "keywords": ["example keyword"],
        })
        result = store.scan_site(site["id"], self.settings)
        self.assertEqual(result["latest_run"]["status"], "completed_with_errors")
        self.assertEqual(result["latest_page"]["status_code"], 200)
        self.assertEqual(result["latest_rankings"][0]["status"], "error")
        codes = {issue["code"] for issue in result["open_issues"]}
        self.assertIn("pagespeed_error", codes)
        self.assertIn("dataforseo_error", codes)

    def test_global_summary_uses_latest_positive_health_scores(self):
        owned = self.create_site()
        self.store.scan_site(owned["id"], self.settings)
        self.create_site(name="Competitor", url="https://competitor.example", site_type="observed", keywords=[])
        summary = self.store.get_summary()
        self.assertEqual(summary["site_count"], 2)
        self.assertEqual(summary["owned_site_count"], 1)
        self.assertEqual(summary["observed_site_count"], 1)
        self.assertGreater(summary["average_health_score"], 0)
        self.assertEqual(len(summary["sites"]), 2)


if __name__ == "__main__":
    unittest.main()
