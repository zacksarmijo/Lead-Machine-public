"""Smoke test for lead_vault_scraper.

Runs against real URLs. Skips gracefully if network is unavailable.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from lead_vault_scraper import ScrapedSite, save_scraped_assets, scrape_site


SKIP_NETWORK = os.environ.get("SKIP_NETWORK_TESTS", "").lower() in ("1", "true", "yes")


class ScraperOfflineTests(unittest.TestCase):
    """Tests that don't require network."""

    def test_invalid_url_returns_error(self) -> None:
        result = scrape_site("not a url")
        self.assertFalse(result.ok)
        self.assertTrue(result.error)

    def test_empty_url_returns_error(self) -> None:
        result = scrape_site("")
        self.assertFalse(result.ok)

    def test_private_network_urls_are_blocked(self) -> None:
        result = scrape_site("http://127.0.0.1:8000", mode="static")
        self.assertFalse(result.ok)
        self.assertIn("blocked", result.error.lower())

    def test_normalize_adds_https(self) -> None:
        # Passes through _normalize_url — scheme should be forced to https.
        from lead_vault_scraper import _normalize_url
        self.assertEqual(_normalize_url("example.com"), "https://example.com")
        self.assertEqual(_normalize_url("  example.com/path  "), "https://example.com/path")

    def test_clean_phone_formats_us_numbers(self) -> None:
        from lead_vault_scraper import _clean_phone
        # 555 exchange is reserved / fictional — now rejected
        self.assertEqual(_clean_phone("3035551212"), "")
        # Real-looking numbers pass (_clean_phone accepts raw digits;
        # the formatting requirement lives in PHONE_RE for extraction).
        self.assertEqual(_clean_phone("3034441212"), "(303) 444-1212")
        self.assertEqual(_clean_phone("+1-303-444-1212"), "(303) 444-1212")
        self.assertEqual(_clean_phone("303.444.1212"), "(303) 444-1212")
        self.assertEqual(_clean_phone("444-1212"), "")  # too short

    def test_phone_regex_requires_formatting(self) -> None:
        """Raw 10-digit hash strings should NOT match the extraction regex."""
        from lead_vault_scraper import PHONE_RE
        # Real phones with separators — must match
        self.assertTrue(PHONE_RE.search("Call us at (303) 444-1212 today"))
        self.assertTrue(PHONE_RE.search("303-444-1212"))
        self.assertTrue(PHONE_RE.search("303.444.1212"))
        self.assertTrue(PHONE_RE.search("+1-303-444-1212"))
        # Raw 10-digit runs embedded in hashes — must NOT match
        self.assertFalse(PHONE_RE.search("abc3034441212def"))
        self.assertFalse(PHONE_RE.search("asset-9060176997-hash"))
        # Plain unseparated digits alone — must NOT match
        self.assertFalse(PHONE_RE.search("3034441212"))

    def test_clean_phone_rejects_invalid_nanp(self) -> None:
        """Invalid area codes / exchange codes must be rejected."""
        from lead_vault_scraper import _clean_phone
        # Area code starting with 0 or 1 is invalid
        self.assertEqual(_clean_phone("0755451611"), "")
        self.assertEqual(_clean_phone("1884471000"), "")
        # Exchange code starting with 0 or 1
        self.assertEqual(_clean_phone("9060176997"), "")
        # N11 codes (211, 311, 411, 511, 611, 711, 811, 911)
        self.assertEqual(_clean_phone("9114441212"), "")
        # All same digit
        self.assertEqual(_clean_phone("8888888888"), "")
        # Sequential
        self.assertEqual(_clean_phone("1234567890"), "")
        # Previously-seen real fakes from mamabearteam.com output
        for fake in ("1880474100", "9130017987", "7764608000", "3920913419"):
            # Area/exchange starting with 0, 1, or N11 should all reject
            result = _clean_phone(fake)
            if result:
                # If any pass through, explicitly assert we understand why
                area = fake[0:3] if len(fake) == 10 else fake[1:4]
                exchange = fake[3:6] if len(fake) == 10 else fake[4:7]
                self.assertNotIn(area[0], "01", f"{fake} -> {result} has invalid area")
                self.assertNotIn(exchange[0], "01", f"{fake} -> {result} has invalid exchange")


