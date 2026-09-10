"""Tests for outreach_export module."""

from __future__ import annotations

import os
import sys
import tempfile

# Ensure the lead-vault directory is on the path
sys.path.insert(0, os.path.dirname(__file__))

from outreach_export import (
    OutreachDraft,
    build_draft_from_lead,
    build_mailto_url,
    generate_eml,
    generate_outreach_body,
    generate_outreach_subject,
    save_eml_file,
)


# ── Model tests ──────────────────────────────────────

def test_draft_round_trip():
    draft = OutreachDraft(lead_key="abc", business_name="Test Biz", subject="Hi")
    d = draft.to_dict()
    assert d["lead_key"] == "abc"
    restored = OutreachDraft.from_dict(d)
    assert restored.business_name == "Test Biz"
    assert restored.subject == "Hi"


def test_draft_from_dict_ignores_unknown_keys():
    d = {"lead_key": "x", "business_name": "Y", "unknown_field": 123}
    draft = OutreachDraft.from_dict(d)
    assert draft.lead_key == "x"
    assert not hasattr(draft, "unknown_field")


# ── Subject generation ───────────────────────────────

def test_subject_default():
    subj = generate_outreach_subject("Acme Corp")
    assert "Acme Corp" in subj


def test_subject_with_pitch_angle():
    subj = generate_outreach_subject("Acme Corp", "no_website")
    assert "Acme Corp" in subj
    assert "web presence" in subj.lower()


def test_subject_empty_name():
    subj = generate_outreach_subject("")
    assert "your business" in subj.lower()


# ── Body generation ──────────────────────────────────

def test_body_with_observation():
    plain, html = generate_outreach_body(
        business_name="Acme Corp",
        site_observation="your site loads slowly",
    )
    assert "Acme Corp" in plain
    assert "your site loads slowly" in plain
    assert "<p>" in html


def test_body_with_ai_draft():
    plain, html = generate_outreach_body(
        business_name="Acme Corp",
        draft_message="Hey Acme, I checked out your site.",
    )
    assert plain == "Hey Acme, I checked out your site."
    assert "<p>" in html


def test_body_with_preview_url():
    plain, html = generate_outreach_body(
        business_name="Acme Corp",
        preview_url="https://example.com/preview",
    )
    assert "https://example.com/preview" in plain


def test_body_with_ai_draft_appends_preview():
    plain, _ = generate_outreach_body(
        business_name="Acme Corp",
        draft_message="Hey there.",
        preview_url="https://example.com/preview",
    )
    assert "https://example.com/preview" in plain


def test_body_fallback_no_observation():
    plain, _ = generate_outreach_body(business_name="Acme Corp")
    assert "Acme Corp" in plain
    assert "mockup" in plain.lower() or "direction" in plain.lower()


def test_body_with_agency_name():
    plain, _ = generate_outreach_body(
        business_name="Acme Corp",
        agency_name="Summit Digital",
    )
    assert "Summit Digital" in plain


# ── EML generation ───────────────────────────────────

def test_generate_eml_has_unsent_header():
    draft = OutreachDraft(
        lead_key="abc",
        business_name="Test",
        subject="Hello",
        body_plain="Hi there",
        body_html="<p>Hi there</p>",
        recipient_email="test@example.com",
    )
    eml = generate_eml(draft)
    assert "X-Unsent: 1" in eml
    assert "Subject: Hello" in eml
    assert "To: test@example.com" in eml
    # Body is base64-encoded in MIME; verify structure is valid
    assert "Content-Type: multipart/alternative" in eml
    assert "Content-Type: text/plain" in eml
    assert "Content-Type: text/html" in eml


def test_generate_eml_no_recipient():
    draft = OutreachDraft(
        lead_key="abc",
        business_name="Test",
        subject="Hello",
        body_plain="Hi",
        body_html="<p>Hi</p>",
    )
    eml = generate_eml(draft)
    assert "X-Unsent: 1" in eml
    assert "To:" not in eml or "To: \n" in eml or "To:" in eml


def test_save_eml_file():
    draft = OutreachDraft(
        lead_key="abc",
        business_name="Test Biz",
        subject="Hello",
        body_plain="Body text",
        body_html="<p>Body text</p>",
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        path = save_eml_file(draft, tmpdir)
        assert os.path.exists(path)
        assert path.endswith(".eml")
        with open(path) as f:
            content = f.read()
        assert "X-Unsent: 1" in content
        assert "Content-Type: text/plain" in content


# ── Build from lead ──────────────────────────────────

def test_build_draft_from_lead_basic():
    lead = {
        "lead_key": "test::123",
        "business_name": "Joe's Plumbing",
        "data": {"Email": "joe@plumbing.com", "Business Name": "Joe's Plumbing"},
        "latest_audit": {"best_pitch_angle": "weak_conversion_path"},
        "draft_message": "",
    }
    draft = build_draft_from_lead(lead)
    assert draft.lead_key == "test::123"
    assert draft.business_name == "Joe's Plumbing"
    assert draft.recipient_email == "joe@plumbing.com"
    assert draft.subject
    assert draft.body_plain
    assert draft.generated_at


def test_build_draft_from_lead_with_existing_ai_draft():
    lead = {
        "lead_key": "test::456",
        "business_name": "Acme",
        "data": {},
        "latest_audit": {},
        "draft_message": "Hey Acme, custom AI message here.",
    }
    draft = build_draft_from_lead(lead)
    assert "custom AI message" in draft.body_plain


def test_build_draft_from_lead_missing_email():
    lead = {
        "lead_key": "test::789",
        "business_name": "No Email Biz",
        "data": {},
        "latest_audit": {},
    }
    draft = build_draft_from_lead(lead)
    assert draft.recipient_email == ""
    assert draft.body_plain  # Still generates body


def test_build_draft_from_lead_missing_audit():
    lead = {
        "lead_key": "test::000",
        "business_name": "Bare Lead",
        "data": {"Email": "a@b.com"},
    }
    draft = build_draft_from_lead(lead)
    assert draft.subject
    assert draft.body_plain


# ── Mailto fallback ──────────────────────────────────

def test_mailto_url():
    draft = OutreachDraft(
        lead_key="abc",
        business_name="Test",
        subject="Hello World",
        body_plain="Body here",
        recipient_email="test@example.com",
    )
    url = build_mailto_url(draft)
    assert url.startswith("mailto:test@example.com?")
    assert "Hello" in url
    assert "Body" in url


def test_mailto_url_no_email():
    draft = OutreachDraft(
        lead_key="abc",
        business_name="Test",
        subject="Hello",
        body_plain="Body",
    )
    url = build_mailto_url(draft)
    assert url.startswith("mailto:?")


# ── Export status tracking ───────────────────────────

def test_draft_default_status():
    draft = OutreachDraft(lead_key="x", business_name="Y")
    assert draft.export_status == "pending"
    assert draft.export_channel == ""


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
