from __future__ import annotations

from datetime import datetime
from typing import Any


TRIGGER_VERSION = "1.2.1"

TRIGGER_TYPE_PRIORITY = {
    "thriving_no_website": 0,
    "domain_issue": 1,
    "high_trust_no_website": 2,
    "broken_links_on_site": 3,
    "outdated_website": 4,
    "recent_review_growth": 5,
    "new_contact_channel": 6,
    "newly_registered_business": 7,
    "third_party_dependence": 8,
    "trade_name_mismatch": 9,
}

TRIGGER_OPERATIONAL_CLASSES = {
    "thriving_no_website": "thriving business without website",
    "domain_issue": "urgent website issue",
    "high_trust_no_website": "demand without owned website",
    "broken_links_on_site": "website has broken links",
    "outdated_website": "website looks outdated",
    "recent_review_growth": "fresh demand signal",
    "new_contact_channel": "new outreach path",
    "newly_registered_business": "early-stage timing window",
    "third_party_dependence": "third-party dependence",
    "trade_name_mismatch": "identity mismatch",
}


def _safe_int(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _text(value: Any) -> str:
    return str(value or "").strip()


def _type_rank(value: Any) -> int:
    cleaned = _text(value)
    return TRIGGER_TYPE_PRIORITY.get(cleaned, 99)


def _ordered_trigger_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        events,
        key=lambda item: (
            _strength_rank(item.get("strength")),
            _type_rank(item.get("type")),
            _text(item.get("label")).lower(),
        ),
    )


def _trigger_operational_class(trigger_type: Any, label: Any = "") -> str:
    cleaned_type = _text(trigger_type)
    if cleaned_type:
        mapped = TRIGGER_OPERATIONAL_CLASSES.get(cleaned_type)
        if mapped:
            return mapped
    cleaned_label = _text(label).lower()
    if "review" in cleaned_label:
        return "fresh demand signal"
    if "contact" in cleaned_label:
        return "new outreach path"
    if "website" in cleaned_label or "domain" in cleaned_label:
        return "urgent website issue"
    return ""


def _parse_fallback_trigger_labels(value: Any) -> list[str]:
    raw = _text(value)
    if not raw:
        return []
    parts = [item.strip() for item in raw.replace("|", ";").split(";")]
    return [part for part in parts if part]


def _fallback_trigger_count(value: Any, fallback_types: Any) -> int:
    explicit = _safe_int(value)
    if explicit > 0:
        return explicit
    return len(_parse_fallback_trigger_labels(fallback_types))


def _extract_strength_from_summary(summary: Any) -> str:
    cleaned = _text(summary)
    if "(High)" in cleaned:
        return "High"
    if "(Medium)" in cleaned:
        return "Medium"
    if "(Low)" in cleaned:
        return "Low"
    return ""


def build_trigger_intelligence(
    events: list[dict[str, Any]],
    *,
    fallback_summary: Any = "",
    fallback_types: Any = "",
    fallback_count: Any = 0,
) -> dict[str, Any]:
    ordered = _ordered_trigger_events(events)
    top_event = ordered[0] if ordered else {}
    top_label = _text(top_event.get("label")) if top_event else ""
    top_strength = _text(top_event.get("strength")) if top_event else ""
    top_type = _text(top_event.get("type")) if top_event else ""
    trigger_summary = summarize_trigger_events(ordered) if ordered else _text(fallback_summary)
    trigger_types = summarize_trigger_types(ordered) if ordered else _text(fallback_types)
    trigger_count = len(ordered) if ordered else _fallback_trigger_count(fallback_count, trigger_types)

    if not top_label:
        fallback_labels = _parse_fallback_trigger_labels(trigger_types)
        if fallback_labels:
            top_label = fallback_labels[0]
    if not top_strength:
        top_strength = _extract_strength_from_summary(trigger_summary)

    top_summary = _text(top_event.get("summary")) if top_event else _text(trigger_summary)
    why_now_summary = _text(top_event.get("why_now")) if top_event else ""
    operational_class = _trigger_operational_class(top_type, top_label)

    return {
        "trigger_count": trigger_count,
        "trigger_summary": trigger_summary,
        "trigger_types": trigger_types,
        "top_trigger_type": top_type,
        "top_trigger_label": top_label,
        "top_trigger_strength": top_strength,
        "top_trigger_summary": top_summary,
        "why_now_summary": why_now_summary,
        "trigger_priority": top_strength,
        "trigger_operational_class": operational_class,
    }


