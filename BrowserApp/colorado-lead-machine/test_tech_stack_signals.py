from __future__ import annotations

from scoring import compute_opportunity_score, compute_website_quality_score
from tech_stack import analyze_builtwith_payload, domain_for_lead


def test_builtwith_payload_flags_missing_analytics_and_stale_cms():
    payload = {
        "free1": {
            "domain": "example.com",
            "first": 1262304000,
            "last": 1451606400,
            "groups": [
                {
                    "name": "cms",
                    "live": 1,
                    "dead": 5,
                    "latest": 1451606400,
                    "oldest": 1262304000,
                    "categories": [{"name": "wordpress", "live": 1, "dead": 3}],
                }
            ],
        }
    }

    result = analyze_builtwith_payload(payload)

    assert result["BuiltWith Status"] == "Measured"
    assert result["BuiltWith Domain"] == "example.com"
    assert result["Tech Stack Signal"] == "Weak or outdated stack"
    assert result["Tech Stack Score"] >= 38
    assert "No analytics" in result["Tech Stack Weak Signals"]


def test_builtwith_payload_recognizes_modern_conversion_stack():
    payload = {
        "free1": {
            "domain": "modern.example",
            "groups": [
                {"name": "analytics", "live": 2, "dead": 0, "categories": [{"name": "web-analytics", "live": 2}]},
                {"name": "marketing", "live": 2, "dead": 0, "categories": [{"name": "tag-management", "live": 1}]},
                {"name": "cms", "live": 1, "dead": 0, "latest": 1893456000, "categories": [{"name": "cms", "live": 1}]},
            ],
        }
    }

    result = analyze_builtwith_payload(payload)

    assert result["Tech Stack Signal"] == "Modern stack signals present"
    assert result["Tech Stack Score"] == 0
    assert "conversion" in result["Tech Stack Strong Signals"].lower()


def test_domain_for_lead_uses_resolved_url_first():
    lead = {
        "Resolved Website URL": "https://www.example.com/about",
        "Official Website": "https://wrong.example",
    }

    assert domain_for_lead(lead) == "example.com"


def test_tech_stack_score_reduces_quality_and_adds_opportunity():
    lead = {
        "Web Presence Status": "Basic site",
        "Quality Score": 52,
        "Viewport Meta": "Found",
        "Word Count": 220,
        "Form Count": 1,
        "CTA Terms": "quote",
        "On-Page Phones": "555-555-5555",
        "Tech Stack Signal": "Weak or outdated stack",
        "Tech Stack Score": 42,
    }

    quality = compute_website_quality_score(dict(lead))
    scored_lead = {**lead, "Website Quality Score": quality["website_quality_score"], "Website Grade": quality["website_grade"]}
    opportunity = compute_opportunity_score(scored_lead, 0)

    assert quality["website_quality_score"] == 42
    assert "weak tech stack" in quality["website_quality_details"]
    assert "Weak tech stack" in opportunity["opportunity_breakdown"]