class PhotoRankingTests(unittest.TestCase):
    def test_content_photos_rank_above_platform_chrome(self) -> None:
        from bs4 import BeautifulSoup
        from lead_vault_scraper import ScrapedSite, _extract_media
        html = """
        <html><body>
            <img src="https://app.highnote.io/static/ui-icon.png" width="200" height="200"/>
            <img src="https://cdn.example.com/wp-content/uploads/2024/hero.jpg" width="800" height="600"/>
            <img src="https://cdn.example.com/generic-image.png" width="400" height="300"/>
            <img src="https://backend.example.com/presentation-asset/real-photo.png" width="800" height="600"/>
        </body></html>
        """
        soup = BeautifulSoup(html, "lxml")
        result = ScrapedSite(final_url="https://example.com/")
        _extract_media(soup, result)
        # First two should be content (wp-content, presentation-asset), last = chrome
        self.assertIn("wp-content", result.photos[0])
        self.assertIn("presentation-asset", result.photos[1])
        # Chrome photo ranked last
        self.assertIn("/static/ui-icon.png", result.photos[-1])

    def test_save_scraped_assets_writes_files(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            sample = ScrapedSite(
                source_url="https://example.com",
                final_url="https://example.com",
                title="Example",
                main_text="Hello world.",
                ok=True,
            )
            out_dir = save_scraped_assets("lead_123", sample, td)
            self.assertTrue((out_dir / "scrape.json").exists())
            self.assertTrue((out_dir / "main_text.txt").exists())
            self.assertIn("Example", (out_dir / "scrape.json").read_text(encoding="utf-8"))

    def test_trafilatura_text_extraction_used_when_available(self) -> None:
        import lead_vault_scraper
        from bs4 import BeautifulSoup
        from unittest.mock import patch

        class FakeTrafilatura:
            @staticmethod
            def extract(*args, **kwargs):  # noqa: ARG004
                return "Clean main content\n\nWithout navigation"

        html = """
        <html><body>
          <nav>Home Services Contact</nav>
          <main><h1>Messy fallback text</h1></main>
        </body></html>
        """
        soup = BeautifulSoup(html, "lxml")
        result = ScrapedSite(source_url="https://example.com", final_url="https://example.com")
        with patch.object(lead_vault_scraper, "_trafilatura", FakeTrafilatura):
            lead_vault_scraper._extract_body_text(html, soup, result)
        self.assertEqual(result.main_text, "Clean main content\n\nWithout navigation")
        self.assertIn("text: trafilatura", result.tech_hints)


class SmartCrawlTests(unittest.TestCase):
    def test_discovers_same_site_high_value_pages(self) -> None:
        from lead_vault_scraper import _discover_inner_page_urls

        html = """
        <html><body>
          <a href="/privacy">Privacy</a>
          <a href="/contact">Contact Us</a>
          <a href="/services">Services</a>
          <a href="https://other.example/about">Other About</a>
          <a href="/about-us?ref=nav">About</a>
          <a href="/menu.pdf">PDF Menu</a>
          <a href="/gallery">Gallery</a>
          <a href="/team">Team</a>
        </body></html>
        """
        urls = _discover_inner_page_urls(html, "https://example.com/")
        self.assertEqual(urls[0], "https://example.com/contact")
        self.assertIn("https://example.com/services", urls)
        self.assertIn("https://example.com/about-us", urls)
        self.assertNotIn("https://example.com/privacy", urls)
        self.assertNotIn("https://example.com/menu.pdf", urls)
        self.assertLessEqual(len(urls), 6)

    def test_smart_crawl_merges_inner_page_evidence(self) -> None:
        import lead_vault_scraper
        from unittest.mock import patch

        homepage = """
        <html><head><title>Home</title></head><body>
          <nav><a href="/services">Services</a><a href="/contact">Contact</a></nav>
          <main><h1>Example Biz</h1><p>Homepage copy for a local service company.</p></main>
        </body></html>
        """
        services = """
        <html><head><title>Services</title></head><body>
          <main><h1>Services</h1><p>Drain cleaning, water heaters, and emergency repair.</p></main>
        </body></html>
        """
        contact = """
        <html><head><title>Contact</title></head><body>
          <main><h1>Contact</h1><p>Call (303) 444-1212 or email hello@example.com.</p></main>
        </body></html>
        """

        def fake_fetch_static(url, timeout, result):  # noqa: ARG001
            result.final_url = url
            result.status_code = 200
            result.has_https = True
            if url.endswith("/services"):
                return services, ""
            if url.endswith("/contact"):
                return contact, ""
            return homepage, ""

        with patch.object(lead_vault_scraper, "_fetch_static", fake_fetch_static), \
                patch.object(lead_vault_scraper, "_robots_allowed", lambda url: (True, "")), \
                patch.object(lead_vault_scraper, "INNER_CRAWL_DELAY_SECONDS", 0):
            result = scrape_site("https://example.com", mode="static")

        self.assertTrue(result.ok, result.error)
        self.assertGreaterEqual(len(result.crawled_pages), 2)
        self.assertIn("(303) 444-1212", result.phones)
        self.assertIn("hello@example.com", result.emails)
        self.assertIn("Services", result.headings)
        self.assertIn("Contact", result.headings)
        self.assertIn("smart crawl: inner pages", result.tech_hints)
        self.assertEqual(
            result.site_blueprint.get("generator_fit"),
            "multi_page_blueprint_needed",
        )

    def test_blueprint_detects_auth_boundary_without_crawling_it(self) -> None:
        import lead_vault_scraper
        from unittest.mock import patch

        homepage = """
        <html><head><title>Home</title></head><body>
          <nav>
            <a href="/services">Services</a>
            <a href="/contact">Contact</a>
            <a href="/bookings">Book Online</a>
            <a href="/login">Client Sign In</a>
            <a href="/terms">Terms</a>
          </nav>
          <form action="/login"><input type="password" name="password"></form>
          <main><h1>Example Biz</h1><p>Public homepage content for a local service company.</p></main>
        </body></html>
        """
        services = """
        <html><head><title>Services</title></head><body>
          <main><h1>Services</h1><p>Backflow testing and fire inspection.</p></main>
        </body></html>
        """
        contact = """
        <html><head><title>Contact</title></head><body>
          <main><h1>Contact</h1><p>Call (303) 444-1212.</p></main>
        </body></html>
        """
        fetched: list[str] = []

        def fake_fetch_static(url, timeout, result):  # noqa: ARG001
            fetched.append(url)
            result.final_url = url
            result.status_code = 200
            result.has_https = True
            if url.endswith("/services"):
                return services, ""
            if url.endswith("/contact"):
                return contact, ""
            if url.endswith("/bookings"):
                result.final_url = "https://example.com/m/login?r=%2Fm%2Fbookings"
                return "<html><head><title>Login</title></head><body>Sign in</body></html>", ""
            if url.endswith("/login"):
                self.fail("Auth/login page should be detected, not crawled")
            return homepage, ""

        with patch.object(lead_vault_scraper, "_fetch_static", fake_fetch_static), \
                patch.object(lead_vault_scraper, "_robots_allowed", lambda url: (True, "")), \
                patch.object(lead_vault_scraper, "INNER_CRAWL_DELAY_SECONDS", 0):
            result = scrape_site("https://example.com", mode="static")

        self.assertTrue(result.ok, result.error)
        self.assertNotIn("https://example.com/login", fetched)
        crawled_urls = {page.get("url") for page in result.crawled_pages}
        self.assertNotIn("https://example.com/m/login?r=%2Fm%2Fbookings", crawled_urls)
        blueprint = result.site_blueprint
        self.assertTrue(blueprint.get("auth_detected"))
        self.assertIn("auth_or_portal_detected", blueprint.get("risk_flags") or [])
        self.assertIn("auth_form_detected", blueprint.get("risk_flags") or [])
        skipped_reasons = {
            item.get("reason") for item in blueprint.get("skipped_pages") or []
        }
        self.assertIn("auth_or_private_area_detected_not_crawled", skipped_reasons)
        self.assertIn("legal_policy_page_recorded_not_crawled", skipped_reasons)
        crawl_errors = {item.get("error") for item in result.crawl_errors}
        self.assertIn("Skipped auth/private redirect", crawl_errors)


@unittest.skipIf(SKIP_NETWORK, "SKIP_NETWORK_TESTS set")
class ScraperLiveTests(unittest.TestCase):
    """Live scrape. Disable with SKIP_NETWORK_TESTS=1."""

    def test_scrape_example_com(self) -> None:
        result = scrape_site("https://example.com", mode="static")
        if not result.ok and "Blocked by robots" in result.error:
            self.skipTest("example.com robots blocked this UA")
        self.assertTrue(result.ok, f"scrape failed: {result.error}")
        self.assertIn("example", result.title.lower())
        self.assertTrue(result.has_https)
        self.assertGreater(len(result.main_text), 0)


class SpaHeuristicTests(unittest.TestCase):
    def test_empty_react_shell_detected(self) -> None:
        from lead_vault_scraper import _looks_like_spa_shell
        shell = (
            "<!DOCTYPE html><html><head><title>App</title></head>"
            '<body><div id="root"></div><script src="/bundle.js"></script></body></html>'
        )
        self.assertTrue(_looks_like_spa_shell(shell))

    def test_real_content_not_flagged(self) -> None:
        from lead_vault_scraper import _looks_like_spa_shell
        # Body text well past THIN_HTML_MIN_BODY_CHARS (400) — realistic
        # small-business landing page content length.
        body_paragraph = (
            "Acme Plumbing has served the greater Denver metro area since 2004, "
            "specializing in 24/7 emergency plumbing, drain cleaning, tankless "
            "water heater installation, sewer line repair, and new construction "
            "rough-in. Our licensed and bonded team carries liability insurance "
            "well above state minimums and backs every repair with a one-year "
            "warranty. Call (303) 555-0100 for a same-day free estimate or "
            "book online through our secure scheduler."
        )
        real = (
            "<!DOCTYPE html><html><head>"
            "<meta charset='utf-8'><title>Acme Plumbing — Denver</title>"
            "<meta name='description' content='Emergency plumbing in Denver.'>"
            "</head><body>"
            "<header><nav><a href='/'>Home</a><a href='/services'>Services</a>"
            "<a href='/contact'>Contact</a></nav></header>"
            f"<main><h1>Acme Plumbing</h1><p>{body_paragraph}</p>"
            f"<p>{body_paragraph}</p></main>"
            "<footer>Licensed in CO.</footer></body></html>"
        )
        self.assertFalse(_looks_like_spa_shell(real))


if __name__ == "__main__":
    unittest.main()
