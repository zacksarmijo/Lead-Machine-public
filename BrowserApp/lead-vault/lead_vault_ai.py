from __future__ import annotations

import json
from dataclasses import dataclass
import re
import sys
from pathlib import Path
from typing import Any

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

try:
    import anthropic as _anthropic
except ImportError:
    _anthropic = None

REPO_ROOT = Path(__file__).resolve().parent.parent
WEBSITE_AUDIT_DIR = REPO_ROOT / "colorado-lead-machine"
if str(WEBSITE_AUDIT_DIR) not in sys.path:
    sys.path.insert(0, str(WEBSITE_AUDIT_DIR))

from website_audit import build_opportunity_thesis, derive_pitch_family


AI_PROVIDERS = ("OpenAI", "Claude", "Anthropic")
DEFAULT_AI_PROVIDER = "OpenAI"
DEFAULT_AI_MODELS = {
    "OpenAI": "gpt-5.4-mini",
    "Claude": "claude-sonnet-4-6",
    "Anthropic": "claude-sonnet-4-6",
}


class LeadVaultAIError(Exception):
    pass


@dataclass
class GeneratedLeadContent:
    opportunity_summary: str
    outreach_strategy: str
    draft_message: str


def sanitize_provider_error(message: str) -> str:
    cleaned = re.sub(r"sk-[A-Za-z0-9_-]+", "[redacted-api-key]", str(message or ""))
    cleaned = re.sub(r"api[_ -]?key[^,\n}]*", "API key [redacted]", cleaned, flags=re.IGNORECASE)
    return cleaned


def default_model_for_provider(provider: str) -> str:
    return DEFAULT_AI_MODELS.get(provider, DEFAULT_AI_MODELS[DEFAULT_AI_PROVIDER])


