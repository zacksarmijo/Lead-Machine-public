"""Tests for lead_vault_website_validator."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from lead_vault_website_validator import (
    ValidationIssue,
    ValidationReport,
    _htmlhint_binary,
    run_design_contract_checks,
    run_a11y_checks,
    run_htmlhint,
    run_structure_checks,
    save_report,
    validate_html,
)


GOOD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="A sample page.">
<title>Sample Dental</title>
</head>
<body>
<h1>Welcome to Sample Dental</h1>
<img src="hero.jpg" alt="Dentist office lobby">
<form>
  <label for="name">Name</label>
  <input id="name" type="text" name="name">
</form>
<button type="submit" aria-label="Submit">Send</button>
<a href="https://example.com" target="_blank" rel="noopener noreferrer">visit</a>
</body>
</html>
"""


class StructureCheckTests(unittest.TestCase):
    def test_clean_html_produces_no_errors(self) -> None:
        issues = run_structure_checks(GOOD_HTML)
        errors = [i for i in issues if i.severity == "error"]
        self.assertEqual(errors, [])

    def test_missing_doctype_flagged(self) -> None:
        html = GOOD_HTML.replace("<!DOCTYPE html>", "")
        issues = run_structure_checks(html)
        self.assertTrue(any(i.rule == "doctype" for i in issues))

    def test_missing_lang_flagged(self) -> None:
        html = GOOD_HTML.replace('<html lang="en">', "<html>")
        issues = run_structure_checks(html)
        self.assertTrue(any(i.rule == "html_lang" for i in issues))

    def test_missing_title_flagged(self) -> None:
        html = GOOD_HTML.replace("<title>Sample Dental</title>", "")
        issues = run_structure_checks(html)
        self.assertTrue(any(i.rule == "title" and i.severity == "error" for i in issues))

    def test_missing_viewport_flagged(self) -> None:
        html = GOOD_HTML.replace(
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            "",
        )
        issues = run_structure_checks(html)
        self.assertTrue(any(i.rule == "meta_viewport" for i in issues))

    def test_multiple_h1_warning(self) -> None:
        html = GOOD_HTML.replace(
            "<h1>Welcome to Sample Dental</h1>",
            "<h1>A</h1><h1>B</h1>",
        )
        issues = run_structure_checks(html)
        self.assertTrue(any(i.rule == "h1_multiple" for i in issues))

    def test_missing_h1_error(self) -> None:
        html = GOOD_HTML.replace(
            "<h1>Welcome to Sample Dental</h1>",
            "<p>no heading</p>",
        )
        issues = run_structure_checks(html)
        self.assertTrue(any(i.rule == "h1_missing" for i in issues))

    def test_csp_missing_warns(self) -> None:
        issues = run_structure_checks(GOOD_HTML)
        self.assertTrue(any(i.rule == "csp_meta_missing" for i in issues))

    def test_csp_present_passes(self) -> None:
        html_with_csp = GOOD_HTML.replace(
            '<meta name="description" content="A sample page.">',
            (
                '<meta name="description" content="A sample page.">\n'
                '<meta http-equiv="Content-Security-Policy" '
                'content="default-src \'self\'">'
            ),
        )
        issues = run_structure_checks(html_with_csp)
        self.assertFalse(any(i.rule == "csp_meta_missing" for i in issues))


