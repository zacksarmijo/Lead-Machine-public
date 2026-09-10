"""Outreach export pipeline — draft generation, .eml creation, Outlook launch.

Designed for future expansion: Gmail, bulk campaigns, saved history, etc.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import urllib.parse
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Outreach draft model
# ---------------------------------------------------------------------------

@dataclass
class OutreachDraft:
    """Structured outreach draft ready for export."""

    lead_key: str
    business_name: str
    recipient_email: str = ""
    subject: str = ""
    body_plain: str = ""
    body_html: str = ""
    preview_url: str = ""
    preview_file_path: str = ""
    generated_at: str = ""
    export_status: str = "pending"  # pending | exported | failed
    export_channel: str = ""  # outlook | gmail | mailto
    export_error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OutreachDraft:
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in known})


# ---------------------------------------------------------------------------
# Subject & body generation (deterministic, no AI call needed)
# ---------------------------------------------------------------------------

def generate_outreach_subject(business_name: str, pitch_angle: str = "") -> str:
    """Generate a grounded, non-spammy subject line."""
    name = business_name.strip() or "your business"
    if pitch_angle:
        angle_map = {
            "no_website": f"Quick idea for {name}'s web presence",
            "broken_site": f"Noticed something on {name}'s site",
            "weak_conversion_path": f"Quick mockup for {name}",
            "outdated_design": f"Fresh direction for {name}'s site",
            "missing_seo": f"Visibility idea for {name}",
            "social_only": f"Web presence idea for {name}",
        }
        for key, subj in angle_map.items():
            if key in pitch_angle.lower():
                return subj
    return f"Quick idea for {name}"


def generate_outreach_body(
    business_name: str,
    site_observation: str = "",
    preview_url: str = "",
    preview_file_path: str = "",
    agency_name: str = "",
    draft_message: str = "",
) -> tuple[str, str]:
    """Return (plain_text, html) outreach body.

    If *draft_message* is provided (from AI generation), use it as the base
    and append preview link. Otherwise build a templated message.
    """
    name = business_name.strip() or "your business"
    sender = agency_name.strip() if agency_name else ""

    # Determine preview reference
    preview_ref = ""
    if preview_url:
        preview_ref = preview_url
    elif preview_file_path:
        preview_ref = f"(preview attached)"

    # If we have an AI-generated draft, use it and append preview
    if draft_message and draft_message.strip():
        plain = draft_message.strip()
        if preview_ref and preview_ref not in plain:
            plain += f"\n\nPreview: {preview_ref}"
        html = _plain_to_html(plain)
        return plain, html

    # Otherwise, build a templated message
    observation = site_observation.strip() if site_observation else ""

    lines = [f"Hey {name} team,"]
    lines.append("")

    if observation:
        lines.append(
            f"I took a look at your current site and noticed {observation}. "
            "I put together a quick mockup with a cleaner direction that "
            "I think could help with trust and conversions."
        )
    else:
        lines.append(
            "I was doing some research in your area and put together a "
            "quick mockup with a direction I think could work well for "
            "your online presence."
        )

    lines.append("")

    if preview_ref and preview_ref != "(preview attached)":
        lines.append(f"Here's the preview: {preview_ref}")
        lines.append("")
    elif preview_ref == "(preview attached)":
        lines.append("I've attached a preview of the concept.")
        lines.append("")

    lines.append(
        "No pressure at all — just thought I'd send it over in case "
        "it's useful. Happy to walk through it or send a fuller version "
        "if you're interested."
    )
    lines.append("")

    if sender:
        lines.append(f"Best,\n{sender}")
    else:
        lines.append("Best")

    plain = "\n".join(lines)
    html = _plain_to_html(plain)
    return plain, html


def _plain_to_html(text: str) -> str:
    """Convert plain text to simple HTML email body."""
    import html as html_mod

    escaped = html_mod.escape(text)
    # Convert URLs to clickable links
    import re

    escaped = re.sub(
        r'(https?://[^\s<]+)',
        r'<a href="\1">\1</a>',
        escaped,
    )
    paragraphs = escaped.split("\n\n")
    body_parts = []
    for p in paragraphs:
        lines = p.replace("\n", "<br>\n")
        body_parts.append(f"<p>{lines}</p>")

    return (
        '<div style="font-family:Arial,sans-serif;font-size:14px;'
        'line-height:1.5;color:#333">\n'
        + "\n".join(body_parts)
        + "\n</div>"
    )


# ---------------------------------------------------------------------------
# Build a full OutreachDraft from lead data
# ---------------------------------------------------------------------------

def build_draft_from_lead(lead: dict[str, Any], agency_name: str = "") -> OutreachDraft:
    """Assemble an OutreachDraft from a lead dict (as returned by the store)."""
    data = lead.get("data") or lead.get("data_json") or {}
    if isinstance(data, str):
        import json
        try:
            data = json.loads(data)
        except Exception:
            data = {}

    business_name = lead.get("business_name") or data.get("Business Name", "")
    email = data.get("Email", "") or ""
    audit = lead.get("latest_audit") or {}
    pitch_angle = audit.get("best_pitch_angle") or data.get("Best Pitch Angle", "")

    # Build a short observation from audit data
    observation = _build_observation(audit, data)

    # Use existing AI draft if available
    draft_message = lead.get("draft_message", "") or ""

    subject = generate_outreach_subject(business_name, pitch_angle)
    body_plain, body_html = generate_outreach_body(
        business_name=business_name,
        site_observation=observation,
        agency_name=agency_name,
        draft_message=draft_message,
    )

    return OutreachDraft(
        lead_key=lead.get("lead_key", ""),
        business_name=business_name,
        recipient_email=email,
        subject=subject,
        body_plain=body_plain,
        body_html=body_html,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


def _build_observation(audit: dict, data: dict) -> str:
    """Extract one short site observation from audit data."""
    observations = []

    pitch = audit.get("best_pitch_angle") or data.get("Best Pitch Angle", "")
    if pitch:
        angle_phrases = {
            "no_website": "you don't seem to have a website yet",
            "broken_site": "your site may have some technical issues",
            "weak_conversion_path": "your site could use a stronger call-to-action flow",
            "outdated_design": "your site design could use a refresh",
            "missing_seo": "there are some quick SEO wins available",
            "social_only": "you're mainly on social but don't have a dedicated site",
        }
        for key, phrase in angle_phrases.items():
            if key in pitch.lower():
                observations.append(phrase)
                break

    if not observations:
        evidence = audit.get("evidence_summary") or data.get("Website Evidence Summary", "")
        if evidence:
            # Take first sentence
            first_sentence = evidence.split(".")[0].strip()
            if first_sentence and len(first_sentence) < 120:
                observations.append(first_sentence.lower())

    if not observations:
        cta = audit.get("cta_strength") or data.get("CTA Strength", "")
        if cta and "weak" in cta.lower():
            observations.append("the call-to-action on your site could be stronger")
        mobile = audit.get("mobile_readiness") or data.get("Mobile Readiness", "")
        if mobile and "no" in mobile.lower():
            observations.append("the site may not be fully mobile-friendly")

    return observations[0] if observations else ""


# ---------------------------------------------------------------------------
# .eml file generation
# ---------------------------------------------------------------------------

def generate_eml(draft: OutreachDraft) -> str:
    """Generate RFC 2822 .eml file content from an OutreachDraft."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = draft.subject
    if draft.recipient_email:
        msg["To"] = draft.recipient_email
    msg["X-Unsent"] = "1"  # Tells Outlook to open as draft, not read-only
    msg["Date"] = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")

    # Plain text part
    msg.attach(MIMEText(draft.body_plain, "plain", "utf-8"))

    # HTML part
    html_full = (
        '<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>\n'
        + draft.body_html
        + "\n</body></html>"
    )
    msg.attach(MIMEText(html_full, "html", "utf-8"))

    return msg.as_string()


