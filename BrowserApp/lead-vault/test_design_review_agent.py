from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from design_review_agent import DESIGN_REVIEW_FILE, review_generated_website, save_design_review


class DesignReviewAgentTests(unittest.TestCase):
    def _write_html(self, html: str) -> tuple[tempfile.TemporaryDirectory, Path]:
        tmp = tempfile.TemporaryDirectory()
        path = Path(tmp.name) / "mockup.html"
        path.write_text(html, encoding="utf-8")
        return tmp, path

    def test_flags_weak_sample_html(self) -> None:
        tmp, path = self._write_html(
            """<!DOCTYPE html><html><body>
            <section data-summit-section="hero"><h1>Welcome to Our Company</h1>
            <a href="#more">Learn More</a></section>
            <section><p>Lorem ipsum placeholder text.</p></section>
            </body></html>"""
        )
        self.addCleanup(tmp.cleanup)
        report = review_generated_website(
            path,
            lead={
                "business_name": "Summit Plumbing",
                "city_area": "Denver",
                "phone": "(303) 555-0100",
            },
        )
        rules = {issue.rule for issue in report.issues}
        self.assertIn("generic_headline", rules)
        self.assertIn("weak_cta", rules)
        self.assertIn("placeholder_copy", rules)
        self.assertFalse(report.passed)

    def test_passes_strong_local_service_html(self) -> None:
        tmp, path = self._write_html(
            """<!DOCTYPE html><html><body>
            <header><a href="tel:3035550100">Call (303) 555-0100</a></header>
            <section data-summit-section="hero"><h1>Drain Cleaning in Denver</h1>
            <p>Summit Plumbing helps Denver homeowners with drain cleaning and water heaters.</p>
            <a href="tel:3035550100">Call Now</a></section>
            <section data-summit-section="trust"><h2>Local Service</h2><p>Serving Denver with clear scheduling and practical plumbing support.</p></section>
            <section data-summit-section="services"><h2>Services</h2><p>Drain Cleaning. Water Heaters.</p></section>
            <section data-summit-section="contact"><h2>Request Service</h2><a href="tel:3035550100">Call (303) 555-0100</a></section>
            </body></html>"""
        )
        self.addCleanup(tmp.cleanup)
        report = review_generated_website(
            path,
            lead={
                "business_name": "Summit Plumbing",
                "city_area": "Denver",
                "phone": "(303) 555-0100",
            },
        )
        self.assertTrue(report.passed)
        self.assertGreaterEqual(report.score, 80)

    def test_flags_repeated_cards_and_saves_report(self) -> None:
        cards = "".join(
            f'<div class="card shadow rounded-lg"><div class="card">Item {i}</div></div>'
            for i in range(16)
        )
        tmp, path = self._write_html(
            f"<!DOCTYPE html><html><body><h1>Service in Denver</h1><a href='tel:3035550100'>Call Now</a>{cards}</body></html>"
        )
        self.addCleanup(tmp.cleanup)
        report = review_generated_website(
            path,
            lead={"business_name": "Service", "city_area": "Denver", "phone": "(303) 555-0100"},
        )
        rules = {issue.rule for issue in report.issues}
        self.assertIn("too_many_same_shaped_cards", rules)
        self.assertIn("nested_cards", rules)
        saved = save_design_review(report, Path(tmp.name))
        self.assertEqual(saved.name, DESIGN_REVIEW_FILE)
        data = json.loads(saved.read_text(encoding="utf-8"))
        self.assertIn("issues", data)


if __name__ == "__main__":
    unittest.main()
