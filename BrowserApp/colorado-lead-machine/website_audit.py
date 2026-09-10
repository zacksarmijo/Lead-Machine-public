from __future__ import annotations

from datetime import datetime
import re
from typing import Any


AUDIT_VERSION = "1.3.0"

_GENERIC_TITLES = {"", "home", "welcome", "index"}
_LIVE_WEBSITE_BUCKETS = {"Weak live site", "Basic live site", "Established website", "Unclassified"}
_CONVERSION_GAP_PHRASES = (
    "missing",
    "weak",
    "unclear",
    "no business cta",
    "no clear cta",
    "no booking",
    "no quote",
    "no real business contact path",
    "0 forms found",
)
_TRUST_GAP_PHRASES = (
    "missing",
    "weak",
    "thin",
    "placeholder",
    "parked",
    "broken landing page",
    "no business visual proof",
    "thin navigation",
    "no usable business navigation",
)
_PITCH_FAMILY_THESIS = {
    "no_website": "The business does not control its own web presence, so trust, search visibility, and lead capture are being left to third-party platforms.",
    "unknown_web_presence": "The discovery run could not verify the business website status, so the lead needs another data source or retry before outreach.",
    "broken_site": "The current website is breaking before visitors can reach a usable business experience, which likely cuts off trust and conversion.",
    "placeholder_site": "Visitors are reaching a placeholder page rather than a finished business website, which weakens first impressions before they contact the business.",
    "parked_domain": "The domain resolves to a parked or for-sale page instead of a business website, so prospects never reach a real destination.",
    "dead_page": "The main website URL leads to a missing or removed page, so visitors hit a dead end instead of a usable website.",
    "security_issue": "Security or SSL failures can block access to the site entirely, which interrupts trust and lead capture before visitors engage.",
    "social_only_dependence": "The business is relying on social profiles instead of an owned website, limiting control over trust, discovery, and conversion.",
    "directory_only_dependence": "The business is relying on directory listings instead of an owned website, leaving discovery and conversion in third-party hands.",
    "weak_live_site": "The site is live, but it still shows enough friction to justify a stronger website opportunity.",
    "weak_conversion_path": "The site is live, but the conversion path is weak enough that interested visitors may not see a clear next step before they leave.",
    "weak_trust_signals": "The site is live, but weak trust signals are likely reducing confidence before prospects decide to call or book.",
}


