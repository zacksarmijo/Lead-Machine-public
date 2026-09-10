from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from lead_vault_preview_qa import (  # noqa: E402
    PREVIEW_QA_FILE,
    evaluate_viewport_metrics,
    run_preview_qa,
)


class MissingBrowserChromium:
    def launch(self, headless=True, **kwargs):
        raise RuntimeError(
            "BrowserType.launch: Executable doesn't exist at C:\\ms-playwright\\chrome.exe\n"
            "Looks like Playwright was just installed or updated.\n"
            "Please run the following command to download new browsers:\n"
            "    playwright install"
        )


class MissingBrowserPlaywright:
    chromium = MissingBrowserChromium()


class MissingBrowserFactory:
    def __call__(self):
        return self

    def __enter__(self):
        return MissingBrowserPlaywright()

    def __exit__(self, exc_type, exc, tb):
        return False


class LeadVaultPreviewQaTests(unittest.TestCase):
    def test_missing_html_writes_failed_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "generated" / "x"
            report = run_preview_qa(Path(tmp) / "missing.html", output_dir)

            self.assertFalse(report["ok"])
            self.assertFalse(report["passed"])
            self.assertEqual(report["status"], "failed")
            self.assertEqual(report["issues"][0]["rule"], "missing_html")

            saved = output_dir / "preview_qa" / PREVIEW_QA_FILE
            self.assertTrue(saved.exists())
            saved_report = json.loads(saved.read_text(encoding="utf-8"))
            self.assertEqual(saved_report["issues"][0]["rule"], "missing_html")

    def test_metrics_flags_blank_sparse_and_overflowing_page(self):
        issues = evaluate_viewport_metrics(
            {
                "body_height": 80,
                "text_chars": 12,
                "image_count": 0,
                "horizontal_overflow_px": 32,
            },
            viewport="mobile",
            screenshot_nonblank=False,
        )
        rules = {issue["rule"] for issue in issues}
        self.assertIn("blank_screenshot", rules)
        self.assertIn("body_too_short", rules)
        self.assertIn("content_too_sparse", rules)
        self.assertIn("horizontal_overflow", rules)

    def test_metrics_flags_motion_runtime_contract_breaks(self):
        issues = evaluate_viewport_metrics(
            {
                "body_height": 640,
                "text_chars": 300,
                "image_count": 1,
                "horizontal_overflow_px": 0,
                "runtime_attr_count": 4,
                "runtime_css": False,
                "runtime_js": True,
                "runtime_loaded": False,
                "reveal_count": 2,
                "revealed_count": 0,
            },
            viewport="desktop",
            screenshot_nonblank=True,
            console_errors=["ReferenceError: SummitMotionRuntime is not defined"],
        )
        rules = {issue["rule"] for issue in issues}
        self.assertIn("runtime_assets_missing", rules)
        self.assertIn("runtime_not_loaded", rules)
        self.assertIn("reveal_not_visible", rules)
        self.assertIn("console_errors", rules)

    def test_missing_playwright_browser_writes_skipped_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            mockup = Path(tmp) / "mockup.html"
            mockup.write_text("<html><body>Preview</body></html>", encoding="utf-8")
            output_dir = Path(tmp) / "generated" / "x"

            report = run_preview_qa(
                mockup,
                output_dir,
                playwright_factory=MissingBrowserFactory(),
            )

            self.assertTrue(report["ok"])
            self.assertIsNone(report["passed"])
            self.assertEqual(report["status"], "skipped")
            self.assertEqual(report["issues"], [])
            playwright_status = report["tool_runs"]["playwright"]
            self.assertIn("python -m playwright install chromium", playwright_status)
            self.assertNotIn("Looks like Playwright", playwright_status)

            saved = output_dir / "preview_qa" / PREVIEW_QA_FILE
            saved_report = json.loads(saved.read_text(encoding="utf-8"))
            self.assertEqual(saved_report["status"], "skipped")


if __name__ == "__main__":
    unittest.main()
