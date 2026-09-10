"""Opportunity Review Agent — a post-score Claude reasoning layer.

Runs AFTER the deterministic audit/scoring pipeline. Produces a strict
JSON review that helps suppress false positives, choose pitch angles,
and summarize opportunities. Does NOT replace deterministic scoring.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any

try:
    import anthropic as _anthropic
except ImportError:
    _anthropic = None

try:
    from openai import OpenAI as _OpenAI
except ImportError:
    _OpenAI = None


# ── Constants ────────────────────────────────────────────────────────

AGENT_REVIEW_MODEL = "claude-sonnet-4-6"
AGENT_REVIEW_TIMEOUT = 30
MIN_AUDIT_CONFIDENCE = 0.55
MIN_EVIDENCE_FIELDS = 3

DEFAULT_AGENT_MODELS = {
    "OpenAI": "gpt-5.4-mini",
    "Anthropic": "claude-sonnet-4-6",
    "Claude": "claude-sonnet-4-6",
}


def _resolve_agent_model(provider: str, model: str) -> str:
    if model and model.strip():
        return model.strip()
    return DEFAULT_AGENT_MODELS.get(provider, AGENT_REVIEW_MODEL)

VALID_VERDICTS = ("high_opportunity", "medium_opportunity", "low_opportunity", "unclear")
VALID_ACTIONS = ("surface", "review", "suppress")
VALID_PRIORITIES = ("high", "medium", "low")


AGENT_SYSTEM_PROMPT = (
    "You are an Opportunity Review Agent for a website opportunity intelligence system.\n\n"
    "Your job is not to rewrite data, scrape websites, or invent facts.\n"
    "Your job is to review structured audit results and decide whether the lead is a real website improvement opportunity.\n\n"
    "You must:\n"
    "- evaluate the evidence conservatively\n"
    "- avoid overrating businesses with already-strong websites\n"
    "- suppress false positives when the site appears professionally built and conversion-ready\n"
    "- choose the single best sales angle based only on the evidence provided\n"
    "- return strict JSON only\n"
    "- never include markdown\n"
    "- never include explanations outside the JSON\n\n"
    "Important rules:\n"
    "1. A high score does not automatically mean high opportunity.\n"
    "2. If the site appears strong across CTA, trust, mobile, and contact flow, suppress the opportunity even if the quality score is high.\n"
    "3. Prefer realistic business impact angles such as:\n"
    "   - more calls\n"
    "   - more quote requests\n"
    "   - stronger trust\n"
    "   - better local visibility\n"
    "   - easier contact flow\n"
    "4. Be conservative when evidence is thin or stale.\n"
    "5. Do not hallucinate website features that are not present in the input.\n"
    "6. If the evidence is mixed, explain the uncertainty in risk_notes.\n"
    "7. Your output must match the required JSON schema exactly."
)

AGENT_USER_PROMPT_TEMPLATE = (
    "Review this business website opportunity record and return a strict JSON decision.\n\n"
    "Required output fields:\n"
    "- verdict: one of [\"high_opportunity\", \"medium_opportunity\", \"low_opportunity\", \"unclear\"]\n"
    "- suppress_opportunity: boolean\n"
    "- why_now: string\n"
    "- best_pitch_angle: string\n"
    "- pitch_angle_confidence: number from 0 to 1\n"
    "- human_summary: string\n"
    "- top_reasons: array of strings\n"
    "- risk_notes: array of strings\n"
    "- recommended_action: one of [\"surface\", \"review\", \"suppress\"]\n"
    "- priority: one of [\"high\", \"medium\", \"low\"]\n\n"
    "Record:\n{record_json}"
)


# ── Data structures ──────────────────────────────────────────────────

@dataclass
class AgentReviewResult:
    verdict: str = "unclear"
    suppress_opportunity: bool = False
    why_now: str = "Agent review unavailable or insufficient evidence."
    best_pitch_angle: str = "Needs manual review"
    pitch_angle_confidence: float = 0.0
    human_summary: str = "Not enough reliable evidence for agent review."
    top_reasons: list[str] = field(default_factory=list)
    risk_notes: list[str] = field(default_factory=list)
    recommended_action: str = "review"
    priority: str = "low"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def fallback(cls, reason: str = "Agent unavailable or audit confidence too low") -> "AgentReviewResult":
        return cls(risk_notes=[reason])

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentReviewResult":
        return cls(
            verdict=str(data.get("verdict", "unclear")),
            suppress_opportunity=bool(data.get("suppress_opportunity", False)),
            why_now=str(data.get("why_now", "")),
            best_pitch_angle=str(data.get("best_pitch_angle", "")),
            pitch_angle_confidence=_safe_float(data.get("pitch_angle_confidence"), 0.0),
            human_summary=str(data.get("human_summary", "")),
            top_reasons=list(data.get("top_reasons") or []),
            risk_notes=list(data.get("risk_notes") or []),
            recommended_action=str(data.get("recommended_action", "review")),
            priority=str(data.get("priority", "low")),
        )


# ── Input builder ────────────────────────────────────────────────────

def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _parse_issues_json(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [str(i).strip() for i in raw if str(i).strip()]
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(i).strip() for i in parsed if str(i).strip()]
        except (json.JSONDecodeError, TypeError):
            return [raw.strip()] if raw.strip() else []
    return []


def _is_strong_signal(value: str) -> bool:
    """Check if an audit diagnostic indicates a strong/good signal."""
    lowered = value.lower().strip()
    return any(k in lowered for k in ("strong", "good", "yes", "present", "excellent", "solid"))


def build_review_input(lead: dict[str, Any]) -> dict[str, Any]:
    """Build the structured record sent to Claude from existing lead + audit data."""
    data = lead.get("data", {}) or {}
    audit = lead.get("latest_audit", {}) or {}

    def _lead_or_data(key: str, default: str = "") -> str:
        v = lead.get(key)
        if v not in (None, ""):
            return _safe_str(v)
        return _safe_str(data.get(key, default))

    def _audit_or_data(key: str, default: str = "") -> str:
        v = audit.get(key)
        if v not in (None, ""):
            return _safe_str(v)
        return _safe_str(data.get(key, default))

    # ── Scores ──
    website_quality_score = _safe_int(lead.get("website_quality_score", data.get("Website Quality Score", 0)))
    opportunity_score = _safe_int(lead.get("opportunity_score", data.get("Opportunity Score", 0)))

    # Trust score: derive from available signals
    trust_signals_count = sum(1 for k in [
        _audit_or_data("Contact Form Status"),
        _lead_or_data("Contact Cross-Reference"),
        _lead_or_data("Colorado Record Status"),
        _audit_or_data("SSL Status"),
    ] if _is_strong_signal(k))
    trust_score = min(100, trust_signals_count * 25)

    # Conversion score
    conversion_factors = [
        _audit_or_data("CTA Strength"),
        _audit_or_data("Contact Form Status"),
        _audit_or_data("Booking Flow Status"),
    ]
    conversion_strong = sum(1 for f in conversion_factors if _is_strong_signal(f))
    conversion_score = min(100, conversion_strong * 33)

    # SEO score
    seo_value = _audit_or_data("SEO Basics")
    seo_score = 70 if _is_strong_signal(seo_value) else (40 if seo_value else 0)

    # Mobile score
    mobile_value = _audit_or_data("Mobile Readiness")
    mobile_score = 70 if _is_strong_signal(mobile_value) else (40 if mobile_value else 0)

    # ── Audit confidence ──
    raw_confidence = _audit_or_data("Audit Confidence", _lead_or_data("Web Presence Confidence", ""))
    audit_confidence = _safe_float(raw_confidence.replace("%", "").strip() if raw_confidence else 0)
    if audit_confidence > 1.0:
        audit_confidence = audit_confidence / 100.0

    # ── Freshness ──
    freshness_str = _safe_str(lead.get("freshness_status", _audit_or_data("Data Freshness")))
    freshness_days = 0
    last_verified = _audit_or_data("Last Verified At")
    if last_verified:
        try:
            dt = datetime.fromisoformat(last_verified.replace("Z", "+00:00"))
            if dt.tzinfo:
                dt = dt.astimezone().replace(tzinfo=None)
            freshness_days = max(0, (datetime.now() - dt).days)
        except (ValueError, TypeError):
            pass

    # ── Disqualifiers ──
    cta_strong = _is_strong_signal(_audit_or_data("CTA Strength"))
    booking_strong = _is_strong_signal(_audit_or_data("Booking Flow Status"))
    contact_form_present = _is_strong_signal(_audit_or_data("Contact Form Status"))
    ssl_ok = _is_strong_signal(_audit_or_data("SSL Status"))
    mobile_ok = _is_strong_signal(_audit_or_data("Mobile Readiness"))
    tech_stack_score = _safe_int(_audit_or_data("Tech Stack Score", _lead_or_data("Tech Stack Score", "0")))
    tech_stack_signal = _audit_or_data("Tech Stack Signal", _lead_or_data("Tech Stack Signal", ""))
    tech_stack_summary = _audit_or_data("Tech Stack Summary", _lead_or_data("Tech Stack Summary", ""))
    tech_stack_modern = "modern" in tech_stack_signal.lower() and tech_stack_score < 10

    # Determine if site looks professional (multiple strong signals)
    strong_count = sum([cta_strong, booking_strong, contact_form_present, ssl_ok, mobile_ok])
    site_looks_professional = strong_count >= 4
    no_major_issues = website_quality_score >= 75 and strong_count >= 3

    # ── Audit flags ──
    has_ssl = "valid" in _audit_or_data("SSL Status").lower() or ssl_ok
    has_meta = bool(_audit_or_data("Meta Description"))
    has_h1 = bool(_audit_or_data("Page Title"))
    has_phone = bool(_audit_or_data("On-Page Phones"))
    has_email = bool(_audit_or_data("On-Page Emails"))
    has_contact_form = contact_form_present
    has_booking = booking_strong
    has_cta = cta_strong
    has_reviews = bool(_lead_or_data("Reviews")) and _safe_int(_lead_or_data("Reviews")) > 0
    has_testimonials = False  # Not tracked in current audit
    evidence_summary_text = _audit_or_data("Website Evidence Summary")
    has_service_area = bool(evidence_summary_text) and "service" in evidence_summary_text.lower()
    has_gallery = False  # Not tracked in current audit
    has_fast_load = _is_strong_signal(_audit_or_data("Page Speed Signal"))
    mobile_friendly = mobile_ok

    # ── Issues and evidence ──
    # Prefer structured list (added in hardening pass) over joined string
    issues_list = audit.get("Audit Issues List") or []
    if isinstance(issues_list, list) and issues_list:
        issues = _parse_issues_json(issues_list)
    else:
        issues = _parse_issues_json(_audit_or_data("Audit Issues"))
    if not issues:
        # Derive issues from weak signals
        if not cta_strong:
            issues.append("No strong primary CTA above the fold")
        if not contact_form_present and not has_phone:
            issues.append("Limited contact options visible")
        if not ssl_ok:
            issues.append("SSL/security issue")
        if not mobile_ok and mobile_value:
            issues.append("Mobile experience needs improvement")
    if tech_stack_score >= 38:
        issues.append(f"Weak or outdated technology stack: {tech_stack_signal}")
    elif tech_stack_score >= 22:
        issues.append(f"Missing analytics, tracking, or conversion-stack signals: {tech_stack_signal}")

    evidence: list[str] = []
    # Prefer structured list over joined string
    impact_list = audit.get("Business Impact List") or []
    evidence_summary_val = _audit_or_data("Website Evidence Summary")
    if evidence_summary_val:
        evidence.append(evidence_summary_val)
    evidence_snippet_val = _audit_or_data("Website Evidence Snippet")
    if evidence_snippet_val and evidence_snippet_val != evidence_summary_val:
        evidence.append(evidence_snippet_val)
    if tech_stack_summary:
        evidence.append(f"Tech stack: {tech_stack_summary}")
    if isinstance(impact_list, list) and impact_list:
        impact_items = _parse_issues_json(impact_list)
    else:
        impact_items = _parse_issues_json(_audit_or_data("Business Impact Summary"))
    evidence.extend(impact_items)

    return {
        "business_name": _safe_str(lead.get("business_name", data.get("Business Name", ""))),
        "category": _safe_str(data.get("Business Type", "")),
        "location": _safe_str(lead.get("city_area", data.get("City/Area", ""))),
        "website_url": _audit_or_data("Resolved Website URL", _lead_or_data("Official Website")),
        "audit_confidence": round(audit_confidence, 2),
        "freshness_days": freshness_days,
        "scores": {
            "website_quality_score": website_quality_score,
            "opportunity_score": opportunity_score,
            "trust_score": trust_score,
            "conversion_score": conversion_score,
            "seo_score": seo_score,
            "mobile_score": mobile_score,
            "tech_stack_score": tech_stack_score,
        },
        "disqualifiers": {
            "site_looks_professional": site_looks_professional,
            "strong_cta": cta_strong,
            "strong_booking_flow": booking_strong,
            "strong_trust_signals": trust_score >= 75,
            "good_mobile_experience": mobile_ok,
            "modern_conversion_stack": tech_stack_modern,
            "no_major_issues_found": no_major_issues,
        },
        "audit_flags": {
            "has_ssl": has_ssl,
            "has_meta_description": has_meta,
            "has_clear_h1": has_h1,
            "has_phone_number": has_phone,
            "has_email": has_email,
            "has_contact_form": has_contact_form,
            "has_booking_system": has_booking,
            "has_clear_cta": has_cta,
            "has_reviews_visible": has_reviews,
            "has_testimonials": has_testimonials,
            "has_service_area_content": has_service_area,
            "has_before_after_gallery": has_gallery,
            "has_fast_load_signals": has_fast_load,
            "mobile_friendly": mobile_friendly,
        },
        "issues": issues[:8],
        "evidence": evidence[:8],
    }


# ── Input hashing ────────────────────────────────────────────────────

def compute_input_hash(review_input: dict[str, Any]) -> str:
    """Stable SHA-256 fingerprint of the review input payload."""
    canonical = json.dumps(review_input, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


# ── Gating logic ────────────────────────────────────────────────────

def should_review(review_input: dict[str, Any]) -> tuple[bool, str]:
    """Decide whether this record warrants an agent review.

    Returns (should_run, skip_reason).
    """
    confidence = review_input.get("audit_confidence", 0.0)
    if confidence < MIN_AUDIT_CONFIDENCE:
        return False, f"audit_confidence {confidence:.2f} < {MIN_AUDIT_CONFIDENCE}"

    # Count meaningful evidence fields
    evidence_count = len(review_input.get("evidence", []))
    issues_count = len(review_input.get("issues", []))
    flags = review_input.get("audit_flags", {})
    true_flags = sum(1 for v in flags.values() if v is True)

    total_evidence = evidence_count + issues_count + true_flags
    if total_evidence < MIN_EVIDENCE_FIELDS:
        return False, f"insufficient evidence ({total_evidence} signals < {MIN_EVIDENCE_FIELDS})"

    return True, ""


def should_skip_cached(
    stored_hash: str | None,
    stored_status: str | None,
    new_hash: str,
) -> bool:
    """Return True if the cached review is still valid (same input hash)."""
    if not stored_hash or not stored_status:
        return False
    if stored_status != "completed":
        return False
    return stored_hash == new_hash


# ── Output validation ────────────────────────────────────────────────

def validate_review_output(raw: dict[str, Any]) -> AgentReviewResult:
    """Parse and validate Claude's JSON output into a safe AgentReviewResult."""
    verdict = str(raw.get("verdict", "unclear"))
    if verdict not in VALID_VERDICTS:
        verdict = "unclear"

    action = str(raw.get("recommended_action", "review"))
    if action not in VALID_ACTIONS:
        action = "review"

    priority = str(raw.get("priority", "low"))
    if priority not in VALID_PRIORITIES:
        priority = "low"

    confidence = _safe_float(raw.get("pitch_angle_confidence"), 0.0)
    confidence = max(0.0, min(1.0, confidence))

    return AgentReviewResult(
        verdict=verdict,
        suppress_opportunity=bool(raw.get("suppress_opportunity", False)),
        why_now=str(raw.get("why_now", ""))[:500],
        best_pitch_angle=str(raw.get("best_pitch_angle", ""))[:300],
        pitch_angle_confidence=round(confidence, 2),
        human_summary=str(raw.get("human_summary", ""))[:1000],
        top_reasons=[str(r)[:200] for r in (raw.get("top_reasons") or [])[:5]],
        risk_notes=[str(r)[:200] for r in (raw.get("risk_notes") or [])[:5]],
        recommended_action=action,
        priority=priority,
    )