class A11yCheckTests(unittest.TestCase):
    def test_img_without_alt_flagged(self) -> None:
        html = '<html lang="en"><body><img src="a.jpg"></body></html>'
        issues = run_a11y_checks(html)
        self.assertTrue(any(i.rule == "img_alt_missing" for i in issues))

    def test_img_with_alt_passes(self) -> None:
        html = '<html lang="en"><body><img src="a.jpg" alt="x"></body></html>'
        issues = run_a11y_checks(html)
        self.assertFalse(any(i.rule == "img_alt_missing" for i in issues))

    def test_input_without_label_warned(self) -> None:
        html = '<html lang="en"><body><input type="text" name="foo"></body></html>'
        issues = run_a11y_checks(html)
        self.assertTrue(any(i.rule == "form_label_missing" for i in issues))

    def test_input_with_label_passes(self) -> None:
        html = (
            '<html lang="en"><body>'
            '<label for="q">Q</label><input id="q" type="text" name="q">'
            "</body></html>"
        )
        issues = run_a11y_checks(html)
        self.assertFalse(any(i.rule == "form_label_missing" for i in issues))

    def test_input_wrapped_in_label_passes(self) -> None:
        html = '<html lang="en"><body><label>Q<input type="text" name="q"></label></body></html>'
        issues = run_a11y_checks(html)
        self.assertFalse(any(i.rule == "form_label_missing" for i in issues))

    def test_target_blank_without_noopener_warned(self) -> None:
        html = '<html lang="en"><body><a href="x" target="_blank">x</a></body></html>'
        issues = run_a11y_checks(html)
        self.assertTrue(any(i.rule == "target_blank_noopener" for i in issues))

    def test_target_blank_with_noopener_passes(self) -> None:
        html = (
            '<html lang="en"><body>'
            '<a href="x" target="_blank" rel="noopener">x</a>'
            "</body></html>"
        )
        issues = run_a11y_checks(html)
        self.assertFalse(any(i.rule == "target_blank_noopener" for i in issues))

    def test_empty_button_warned(self) -> None:
        html = '<html lang="en"><body><button></button></body></html>'
        issues = run_a11y_checks(html)
        self.assertTrue(any(i.rule == "button_accessible_name" for i in issues))

    def test_button_with_aria_label_passes(self) -> None:
        html = '<html lang="en"><body><button aria-label="Close"></button></body></html>'
        issues = run_a11y_checks(html)
        self.assertFalse(any(i.rule == "button_accessible_name" for i in issues))

    def test_external_script_without_sri_warns(self) -> None:
        html = (
            '<html lang="en"><body>'
            '<script src="https://cdn.example.com/lib.js"></script>'
            "</body></html>"
        )
        issues = run_a11y_checks(html)
        self.assertTrue(any(i.rule == "external_script_no_sri" for i in issues))

    def test_external_script_with_sri_passes(self) -> None:
        html = (
            '<html lang="en"><body>'
            '<script src="https://cdn.example.com/lib.js" '
            'integrity="sha384-abc"></script>'
            "</body></html>"
        )
        issues = run_a11y_checks(html)
        self.assertFalse(any(i.rule == "external_script_no_sri" for i in issues))

    def test_inline_event_handler_warns(self) -> None:
        html = (
            '<html lang="en"><body>'
            '<button onclick="doThing()">Click</button>'
            "</body></html>"
        )
        issues = run_a11y_checks(html)
        self.assertTrue(any(i.rule == "inline_event_handler" for i in issues))


DESIGN_BRIEF = {
    "business_name": "Sample Dental",
    "experience_dna": {
        "recommended_primitives": ["reveal_up", "gradient_mesh", "sticky_cta"],
        "blocked_primitives": ["cursor_spotlight"],
        "primitive_contracts": {
            "reveal_up": {"performance": {"max_instances": 2}},
            "gradient_mesh": {"performance": {"max_instances": 1}},
            "sticky_cta": {"performance": {"max_instances": 1}},
        },
    },
}


DESIGN_CONTRACT_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="A sample page.">
<meta http-equiv="Content-Security-Policy" content="default-src 'self'">
<title>Sample Dental</title>
<link rel="stylesheet" href="summit-motion.css" data-summit-motion-runtime="css">
<script defer src="summit-motion.js" data-summit-motion-runtime="js"></script>
</head>
<body>
<main>
  <section data-bg="gradient-mesh">
    <h1 data-motion="reveal-up">Welcome to Sample Dental</h1>
    <a data-motion="sticky-cta" href="tel:+15555550100">Call Sample Dental</a>
  </section>
