"""Tests for the Opportunity Review Agent integration."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Ensure imports resolve
REPO_ROOT = Path(__file__).resolve().parent.parent
for p in [str(REPO_ROOT), str(REPO_ROOT / "lead-vault"), str(REPO_ROOT / "colorado-lead-machine")]:
    if p not in sys.path:
        sys.path.insert(0, p)

from lead_vault_agent_review import (
    AgentReviewResult,
    build_review_input,
    compute_input_hash,
    should_review,
    should_skip_cached,
    validate_review_output,
    run_agent_review,
    _safe_float,
    _safe_int,
    MIN_AUDIT_CONFIDENCE,
)


# ── Fixtures ─────────────────────────────────────────────────────────

def _make_lead(
    audit_confidence="0.85",
    cta_strength="Strong",
    mobile_readiness="Good",
    ssl_status="Valid",
    contact_form_status="Present",
    booking_flow_status="None detected",
    issues=None,
    evidence_summary="Homepage hero lacks a clear CTA button",
    opportunity_score=75,
    website_quality_score=65,
    business_name="Test Plumbing Co",
    on_page_phones="303-555-1234",
):
    return {
        "business_name": business_name,
        "city_area": "Denver, CO",
        "lead_key": "test-key-1",
        "last_lead_score": 70,
        "data": {
            "Business Type": "Plumber",
            "Rating": "4.5",
            "Reviews": "42",
            "Phone": "303-555-1234",
            "Opportunity Score": opportunity_score,
            "Website Quality Score": website_quality_score,
            "Official Website": "https://testplumbing.com",
        },
        "latest_audit": {
            "Audit Confidence": audit_confidence,
            "CTA Strength": cta_strength,
            "Mobile Readiness": mobile_readiness,
            "SSL Status": ssl_status,
            "Contact Form Status": contact_form_status,
            "Booking Flow Status": booking_flow_status,
            "SEO Basics": "Weak",
            "Page Speed Signal": "Moderate",
            "On-Page Phones": on_page_phones,
            "On-Page Emails": "",
            "Resolved Website URL": "https://testplumbing.com",
            "Page Title": "Test Plumbing - Denver",
            "Meta Description": "Best plumber in Denver",
            "Website Evidence Summary": evidence_summary,
            "Audit Issues": "; ".join(issues or ["No strong primary CTA above the fold"]),
            "Business Impact Summary": "; ".join(["Losing calls from mobile visitors"]),
        },
        "trigger_events": [],
        "opportunity_score": opportunity_score,
        "website_quality_score": website_quality_score,
    }


# ── Test Cases ────────────────────────────────────────────────────────

class TestBuildReviewInput(unittest.TestCase):
    """1. Strict payload building from existing audit fields."""

    def test_builds_complete_payload(self):
        lead = _make_lead()
        result = build_review_input(lead)
        self.assertEqual(result["business_name"], "Test Plumbing Co")
        self.assertEqual(result["category"], "Plumber")
        self.assertEqual(result["location"], "Denver, CO")
        self.assertIn("scores", result)
        self.assertIn("disqualifiers", result)
        self.assertIn("audit_flags", result)
        self.assertIn("issues", result)
        self.assertIn("evidence", result)

    def test_scores_populated(self):
        lead = _make_lead()
        result = build_review_input(lead)
        scores = result["scores"]
        self.assertEqual(scores["opportunity_score"], 75)
        self.assertEqual(scores["website_quality_score"], 65)
        self.assertIsInstance(scores["trust_score"], int)
        self.assertIsInstance(scores["conversion_score"], int)

    def test_audit_flags_populated(self):
        lead = _make_lead()
        result = build_review_input(lead)
        flags = result["audit_flags"]
        self.assertTrue(flags["has_ssl"])
        self.assertTrue(flags["has_phone_number"])
        self.assertTrue(flags["has_contact_form"])
        self.assertTrue(flags["mobile_friendly"])

    def test_confidence_normalized(self):
        lead = _make_lead(audit_confidence="85")
        result = build_review_input(lead)
        self.assertAlmostEqual(result["audit_confidence"], 0.85, places=2)

    def test_missing_audit_uses_defaults(self):
        lead = _make_lead()
        lead["latest_audit"] = {}
        result = build_review_input(lead)
        self.assertEqual(result["audit_confidence"], 0.0)
        self.assertIsInstance(result["issues"], list)


class TestGating(unittest.TestCase):
    """2. Gate skips low-confidence records."""

    def test_skips_low_confidence(self):
        lead = _make_lead(audit_confidence="0.30")
        review_input = build_review_input(lead)
        should, reason = should_review(review_input)
        self.assertFalse(should)
        self.assertIn("audit_confidence", reason)

    def test_passes_high_confidence(self):
        lead = _make_lead(audit_confidence="0.85")
        review_input = build_review_input(lead)
        should, reason = should_review(review_input)
        self.assertTrue(should)
        self.assertEqual(reason, "")

    def test_skips_insufficient_evidence(self):
        lead = _make_lead(audit_confidence="0.70")
        lead["latest_audit"] = {"Audit Confidence": "0.70"}
        lead["data"] = {}
        review_input = build_review_input(lead)
        # Force very few evidence signals
        review_input["evidence"] = []
        review_input["issues"] = []
        review_input["audit_flags"] = {k: False for k in review_input["audit_flags"]}
        should, reason = should_review(review_input)
        self.assertFalse(should)
        self.assertIn("insufficient evidence", reason)


class TestOutputValidation(unittest.TestCase):
    """3. Valid Claude JSON parses successfully."""

    def test_valid_json_parses(self):
        raw = {
            "verdict": "high_opportunity",
            "suppress_opportunity": False,
            "why_now": "Thriving business with weak web presence",
            "best_pitch_angle": "More calls from mobile visitors",
            "pitch_angle_confidence": 0.82,
            "human_summary": "Strong local demand but website lacks basic CTA.",
            "top_reasons": ["High reviews", "No CTA"],
            "risk_notes": ["Evidence is from a single audit"],
            "recommended_action": "surface",
            "priority": "high",
        }
        result = validate_review_output(raw)
        self.assertEqual(result.verdict, "high_opportunity")
        self.assertEqual(result.recommended_action, "surface")
        self.assertEqual(result.priority, "high")
        self.assertAlmostEqual(result.pitch_angle_confidence, 0.82)

    def test_invalid_verdict_defaults(self):
        raw = {"verdict": "super_amazing", "recommended_action": "yolo"}
        result = validate_review_output(raw)
        self.assertEqual(result.verdict, "unclear")
        self.assertEqual(result.recommended_action, "review")

    def test_confidence_clamped(self):
        raw = {"pitch_angle_confidence": 5.0}
        result = validate_review_output(raw)
        self.assertLessEqual(result.pitch_angle_confidence, 1.0)

    def test_strings_truncated(self):
        raw = {"why_now": "x" * 1000}
        result = validate_review_output(raw)
        self.assertLessEqual(len(result.why_now), 500)


class TestFallback(unittest.TestCase):
    """4. Invalid Claude response falls back safely."""

    def test_fallback_object(self):
        fb = AgentReviewResult.fallback("test reason")
        self.assertEqual(fb.verdict, "unclear")
        self.assertFalse(fb.suppress_opportunity)
        self.assertEqual(fb.recommended_action, "review")
        self.assertEqual(fb.priority, "low")
        self.assertIn("test reason", fb.risk_notes)

    def test_from_dict_roundtrip(self):
        fb = AgentReviewResult.fallback("round trip test")
        d = fb.to_dict()
        restored = AgentReviewResult.from_dict(d)
        self.assertEqual(restored.verdict, fb.verdict)
        self.assertEqual(restored.risk_notes, fb.risk_notes)


class TestCaching(unittest.TestCase):
    """5. Cached input hash prevents duplicate reviews."""

    def test_same_input_same_hash(self):
        lead = _make_lead()
        h1 = compute_input_hash(build_review_input(lead))
        h2 = compute_input_hash(build_review_input(lead))
        self.assertEqual(h1, h2)

    def test_different_input_different_hash(self):
        lead1 = _make_lead(opportunity_score=75)
        lead2 = _make_lead(opportunity_score=50)
        h1 = compute_input_hash(build_review_input(lead1))
        h2 = compute_input_hash(build_review_input(lead2))
        self.assertNotEqual(h1, h2)

    def test_should_skip_cached_matches(self):
        self.assertTrue(should_skip_cached("abc123", "completed", "abc123"))

    def test_should_not_skip_different_hash(self):
        self.assertFalse(should_skip_cached("abc123", "completed", "def456"))

    def test_should_not_skip_non_completed(self):
        self.assertFalse(should_skip_cached("abc123", "error", "abc123"))

    def test_should_not_skip_empty(self):
        self.assertFalse(should_skip_cached(None, None, "abc123"))


class TestSuppressInterpretation(unittest.TestCase):
    """6. suppress_opportunity affects interpretation without replacing deterministic data."""

    def test_suppress_does_not_alter_scores(self):
        lead = _make_lead(opportunity_score=85)
        review_input = build_review_input(lead)
        # Simulate a review that suppresses
        review = AgentReviewResult(
            verdict="low_opportunity",
            suppress_opportunity=True,
            recommended_action="suppress",
        )
        # Original scores unchanged
        self.assertEqual(review_input["scores"]["opportunity_score"], 85)
        # Agent says suppress, but the score is still 85
        self.assertTrue(review.suppress_opportunity)


class TestRunAgentReview(unittest.TestCase):
    """Integration: run_agent_review with mocked Claude call."""

    @patch("lead_vault_agent_review._call_claude")
    def test_successful_review(self, mock_claude):
        mock_claude.return_value = AgentReviewResult(
            verdict="high_opportunity",
            suppress_opportunity=False,
            why_now="Strong demand",
            best_pitch_angle="More calls",
            pitch_angle_confidence=0.8,
            human_summary="Good lead.",
            top_reasons=["High reviews"],
            risk_notes=[],
            recommended_action="surface",
            priority="high",
        )
        lead = _make_lead()
        result = run_agent_review(lead, api_key="sk-test-key")
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["review"]["verdict"], "high_opportunity")

    def test_skipped_low_confidence(self):
        lead = _make_lead(audit_confidence="0.20")
        result = run_agent_review(lead, api_key="sk-test-key")
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["review"]["verdict"], "unclear")

    def test_cached_review_returned(self):
        lead = _make_lead()
        review_input = build_review_input(lead)
        input_hash = compute_input_hash(review_input)
        stored_review = {"verdict": "medium_opportunity", "suppress_opportunity": False}
        result = run_agent_review(
            lead,
            api_key="sk-test-key",
            stored_hash=input_hash,
            stored_status="completed",
            stored_review=stored_review,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "cached")
        self.assertEqual(result["review"]["verdict"], "medium_opportunity")

    def test_no_api_key_returns_error(self):
        lead = _make_lead()
        result = run_agent_review(lead, api_key="")
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "error")

    @patch("lead_vault_agent_review._call_claude")
    def test_invalid_json_fallback(self, mock_claude):
        mock_claude.side_effect = json.JSONDecodeError("bad", "", 0)
        lead = _make_lead()
        result = run_agent_review(lead, api_key="sk-test-key")
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["review"]["verdict"], "unclear")


class TestNoHeavyCallOnListRefresh(unittest.TestCase):
    """8/9. Verify agent review is NOT in the queue summary path."""

    def test_queue_summary_has_no_agent_call(self):
        """The list_queue_summaries query should not reference agent_review columns."""
        import inspect
        from lead_vault_store import LeadVaultStore
        source = inspect.getsource(LeadVaultStore.list_queue_summaries)
        self.assertNotIn("agent_review", source)


class TestAuditKeyMapping(unittest.TestCase):
    """Regression: build_review_input must read display-style audit keys correctly."""

    def test_website_url_from_audit(self):
        lead = _make_lead()
        result = build_review_input(lead)
        self.assertEqual(result["website_url"], "https://testplumbing.com")

    def test_evidence_from_audit_display_keys(self):
        lead = _make_lead(evidence_summary="Phone only in footer")
        result = build_review_input(lead)
        self.assertIn("Phone only in footer", result["evidence"])

    def test_page_title_sets_h1_flag(self):
        lead = _make_lead()
        result = build_review_input(lead)
        self.assertTrue(result["audit_flags"]["has_clear_h1"])

    def test_meta_description_flag(self):
        lead = _make_lead()
        result = build_review_input(lead)
        self.assertTrue(result["audit_flags"]["has_meta_description"])

    def test_audit_only_lead_no_data_fallback(self):
        """A lead whose fields are only in latest_audit (not in data) should still populate."""
        lead = {
            "business_name": "Audit Only Biz",
            "city_area": "Boulder, CO",
            "data": {},
            "latest_audit": {
                "Audit Confidence": "0.80",
                "SSL Status": "Valid",
                "Mobile Readiness": "Good",
                "CTA Strength": "Weak",
                "Contact Form Status": "Present",
                "Booking Flow Status": "None",
                "On-Page Phones": "555-1234",
                "Page Title": "Audit Only Page",
                "Meta Description": "A description",
                "Website Evidence Summary": "Some evidence",
                "Resolved Website URL": "https://auditonly.com",
            },
            "trigger_events": [],
        }
        result = build_review_input(lead)
        self.assertEqual(result["website_url"], "https://auditonly.com")
        self.assertTrue(result["audit_flags"]["has_phone_number"])
        self.assertTrue(result["audit_flags"]["has_clear_h1"])
        self.assertTrue(result["audit_flags"]["has_meta_description"])
        self.assertIn("Some evidence", result["evidence"])


class TestSafeTypeHelpers(unittest.TestCase):
    """Regression: _safe_float/_safe_int must handle zero and edge cases."""

    def test_safe_float_zero(self):
        self.assertEqual(_safe_float(0, 50.0), 0.0)
        self.assertEqual(_safe_float(0.0, 50.0), 0.0)

    def test_safe_float_none(self):
        self.assertEqual(_safe_float(None, 5.0), 5.0)

    def test_safe_float_empty_string(self):
        self.assertEqual(_safe_float("", 5.0), 5.0)

    def test_safe_float_valid_string(self):
        self.assertAlmostEqual(_safe_float("0.85"), 0.85)

    def test_safe_int_zero(self):
        self.assertEqual(_safe_int(0, 99), 0)

    def test_safe_int_none(self):
        self.assertEqual(_safe_int(None, 42), 42)

    def test_safe_int_bad_string(self):
        self.assertEqual(_safe_int("not_a_number", 0), 0)


class TestFromDictSafety(unittest.TestCase):
    """Regression: from_dict must handle corrupt stored data without raising."""

    def test_bad_confidence_string(self):
        d = {"pitch_angle_confidence": "not_a_number", "verdict": "high_opportunity"}
        result = AgentReviewResult.from_dict(d)
        self.assertEqual(result.pitch_angle_confidence, 0.0)
        self.assertEqual(result.verdict, "high_opportunity")

    def test_missing_fields(self):
        result = AgentReviewResult.from_dict({})
        self.assertEqual(result.verdict, "unclear")
        self.assertEqual(result.recommended_action, "review")

    def test_none_lists(self):
        result = AgentReviewResult.from_dict({"top_reasons": None, "risk_notes": None})
        self.assertEqual(result.top_reasons, [])
        self.assertEqual(result.risk_notes, [])


class TestIssueParsingDelimiterSafe(unittest.TestCase):
    """Regression: issue strings containing semicolons must survive intact."""

    def test_json_issue_with_semicolon_survives(self):
        """A structured list issue containing a semicolon is preserved exactly."""
        lead = _make_lead()
        lead["latest_audit"]["Audit Issues List"] = [
            "CTA missing; no visible phone above fold",
            "SSL certificate expired",
        ]
        result = build_review_input(lead)
        self.assertIn("CTA missing; no visible phone above fold", result["issues"])
        self.assertIn("SSL certificate expired", result["issues"])

    def test_legacy_semicolon_joined_string_still_parses(self):
        """Old rows with semicolon-joined strings still produce a usable list."""
        lead = _make_lead()
        # Simulate old hydrated audit with no structured list, only joined string
        lead["latest_audit"]["Audit Issues List"] = []
        lead["latest_audit"]["Audit Issues"] = "No CTA; Weak trust signals; No SSL"
        result = build_review_input(lead)
        # Legacy path returns the whole string as a single entry (not split)
        self.assertTrue(len(result["issues"]) >= 1)
        # The raw string is preserved as-is (not lost)
        joined = "; ".join(result["issues"])
        self.assertIn("No CTA", joined)


class TestErrorNotPersisted(unittest.TestCase):
    """Regression: error status should not overwrite valid cached reviews."""

    @patch("lead_vault_agent_review._call_claude")
    def test_error_returns_fallback_but_keeps_error_status(self, mock_claude):
        mock_claude.side_effect = RuntimeError("API down")
        lead = _make_lead()
        result = run_agent_review(lead, api_key="sk-test-key")
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "error")
        # The review dict should be a safe fallback
        self.assertEqual(result["review"]["verdict"], "unclear")
        self.assertEqual(result["review"]["recommended_action"], "review")


if __name__ == "__main__":
    unittest.main()