@dataclass
class LeadDraftGenerator:
    api_key: str
    provider: str = DEFAULT_AI_PROVIDER
    model: str = ""

    def _coalesce_text(self, *values: Any) -> str:
        for value in values:
            cleaned = str(value or "").strip()
            if cleaned:
                return cleaned
        return ""

    def _summarize_points(self, points: list[str], *, default: str, limit: int = 6) -> str:
        cleaned = [str(point).strip() for point in points if str(point).strip()]
        if not cleaned:
            return default
        return "; ".join(cleaned[:limit])

    def _default_offer_positioning(self) -> str:
        return (
            "We can show a preview direction before any commitment and focus on helping businesses turn weak web presence "
            "into more trust, more calls, and more booked work."
        )

    def _lead_data(self, lead: dict[str, Any]) -> dict[str, Any]:
        payload = lead.get("data", {})
        return payload if isinstance(payload, dict) else {}

    def _lead_audit(self, lead: dict[str, Any]) -> dict[str, Any]:
        audit = lead.get("latest_audit", {}) or {}
        return audit if isinstance(audit, dict) else {}

    def _payload_value(self, lead: dict[str, Any], key: str, default: str = "") -> str:
        value = lead.get(key)
        if value not in (None, ""):
            return str(value).strip()
        payload = self._lead_data(lead)
        payload_value = payload.get(key)
        if payload_value not in (None, ""):
            return str(payload_value).strip()
        return str(default or "").strip()

    def _audit_value(self, lead: dict[str, Any], key: str, fallback: Any = "") -> Any:
        audit = self._lead_audit(lead)
        value = audit.get(key)
        if value not in (None, ""):
            return value
        return fallback

    def _resolved_web_intel(self, lead: dict[str, Any]) -> dict[str, str]:
        legacy_web_status = self._payload_value(
            lead,
            "Web Presence Status",
            self._payload_value(
                lead,
                "Website Status",
                self._payload_value(lead, "last_web_presence_status"),
            ),
        )
        website_bucket = str(
            self._audit_value(
                lead,
                "Website Bucket",
                self._payload_value(lead, "Website Bucket", legacy_web_status),
            )
        ).strip()
        audit_confidence = str(
            self._audit_value(
                lead,
                "Audit Confidence",
                self._payload_value(lead, "Audit Confidence", self._payload_value(lead, "Web Presence Confidence")),
            )
        ).strip()
        web_intel = {
            "website_bucket": website_bucket,
            "web_presence_status": website_bucket,
            "website_failure_type": str(
                self._audit_value(
                    lead,
                    "Website Failure Type",
                    self._payload_value(lead, "Website Failure Type"),
                )
            ).strip(),
            "resolved_url": str(
                self._audit_value(
                    lead,
                    "Resolved Website URL",
                    self._payload_value(lead, "Resolved Website URL", self._payload_value(lead, "Official Website")),
                )
            ).strip(),
            "page_title": str(self._audit_value(lead, "Page Title", self._payload_value(lead, "Page Title"))).strip(),
            "meta_description": str(
                self._audit_value(lead, "Meta Description", self._payload_value(lead, "Meta Description"))
            ).strip(),
            "evidence_summary": str(
                self._audit_value(
                    lead,
                    "Website Evidence Summary",
                    self._payload_value(lead, "Website Evidence Summary"),
                )
            ).strip(),
            "evidence_snippet": str(
                self._audit_value(
                    lead,
                    "Website Evidence Snippet",
                    self._payload_value(lead, "Website Evidence Snippet"),
                )
            ).strip(),
            "primary_business_impact": str(
                self._audit_value(
                    lead,
                    "Primary Business Impact",
                    self._payload_value(lead, "Primary Business Impact"),
                )
            ).strip(),
            "best_pitch_angle": str(
                self._audit_value(
                    lead,
                    "Best Pitch Angle",
                    self._payload_value(lead, "Best Pitch Angle"),
                )
            ).strip(),
            "audit_confidence": audit_confidence,
            "web_confidence": audit_confidence,
            "last_audited_at": str(
                self._audit_value(
                    lead,
                    "Last Audited At",
                    self._payload_value(lead, "Last Audited At"),
                )
            ).strip(),
            "last_verified_at": str(
                self._audit_value(
                    lead,
                    "Last Verified At",
                    self._payload_value(lead, "Last Verified At"),
                )
            ).strip(),
            "data_freshness": str(
                self._audit_value(
                    lead,
                    "Data Freshness",
                    self._payload_value(lead, "Data Freshness"),
                )
            ).strip(),
            "mobile_readiness": str(
                self._audit_value(
                    lead,
                    "Mobile Readiness",
                    self._payload_value(lead, "Mobile Readiness"),
                )
            ).strip(),
            "ssl_status": str(
                self._audit_value(
                    lead,
                    "SSL Status",
                    self._payload_value(lead, "SSL Status"),
                )
            ).strip(),
            "page_speed_signal": str(
                self._audit_value(
                    lead,
                    "Page Speed Signal",
                    self._payload_value(lead, "Page Speed Signal"),
                )
            ).strip(),
            "contact_form_status": str(
                self._audit_value(
                    lead,
                    "Contact Form Status",
                    self._payload_value(lead, "Contact Form Status"),
                )
            ).strip(),
            "booking_flow_status": str(
                self._audit_value(
                    lead,
                    "Booking Flow Status",
                    self._payload_value(lead, "Booking Flow Status"),
                )
            ).strip(),
            "cta_strength": str(
                self._audit_value(
                    lead,
                    "CTA Strength",
                    self._payload_value(lead, "CTA Strength"),
                )
            ).strip(),
            "seo_basics": str(
                self._audit_value(
                    lead,
                    "SEO Basics",
                    self._payload_value(lead, "SEO Basics"),
                )
            ).strip(),
            "social_dependence": str(
                self._audit_value(
                    lead,
                    "Social Dependence",
                    self._payload_value(lead, "Social Dependence"),
                )
            ).strip(),
            "directory_dependence": str(
                self._audit_value(
                    lead,
                    "Directory Dependence",
                    self._payload_value(lead, "Directory Dependence"),
                )
            ).strip(),
            "image_quality_signal": str(
                self._audit_value(
                    lead,
                    "Image Quality Signal",
                    self._payload_value(lead, "Image Quality Signal"),
                )
            ).strip(),
            "navigation_quality": str(
                self._audit_value(
                    lead,
                    "Navigation Quality",
                    self._payload_value(lead, "Navigation Quality"),
                )
            ).strip(),
            "on_page_phones": str(
                self._audit_value(
                    lead,
                    "On-Page Phones",
                    self._payload_value(lead, "On-Page Phones"),
                )
            ).strip(),
            "on_page_emails": str(
                self._audit_value(
                    lead,
                    "On-Page Emails",
                    self._payload_value(lead, "On-Page Emails"),
                )
            ).strip(),
            "cta_terms": str(self._audit_value(lead, "CTA Terms", self._payload_value(lead, "CTA Terms"))).strip(),
            "booking_terms": str(
                self._audit_value(
                    lead,
                    "Booking Terms",
                    self._payload_value(lead, "Booking Terms"),
                )
            ).strip(),
            "viewport_meta": str(
                self._audit_value(
                    lead,
                    "Viewport Meta",
                    self._payload_value(lead, "Viewport Meta"),
                )
            ).strip(),
            "audit_issues": str(
                self._audit_value(
                    lead,
                    "Audit Issues",
                    self._payload_value(lead, "Audit Issues"),
                )
            ).strip(),
            "business_impact_summary": str(
                self._audit_value(
                    lead,
                    "Business Impact Summary",
                    self._payload_value(lead, "Business Impact Summary"),
                )
            ).strip(),
            "opportunity_brief": self._payload_value(lead, "Opportunity Brief"),
            "why_kept": self._payload_value(lead, "Why Kept"),
            "lead_rationale": self._payload_value(lead, "Lead Rationale"),
            "web_presence_details": self._payload_value(lead, "Web Presence Details"),
            "website_signals": self._payload_value(lead, "Website Signals"),
            "score_breakdown": self._payload_value(lead, "Score Breakdown"),
        }
        pitch_family = self._payload_value(lead, "Pitch Family") or derive_pitch_family(web_intel)
        opportunity_thesis = self._payload_value(lead, "Opportunity Thesis") or build_opportunity_thesis(
            {
                **web_intel,
                "Pitch Family": pitch_family,
            }
        )
        web_intel["pitch_family"] = str(pitch_family).strip()
        web_intel["opportunity_thesis"] = str(opportunity_thesis).strip()
        return web_intel

    def _contact_channels_summary(self, lead: dict[str, Any], web_intel: dict[str, str]) -> str:
        phone = self._coalesce_text(lead.get("phone"), self._payload_value(lead, "Phone"), web_intel.get("on_page_phones"))
        email = self._coalesce_text(lead.get("email"), self._payload_value(lead, "Email"), web_intel.get("on_page_emails"))
        linkedin = self._payload_value(lead, "LinkedIn Profile")
        social = self._coalesce_text(self._payload_value(lead, "Social Profile URLs"), self._payload_value(lead, "Social Profiles"))
        channels: list[str] = []
        if phone:
            channels.append(f"Phone: {phone}")
        if email:
            channels.append(f"Email: {email}")
        if linkedin:
            channels.append("LinkedIn profile present")
        if social:
            channels.append("Social profile present")
        return self._summarize_points(channels, default="No confirmed direct contact channel")

    def _trust_signals_summary(self, lead: dict[str, Any], trigger_types: str) -> str:
        business_reality = self._payload_value(lead, "Business Reality")
        reality_confidence = self._payload_value(lead, "Reality Confidence")
        colorado_status = self._coalesce_text(
            self._payload_value(lead, "Colorado Status Category"),
            self._payload_value(lead, "Colorado Record Status"),
        )
        colorado_note = self._payload_value(lead, "Colorado Status Note")
        contact_cross_reference = self._payload_value(lead, "Contact Cross-Reference")
        linkedin = self._payload_value(lead, "LinkedIn Profile")
        social = self._coalesce_text(self._payload_value(lead, "Social Profile URLs"), self._payload_value(lead, "Social Profiles"))
        trust_points: list[str] = []
        if business_reality:
            label = f"Business reality: {business_reality}"
            if reality_confidence:
                label += f" ({reality_confidence})"
            trust_points.append(label)
        if colorado_status:
            trust_points.append(f"Colorado status: {colorado_status}")
        if colorado_note:
            trust_points.append(f"Colorado note: {colorado_note}")
        if contact_cross_reference:
            trust_points.append(f"Contact cross-reference: {contact_cross_reference}")
        if linkedin:
            trust_points.append("LinkedIn profile found")
        if social:
            trust_points.append("Social profile found")
        if trigger_types:
            trust_points.append(f"Trigger signals: {trigger_types}")
        return self._summarize_points(trust_points, default="Limited trust signals captured")

    def _website_evidence_snapshot(self, web_intel: dict[str, str]) -> str:
        website_bucket = self._coalesce_text(web_intel.get("website_bucket"), web_intel.get("web_presence_status"))
        website_failure = self._coalesce_text(web_intel.get("website_failure_type"))
        pitch_family = self._coalesce_text(web_intel.get("pitch_family"))
        opportunity_thesis = self._coalesce_text(web_intel.get("opportunity_thesis"))
        resolved_url = self._coalesce_text(web_intel.get("resolved_url"))
        page_title = self._coalesce_text(web_intel.get("page_title"))
        meta_description = self._coalesce_text(web_intel.get("meta_description"))
        website_signals = self._coalesce_text(web_intel.get("website_signals"))
        evidence_summary = self._coalesce_text(web_intel.get("evidence_summary"))
        evidence_snippet = self._coalesce_text(web_intel.get("evidence_snippet"))
        audit_issues = self._coalesce_text(web_intel.get("audit_issues"))
        business_impact = self._coalesce_text(web_intel.get("business_impact_summary"))
        snapshot_points: list[str] = []
        if website_bucket or website_failure:
            snapshot_points.append(
                "Website state: "
                + (website_bucket or "Unknown")
                + (f" | Failure: {website_failure}" if website_failure else "")
            )
        if pitch_family:
            snapshot_points.append(f"Pitch family: {pitch_family}")
        if opportunity_thesis:
            snapshot_points.append(f"Opportunity thesis: {opportunity_thesis}")
        if resolved_url:
            snapshot_points.append(f"Resolved URL: {resolved_url}")
        if page_title:
            snapshot_points.append(f"Page title: {page_title}")
        if meta_description:
            snapshot_points.append(f"Meta description: {meta_description}")
        if website_signals:
            snapshot_points.append(f"Observed signals: {website_signals}")
        if evidence_summary:
            snapshot_points.append(f"Evidence summary: {evidence_summary}")
        if evidence_snippet:
            snapshot_points.append(f"Evidence snippet: {evidence_snippet}")
        if audit_issues:
            snapshot_points.append(f"Audit issues: {audit_issues}")
        if business_impact:
            snapshot_points.append(f"Likely business impact: {business_impact}")
        return self._summarize_points(snapshot_points, default="Limited website evidence captured", limit=8)

    def _audit_diagnostics_snapshot(self, web_intel: dict[str, str]) -> str:
        diagnostics_points: list[str] = []
        verification = self._summarize_points(
            [
                f"Audit confidence: {web_intel.get('audit_confidence', '')}" if web_intel.get("audit_confidence") else "",
                f"Last verified: {web_intel.get('last_verified_at', '')}" if web_intel.get("last_verified_at") else "",
                f"Freshness: {web_intel.get('data_freshness', '')}" if web_intel.get("data_freshness") else "",
            ],
            default="",
            limit=3,
        )
        if verification:
            diagnostics_points.append(verification)
        ux_basics = self._summarize_points(
            [
                f"Mobile: {web_intel.get('mobile_readiness', '')}" if web_intel.get("mobile_readiness") else "",
                f"SSL: {web_intel.get('ssl_status', '')}" if web_intel.get("ssl_status") else "",
                f"Speed: {web_intel.get('page_speed_signal', '')}" if web_intel.get("page_speed_signal") else "",
            ],
            default="",
            limit=3,
        )
        if ux_basics:
            diagnostics_points.append(f"UX basics: {ux_basics}")
        conversion = self._summarize_points(
            [
                f"Contact form: {web_intel.get('contact_form_status', '')}" if web_intel.get("contact_form_status") else "",
                f"Booking flow: {web_intel.get('booking_flow_status', '')}" if web_intel.get("booking_flow_status") else "",
                f"CTA strength: {web_intel.get('cta_strength', '')}" if web_intel.get("cta_strength") else "",
                f"SEO basics: {web_intel.get('seo_basics', '')}" if web_intel.get("seo_basics") else "",
            ],
            default="",
            limit=4,
        )
        if conversion:
            diagnostics_points.append(f"Conversion signals: {conversion}")
        dependence = self._summarize_points(
            [
                f"Social dependence: {web_intel.get('social_dependence', '')}" if web_intel.get("social_dependence") else "",
                f"Directory dependence: {web_intel.get('directory_dependence', '')}" if web_intel.get("directory_dependence") else "",
                f"Images: {web_intel.get('image_quality_signal', '')}" if web_intel.get("image_quality_signal") else "",
                f"Navigation: {web_intel.get('navigation_quality', '')}" if web_intel.get("navigation_quality") else "",
            ],
            default="",
            limit=4,
        )
        if dependence:
            diagnostics_points.append(f"Dependence / quality: {dependence}")
        on_page_contacts = self._summarize_points(
            [
                f"On-page phones: {web_intel.get('on_page_phones', '')}" if web_intel.get("on_page_phones") else "",
                f"On-page emails: {web_intel.get('on_page_emails', '')}" if web_intel.get("on_page_emails") else "",
            ],
            default="",
            limit=2,
        )
        if on_page_contacts:
            diagnostics_points.append(on_page_contacts)
        content_terms = self._summarize_points(
            [
                f"CTA terms: {web_intel.get('cta_terms', '')}" if web_intel.get("cta_terms") else "",
                f"Booking terms: {web_intel.get('booking_terms', '')}" if web_intel.get("booking_terms") else "",
                f"Viewport meta: {web_intel.get('viewport_meta', '')}" if web_intel.get("viewport_meta") else "",
            ],
            default="",
            limit=3,
        )
        if content_terms:
            diagnostics_points.append(content_terms)
        return self._summarize_points(
            diagnostics_points,
            default="No structured audit diagnostics captured",
            limit=6,
        )

    def generate_assets(
        self,
        lead: dict[str, Any],
        personalization_notes: str = "",
        outreach_angle: str = "",
        existing_draft: str = "",
        existing_summary: str = "",
        agency_name: str = "",
        offer_positioning: str = "",
    ) -> GeneratedLeadContent:
        if OpenAI is None:
            raise LeadVaultAIError("Install the openai package to use AI draft generation. Run: pip install openai")
        if not self.api_key.strip():
            raise LeadVaultAIError(f"Add a {self.provider} API key in Lead Vault before generating drafts.")

        provider = self.provider.strip() or DEFAULT_AI_PROVIDER
        prompt = self._build_prompt(
            lead,
            personalization_notes,
            outreach_angle,
            existing_draft,
            existing_summary,
            agency_name,
            offer_positioning,
        )

        if provider == "OpenAI":
            return self._generate_openai_assets(prompt)
        if provider in ("Claude", "Anthropic"):
            return self._generate_claude_assets(prompt)
        raise LeadVaultAIError(f"Unsupported AI provider: {provider}")

    def generate_draft(
        self,
        lead: dict[str, Any],
        personalization_notes: str = "",
        outreach_angle: str = "",
        existing_draft: str = "",
        existing_summary: str = "",
        agency_name: str = "",
        offer_positioning: str = "",
    ) -> str:
        return self.generate_assets(
            lead=lead,
            personalization_notes=personalization_notes,
            outreach_angle=outreach_angle,
            existing_draft=existing_draft,
            existing_summary=existing_summary,
            agency_name=agency_name,
            offer_positioning=offer_positioning,
        ).draft_message

    def _generate_openai_assets(self, prompt: str) -> GeneratedLeadContent:
        client = OpenAI(api_key=self.api_key.strip())
        try:
            response = client.responses.create(
                model=self.model.strip() or default_model_for_provider("OpenAI"),
                store=False,
                instructions=self._system_prompt(),
                input=prompt,
            )
        except Exception as exc:
            message = sanitize_provider_error(str(exc))
            lowered = message.lower()
            if "invalid_api_key" in lowered or "incorrect api key" in lowered:
                raise LeadVaultAIError(
                    "OpenAI rejected that API key. Paste a valid OpenAI API key into the API Key field, then try again."
                ) from exc
            raise LeadVaultAIError(f"OpenAI draft generation failed: {message}") from exc
        output = (response.output_text or "").strip()
        if not output:
            raise LeadVaultAIError("The OpenAI response was empty. Try adjusting the lead notes and generating again.")
        return self._parse_generated_assets(output)

    def _generate_claude_assets(self, prompt: str) -> GeneratedLeadContent:
        if _anthropic is None:
            raise LeadVaultAIError("Install the anthropic package to use Claude. Run: pip install anthropic")
        client = _anthropic.Anthropic(api_key=self.api_key.strip())
        model = self.model.strip() or default_model_for_provider(self.provider or "Claude")
        try:
            response = client.messages.create(
                model=model,
                max_tokens=1024,
                system=self._system_prompt(),
                messages=[
                    {"role": "user", "content": prompt},
                ],
            )
        except _anthropic.AuthenticationError as exc:
            raise LeadVaultAIError(
                "Claude rejected that API key. Paste a valid Anthropic API key into the API Key field, then try again."
            ) from exc
        except Exception as exc:
            message = sanitize_provider_error(str(exc))
            raise LeadVaultAIError(f"Claude draft generation failed: {message}") from exc
        try:
            output = str(response.content[0].text or "").strip()
        except Exception as exc:
            raise LeadVaultAIError(f"Claude did not return a usable draft: {exc}") from exc
        if not output:
            raise LeadVaultAIError("The Claude response was empty. Try adjusting the lead notes and generating again.")
        return self._parse_generated_assets(output)

    def _system_prompt(self) -> str:
        return (
            "You help a lead-generation operator review local-business leads and draft first-contact outreach for a preview-first website improvement offer. "
            "Return only valid JSON with three string fields: opportunity_summary, outreach_strategy, and draft_message. "
            "The opportunity_summary is an internal note for the operator, not outreach copy. It should explain why this business is a worthwhile lead, "
            "what weak or missing web-presence issue stands out, which concrete evidence supports that conclusion, and why that likely affects trust, calls, bookings, or search visibility. "
            "The outreach_strategy is also an internal note. It should explain the best way to contact the business, backup ways to contact them, "
            "which proof points to mention, and how to frame a low-pressure preview or direction before asking for a larger commitment. "
            "The draft_message should sound human, specific, low-pressure, and commercially aware. It should feel like a real one-to-one note, not a generic agency template. "
            "Use the operator's offer positioning as the main commercial frame. Prefer evidence over hype, and do not invent facts when details are missing. "
            "Do not mention AI, scraping, databases, or internal scoring. "
            "Do not promise guaranteed rankings or guaranteed lead counts. "
            "Avoid generic filler like 'I hope you're well' or vague claims that could fit any business. "
            "If the web evidence is weak, explain the business impact in simple terms instead of technical jargon."
        )

    def _parse_generated_assets(self, text: str) -> GeneratedLeadContent:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise LeadVaultAIError("The AI response could not be parsed. Try again with a little more lead context.") from exc

        summary = str(payload.get("opportunity_summary", "")).strip()
        strategy = str(payload.get("outreach_strategy", "")).strip()
        draft = str(payload.get("draft_message", "")).strip()
        if not summary or not strategy or not draft:
            raise LeadVaultAIError("The AI response was missing the summary, strategy, or draft. Try generating it again.")
        return GeneratedLeadContent(opportunity_summary=summary, outreach_strategy=strategy, draft_message=draft)

    def _build_prompt(
        self,
        lead: dict[str, Any],
        personalization_notes: str,
        outreach_angle: str,
        existing_draft: str,
        existing_summary: str,
        agency_name: str,
        offer_positioning: str,
    ) -> str:
        data = self._lead_data(lead)
        web_intel = self._resolved_web_intel(lead)
        trigger_events = lead.get("trigger_events", []) or []
        trigger_summary = str(data.get("Trigger Summary", "")).strip()
        if not trigger_summary and trigger_events:
            trigger_summary = " | ".join(
                str(event.get("summary", "")).strip()
                for event in trigger_events
                if str(event.get("summary", "")).strip()
            )
        trigger_types = str(data.get("Trigger Types", "")).strip()
        if not trigger_types and trigger_events:
            trigger_types = "; ".join(
                str(event.get("label", "")).strip()
                for event in trigger_events
                if str(event.get("label", "")).strip()
            )
        phone = self._coalesce_text(lead.get("phone"), data.get("Phone"), web_intel.get("on_page_phones"))
        email = self._coalesce_text(lead.get("email"), data.get("Email"), web_intel.get("on_page_emails"))
        resolved_url = self._coalesce_text(web_intel.get("resolved_url"))
        offer_frame = offer_positioning.strip() or self._default_offer_positioning()
        contact_channels = self._contact_channels_summary(lead, web_intel)
        trust_signals = self._trust_signals_summary(lead, trigger_types)
        website_snapshot = self._website_evidence_snapshot(web_intel)
        audit_diagnostics = self._audit_diagnostics_snapshot(web_intel)
        return (
            "Create an internal opportunity summary, an outreach strategy, and an outreach draft for this lead.\n\n"
            "Offer context:\n"
            f"- Agency / brand name: {agency_name.strip() or 'Not provided'}\n"
            f"- Preview-first offer framing: {offer_frame}\n"
            "- Sales objective: Earn permission to show a useful preview or direction before asking for a bigger website commitment.\n\n"
            "Lead context:\n"
            f"Business name: {lead.get('business_name', '')}\n"
            f"City/Area: {lead.get('city_area', '')}\n"
            f"Business type: {data.get('Business Type', '')}\n"
            f"Review bucket: {data.get('Review Bucket', '')}\n"
            f"Opportunity brief: {web_intel.get('opportunity_brief', '')}\n"
            f"Lead rationale: {web_intel.get('lead_rationale', '')}\n"
            f"Business reality: {data.get('Business Reality', '')}\n"
            f"Reality confidence: {data.get('Reality Confidence', '')}\n"
            f"Web presence status: {web_intel.get('web_presence_status', '')}\n"
            f"Web details: {web_intel.get('web_presence_details', '')}\n"
            f"Web confidence: {web_intel.get('web_confidence', '')}\n"
            f"Website signals: {web_intel.get('website_signals', '')}\n"
            f"Website bucket: {web_intel.get('website_bucket', '')}\n"
            f"Website failure type: {web_intel.get('website_failure_type', '')}\n"
            f"Pitch family: {web_intel.get('pitch_family', '')}\n"
            f"Opportunity thesis: {web_intel.get('opportunity_thesis', '')}\n"
            f"Resolved website URL: {resolved_url}\n"
            f"Page title: {web_intel.get('page_title', '')}\n"
            f"Meta description: {web_intel.get('meta_description', '')}\n"
            f"Website evidence summary: {web_intel.get('evidence_summary', '')}\n"
            f"Website evidence snippet: {web_intel.get('evidence_snippet', '')}\n"
            f"Primary business impact: {web_intel.get('primary_business_impact', '')}\n"
            f"Best pitch angle: {web_intel.get('best_pitch_angle', '')}\n"
            f"Audit confidence: {web_intel.get('audit_confidence', '')}\n"
            f"Last audited at: {web_intel.get('last_audited_at', '')}\n"
            f"Last verified: {web_intel.get('last_verified_at', '')}\n"
            f"Data freshness: {web_intel.get('data_freshness', '')}\n"
            f"Trigger types: {trigger_types}\n"
            f"Trigger summary: {trigger_summary}\n"
            f"Audit issues: {web_intel.get('audit_issues', '')}\n"
            f"Business impact summary: {web_intel.get('business_impact_summary', '')}\n"
            f"Phone: {phone}\n"
            f"Email: {email}\n"
            f"Contact cross-reference: {data.get('Contact Cross-Reference', '')}\n"
            f"Cross-reference details: {data.get('Cross-Reference Details', '')}\n"
            f"LinkedIn profile: {data.get('LinkedIn Profile', '')}\n"
            f"Social profiles: {data.get('Social Profiles', '')}\n"
            f"Social profile URLs: {data.get('Social Profile URLs', '')}\n"
            f"Colorado status: {data.get('Colorado Status Category', data.get('Colorado Record Status', ''))}\n"
            f"Colorado status note: {data.get('Colorado Status Note', '')}\n"
            f"Colorado history: {data.get('Colorado History Summary', '')}\n"
            f"Available contact channels: {contact_channels}\n"
            f"Trust signals summary: {trust_signals}\n"
            f"Website evidence snapshot: {website_snapshot}\n"
            f"Audit diagnostics summary: {audit_diagnostics}\n"
            f"Offer positioning / incentive: {offer_frame}\n"
            f"Personalization notes: {personalization_notes.strip() or 'None provided'}\n"
            f"Existing outreach strategy to improve: {outreach_angle.strip() or 'None provided'}\n"
            f"Existing opportunity summary to improve: {existing_summary.strip() or 'None'}\n"
            f"Existing draft to improve: {existing_draft.strip() or 'None'}\n\n"
            "Requirements:\n"
            "- Output valid JSON only.\n"
            "- JSON format: {\"opportunity_summary\": \"...\", \"outreach_strategy\": \"...\", \"draft_message\": \"...\"}\n"
            "- opportunity_summary should be 3 to 5 sentences, easy to skim, and written for internal use only.\n"
            "- opportunity_summary should explain why the business was selected as a lead, not read like a message to the customer.\n"
            "- opportunity_summary should use 2 to 4 concrete facts from the lead when possible and connect those facts to likely business impact.\n"
            "- opportunity_summary should build on the deterministic opportunity thesis and pitch family instead of inventing a brand new angle.\n"
            "- If there is no website, explain the missed trust/search/conversion opportunity and likely ROI from having one.\n"
            "- If the site is broken or weak, explain why that likely hurts calls, bookings, or credibility.\n"
            "- outreach_strategy should be 3 to 5 short bullets or sentences for internal use only.\n"
            "- outreach_strategy should recommend the best first channel, backup channel, what proof points to mention, and how to frame the preview-first offer.\n"
            "- outreach_strategy should stay consistent with the pitch family and best pitch angle unless the evidence clearly supports a narrower version of the same thesis.\n"
            "- outreach_strategy should use the available contact evidence like phone, email, LinkedIn, or social when relevant.\n"
            "- If a channel is not supported by the lead data, do not recommend it as the primary outreach path.\n"
            "- draft_message should be 110 to 170 words.\n"
            "- Make the draft sound human and specific to this lead.\n"
            "- Open with a natural business-specific observation or hook, not a generic intro that could fit any prospect.\n"
            "- Mention at least one concrete web or trust observation and one practical business outcome.\n"
            "- If the operator offers preview/mockup work before commitment, weave that in naturally when the offer positioning suggests it.\n"
            "- Focus on growth, visibility, trust, and easier conversion rather than only listing defects.\n"
            "- Sound like a real person helping a local business, not a generic agency blast or a technical audit report.\n"
            "- If existing notes or a draft are provided, improve them with sharper specifics instead of repeating them verbatim.\n"
            "- End with a soft, low-pressure call to action.\n"
        )