def save_eml_file(draft: OutreachDraft, output_dir: str | None = None) -> str:
    """Write .eml to disk and return the file path."""
    if not output_dir:
        output_dir = tempfile.gettempdir()
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in draft.business_name)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"outreach_{safe_name}_{timestamp}.eml"
    filepath = os.path.join(output_dir, filename)

    eml_content = generate_eml(draft)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(eml_content)

    return filepath


# ---------------------------------------------------------------------------
# Outlook export (Windows desktop)
# ---------------------------------------------------------------------------

def export_to_outlook(draft: OutreachDraft, output_dir: str | None = None) -> dict[str, Any]:
    """Export draft to Outlook.

    Strategy:
    1. Generate .eml file with X-Unsent header (opens as editable draft)
    2. Open with os.startfile (Windows) or subprocess fallback
    3. Fall back to mailto: if .eml open fails

    Returns dict with status, method used, file path, and any error.
    """
    result: dict[str, Any] = {
        "ok": False,
        "method": "",
        "eml_path": "",
        "error": "",
    }

    # Try .eml approach first
    try:
        eml_path = save_eml_file(draft, output_dir)
        result["eml_path"] = eml_path

        if sys.platform == "win32":
            os.startfile(eml_path)  # type: ignore[attr-defined]
            result["ok"] = True
            result["method"] = "eml_startfile"
            return result
        elif sys.platform == "darwin":
            try:
                subprocess.Popen(["open", eml_path])
                result["ok"] = True
                result["method"] = "eml_open"
                return result
            except FileNotFoundError:
                pass
        else:
            try:
                subprocess.Popen(["xdg-open", eml_path])
                result["ok"] = True
                result["method"] = "eml_xdg"
                return result
            except FileNotFoundError:
                pass

    except Exception as exc:
        result["error"] = f"EML generation failed: {exc}"

    # Fallback: mailto
    try:
        mailto = build_mailto_url(draft)
        if sys.platform == "win32":
            os.startfile(mailto)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", mailto])
        else:
            subprocess.Popen(["xdg-open", mailto])
        result["ok"] = True
        result["method"] = "mailto"
        if result["error"]:
            result["error"] += " (fell back to mailto)"
        return result
    except Exception as exc:
        result["error"] += f" Mailto fallback also failed: {exc}"

    return result


def build_mailto_url(draft: OutreachDraft) -> str:
    """Build a mailto: URL as a last-resort fallback."""
    params = {
        "subject": draft.subject,
        "body": draft.body_plain,
    }
    to = draft.recipient_email or ""
    query = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    return f"mailto:{to}?{query}"
