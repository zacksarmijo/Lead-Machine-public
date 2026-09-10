"""Offline regression checks for malicious scrape URLs and generated previews."""
from __future__ import annotations

import socket
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import lead_vault_scraper as scraper
from lead_vault_preview_qa import PREVIEW_ORIGIN, _route_preview_asset
from lead_vault_preview_qa import run_preview_qa
from lead_vault_website_validator import run_lighthouse, run_pa11y


PUBLIC_DNS = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]


def response(url, status=200, body=b"<html>Public content</html>", headers=None):
    result = Mock(url=url, status_code=status)
    result.headers = headers or {"Content-Type": "text/html"}
    result.iter_content.return_value = [body]
    return result


class ScraperNetworkSecurityTests(unittest.TestCase):
    def setUp(self):
        self.dns = patch.object(scraper.socket, "getaddrinfo", return_value=PUBLIC_DNS)
        self.dns.start()
        self.addCleanup(self.dns.stop)

    def fake_session(self, *responses):
        session = Mock()
        session.get.side_effect = responses
        manager = Mock()
        manager.__enter__ = Mock(return_value=session)
        manager.__exit__ = Mock(return_value=False)
        return session, patch.object(scraper, "_public_session", return_value=manager)

    def test_redirect_to_private_host_never_contacts_destination(self):
        first = response("https://example.test/", 302, headers={"Location": "http://127.0.0.1/private"})
        session, manager = self.fake_session(first)
        with manager:
            html, error = scraper._fetch_static("https://example.test/", (1, 1), scraper.ScrapedSite())
        self.assertEqual(html, "")
        self.assertIn("blocked", error.lower())
        self.assertEqual(session.get.call_count, 1)
        self.assertFalse(session.get.call_args.kwargs["allow_redirects"])
        first.close.assert_called_once()

    def test_valid_public_redirect_is_followed_and_content_returned(self):
        first = response("https://example.test/start", 301, headers={"Location": "/about"})
        final = response("https://example.test/about")
        session, manager = self.fake_session(first, final)
        result = scraper.ScrapedSite()
        with manager:
            html, error = scraper._fetch_static("https://example.test/start", (1, 1), result)
        self.assertEqual(error, "")
        self.assertIn("Public content", html)
        self.assertEqual(result.final_url, "https://example.test/about")
        self.assertEqual(session.get.call_args_list[1].args[0], result.final_url)

    def test_robots_redirect_cannot_reach_metadata_service(self):
        first = response("https://example.test/robots.txt", 302, headers={"Location": "http://169.254.169.254/latest/"})
        session, manager = self.fake_session(first)
        with manager:
            allowed, error = scraper._robots_allowed("https://example.test/")
        self.assertFalse(allowed)
        self.assertIn("unsafe", error)
        self.assertEqual(session.get.call_count, 1)

    def test_robots_disallow_is_still_respected(self):
        data = response("https://example.test/robots.txt", body=b"User-agent: *\nDisallow: /private\n")
        _, manager = self.fake_session(data)
        with manager:
            self.assertFalse(scraper._robots_allowed("https://example.test/private")[0])

    def test_failed_dns_and_credential_urls_are_rejected(self):
        with patch.object(scraper.socket, "getaddrinfo", side_effect=socket.gaierror):
            self.assertIn("resolved", scraper._url_security_error("https://example.test/"))
        self.assertIn("credentials", scraper._url_security_error("https://user:password@example.test/"))
        self.assertTrue(scraper._url_security_error("https://example.test:bad/"))
        self.assertTrue(scraper._url_security_error("https://[invalid/"))
        self.assertTrue(scraper._url_security_error("http://100.64.0.1/"))

    def test_session_does_not_use_ambient_credentials_or_proxy(self):
        with scraper._public_session() as session:
            self.assertFalse(session.trust_env)
            self.assertEqual(session.proxies, {})
            self.assertIsNone(session.auth)

    def test_connection_rechecks_dns_before_connecting(self):
        with scraper._public_session() as session:
            pool = session.get_adapter("https://").poolmanager.connection_from_url("https://example.test/")
            connection = pool.ConnectionCls("example.test", port=443)
            private = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]
            with patch.object(scraper.socket, "getaddrinfo", return_value=private), \
                    patch("urllib3.util.connection.create_connection") as connect:
                with self.assertRaises(OSError):
                    connection._new_conn()
                connect.assert_not_called()

    def test_connection_pins_numeric_address_and_preserves_tls_hostname(self):
        with patch("urllib3.util.connection.create_connection") as connect:
            with scraper._public_session() as session:
                pool = session.get_adapter("https://").poolmanager.connection_from_url("https://example.test/")
                connection = pool.ConnectionCls("example.test", port=443)
                connection._new_conn()
                self.assertEqual(connect.call_args.args[0], ("93.184.216.34", 443))
                self.assertEqual(connection.host, "example.test")

    def test_browser_subrequest_redirect_is_checked_before_private_fetch(self):
        first = response("https://example.test/image", 302, headers={"Location": "http://10.0.0.1/"})
        session, manager = self.fake_session(first)
        route = Mock(request=SimpleNamespace(url="https://example.test/image", method="GET"))
        with manager:
            scraper._route_public_browser_request(route)
        route.abort.assert_called_once_with("blockedbyclient")
        route.fulfill.assert_not_called()
        self.assertEqual(session.get.call_count, 1)

    def test_browser_does_not_submit_forms(self):
        route = Mock(request=SimpleNamespace(url="https://example.test/submit", method="POST"))
        with patch.object(scraper, "_request_public") as fetch:
            scraper._route_public_browser_request(route)
        fetch.assert_not_called()
        route.abort.assert_called_once()

    def test_browser_boundary_is_installed_before_navigation(self):
        playwright = MagicMock()
        context = playwright.chromium.launch.return_value.new_context.return_value
        page = context.new_page.return_value
        page.goto.return_value = SimpleNamespace(status=200, url="https://example.test/final")
        page.content.return_value = "<html>Rendered</html>"
        manager = MagicMock()
        manager.__enter__.return_value = playwright
        api = SimpleNamespace(sync_playwright=Mock(return_value=manager), Error=RuntimeError)
        with patch.dict(sys.modules, {"playwright.sync_api": api}), \
                patch.object(scraper, "_request_public", return_value=response("https://example.test/final")):
            html, error = scraper._fetch_browser("https://example.test/start", scraper.ScrapedSite())
        self.assertEqual(error, "")
        self.assertIn("Rendered", html)
        self.assertTrue(playwright.chromium.launch.call_args.kwargs["chromium_sandbox"])
        self.assertEqual(playwright.chromium.launch.return_value.new_context.call_args.kwargs["service_workers"], "block")
        self.assertEqual(page.goto.call_args.args[0], "https://example.test/final")
        context.route.assert_called_once_with("**/*", scraper._route_public_browser_request)
        context.route_web_socket.assert_called_once()
        operations = [call[0] for call in context.method_calls]
        self.assertLess(operations.index("route"), operations.index("new_page"))
        self.assertLess(operations.index("route_web_socket"), operations.index("new_page"))