def _text_value(source: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = source.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _contains_any(text: str, phrases: list[str]) -> bool:
    return any(phrase in text for phrase in phrases)


def _int_value(value: Any) -> int:
    if value in ("", None):
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    match = re.search(r"-?\d+", str(value))
    return int(match.group(0)) if match else 0


def _split_terms(value: Any) -> list[str]:
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


def _broken_site_fact_profile(failure_type: str, details: str, signals: str) -> dict[str, str]:
    lowered = f"{failure_type} {details} {signals}".lower()

    if _contains_any(lowered, ["parked", "for-sale", "for sale"]):
        return {
            "mobile": "Could not verify on parked page",
            "page_speed": "Could not measure; parked page",
            "contact_form": "No real business contact path visible",
            "booking_flow": "No booking or quote flow visible",
            "cta_strength": "No business CTA visible",
            "seo_basics": "Parked page, not business content",
            "image_quality": "No business visual proof visible",
            "navigation_quality": "No usable business navigation visible",
            "issue": "Domain appears parked or listed for sale instead of serving a business website",
            "impact": "Visitors are landing on a parked page instead of a real business website.",
            "pitch": "Parked domain; visitors are not reaching a real business website.",
        }

    if _contains_any(lowered, ["placeholder", "under-construction", "under construction", "coming-soon", "coming soon", "holding page", "default hosting page"]):
        return {
            "mobile": "Could not verify on placeholder page",
            "page_speed": "Could not measure; placeholder page",
            "contact_form": "No real business contact path visible",
            "booking_flow": "No booking or quote flow visible",
            "cta_strength": "No business CTA visible",
            "seo_basics": "Placeholder content only",
            "image_quality": "No business visual proof visible",
            "navigation_quality": "No usable business navigation visible",
            "issue": "Page still looks like a placeholder instead of a finished business website",
            "impact": "Visitors are landing on a placeholder page instead of a finished business website.",
            "pitch": "Placeholder page; visitors are not reaching a finished business website.",
        }

    if _contains_any(lowered, ["dead page", "page missing", "removed", "http 404", "http 410", "missing page"]):
        return {
            "mobile": "Could not verify; landing page missing",
            "page_speed": "Could not measure; landing page missing",
            "contact_form": "Could not verify; landing page missing",
            "booking_flow": "Could not verify; landing page missing",
            "cta_strength": "Could not verify; landing page missing",
            "seo_basics": "Broken landing page",
            "image_quality": "Could not verify; landing page missing",
            "navigation_quality": "Could not verify; landing page missing",
            "issue": "Main website URL returns a missing or removed page",
            "impact": "Visitors are hitting a missing page instead of a working website.",
            "pitch": "Missing website page; visitors are hitting a dead page instead of a working site.",
        }

    if _contains_any(lowered, ["ssl", "tls", "security failure"]):
        return {
            "mobile": "Could not verify due to SSL/security failure",
            "page_speed": "Could not measure; SSL/security failure",
            "contact_form": "Could not verify; SSL/security failure",
            "booking_flow": "Could not verify; SSL/security failure",
            "cta_strength": "Could not verify; SSL/security failure",
            "seo_basics": "Could not evaluate; SSL/security failure",
            "image_quality": "Could not evaluate; SSL/security failure",
            "navigation_quality": "Could not evaluate; SSL/security failure",
            "issue": "Website failed SSL or security validation",
            "impact": "Some visitors may fail to load the website at all because of a security or SSL issue.",
            "pitch": "SSL/security issue; some visitors may fail to load the site at all.",
        }

    if _contains_any(lowered, ["server error", "http 5"]):
        return {
            "mobile": "Could not verify due to server error",
            "page_speed": "Could not measure; server error",
            "contact_form": "Could not verify; server error",
            "booking_flow": "Could not verify; server error",
            "cta_strength": "Could not verify; server error",
            "seo_basics": "Could not evaluate; server error",
            "image_quality": "Could not evaluate; server error",
            "navigation_quality": "Could not evaluate; server error",
            "issue": "Website is returning a server error instead of a usable page",
            "impact": "Visitors may abandon before calling or booking because the site is serving an error.",
            "pitch": "Server error website; visitors may hit an error page instead of a usable site.",
        }

    if _contains_any(lowered, ["timeout", "connection failure", "dns", "too many redirects", "redirect loop", "redirect problem"]):
        return {
            "mobile": "Could not verify due to site failure",
            "page_speed": "Could not measure; site unavailable",
            "contact_form": "Could not verify; site unavailable",
            "booking_flow": "Could not verify; site unavailable",
            "cta_strength": "Could not verify; site unavailable",
            "seo_basics": "Could not evaluate; site unavailable",
            "image_quality": "Could not evaluate; site unavailable",
            "navigation_quality": "Could not evaluate; site unavailable",
            "issue": "Website could not be reached reliably enough to inspect",
            "impact": "Visitors may drop before calling or booking because the site is unavailable or unstable.",
            "pitch": "Unavailable website; visitors may fail to reach the site at all.",
        }

    return {
        "mobile": "Could not verify due to broken site",
        "page_speed": "Could not measure; broken site",
        "contact_form": "Could not verify; broken site",
        "booking_flow": "Could not verify; broken site",
        "cta_strength": "Could not verify; broken site",
        "seo_basics": "Could not evaluate; broken site",
        "image_quality": "Could not evaluate; broken site",
        "navigation_quality": "Could not evaluate; broken site",
        "issue": "Website is broken or unusable",
        "impact": "Visitors may leave before contacting the business because the website experience is broken.",
        "pitch": "Broken website; visitors are likely dropping off before calling or booking.",
    }


def derive_pitch_family(source: dict[str, Any]) -> str:
    explicit_pitch_family = _text_value(
        source,
        "Pitch Family",
        "pitch_family",
    )
    if explicit_pitch_family:
        return explicit_pitch_family

    website_bucket = _text_value(
        source,
        "Website Bucket",
        "website_bucket",
        "Web Presence Status",
        "web_presence_status",
    )
    failure_type = _text_value(source, "Website Failure Type", "website_failure_type")
    ssl_status = _text_value(source, "SSL Status", "ssl_status")
    http_status = _text_value(source, "HTTP Status", "http_status")
    contact_form_status = _text_value(source, "Contact Form Status", "contact_form_status")
    booking_flow_status = _text_value(source, "Booking Flow Status", "booking_flow_status")
    cta_strength = _text_value(source, "CTA Strength", "cta_strength")
    seo_basics = _text_value(source, "SEO Basics", "seo_basics")
    image_quality = _text_value(source, "Image Quality Signal", "image_quality_signal")
    navigation_quality = _text_value(source, "Navigation Quality", "navigation_quality")
    social_dependence = _text_value(source, "Social Dependence", "social_dependence")
    directory_dependence = _text_value(source, "Directory Dependence", "directory_dependence")
    lowered = " ".join(
        part.lower()
        for part in [
            website_bucket,
            failure_type,
            ssl_status,
            http_status,
        ]
        if part
    )

    if website_bucket == "No website":
        return "no_website"
    if website_bucket == "Unknown web presence":
        return "unknown_web_presence"
    if website_bucket == "Social-only presence" or website_bucket == "Social only" or social_dependence == "High":
        return "social_only_dependence"
    if website_bucket == "Directory-only presence" or website_bucket == "Directory only" or directory_dependence == "High":
        return "directory_only_dependence"
    if _contains_any(lowered, ["ssl", "tls", "security failure", "security issue"]):
        return "security_issue"
    if _contains_any(lowered, ["parked", "for-sale", "for sale"]):
        return "parked_domain"
    if _contains_any(lowered, ["placeholder", "under-construction", "under construction", "coming-soon", "coming soon", "holding page", "default hosting page"]):
        return "placeholder_site"
    if _contains_any(lowered, ["dead page", "page missing", "removed", "http 404", "http 410", "404", "410", "missing page"]):
        return "dead_page"
    if website_bucket == "Broken site":
        return "broken_site"

    conversion_signal_text = " ".join(
        part.lower()
        for part in [contact_form_status, booking_flow_status, cta_strength]
        if part
    )
    trust_signal_text = " ".join(
        part.lower()
        for part in [seo_basics, image_quality, navigation_quality]
        if part
    )
    if website_bucket in _LIVE_WEBSITE_BUCKETS or website_bucket == "Weak live site":
        if _contains_any(conversion_signal_text, list(_CONVERSION_GAP_PHRASES)):
            return "weak_conversion_path"
        if _contains_any(trust_signal_text, list(_TRUST_GAP_PHRASES)):
            return "weak_trust_signals"
        return "weak_live_site"

    return ""


def build_opportunity_thesis(source: dict[str, Any]) -> str:
    explicit_thesis = _text_value(source, "Opportunity Thesis", "opportunity_thesis")
    if explicit_thesis:
        return explicit_thesis

    pitch_family = derive_pitch_family(source)
    if not pitch_family:
        return ""

    thesis = _PITCH_FAMILY_THESIS.get(
        pitch_family,
        "The web presence still shows enough friction to justify a clearer website opportunity thesis.",
    )
    primary_business_impact = _text_value(source, "Primary Business Impact", "primary_business_impact")
    evidence_summary = _text_value(source, "Website Evidence Summary", "evidence_summary")
    clauses = [thesis]
    if primary_business_impact:
        clauses.append(f"Primary impact: {primary_business_impact}")
    if evidence_summary:
        clauses.append(f"Evidence: {evidence_summary}")
    return " ".join(clause for clause in clauses if clause).strip()


def compute_audit_confidence_score(
    web_presence_confidence: str,
    status: str,
    evidence_available: bool,
    *,
    page_title: str = "",
    meta_description: str = "",
    word_count: int = 0,
    form_count_checked: bool = False,
    image_count_checked: bool = False,
    internal_link_count_checked: bool = False,
    viewport_meta: str = "",
    on_page_phones: str = "",
    on_page_emails: str = "",
    cta_terms: str = "",
    http_status: str = "",
    inner_pages_checked: int = 0,
    discovery_source_count: int = 0,
) -> int:
    """Compute numeric 0-100 audit confidence from what was actually measured.

    Higher = more evidence was collected and cross-verified.
    """
    # Base confidence from web presence discovery method
    base_map = {"High": 40, "Medium": 25, "Low": 10, "": 15}
    score = base_map.get(web_presence_confidence, 15)

    # For no-website/social/directory, limited evidence is expected
    if status in {"No website", "Unknown web presence", "Social only", "Directory only"}:
        # Boost if multiple discovery sources confirmed the absence
        if discovery_source_count >= 3:
            score += 20
        elif discovery_source_count >= 2:
            score += 10
        return max(0, min(score, 100))

    # For broken sites where nothing could be measured
    if status == "Broken site" and not evidence_available:
        return max(score - 10, 10)

    # Evidence coverage: what was actually measured
    evidence_fields = {
        "page_title": bool(page_title),
        "meta_description": bool(meta_description),
        "word_count": word_count > 0,
        "form_count": form_count_checked,
        "image_count": image_count_checked,
        "internal_link_count": internal_link_count_checked,
        "viewport_meta": bool(viewport_meta),
        "on_page_phones": bool(on_page_phones),
        "on_page_emails": bool(on_page_emails),
        "cta_terms": bool(cta_terms),
        "http_status": bool(http_status),
    }
    measured = sum(1 for v in evidence_fields.values() if v)
    total = len(evidence_fields)

    if measured == 0:
        return max(score - 15, 5)

    # Evidence coverage contributes up to 40 points
    coverage = measured / total
    score += int(coverage * 40)

    # Inner page evidence bonus: up to 15 points
    if inner_pages_checked >= 2:
        score += 15
    elif inner_pages_checked == 1:
        score += 8

    # Multiple discovery sources bonus: up to 5 points
    if discovery_source_count >= 3:
        score += 5
    elif discovery_source_count >= 2:
        score += 3

    return max(0, min(score, 100))


def confidence_label_from_score(score: int) -> str:
    """Convert numeric confidence to label for backward compatibility."""
    if score >= 65:
        return "High"
    if score >= 35:
        return "Medium"
    return "Low"


def compute_audit_confidence(
    web_presence_confidence: str,
    status: str,
    evidence_available: bool,
    *,
    page_title: str = "",
    meta_description: str = "",
    word_count: int = 0,
    form_count_checked: bool = False,
    image_count_checked: bool = False,
    internal_link_count_checked: bool = False,
    viewport_meta: str = "",
    on_page_phones: str = "",
    on_page_emails: str = "",
    cta_terms: str = "",
    http_status: str = "",
    inner_pages_checked: int = 0,
    discovery_source_count: int = 0,
) -> str:
    """Compute audit confidence label. Wraps numeric score for backward compat."""
    score = compute_audit_confidence_score(
        web_presence_confidence,
        status,
        evidence_available,
        page_title=page_title,
        meta_description=meta_description,
        word_count=word_count,
        form_count_checked=form_count_checked,
        image_count_checked=image_count_checked,
        internal_link_count_checked=internal_link_count_checked,
        viewport_meta=viewport_meta,
        on_page_phones=on_page_phones,
        on_page_emails=on_page_emails,
        cta_terms=cta_terms,
        http_status=http_status,
        inner_pages_checked=inner_pages_checked,
        discovery_source_count=discovery_source_count,
    )
    return confidence_label_from_score(score)


def _no_site_default(field_value: str, status: str) -> str:
    """Return accurate default for rich audit fields when there's no owned site."""
    if field_value:
        return field_value
    if status == "Unknown web presence":
        return "Not verified"
    if status in {"No website", "Social only", "Directory only"}:
        return "No owned site to evaluate"
    return "Not checked"


def _broken_site_audit_default(field_value: str, broken_profile: dict[str, str], key: str) -> str:
    """Return accurate default for broken site fields — never 'Not checked'."""
    if field_value:
        return field_value
    return broken_profile.get(key, "Could not evaluate; broken site")


def build_website_opportunity_scorecard(lead: dict[str, Any], *, audited_at: str | None = None) -> dict[str, Any]:
    audited_at = audited_at or datetime.now().isoformat(timespec="seconds")
    status = str(lead.get("Web Presence Status", "")).strip()
    failure_type = str(lead.get("Website Failure Type", "")).strip()
    details = str(lead.get("Web Presence Details", "")).strip()
    signals = str(lead.get("Website Signals", "")).strip()
    website = str(lead.get("Official Website", "")).strip()
    listed_on = str(lead.get("Listed On", "")).strip()
    social_profiles = str(lead.get("Social Profiles", "")).strip()
    confidence = str(lead.get("Web Presence Confidence", "")).strip() or "Medium"
    lowered = f"{details} {signals}".lower()

    resolved_url = str(lead.get("Resolved Website URL", website)).strip()
    http_status = str(lead.get("HTTP Status", "")).strip()
    fetch_time_ms = _int_value(lead.get("Fetch Time Ms"))
    page_title = str(lead.get("Page Title", "")).strip()
    meta_description = str(lead.get("Meta Description", "")).strip()
    word_count = _int_value(lead.get("Word Count"))
    form_count = _int_value(lead.get("Form Count"))
    internal_link_count = _int_value(lead.get("Internal Link Count"))
    image_count = _int_value(lead.get("Image Count"))
    on_page_phones = str(lead.get("On-Page Phones", "")).strip()
    on_page_emails = str(lead.get("On-Page Emails", "")).strip()
    cta_terms_text = str(lead.get("CTA Terms", "")).strip()
    booking_terms_text = str(lead.get("Booking Terms", "")).strip()
    viewport_meta = str(lead.get("Viewport Meta", "")).strip()
    evidence_summary = str(lead.get("Website Evidence Summary", "")).strip()
    evidence_snippet = str(lead.get("Website Evidence Snippet", "")).strip()
    pagespeed_status = str(lead.get("PageSpeed Status", "")).strip()
    pagespeed_signal = str(lead.get("Page Speed Signal", "")).strip()
    pagespeed_performance = _int_value(lead.get("PageSpeed Performance Score"))
    pagespeed_accessibility = _int_value(lead.get("PageSpeed Accessibility Score"))
    pagespeed_best_practices = _int_value(lead.get("PageSpeed Best Practices Score"))
    pagespeed_seo = _int_value(lead.get("PageSpeed SEO Score"))
    pagespeed_summary = str(lead.get("PageSpeed Summary", "")).strip()
    pagespeed_field_summary = str(lead.get("PageSpeed Field Summary", "")).strip()
    pagespeed_opportunities = str(lead.get("PageSpeed Opportunities", "")).strip()
    pagespeed_error = str(lead.get("PageSpeed Error", "")).strip()
    builtwith_status = str(lead.get("BuiltWith Status", "")).strip()
    builtwith_domain = str(lead.get("BuiltWith Domain", "")).strip()
    builtwith_groups = str(lead.get("BuiltWith Groups", "")).strip()
    builtwith_categories = str(lead.get("BuiltWith Category Summary", "")).strip()
    tech_stack_signal = str(lead.get("Tech Stack Signal", "")).strip()
    tech_stack_score = _int_value(lead.get("Tech Stack Score"))
    tech_stack_summary = str(lead.get("Tech Stack Summary", "")).strip()
    tech_stack_weak = str(lead.get("Tech Stack Weak Signals", "")).strip()
    tech_stack_strong = str(lead.get("Tech Stack Strong Signals", "")).strip()
    tech_stack_error = str(lead.get("Tech Stack Error", "")).strip()
    google_analytics = str(lead.get("Google Analytics", "")).strip()
    facebook_pixel = str(lead.get("Facebook Pixel", "")).strip()
    schema_markup = str(lead.get("Schema Markup", "")).strip()
    open_graph_tags = str(lead.get("Open Graph Tags", "")).strip()
    canonical_tag = str(lead.get("Canonical Tag", "")).strip()
    robots_meta = str(lead.get("Robots Meta", "")).strip()
    booking_platforms = str(lead.get("Booking Platforms", "")).strip()
    social_links = str(lead.get("Social Links", "")).strip()
    review_widget = str(lead.get("Review Widget", "")).strip()
    chat_widget = str(lead.get("Chat Widget", "")).strip()
    accessibility_indicators = str(lead.get("Accessibility Indicators", "")).strip()
    images_with_alt_text = _int_value(lead.get("Images With Alt Text"))
    cta_terms = _split_terms(cta_terms_text)
    booking_terms = _split_terms(booking_terms_text)
    title_is_generic = page_title.strip().lower() in _GENERIC_TITLES or len(page_title.strip()) < 8
    evidence_available = any(
        [
            page_title,
            meta_description,
            word_count > 0,
            form_count > 0,
            internal_link_count > 0,
            image_count > 0,
            on_page_phones,
            on_page_emails,
            cta_terms_text,
            booking_terms_text,
            evidence_snippet,
            pagespeed_status == "Measured",
            builtwith_status == "Measured",
        ]
    )
    broken_profile = _broken_site_fact_profile(failure_type, details, signals) if status == "Broken site" else {}

    if status == "No website":
        website_bucket = "No website"
    elif status == "Unknown web presence":
        website_bucket = "Unknown web presence"
    elif status == "Broken site":
        website_bucket = "Broken site"
    elif status == "Weak site":
        website_bucket = "Weak live site"
    elif status == "Basic site":
        website_bucket = "Basic live site"
    elif status == "Social only":
        website_bucket = "Social-only presence"
    elif status == "Directory only":
        website_bucket = "Directory-only presence"
    elif status == "Real website":
        website_bucket = "Established website"
    else:
        website_bucket = status or "Unclassified"

    if status in {"No website", "Social only", "Directory only"}:
        mobile_readiness = "No owned site to evaluate"
    elif status == "Unknown web presence":
        mobile_readiness = "Not verified"
    elif evidence_available:
        mobile_readiness = "Viewport meta found on inspected page" if viewport_meta == "Found" else "No viewport meta found on inspected page"
    elif "phones and smaller screens" in lowered and "may not be set up" in lowered:
        mobile_readiness = "Needs mobile work"
    elif "phones and smaller screens" in lowered:
        mobile_readiness = "Looks mobile-friendly"
    elif status == "Broken site":
        mobile_readiness = broken_profile["mobile"]
    else:
        mobile_readiness = "Not checked"

    if failure_type == "SSL or security failure":
        ssl_status = "SSL/security issue detected"
    elif status in {"No website", "Social only", "Directory only"}:
        ssl_status = "No owned site to evaluate"
    elif status == "Unknown web presence":
        ssl_status = "Not verified"
    elif website.startswith("https://") or resolved_url.startswith("https://"):
        ssl_status = "HTTPS in use"
    elif website.startswith("http://") or resolved_url.startswith("http://"):
        ssl_status = "No HTTPS visible"
    elif status == "Broken site":
        ssl_status = "Could not verify due to broken site"
    else:
        ssl_status = "Not checked"

    if pagespeed_status == "Measured" and pagespeed_signal:
        page_speed_signal = pagespeed_signal
    elif pagespeed_status == "Error":
        page_speed_signal = f"PageSpeed error: {pagespeed_error or 'not measured'}"
    elif status in {"No website", "Social only", "Directory only"}:
        page_speed_signal = "No owned site to measure"
    elif status == "Unknown web presence":
        page_speed_signal = "Not measured; web presence unknown"
    elif fetch_time_ms:
        page_speed_signal = f"Basic fetch took {fetch_time_ms} ms (not a full lab speed test)"
    elif http_status:
        page_speed_signal = f"HTTP {http_status} page was reached, but timing was not captured"
    elif status == "Broken site":
        page_speed_signal = broken_profile["page_speed"]
    else:
        page_speed_signal = "Not measured yet"

    if status in {"No website", "Social only", "Directory only"}:
        contact_form_status = "Missing"
    elif status == "Unknown web presence":
        contact_form_status = "Not verified"
    elif evidence_available:
        if form_count > 0:
            contact_form_status = f"{form_count} form(s) found on inspected page"
        elif on_page_phones or on_page_emails:
            contact_form_status = "0 forms found; phone or email is visible on the page"
        else:
            contact_form_status = "0 forms found and no phone or email was visible on the page"
    elif "clear way to contact" in lowered or "shows a phone number or email" in lowered:
        contact_form_status = "Contact path present"
    elif "does not clearly show a contact page" in lowered or "does not show a phone number or email" in lowered:
        contact_form_status = "Weak or missing"
    elif status == "Broken site":
        contact_form_status = broken_profile["contact_form"]
    else:
        contact_form_status = "Not enough evidence"

    if status in {"No website", "Social only", "Directory only"}:
        booking_flow_status = "Missing"
    elif status == "Unknown web presence":
        booking_flow_status = "Not verified"
    elif evidence_available:
        if booking_terms:
            booking_flow_status = f"Booking or quote terms found: {', '.join(booking_terms)}"
        elif form_count > 0:
            booking_flow_status = "Form found, but no booking or quote terms were detected"
        else:
            booking_flow_status = "No booking or quote terms found on inspected page"
    elif "clear next step like quote, booking, or service request" in lowered:
        booking_flow_status = "Present"
    elif "does not give visitors a clear next step" in lowered:
        booking_flow_status = "Missing or unclear"
    elif status == "Broken site":
        booking_flow_status = broken_profile["booking_flow"]
    else:
        booking_flow_status = "Not enough evidence"

    if status in {"No website", "Social only", "Directory only"}:
        cta_strength = "Missing"
    elif status == "Unknown web presence":
        cta_strength = "Not verified"
    elif evidence_available:
        if cta_terms:
            cta_strength = f"CTA terms found: {', '.join(cta_terms)}"
        else:
            cta_strength = "No clear CTA terms found on inspected page"
    elif "clear next step like quote, booking, or service request" in lowered:
        cta_strength = "Clear"
    elif "does not give visitors a clear next step" in lowered:
        cta_strength = "Weak"
    elif status == "Broken site":
        cta_strength = broken_profile["cta_strength"]
    else:
        cta_strength = "Not enough evidence"

    if status in {"No website", "Social only", "Directory only"}:
        seo_basics = "Missing"
    elif status == "Unknown web presence":
        seo_basics = "Not verified"
    elif evidence_available:
        title_signal = "title missing or generic" if title_is_generic else "title present"
        meta_signal = "meta description missing" if not meta_description else "meta description present"
        seo_basics = f"{title_signal}; {meta_signal}; {word_count} words on page"
    elif "very little written content" in lowered or "page title is generic or missing" in lowered:
        seo_basics = "Weak"
    elif "some written content but not much depth" in lowered:
        seo_basics = "Basic but thin"
    elif "enough written content" in lowered and "page title clearly describes the business" in lowered:
        seo_basics = "Solid basics"
    elif status == "Broken site":
        seo_basics = broken_profile["seo_basics"]
    else:
        seo_basics = "Not enough evidence"

    if status == "Social only":
        social_dependence = "High"
    elif social_profiles and status in {"No website", "Broken site", "Weak site"}:
        social_dependence = "Medium"
    elif social_profiles:
        social_dependence = "Low"
    else:
        social_dependence = "None found"

    if status == "Directory only":
        directory_dependence = "High"
    elif listed_on and status in {"No website", "Broken site", "Weak site"}:
        directory_dependence = "Medium"
    elif listed_on:
        directory_dependence = "Low"
    else:
        directory_dependence = "None found"

    if status in {"No website", "Social only", "Directory only"}:
        image_quality_signal = "No owned site to evaluate"
    elif status == "Unknown web presence":
        image_quality_signal = "Not verified"
    elif evidence_available:
        image_quality_signal = f"{image_count} image(s) found on inspected page"
    elif "few usable images" in lowered:
        image_quality_signal = "Weak visual proof"
    elif "visual proof like team, project, or service photos" in lowered:
        image_quality_signal = "Visual proof present"
    elif status == "Broken site":
        image_quality_signal = broken_profile["image_quality"]
    else:
        image_quality_signal = "Not enough evidence"

    if status in {"No website", "Social only", "Directory only"}:
        navigation_quality = "No owned site to evaluate"
    elif status == "Unknown web presence":
        navigation_quality = "Not verified"
    elif evidence_available:
        navigation_quality = f"{internal_link_count} internal link(s) found on inspected page"
    elif "only get" in lowered and "real links or pages" in lowered:
        navigation_quality = "Thin navigation"
    elif "visitors can move through the site" in lowered:
        navigation_quality = "Usable navigation"
    elif status == "Broken site":
        navigation_quality = broken_profile["navigation_quality"]
    else:
        navigation_quality = "Not enough evidence"

    issues: list[str] = []
    if status == "No website":
        issues.append("No standalone website found")
    elif status == "Unknown web presence":
        issues.append("Web presence could not be verified with enough evidence")
    elif status == "Social only":
        issues.append("Business relies on social platforms instead of an owned website")
    elif status == "Directory only":
        issues.append("Business relies on directory listings instead of an owned website")
    elif status == "Broken site":
        issues.append(broken_profile["issue"])
    elif status == "Weak site":
        issues.append("Website is live but still weak enough to hurt trust or conversion")

    if evidence_available and status not in {"No website", "Unknown web presence", "Social only", "Directory only"}:
        if http_status:
            issues.append(f"HTTP status observed: {http_status}")
        if form_count == 0:
            issues.append("0 forms found on inspected page")
        if not on_page_phones and not on_page_emails:
            issues.append("No phone or email found on inspected page")
        if not cta_terms:
            issues.append("No clear CTA terms found on inspected page")
        if not booking_terms and form_count == 0:
            issues.append("No booking or quote terms found on inspected page")
        if word_count < 100:
            issues.append(f"Only {word_count} words found on inspected page")
        elif word_count < 250:
            issues.append(f"Content is thin at {word_count} words")
        if image_count < 3:
            issues.append(f"Only {image_count} image(s) found on inspected page")
        if internal_link_count < 5:
            issues.append(f"Only {internal_link_count} internal link(s) found on inspected page")
        if title_is_generic:
            issues.append("Page title is missing or generic")
        if not meta_description:
            issues.append("Meta description is missing")
        if pagespeed_status == "Measured":
            if pagespeed_performance and pagespeed_performance < 50:
                issues.append(f"PageSpeed performance is poor at {pagespeed_performance}/100")
            elif pagespeed_performance and pagespeed_performance < 75:
                issues.append(f"PageSpeed performance needs improvement at {pagespeed_performance}/100")
            if pagespeed_accessibility and pagespeed_accessibility < 75:
                issues.append(f"Accessibility score is weak at {pagespeed_accessibility}/100")
            if pagespeed_seo and pagespeed_seo < 80:
                issues.append(f"SEO score is weak at {pagespeed_seo}/100")
            if pagespeed_best_practices and pagespeed_best_practices < 75:
                issues.append(f"Best practices score is weak at {pagespeed_best_practices}/100")
            if pagespeed_opportunities:
                issues.append(f"PageSpeed opportunities: {pagespeed_opportunities}")
        if builtwith_status == "Measured" and tech_stack_score >= 38:
            issues.append(f"BuiltWith tech stack signal is weak ({tech_stack_score}/100): {tech_stack_weak or tech_stack_signal}")
        elif builtwith_status == "Measured" and tech_stack_score >= 22:
            issues.append(f"BuiltWith found missing tech stack signals ({tech_stack_score}/100): {tech_stack_weak or tech_stack_signal}")
        elif builtwith_status == "Error":
            issues.append(f"BuiltWith tech stack check failed: {tech_stack_error or 'unknown error'}")
    else:
        if mobile_readiness == "Needs mobile work":
            issues.append("Mobile experience likely needs work")
        if contact_form_status in {"Weak or missing", "No real business contact path visible"}:
            issues.append("Contact path is weak or missing")
        if booking_flow_status in {"Missing or unclear", "No booking or quote flow visible"}:
            issues.append("Booking or quote flow is missing or unclear")
        if cta_strength in {"Weak", "No business CTA visible"}:
            issues.append("Calls to action are weak or missing")
        if seo_basics in {"Weak", "Basic but thin", "Placeholder content only", "Parked page, not business content", "Broken landing page"}:
            issues.append("Search and service content basics are weak")
        if image_quality_signal in {"Weak visual proof", "No business visual proof visible"}:
            issues.append("Visual proof is weak or missing")
        if navigation_quality in {"Thin navigation", "No usable business navigation visible"}:
            issues.append("Navigation is weak or missing")

    business_impacts: list[str] = []
    if status in {"No website", "Social only", "Directory only"}:
        business_impacts.append(
            "The business does not fully control how visitors learn about services, trust the brand, or take the next step."
        )
    elif status == "Unknown web presence":
        business_impacts.append("Discovery evidence is incomplete, so outreach should wait for a recheck or another source.")
    if status == "Broken site":
        business_impacts.append(broken_profile["impact"])
    if status == "Weak site":
        business_impacts.append("The current site is likely leaving calls, bookings, or quote requests on the table.")
    if evidence_available and status not in {"No website", "Unknown web presence", "Social only", "Directory only"}:
        if form_count == 0 and not on_page_phones and not on_page_emails:
            business_impacts.append("Visitors may not find a direct response path before they leave the page.")
        elif form_count == 0:
            business_impacts.append("Visitors can reach the business, but the page still lacks a clear form-based response path.")
        if not cta_terms and not booking_terms:
            business_impacts.append("Prospects may not see an obvious next step to call, book, or request a quote.")
        if word_count < 100:
            business_impacts.append("Thin on-page content may fail to explain services well enough to convert visitors.")
        if pagespeed_status == "Measured" and pagespeed_performance and pagespeed_performance < 75:
            business_impacts.append("Slow mobile performance can make visitors drop before they call, book, or request a quote.")
        if pagespeed_status == "Measured" and pagespeed_field_summary:
            business_impacts.append(f"Real-user speed data: {pagespeed_field_summary}")
        if builtwith_status == "Measured" and tech_stack_score >= 22:
            business_impacts.append(
                "Missing analytics, tracking, or conversion-stack signals can make the site harder to measure and optimize."
            )
    else:
        if cta_strength in {"Missing", "Weak", "No business CTA visible"} or booking_flow_status in {"Missing", "Missing or unclear", "No booking or quote flow visible"}:
            business_impacts.append("Prospects may not see a clear next step to call, book, or request a quote.")
        if contact_form_status in {"Missing", "Weak or missing", "No real business contact path visible"}:
            business_impacts.append("Interested visitors may have trouble reaching the business directly from the site.")
        if seo_basics in {"Missing", "Weak", "Basic but thin", "Placeholder content only", "Parked page, not business content", "Broken landing page"}:
            business_impacts.append("Search visibility and service clarity are likely weaker than they should be.")

    if evidence_summary and evidence_summary not in business_impacts:
        business_impacts.append(f"Website facts: {evidence_summary}")
    if tech_stack_summary and builtwith_status == "Measured":
        business_impacts.append(f"Tech stack: {tech_stack_summary}")

    if not business_impacts:
        business_impacts.append("The web presence still shows enough friction to justify a closer sales review.")

    pitch_family = derive_pitch_family(
        {
            "Website Bucket": website_bucket,
            "Website Failure Type": failure_type or website_bucket,
            "SSL Status": ssl_status,
            "HTTP Status": http_status,
            "Contact Form Status": contact_form_status,
            "Booking Flow Status": booking_flow_status,
            "CTA Strength": cta_strength,
            "SEO Basics": seo_basics,
            "Social Dependence": social_dependence,
            "Directory Dependence": directory_dependence,
            "Image Quality Signal": image_quality_signal,
            "Navigation Quality": navigation_quality,
        }
    )
    primary_business_impact = business_impacts[0]
    opportunity_thesis = build_opportunity_thesis(
        {
            "Pitch Family": pitch_family,
            "Primary Business Impact": primary_business_impact,
            "Website Evidence Summary": evidence_summary,
        }
    )

    if status == "Broken site":
        best_pitch_angle = broken_profile["pitch"]
    elif pitch_family == "no_website":
        best_pitch_angle = "No website; likely losing direct trust, search visibility, and owned lead capture."
    elif pitch_family == "unknown_web_presence":
        best_pitch_angle = "Unknown web presence; verify with another source before treating this as a no-website lead."
    elif pitch_family == "social_only_dependence":
        best_pitch_angle = "Social-only presence; visibility exists, but the business does not control conversion or lead capture."
    elif pitch_family == "directory_only_dependence":
        best_pitch_angle = "Directory-only presence; discovery depends on third-party platforms instead of an owned conversion path."
    elif pitch_family == "weak_conversion_path":
        best_pitch_angle = "Live site with a weak conversion path; interested visitors may not see a clear next step to call, book, or request a quote."
    elif pitch_family == "weak_trust_signals":
        best_pitch_angle = "Live site with weak trust signals; the business looks real, but the site may not build enough confidence to convert visitors."
    elif pitch_family == "security_issue":
        best_pitch_angle = "Security issue on the website; some visitors may fail to load the site at all, which cuts off trust and lead capture."
    elif pitch_family == "weak_live_site":
        best_pitch_angle = "Live but weak website; credibility exists, but conversion and trust signals look soft."
    else:
        best_pitch_angle = "Weak digital presence; worth reviewing as a website opportunity."

    return {
        "Audit Version": AUDIT_VERSION,
        "Website Bucket": website_bucket,
        "Website Failure Type": failure_type or website_bucket,
        "Mobile Readiness": mobile_readiness,
        "SSL Status": ssl_status,
        "Page Speed Signal": page_speed_signal,
        "PageSpeed Status": pagespeed_status,
        "PageSpeed Strategy": str(lead.get("PageSpeed Strategy", "")).strip(),
        "PageSpeed Final URL": str(lead.get("PageSpeed Final URL", "")).strip(),
        "PageSpeed Analysis Timestamp": str(lead.get("PageSpeed Analysis Timestamp", "")).strip(),
        "PageSpeed Lighthouse Version": str(lead.get("PageSpeed Lighthouse Version", "")).strip(),
        "PageSpeed Performance Score": pagespeed_performance,
        "PageSpeed Accessibility Score": pagespeed_accessibility,
        "PageSpeed Best Practices Score": pagespeed_best_practices,
        "PageSpeed SEO Score": pagespeed_seo,
        "PageSpeed FCP": str(lead.get("PageSpeed FCP", "")).strip(),
        "PageSpeed LCP": str(lead.get("PageSpeed LCP", "")).strip(),
        "PageSpeed Speed Index": str(lead.get("PageSpeed Speed Index", "")).strip(),
        "PageSpeed TBT": str(lead.get("PageSpeed TBT", "")).strip(),
        "PageSpeed CLS": str(lead.get("PageSpeed CLS", "")).strip(),
        "PageSpeed Interactive": str(lead.get("PageSpeed Interactive", "")).strip(),
        "PageSpeed CrUX Overall": str(lead.get("PageSpeed CrUX Overall", "")).strip(),
        "PageSpeed Origin CrUX Overall": str(lead.get("PageSpeed Origin CrUX Overall", "")).strip(),
        "PageSpeed CrUX FCP": str(lead.get("PageSpeed CrUX FCP", "")).strip(),
        "PageSpeed CrUX FCP Category": str(lead.get("PageSpeed CrUX FCP Category", "")).strip(),
        "PageSpeed CrUX LCP": str(lead.get("PageSpeed CrUX LCP", "")).strip(),
        "PageSpeed CrUX LCP Category": str(lead.get("PageSpeed CrUX LCP Category", "")).strip(),
        "PageSpeed CrUX INP": str(lead.get("PageSpeed CrUX INP", "")).strip(),
        "PageSpeed CrUX INP Category": str(lead.get("PageSpeed CrUX INP Category", "")).strip(),
        "PageSpeed CrUX CLS": str(lead.get("PageSpeed CrUX CLS", "")).strip(),
        "PageSpeed CrUX CLS Category": str(lead.get("PageSpeed CrUX CLS Category", "")).strip(),
        "PageSpeed CrUX TTFB": str(lead.get("PageSpeed CrUX TTFB", "")).strip(),
        "PageSpeed CrUX TTFB Category": str(lead.get("PageSpeed CrUX TTFB Category", "")).strip(),
        "PageSpeed Field Summary": pagespeed_field_summary,
        "PageSpeed Summary": pagespeed_summary,
        "PageSpeed Opportunities": pagespeed_opportunities,
        "PageSpeed Error": pagespeed_error,
        "BuiltWith Status": builtwith_status,
        "BuiltWith Domain": builtwith_domain,
        "BuiltWith Groups": builtwith_groups,
        "BuiltWith Category Summary": builtwith_categories,
        "Tech Stack Signal": tech_stack_signal,
        "Tech Stack Score": tech_stack_score,
        "Tech Stack Summary": tech_stack_summary,
        "Tech Stack Weak Signals": tech_stack_weak,
        "Tech Stack Strong Signals": tech_stack_strong,
        "Tech Stack Error": tech_stack_error,
        "Contact Form Status": contact_form_status,
        "Booking Flow Status": booking_flow_status,
        "CTA Strength": cta_strength,
        "SEO Basics": seo_basics,
        "Social Dependence": social_dependence,
        "Directory Dependence": directory_dependence,
        "Image Quality Signal": image_quality_signal,
        "Navigation Quality": navigation_quality,
        "Primary Business Impact": primary_business_impact,
        "Pitch Family": pitch_family,
        "Opportunity Thesis": opportunity_thesis,
        "Best Pitch Angle": best_pitch_angle,
        "Audit Confidence": compute_audit_confidence(
            confidence,
            status,
            evidence_available,
            page_title=page_title,
            meta_description=meta_description,
            word_count=word_count,
            form_count_checked=evidence_available,
            image_count_checked=evidence_available,
            internal_link_count_checked=evidence_available,
            viewport_meta=viewport_meta,
            on_page_phones=on_page_phones,
            on_page_emails=on_page_emails,
            cta_terms=cta_terms_text,
            http_status=http_status,
            inner_pages_checked=int(lead.get("Inner Pages Checked") or 0),
            discovery_source_count=len(str(lead.get("Discovery Sources", "")).split("; ")) if lead.get("Discovery Sources") else 0,
        ),
        "Audit Confidence Score": compute_audit_confidence_score(
            confidence,
            status,
            evidence_available,
            page_title=page_title,
            meta_description=meta_description,
            word_count=word_count,
            form_count_checked=evidence_available,
            image_count_checked=evidence_available,
            internal_link_count_checked=evidence_available,
            viewport_meta=viewport_meta,
            on_page_phones=on_page_phones,
            on_page_emails=on_page_emails,
            cta_terms=cta_terms_text,
            http_status=http_status,
            inner_pages_checked=int(lead.get("Inner Pages Checked") or 0),
            discovery_source_count=len(str(lead.get("Discovery Sources", "")).split("; ")) if lead.get("Discovery Sources") else 0,
        ),
        "Last Audited At": audited_at,
        "Last Verified At": audited_at,
        "Data Freshness": "Verified this run",
        "Resolved Website URL": resolved_url,
        "HTTP Status": http_status,
        "Fetch Time Ms": fetch_time_ms,
        "Page Title": page_title,
        "Meta Description": meta_description,
        "Word Count": word_count,
        "Form Count": form_count,
        "Internal Link Count": internal_link_count,
        "Image Count": image_count,
        "On-Page Phones": on_page_phones,
        "On-Page Emails": on_page_emails,
        "CTA Terms": cta_terms_text,
        "Booking Terms": booking_terms_text,
        "Viewport Meta": viewport_meta,
        "Website Evidence Summary": evidence_summary,
        "Website Evidence Snippet": evidence_snippet,
        "Google Analytics": _no_site_default(google_analytics, status),
        "Facebook Pixel": _no_site_default(facebook_pixel, status),
        "Schema Markup": _no_site_default(schema_markup, status),
        "Open Graph Tags": _no_site_default(open_graph_tags, status),
        "Canonical Tag": _no_site_default(canonical_tag, status),
        "Robots Meta": _no_site_default(robots_meta, status),
        "Booking Platforms": _no_site_default(booking_platforms, status) if not booking_platforms else booking_platforms,
        "Social Links": social_links or "None found",
        "Review Widget": _no_site_default(review_widget, status),
        "Chat Widget": _no_site_default(chat_widget, status),
        "Accessibility Indicators": _no_site_default(accessibility_indicators, status),
        "Images With Alt Text": images_with_alt_text,
        "Audit Issues": "; ".join(dict.fromkeys(item for item in issues if item)),
        "Business Impact Summary": "; ".join(dict.fromkeys(item for item in business_impacts if item)),
        "Audit Issues Json": list(dict.fromkeys(item for item in issues if item)),
        "Business Impact Json": list(dict.fromkeys(item for item in business_impacts if item)),
    }