# ── Claude call ──────────────────────────────────────────────────────

def _strip_fences(output: str) -> str:
    if output.startswith("```"):
        import re
        output = re.sub(r"^```(?:json)?\s*", "", output)
        output = re.sub(r"\s*```$", "", output)
    return output


def _call_claude(
    api_key: str,
    review_input: dict[str, Any],
    model: str = "",
) -> AgentReviewResult:
    """Call Claude and return a validated AgentReviewResult."""
    if _anthropic is None:
        raise RuntimeError("anthropic package not installed")

    client = _anthropic.Anthropic(
        api_key=api_key.strip(),
        timeout=AGENT_REVIEW_TIMEOUT,
    )
    record_json = json.dumps(review_input, indent=2)
    user_prompt = AGENT_USER_PROMPT_TEMPLATE.format(record_json=record_json)

    response = client.messages.create(
        model=model.strip() or AGENT_REVIEW_MODEL,
        max_tokens=1024,
        system=AGENT_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    output = _strip_fences(str(response.content[0].text or "").strip())
    parsed = json.loads(output)
    return validate_review_output(parsed)


def _call_openai(
    api_key: str,
    review_input: dict[str, Any],
    model: str = "",
) -> AgentReviewResult:
    """Call OpenAI and return a validated AgentReviewResult."""
    if _OpenAI is None:
        raise RuntimeError("openai package not installed")

    client = _OpenAI(api_key=api_key.strip(), timeout=AGENT_REVIEW_TIMEOUT)
    record_json = json.dumps(review_input, indent=2)
    user_prompt = AGENT_USER_PROMPT_TEMPLATE.format(record_json=record_json)
    used_model = model.strip() or DEFAULT_AGENT_MODELS["OpenAI"]

    response = client.chat.completions.create(
        model=used_model,
        max_tokens=1024,
        messages=[
            {"role": "system", "content": AGENT_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
    )
    output = _strip_fences(str(response.choices[0].message.content or "").strip())
    parsed = json.loads(output)
    return validate_review_output(parsed)


# ── Public API ───────────────────────────────────────────────────────

def run_agent_review(
    lead: dict[str, Any],
    api_key: str,
    model: str = "",
    stored_hash: str | None = None,
    stored_status: str | None = None,
    stored_review: dict[str, Any] | None = None,
    force: bool = False,
    provider: str = "Anthropic",
) -> dict[str, Any]:
    """Run the Opportunity Review Agent for a single lead.

    Returns a dict with:
        ok: bool
        review: dict (AgentReviewResult as dict)
        status: "completed" | "skipped" | "cached" | "error"
        input_hash: str
        model: str
        skip_reason: str (if skipped)
        error: str (if error)
    """
    review_input = build_review_input(lead)
    input_hash = compute_input_hash(review_input)
    provider = (provider or "Anthropic").strip() or "Anthropic"
    used_model = _resolve_agent_model(provider, model)

    # Gate: should we review? (force=True bypasses gating for manual runs)
    should, skip_reason = should_review(review_input)
    if not should and not force:
        fallback = AgentReviewResult.fallback(skip_reason)
        return {
            "ok": True,
            "review": fallback.to_dict(),
            "status": "skipped",
            "input_hash": input_hash,
            "model": used_model,
            "skip_reason": skip_reason,
        }

    # Cache check
    if should_skip_cached(stored_hash, stored_status, input_hash) and stored_review:
        return {
            "ok": True,
            "review": stored_review,
            "status": "cached",
            "input_hash": input_hash,
            "model": used_model,
            "skip_reason": "",
        }

    # Call provider
    if not api_key or not api_key.strip():
        fallback = AgentReviewResult.fallback(f"No {provider} API key configured")
        return {
            "ok": False,
            "review": fallback.to_dict(),
            "status": "error",
            "input_hash": input_hash,
            "model": used_model,
            "error": f"No {provider} API key configured",
        }

    try:
        if provider in ("Anthropic", "Claude"):
            result = _call_claude(api_key, review_input, model=used_model)
        elif provider == "OpenAI":
            result = _call_openai(api_key, review_input, model=used_model)
        else:
            raise RuntimeError(f"Unsupported provider: {provider}")
        return {
            "ok": True,
            "review": result.to_dict(),
            "status": "completed",
            "input_hash": input_hash,
            "model": used_model,
            "skip_reason": "",
        }
    except json.JSONDecodeError as exc:
        fallback = AgentReviewResult.fallback("Claude returned invalid JSON")
        return {
            "ok": False,
            "review": fallback.to_dict(),
            "status": "error",
            "input_hash": input_hash,
            "model": used_model,
            "error": f"Invalid JSON from Claude: {exc}",
        }
    except Exception as exc:
        from lead_vault_ai import sanitize_provider_error
        error_msg = sanitize_provider_error(str(exc))
        fallback = AgentReviewResult.fallback(f"Agent error: {error_msg}")
        return {
            "ok": False,
            "review": fallback.to_dict(),
            "status": "error",
            "input_hash": input_hash,
            "model": used_model,
            "error": error_msg,
        }