class PreviewBoundaryTests(unittest.TestCase):
    def test_preview_navigates_to_virtual_origin_with_boundary_installed(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "mockup.html"
            path.write_text("<h1>Preview</h1>", encoding="utf-8")
            playwright = MagicMock()
            context = playwright.chromium.launch.return_value.new_context.return_value
            page = context.new_page.return_value
            page.screenshot.side_effect = lambda **kwargs: Path(kwargs["path"]).write_bytes(b"fake png")
            page.evaluate.return_value = {"body_height": 800, "text_chars": 500, "image_count": 1}
            manager = MagicMock()
            manager.__enter__.return_value = playwright
            with patch("lead_vault_preview_qa._png_nonblank", return_value=True):
                report = run_preview_qa(path, playwright_factory=lambda: manager)
            self.assertEqual(report["status"], "completed")
            self.assertEqual(report["network_policy"], "offline: generated bundle assets only")
            self.assertTrue(playwright.chromium.launch.call_args.kwargs["chromium_sandbox"])
            self.assertEqual(context.route.call_count, 2)
            self.assertEqual(context.route_web_socket.call_count, 2)
            for call in page.goto.call_args_list:
                self.assertEqual(call.args[0], f"{PREVIEW_ORIGIN}/mockup.html")

    def test_only_bundle_assets_are_served(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "bundle"
            root.mkdir()
            (root / "page.html").write_text("<h1>Preview</h1>", encoding="utf-8")
            route = Mock(request=SimpleNamespace(url=f"{PREVIEW_ORIGIN}/page.html", method="GET"))
            _route_preview_asset(route, root)
            self.assertEqual(route.fulfill.call_args.kwargs["body"], b"<h1>Preview</h1>")
            self.assertIn("connect-src 'none'", route.fulfill.call_args.kwargs["headers"]["Content-Security-Policy"])

    def test_external_files_traversal_and_network_requests_are_blocked(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "bundle"
            root.mkdir()
            (Path(temp) / "private.txt").write_text("DO NOT SERVE", encoding="utf-8")
            urls = [
                f"{PREVIEW_ORIGIN}/%2e%2e/private.txt",
                f"{PREVIEW_ORIGIN}/..%5cprivate.txt",
                "file:///private.txt", "http://127.0.0.1:8000/settings",
                "https://example.test/tracker", "ws://localhost:8000/",
            ]
            for url in urls:
                with self.subTest(url=url):
                    route = Mock(request=SimpleNamespace(url=url, method="GET"))
                    _route_preview_asset(route, root)
                    route.abort.assert_called_once_with("blockedbyclient")
                    route.fulfill.assert_not_called()

    def test_unisolated_optional_browser_audits_never_spawn(self):
        with patch("lead_vault_website_validator.subprocess.run") as spawn:
            for audit in (run_lighthouse, run_pa11y):
                issues, status = audit(Path("untrusted.html"))
                self.assertEqual(issues, [])
                self.assertIn("skipped:", status)
                self.assertIn("boundary", status)
            spawn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
