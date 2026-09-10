"""Smoke test agent review for both providers."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "colorado-lead-machine"))

from lead_vault_agent_review import run_agent_review

settings = json.loads((Path(__file__).parent / "lead_vault_settings.json").read_text(encoding="utf-8"))

MOCK_LEAD = {
    "business_name": "Test Plumbing Co",
    "city_area": "Denver, CO",
    "website_quality_score": 45,
    "opportunity_score": 78,
    "freshness_status": "fresh",
    "data": {
        "Business Name": "Test Plumbing Co",
        "Business Type": "Plumber",
        "City/Area": "Denver, CO",
        "Reviews": "22",
    },
    "latest_audit": {
        "Resolved Website URL": "https://example.com",
        "Audit Confidence": "0.85",
        "Last Verified At": "2026-04-01T12:00:00Z",
        "CTA Strength": "weak",
        "Contact Form Status": "missing",
        "Booking Flow Status": "missing",
        "SSL Status": "valid",
        "Mobile Readiness": "weak",
        "Page Title": "Test Plumbing",
        "Meta Description": "We fix pipes",
        "On-Page Phones": "303-555-1234",
        "On-Page Emails": "",
        "SEO Basics": "weak",
        "Page Speed Signal": "slow",
        "Audit Issues": json.dumps([
            "No call-to-action above the fold",
            "No online booking",
            "No contact form",
        ]),
        "Website Evidence Summary": "Site has phone but no forms. Slow mobile.",
        "Business Impact Summary": json.dumps([
            "Losing quote requests to faster competitors",
            "No after-hours capture",
        ]),
    },
}


def run(provider, key_field):
    key = settings.get(key_field, "")
    if not key:
        print(f"[{provider}] SKIP — no key in settings.{key_field}")
        return
    print(f"\n[{provider}] calling with key ...{key[-6:]}")
    result = run_agent_review(
        lead=MOCK_LEAD,
        api_key=key,
        provider=provider,
        force=True,
    )
    print(f"  status: {result['status']}")
    print(f"  ok: {result['ok']}")
    if result.get("error"):
        print(f"  error: {result['error']}")
    else:
        r = result["review"]
        print(f"  verdict: {r['verdict']}")
        print(f"  action: {r['recommended_action']}")
        print(f"  angle: {r['best_pitch_angle'][:60]}")


run("OpenAI", "openai_api_key")
run("Anthropic", "anthropic_api_key")