</main>
</body>
</html>
"""


class DesignContractCheckTests(unittest.TestCase):
    def test_design_contract_passes_when_runtime_matches_brief(self) -> None:
        issues = run_design_contract_checks(DESIGN_CONTRACT_HTML, DESIGN_BRIEF)
        self.assertFalse([i for i in issues if i.severity == "error"])
        self.assertFalse(any(i.rule == "recommended_primitive_missing" for i in issues))

    def test_runtime_attrs_without_runtime_assets_error(self) -> None:
        html = (
            '<html lang="en"><body><h1 data-motion="reveal-up">'
            "Sample Dental</h1></body></html>"
        )
        issues = run_design_contract_checks(html, None)
        self.assertTrue(any(i.rule == "runtime_assets_missing" for i in issues))

    def test_missing_recommended_primitive_warns(self) -> None:
        html = DESIGN_CONTRACT_HTML.replace('data-motion="sticky-cta"', "")
        issues = run_design_contract_checks(html, DESIGN_BRIEF)
        self.assertTrue(any(i.rule == "recommended_primitive_missing" for i in issues))

    def test_blocked_primitive_errors(self) -> None:
        html = DESIGN_CONTRACT_HTML.replace(
            'data-bg="gradient-mesh"',
            'data-bg="gradient-mesh"><div data-bg="cursor-spotlight"',
        )
        issues = run_design_contract_checks(html, DESIGN_BRIEF)
        self.assertTrue(any(i.rule == "blocked_primitive_used" for i in issues))

    def test_water_attractor_primitive_is_recognized(self) -> None:
        brief = json.loads(json.dumps(DESIGN_BRIEF))
        brief["experience_dna"]["recommended_primitives"] = ["water_attractor"]
        brief["experience_dna"]["primitive_contracts"] = {
            "water_attractor": {"performance": {"max_instances": 1}}
        }
        html = DESIGN_CONTRACT_HTML.replace(
            'data-bg="gradient-mesh"',
            'data-bg="water-attractor" data-water-palette="aqua"',
        )
        issues = run_design_contract_checks(html, brief)
        self.assertFalse(any(i.rule == "recommended_primitive_missing" for i in issues))

    def test_primitive_budget_warning(self) -> None:
        html = DESIGN_CONTRACT_HTML.replace(
            "<h1 data-motion=\"reveal-up\">",
            '<p data-motion="reveal-up">One</p><p data-motion="reveal-up">Two</p><h1 data-motion="reveal-up">',
        )
        issues = run_design_contract_checks(html, DESIGN_BRIEF)
        self.assertTrue(any(i.rule == "primitive_budget_exceeded" for i in issues))

    def test_custom_runtime_motion_css_errors(self) -> None:
        html = DESIGN_CONTRACT_HTML.replace(
            "</head>",
            '<style>[data-motion="reveal-up"] { opacity: 0; transform: translateY(20px); }</style></head>',
        )
        issues = run_design_contract_checks(html, DESIGN_BRIEF)
        self.assertTrue(any(i.rule == "custom_runtime_motion_css" for i in issues))


class AlpineCspTests(unittest.TestCase):
    def test_alpine_without_unsafe_eval_errors(self) -> None:
        html = DESIGN_CONTRACT_HTML.replace(
            "</head>",
            '<script defer src="https://unpkg.com/alpinejs"></script></head>',
        ).replace(
            "<body>",
            '<body><nav x-data="{open:false}"><button @click="open=!open">Menu</button></nav>',
        )
        issues = run_structure_checks(html)
        self.assertTrue(any(i.rule == "alpine_csp_blocks_runtime" for i in issues))

    def test_alpine_with_unsafe_eval_passes_csp_check(self) -> None:
        html = DESIGN_CONTRACT_HTML.replace(
            "default-src 'self'",
            "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval' https://unpkg.com",
        ).replace(
            "</head>",
            '<script defer src="https://unpkg.com/alpinejs"></script></head>',
        ).replace(
            "<body>",
            '<body><nav x-data="{open:false}"><button @click="open=!open">Menu</button></nav>',
        )
        issues = run_structure_checks(html)
        self.assertFalse(any(i.rule == "alpine_csp_blocks_runtime" for i in issues))


class HtmlHintIntegrationTests(unittest.TestCase):
    def test_runs_when_binary_present(self) -> None:
        if _htmlhint_binary() is None:
            self.skipTest("htmlhint not installed — skipping live run")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.html"
            path.write_text(GOOD_HTML, encoding="utf-8")
            issues, status = run_htmlhint(path)
            self.assertEqual(status, "ok")
            self.assertIsInstance(issues, list)

    def test_detects_missing_alt(self) -> None:
        if _htmlhint_binary() is None:
            self.skipTest("htmlhint not installed — skipping live run")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.html"
            path.write_text(
                '<!DOCTYPE html><html lang="en"><head><title>t</title></head>'
                '<body><img src="x"></body></html>',
                encoding="utf-8",
            )
            issues, status = run_htmlhint(path)
            self.assertEqual(status, "ok")
            self.assertTrue(any("alt" in i.rule.lower() or "alt" in i.message.lower() for i in issues))


class ValidateHtmlTests(unittest.TestCase):
    def test_good_html_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.html"
            path.write_text(GOOD_HTML, encoding="utf-8")
            report = validate_html(path)
            self.assertTrue(report.passed, msg=f"issues: {report.issues}")

    def test_broken_html_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.html"
            path.write_text("<html><body>no head, no title</body></html>", encoding="utf-8")
            report = validate_html(path)
            self.assertFalse(report.passed)
            self.assertGreater(report.error_count, 0)

    def test_missing_file_fails(self) -> None:
        report = validate_html(Path("/does/not/exist.html"))
        self.assertFalse(report.passed)
        self.assertTrue(any(i.rule == "missing_file" for i in report.issues))

    def test_validate_html_loads_site_design_brief(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            html_path = root / "mockup.html"
            html_path.write_text(DESIGN_CONTRACT_HTML, encoding="utf-8")
            (root / "site_design_brief.json").write_text(
                json.dumps(DESIGN_BRIEF),
                encoding="utf-8",
            )
            report = validate_html(html_path)
            self.assertEqual(report.tool_runs["design_contract"], "ok")
            self.assertFalse(any(i.rule == "runtime_assets_missing_for_brief" for i in report.issues))


class ReportSerializationTests(unittest.TestCase):
    def test_save_report_writes_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = ValidationReport(
                passed=False,
                issues=[ValidationIssue("error", "structure", "title", "oops")],
                tool_runs={"htmlhint": "ok"},
            )
            out = save_report(report, Path(tmp))
            self.assertTrue(out.exists())
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(data["passed"], False)
            self.assertEqual(data["error_count"], 1)
            self.assertEqual(data["tool_runs"]["htmlhint"], "ok")


if __name__ == "__main__":
    unittest.main()