def _add_event(
    events: list[dict[str, Any]],
    *,
    trigger_type: str,
    label: str,
    strength: str,
    summary: str,
    why_now: str,
    evidence: list[str],
    observed_at: str,
) -> None:
    cleaned_evidence = [item.strip() for item in evidence if str(item).strip()]
    events.append(
        {
            "type": trigger_type,
            "label": label,
            "strength": strength,
            "summary": summary.strip(),
            "why_now": why_now.strip(),
            "evidence": cleaned_evidence,
            "observed_at": observed_at,
            "version": TRIGGER_VERSION,
        }
    )


def detect_trigger_events(
    lead: dict[str, Any],
    previous_lead: dict[str, Any] | None = None,
    *,
    observed_at: str | None = None,
) -> list[dict[str, Any]]:
    observed_at = observed_at or datetime.now().isoformat(timespec="seconds")
    previous = previous_lead or {}
    events: list[dict[str, Any]] = []

    web_presence = _text(lead.get("Web Presence Status", lead.get("Website Status", "")))
    failure_type = _text(lead.get("Website Failure Type"))
    business_reality = _text(lead.get("Business Reality"))
    reviews = _safe_int(lead.get("Reviews"))
    previous_reviews = _safe_int(previous.get("Reviews"))
    review_delta = max(0, reviews - previous_reviews)
    business_age_days = _safe_int(lead.get("Business Age Days"))
    previous_phone = _text(previous.get("Phone"))
    previous_email = _text(previous.get("Email"))
    phone = _text(lead.get("Phone"))
    email = _text(lead.get("Email"))
    social_profiles = _text(lead.get("Social Profiles"))
    listed_on = _text(lead.get("Listed On"))
    match_type = _text(lead.get("Colorado Match Type")).lower()

    if previous_reviews and review_delta >= 5:
        growth_percent = int(round((review_delta / max(previous_reviews, 1)) * 100))
        strength = "High" if review_delta >= 12 or growth_percent >= 40 else "Medium"
        _add_event(
            events,
            trigger_type="recent_review_growth",
            label="Recent review growth",
            strength=strength,
            summary=f"Google reviews increased by {review_delta} since the last verification.",
            why_now="Fresh customer activity makes weak web presence more costly because more people are actively checking the business right now.",
            evidence=[
                f"Current reviews: {reviews}",
                f"Previous reviews: {previous_reviews}",
                f"Growth since last snapshot: {review_delta} ({growth_percent}%)",
            ],
            observed_at=observed_at,
        )

    if business_age_days and business_age_days <= 365:
        strength = "High" if business_age_days <= 120 else "Medium"
        _add_event(
            events,
            trigger_type="newly_registered_business",
            label="Newly registered business",
            strength=strength,
            summary=f"The business appears to be only about {business_age_days} days old.",
            why_now="Newer businesses often need their first real website quickly so they can look established and capture early demand.",
            evidence=[
                f"Business age: {business_age_days} days",
                f"Business reality: {business_reality or 'Not yet classified'}",
            ],
            observed_at=observed_at,
        )

    if web_presence == "Broken site":
        broken_types = {
            "Dead domain or missing page": "The site appears dead or missing, so visitors may click through and hit a wall.",
            "Parked or for-sale domain": "The domain appears parked or for sale instead of showing a real business website.",
            "Placeholder or under-construction site": "The site looks unfinished, which can make an active business feel less credible.",
            "SSL or security failure": "Security or certificate warnings can stop people before they ever contact the business.",
        }
        summary = broken_types.get(
            failure_type,
            "A live website issue is visible right now and is likely hurting trust or conversion."
        )
        _add_event(
            events,
            trigger_type="domain_issue",
            label="Live website issue",
            strength="High",
            summary=summary,
            why_now="This is a visible problem today, not just a theoretical improvement opportunity.",
            evidence=[
                f"Web presence: {web_presence}",
                f"Failure type: {failure_type or 'Unspecified issue'}",
                f"Business reality: {business_reality or 'Unknown'}",
            ],
            observed_at=observed_at,
        )

    # ── Thriving business without any website ──
    thriving_tier = _text(lead.get("Thriving Tier"))
    thriving_score = _safe_int(lead.get("Thriving Score"))
    if web_presence == "No website" and thriving_tier in {"Thriving", "Established"} and reviews >= 15:
        _add_event(
            events,
            trigger_type="thriving_no_website",
            label="Thriving business with no website",
            strength="High",
            summary=f"This business is {thriving_tier.lower()} (score {thriving_score}/100) with {reviews} reviews but has zero web presence.",
            why_now="A thriving business without a website is leaving money on the table every day — competitors with websites are capturing their search traffic.",
            evidence=[
                f"Thriving tier: {thriving_tier} ({thriving_score}/100)",
                f"Google reviews: {reviews}",
                f"Rating: {lead.get('Rating', 'N/A')}",
                f"Web presence: {web_presence}",
            ],
            observed_at=observed_at,
        )

    # ── Broken internal links on live site ──
    broken_link_count = _safe_int(lead.get("Broken Link Count"))
    broken_links_checked = _safe_int(lead.get("Broken Links Checked"))
    if broken_link_count >= 2 and web_presence in {"Weak site", "Basic site"}:
        ratio = broken_link_count / max(broken_links_checked, 1)
        strength = "High" if ratio >= 0.4 or broken_link_count >= 5 else "Medium"
        _add_event(
            events,
            trigger_type="broken_links_on_site",
            label="Website has broken internal links",
            strength=strength,
            summary=f"{broken_link_count} out of {broken_links_checked} checked internal links are broken or returning errors.",
            why_now="Broken links actively hurt SEO rankings and frustrate visitors trying to navigate the site.",
            evidence=[
                f"Broken links: {broken_link_count}/{broken_links_checked}",
                f"Broken link ratio: {ratio:.0%}",
                f"Details: {_text(lead.get('Broken Links', ''))[:200]}",
            ],
            observed_at=observed_at,
        )

    # ── Outdated website design ──
    outdated_markers = _text(lead.get("Outdated Design Markers"))
    if outdated_markers and web_presence in {"Weak site", "Basic site"}:
        _add_event(
            events,
            trigger_type="outdated_website",
            label="Website looks outdated",
            strength="Medium",
            summary=f"The website shows outdated design elements: {outdated_markers}.",
            why_now="An outdated-looking website signals to potential customers that the business may not be active or professional.",
            evidence=[
                f"Outdated markers: {outdated_markers}",
                f"Web presence: {web_presence}",
            ],
            observed_at=observed_at,
        )

    if web_presence in {"No website", "Social only", "Directory only"}:
        dependence_bits: list[str] = []
        if social_profiles:
            dependence_bits.append("social profiles are active")
        if listed_on:
            dependence_bits.append("directory/listing presence exists")
        evidence = [
            f"Web presence: {web_presence}",
            f"Social profiles: {social_profiles or 'None found'}",
            f"Listed on: {listed_on or 'None found'}",
        ]
        if web_presence == "No website" and reviews >= 20:
            _add_event(
                events,
                trigger_type="high_trust_no_website",
                label="High-trust business with no website",
                strength="High",
                summary=f"The business has no owned website but already has {reviews} Google reviews.",
                why_now="Strong demand signals without an owned site usually mean trust and conversion are leaking to third-party platforms.",
                evidence=evidence + [f"Google reviews: {reviews}"],
                observed_at=observed_at,
            )
        elif social_profiles or listed_on:
            _add_event(
                events,
                trigger_type="third_party_dependence",
                label="Third-party dependence",
                strength="Medium",
                summary=f"The business is relying on {' and '.join(dependence_bits) or 'third-party platforms'} instead of a strong owned website.",
                why_now="That usually limits how much control the business has over trust, messaging, and lead capture.",
                evidence=evidence,
                observed_at=observed_at,
            )

    if ("trade-name mismatch" in match_type or "dba" in match_type) and business_reality:
        _add_event(
            events,
            trigger_type="trade_name_mismatch",
            label="Possible rebrand or trade-name mismatch",
            strength="Medium",
            summary="The public business name and the Colorado record do not line up cleanly.",
            why_now="That can signal a DBA, rebrand, or operating-name mismatch worth acknowledging during research or outreach.",
            evidence=[
                f"Colorado match type: {_text(lead.get('Colorado Match Type')) or 'Unknown'}",
                f"Business reality: {business_reality}",
            ],
            observed_at=observed_at,
        )

    if (phone and not previous_phone) or (email and not previous_email):
        new_channels: list[str] = []
        if phone and not previous_phone:
            new_channels.append("phone")
        if email and not previous_email:
            new_channels.append("email")
        _add_event(
            events,
            trigger_type="new_contact_channel",
            label="New contact channel found",
            strength="Medium",
            summary=f"A new public {' and '.join(new_channels)} channel was found compared with the previous snapshot.",
            why_now="Fresh contact coverage can make the lead more usable for outreach than it was before.",
            evidence=[
                f"Current phone: {phone or 'None'}",
                f"Current email: {email or 'None'}",
                f"Previous phone: {previous_phone or 'None'}",
                f"Previous email: {previous_email or 'None'}",
            ],
            observed_at=observed_at,
        )

    return events


