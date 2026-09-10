"""Live smoke test for Phase 3 website generator.

Runs one real Anthropic call against the `test_lead` scraped fixture,
writes output to `<Lead Machine>/generated/test_lead/`, and runs the
validator over the result. Prints a summary to stdout.

Not a unit test — intentionally side-effecting. Costs real money.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

LEAD_VAULT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(LEAD_VAULT_DIR))

from lead_vault_website_generator import (
    WebsiteGenerator,
    WebsiteGeneratorError,
)
from lead_vault_website_validator import validate_html, save_report


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings_path = LEAD_VAULT_DIR / "lead_vault_settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    api_key = settings.get("anthropic_api_key", "").strip()
    model = settings.get("ai_model", "claude-sonnet-4-6").strip()
    if not api_key:
        print("FAIL: no anthropic_api_key in settings", file=sys.stderr)
        return 1

    lead = {
        "lead_key": "test_lead",
        "business_name": "Riverside Dental",
        "data": {
            "Business Name": "Riverside Dental",
            "Business Type": "Dentist",
            "City": "Littleton",
            "State": "CO",
        },
    }

    generator = WebsiteGenerator(api_key=api_key, model=model)
    print(f"Calling Anthropic with model={model} lead_key=test_lead ...")
    t0 = time.time()
    try:
        result = generator.generate(lead)
    except WebsiteGeneratorError as exc:
        print(f"FAIL generator: {exc}", file=sys.stderr)
        return 2
    elapsed = time.time() - t0
    html_size = result.mockup_path.stat().st_size
    print(
        f"OK generator: {elapsed:.1f}s  html={html_size} bytes  "
        f"mockup={result.mockup_path}"
    )

    report = validate_html(result.mockup_path)
    report_path = save_report(report, result.output_dir)
    print(
        f"Validator: passed={report.passed}  errors={report.error_count}  "
        f"warnings={report.warning_count}  report={report_path}"
    )
    if report.error_count:
        print("--- validation errors ---")
        for issue in report.issues:
            if issue.severity == "error":
                print(f"  [{issue.source}] {issue.rule}: {issue.message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