def summarize_trigger_events(events: list[dict[str, Any]], *, max_items: int = 3) -> str:
    if not events:
        return ""
    ordered = _ordered_trigger_events(events)
    snippets: list[str] = []
    for event in ordered[:max_items]:
        label = _text(event.get("label"))
        strength = _text(event.get("strength"))
        summary = _text(event.get("summary"))
        if label and summary:
            suffix = f" ({strength})" if strength else ""
            snippets.append(f"{label}{suffix}: {summary}")
    return " | ".join(snippets)


def summarize_trigger_types(events: list[dict[str, Any]], *, max_items: int = 5) -> str:
    labels = [_text(event.get("label")) for event in _ordered_trigger_events(events)]
    unique_labels = list(dict.fromkeys(label for label in labels if label))
    return "; ".join(unique_labels[:max_items])


def format_trigger_events(events: list[dict[str, Any]]) -> str:
    if not events:
        return ""
    ordered = _ordered_trigger_events(events)
    lines: list[str] = []
    for event in ordered:
        label = _text(event.get("label")) or "Trigger"
        strength = _text(event.get("strength"))
        summary = _text(event.get("summary"))
        why_now = _text(event.get("why_now"))
        evidence = [str(item).strip() for item in event.get("evidence", []) if str(item).strip()]
        heading = f"- {label}"
        if strength:
            heading += f" ({strength})"
        if summary:
            heading += f": {summary}"
        lines.append(heading)
        if why_now:
            lines.append(f"  Why now: {why_now}")
        if evidence:
            lines.append(f"  Evidence: {'; '.join(evidence)}")
    return "\n".join(lines)


def _strength_rank(value: Any) -> int:
    cleaned = _text(value).lower()
    return {"high": 0, "medium": 1, "low": 2}.get(cleaned, 3)
