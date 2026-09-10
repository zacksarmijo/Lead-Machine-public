from __future__ import annotations

"""Lead scoring and outreach-priority helpers for the Colorado lead machine."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lead_machine import LeadMachine


def format_age_summary(age_days: object) -> str:
    if not isinstance(age_days, int) or age_days <= 0:
        return ""
    years = age_days / 365
    if years >= 1:
        return f"Operating about {years:.1f} years"
    return f"Operating about {age_days} days"


def primary_business_label(lead: dict) -> str:
    raw = str(lead.get("Business Type", "")).split(",")[0].strip().lower()
    if not raw:
        return "business"
    label = raw.replace("_", " ").replace("-", " ").strip()
    if label in {"point of interest", "establishment", "store"}:
        return "business"
    return label


def join_readable_list(items: list[str]) -> str:
    cleaned = [item.strip() for item in items if item and item.strip()]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    if len(cleaned) == 2:
        return f"{cleaned[0]} and {cleaned[1]}"
    return f"{', '.join(cleaned[:-1])}, and {cleaned[-1]}"


def official_record_value(lead: dict, official_key: str, legacy_key: str = "") -> str:
    value = str(lead.get(official_key, "") or "").strip()
    if value or not legacy_key:
        return value
    return str(lead.get(legacy_key, "") or "").strip()


def official_record_state_label(lead: dict) -> str:
    state_code = official_record_value(lead, "Official Record State").upper()
    if state_code == "CO":
        return "Colorado"
    if state_code == "CA":
        return "California"
    city_area = str(lead.get("City/Area", "") or "").strip()
    if city_area.endswith(", CO") or city_area.endswith(", Colorado"):
        return "Colorado"
    if city_area.endswith(", CA") or city_area.endswith(", California"):
        return "California"
    return ""


def official_record_label(lead: dict) -> str:
    state_label = official_record_state_label(lead)
    return f"{state_label} record" if state_label else "official record"


def evaluate_business_reality(machine: "LeadMachine", lead: dict, *, cross_reference: str = "") -> tuple[str, str, str]:
    record_status = official_record_value(lead, "Official Status Category", "Colorado Status Category")
    match_type = official_record_value(lead, "Official Match Type", "Colorado Match Type")
    match_confidence = official_record_value(lead, "Official Match Confidence", "Colorado Match Confidence")
    record_label = official_record_label(lead)
    phone = bool(str(lead.get("Phone", "")).strip())
    email = bool(str(lead.get("Email", "")).strip())
    reviews = int(lead.get("Reviews") or 0)
    google_place_id = bool(str(lead.get("Google Place ID", "")).strip())
    license_status = str(lead.get("License Status", "")).strip()
    yelp_status = str(lead.get("Yelp Match Status", "")).strip()
    try:
        identity_confidence = int(lead.get("Business Identity Confidence") or lead.get("Yelp Match Confidence") or 0)
    except (TypeError, ValueError):
        identity_confidence = 0

    evidence: list[str] = []
    strong_signals = 0

    if record_status == "Active":
        strong_signals += 2
        evidence.append(f"active {record_label}")
    elif record_status == "Compliance issue":
        evidence.append(f"{record_label} has compliance issues")
    elif match_type == "Possible DBA or trade-name mismatch":
        evidence.append(f"{record_label} may be under a different legal or trade name")
    elif match_type:
        evidence.append(match_type.lower())

    if match_confidence == "High":
        strong_signals += 1

    if phone or email:
        strong_signals += 1
        evidence.append("public contact info is available")
    if reviews >= 10 or google_place_id:
        strong_signals += 1
        evidence.append("maps/listing presence is established")
    if cross_reference in {"Strong", "Good"}:
        strong_signals += 1
        evidence.append(f"contact cross-reference is {cross_reference.lower()}")
    elif cross_reference == "Needs review":
        evidence.append("contact cross-reference needs review")
    if yelp_status == "Matched" and identity_confidence >= 65:
        strong_signals += 1
        evidence.append(f"Yelp match supports business identity ({identity_confidence}/100)")
    elif yelp_status == "Mismatch":
        evidence.append("Yelp returned a weak or mismatched candidate")

    if license_status == "License verified":
        strong_signals += 1
        evidence.append("official license match found")
    elif license_status in {"Likely licensed - review", "Manual review recommended"}:
        evidence.append(f"license check: {license_status.lower()}")

    if record_status == "Active" and strong_signals >= 4:
        return "Real active business", "High", "; ".join(evidence[:4])
    if record_status in {"Active", "Compliance issue"} or strong_signals >= 2 or match_type == "Possible DBA or trade-name mismatch":
        return "Likely active - needs review", "Medium", "; ".join(evidence[:4])
    return "Uncertain / weak match", "Low", "; ".join(evidence[:4]) or "Public signals are limited and the business match is weak"


def why_it_matters(lead: dict) -> str:
    web_presence = str(lead.get("Web Presence Status", "")).strip()
    failure_type = str(lead.get("Website Failure Type", "")).strip()
    tech_stack_score = _int_value(lead.get("Tech Stack Score"))
    if web_presence == "No website":
        return "Without an owned site, the business has less control over trust, search visibility, and lead capture"
    if web_presence == "Unknown web presence":
        return "The current discovery run could not verify whether the business has an owned website, so it needs recheck before outreach"
    if web_presence == "Directory only":
        return "Relying on directory pages means the business does not control the message, conversion flow, or search landing page"
    if web_presence == "Social only":
        return "Social pages are a weak replacement for a site that explains services, ranks in search, and captures inquiries"
    if failure_type == "Live but weak website":
        return "A weak live site can turn interested visitors into drop-offs because it does not build trust or drive action well"
    if failure_type:
        return f"A {failure_type.lower()} can make visitors lose trust or leave before they ever call or book"
    if tech_stack_score >= 22:
        return "Missing analytics, tracking, or conversion-stack signals can make the site harder to improve and harder to measure"
    return "The current web presence looks limited enough to hurt trust or lead conversion"


def why_business_is_worth_contacting(
    machine: "LeadMachine",
    lead: dict,
    business_reality: str,
    reality_details: str,
) -> str:
    reasons: list[str] = []
    rating = lead.get("Rating") or 0
    reviews = int(lead.get("Reviews") or 0)
    age_summary = machine.format_age_summary(lead.get("Business Age Days"))
    phone = bool(str(lead.get("Phone", "")).strip())
    email = bool(str(lead.get("Email", "")).strip())
    license_status = str(lead.get("License Status", "")).strip()
    match_type = official_record_value(lead, "Official Match Type", "Colorado Match Type")
    record_label = official_record_label(lead)

    if reviews and rating:
        reasons.append(f"{reviews} Google reviews at {float(rating):.1f} stars")
    elif reviews:
        reasons.append(f"{reviews} Google reviews")
    if age_summary:
        reasons.append(age_summary.lower())
    if business_reality == "Real active business":
        reasons.append(f"{record_label} supports that the business is active")
    elif reality_details:
        reasons.append(reality_details)
    if license_status == "License verified":
        reasons.append("official licensing is confirmed")
    elif match_type == "Possible DBA or trade-name mismatch":
        reasons.append("the public business name may differ from the legal entity name")
    if phone and email:
        reasons.append("both phone and email are available")
    elif phone or email:
        reasons.append("public contact information is available")

    if reasons:
        return f"The business still looks worth contacting because {machine.join_readable_list(reasons[:3])}"
    return "The business still looks worth contacting because the public signals are strong enough to justify review"


def build_why_kept_summary(
    machine: "LeadMachine",
    lead: dict,
    *,
    business_reality: str,
    reality_details: str,
) -> str:
    what_is_wrong = str(lead.get("Opportunity Brief", "")).strip()
    if not what_is_wrong:
        what_is_wrong = f"{lead.get('Business Name', 'This business')} still shows a meaningful web-presence gap"
    return "\n".join(
        [
            f"- What is wrong: {what_is_wrong}",
            f"- Why it matters: {machine.why_it_matters(lead)}",
            f"- Why it is worth contacting: {machine.why_business_is_worth_contacting(lead, business_reality, reality_details)}",
        ]
    )


def build_opportunity_brief(
    machine: "LeadMachine",
    lead: dict,
    *,
    cross_reference: str = "",
) -> str:
    business_name = str(lead.get("Business Name", "")).strip() or "This business"
    city_area = str(lead.get("City/Area", "")).strip()
    web_presence = str(lead.get("Web Presence Status", "")).strip()
    web_details = str(lead.get("Web Presence Details", "")).strip()
    rating = lead.get("Rating") or 0
    reviews = int(lead.get("Reviews") or 0)
    age_summary = machine.format_age_summary(lead.get("Business Age Days"))
    business_label = machine.primary_business_label(lead)
    phone = str(lead.get("Phone", "")).strip()
    email = str(lead.get("Email", "")).strip()
    listed_on = str(lead.get("Listed On", "")).strip()
    linkedin_url = str(lead.get("LinkedIn Profile", "")).strip()
    social_profiles = [item.strip() for item in str(lead.get("Social Profiles", "")).split(",") if item.strip()]
    record_status_category = official_record_value(lead, "Official Status Category", "Colorado Status Category")
    record_match_type = official_record_value(lead, "Official Match Type", "Colorado Match Type")
    record_label = official_record_label(lead)

    presence_channels: list[str] = []
    if listed_on:
        presence_channels.append(listed_on)
    if social_profiles:
        presence_channels.append("social profiles")
    if linkedin_url:
        presence_channels.append("LinkedIn")
    channel_summary = machine.join_readable_list(presence_channels)

    market_signals: list[str] = []
    if reviews and rating:
        market_signals.append(f"{reviews} Google reviews at {float(rating):.1f} stars")
    elif reviews:
        market_signals.append(f"{reviews} Google reviews")
    if age_summary:
        market_signals.append(age_summary.lower())
    if record_status_category == "Active":
        market_signals.append(f"an active {record_label}")
    elif record_match_type == "Possible DBA or trade-name mismatch":
        market_signals.append(f"{record_label} that may sit under a different legal or trade name")

    if phone and email:
        contact_summary = "Customers can already call or email the business"
    elif phone:
        contact_summary = "Customers can call the business"
    elif email:
        contact_summary = "Customers can email the business"
    else:
        contact_summary = "Public contact options are limited"

    if web_presence == "No website":
        brief_parts = [
            f"{business_name} does not appear to have a standalone website" + (f" in {city_area}" if city_area else "") + ".",
        ]
        if channel_summary:
            brief_parts.append(f"Public presence appears to rely on {channel_summary} instead of an owned site.")
        else:
            brief_parts.append("Public presence appears to rely on maps listings or word of mouth instead of an owned site.")
        if market_signals:
            brief_parts.append(f"The business already shows demand with {machine.join_readable_list(market_signals)}.")
        brief_parts.append(
            f"{contact_summary}, but there is no owned page to explain services, show proof, answer questions, or capture inquiries online."
        )
        if business_label != "business":
            brief_parts.append(
                f"For a {business_label} business, that usually means less control over search visibility, trust, and lead capture."
            )
        return " ".join(brief_parts)

    if web_presence == "Unknown web presence":
        return (
            f"{business_name} could not be verified as a true no-website business in this run. "
            f"{web_details or 'Public discovery did not produce enough independent evidence.'} "
            "This should be retried or checked with another source before it is treated as an outreach-ready no-website lead."
        )

    if web_presence == "Directory only":
        return (
            f"{business_name} appears to rely on third-party listings instead of an owned website. "
            + (f"The current public presence is mostly {channel_summary}. " if channel_summary else "")
            + f"{contact_summary}, but the business still lacks a dedicated place to control messaging, trust, and conversions."
        ).strip()

    if web_presence == "Social only":
        return (
            f"{business_name} appears to rely on social platforms instead of a real website. "
            f"{contact_summary}, but social pages are a weak replacement for a site that explains services, captures leads, and ranks for local searches."
        )

    if web_presence == "Broken site":
        return (
            f"{business_name} has a website link, but it is not giving visitors a usable business site. "
            f"{web_details or 'The current site experience looks broken or incomplete.'} "
            "That means people who do try to visit may lose trust or drop off before contacting the business."
        )

    if web_presence == "Weak site":
        tech_summary = str(lead.get("Tech Stack Summary", "")).strip()
        return (
            f"{business_name} has a live website, but it still looks weak enough to hurt trust or conversion. "
            f"{web_details or 'The site loads, but it appears to have meaningful quality gaps.'} "
            + (f"Technology stack signal: {tech_summary}. " if tech_summary else "")
            + "This is still a web-improvement lead, but it is a weaker fit than a true no-website business."
        )

    return (
        f"{business_name} survived filtering and still looks worth reviewing. "
        f"{web_details or 'Public web presence is limited enough to justify a closer look.'}"
    )


def compute_thriving_signals(lead: dict) -> dict:
    """Compute signals that indicate a business is thriving (high demand, active, established)."""
    rating = float(lead.get("Rating") or 0)
    reviews = int(lead.get("Reviews") or 0)
    age_days = lead.get("Business Age Days")
    record_status = official_record_value(lead, "Official Record Status", "Colorado Record Status").lower()
    record_category = official_record_value(lead, "Official Status Category", "Colorado Status Category")
    record_label = official_record_label(lead)
    license_status = str(lead.get("License Status", "")).strip()
    phone = bool(lead.get("Phone"))
    email = bool(lead.get("Email"))

    thriving_score = 0
    thriving_signals: list[str] = []

    if reviews >= 100:
        thriving_score += 30
        thriving_signals.append(f"High demand: {reviews} reviews")
    elif reviews >= 50:
        thriving_score += 22
        thriving_signals.append(f"Strong demand: {reviews} reviews")
    elif reviews >= 25:
        thriving_score += 15
        thriving_signals.append(f"Solid demand: {reviews} reviews")
    elif reviews >= 10:
        thriving_score += 8
        thriving_signals.append(f"Some demand: {reviews} reviews")

    if rating >= 4.8 and reviews >= 15:
        thriving_score += 20
        thriving_signals.append(f"Exceptional reputation: {rating:.1f} stars")
    elif rating >= 4.5 and reviews >= 10:
        thriving_score += 14
        thriving_signals.append(f"Strong reputation: {rating:.1f} stars")
    elif rating >= 4.0:
        thriving_score += 7
        thriving_signals.append(f"Decent reputation: {rating:.1f} stars")

    if isinstance(age_days, int) and age_days > 0 and reviews > 0:
        reviews_per_year = (reviews / age_days) * 365
        if reviews_per_year >= 30:
            thriving_score += 15
            thriving_signals.append(f"~{int(reviews_per_year)} reviews/year (fast growth)")
        elif reviews_per_year >= 15:
            thriving_score += 10
            thriving_signals.append(f"~{int(reviews_per_year)} reviews/year (steady growth)")
        elif reviews_per_year >= 6:
            thriving_score += 5
            thriving_signals.append(f"~{int(reviews_per_year)} reviews/year")
        lead["Review Velocity"] = f"~{int(reviews_per_year)}/year"
    else:
        lead["Review Velocity"] = ""

    if isinstance(age_days, int):
        if age_days >= 365 * 5:
            thriving_score += 10
            thriving_signals.append("5+ years in business")
        elif age_days >= 365 * 2:
            thriving_score += 6
            thriving_signals.append("2+ years in business")

    if record_category == "Active" or "good standing" in record_status:
        thriving_score += 5
        thriving_signals.append(f"Active {record_label}")
    if license_status == "License verified":
        thriving_score += 5
        thriving_signals.append("Licensed professional")

    if phone and email:
        thriving_score += 3

    thriving_score = min(thriving_score, 100)

    if thriving_score >= 65:
        thriving_tier = "Thriving"
    elif thriving_score >= 40:
        thriving_tier = "Established"
    elif thriving_score >= 20:
        thriving_tier = "Growing"
    else:
        thriving_tier = "Early-stage"

    return {
        "thriving_score": thriving_score,
        "thriving_tier": thriving_tier,
        "thriving_signals": thriving_signals,
    }


def compute_revenue_tier(lead: dict) -> dict:
    """Estimate revenue tier from public signals. Not exact - directional only."""
    reviews = int(lead.get("Reviews") or 0)
    license_status = str(lead.get("License Status", "")).strip()

    if reviews >= 200:
        estimated_tier = "High revenue"
        revenue_note = f"{reviews} reviews suggest high customer volume"
    elif reviews >= 75:
        estimated_tier = "Medium-high revenue"
        revenue_note = f"{reviews} reviews suggest solid customer volume"
    elif reviews >= 30:
        estimated_tier = "Medium revenue"
        revenue_note = f"{reviews} reviews suggest moderate customer volume"
    elif reviews >= 10:
        estimated_tier = "Low-medium revenue"
        revenue_note = f"{reviews} reviews suggest some regular customer flow"
    else:
        estimated_tier = "Low/unknown revenue"
        revenue_note = "Insufficient review data to estimate volume"

    if license_status == "License verified" and reviews >= 20:
        if estimated_tier.startswith("Low"):
            estimated_tier = "Medium revenue"
            revenue_note += "; licensed professional (higher per-job value)"

    return {
        "revenue_tier": estimated_tier,
        "revenue_note": revenue_note,
    }


def compute_premium_fit_confidence(machine: "LeadMachine", lead: dict) -> dict:
    """Estimate client fit from public signals without claiming an actual budget."""
    reviews = int(lead.get("Reviews") or 0)
    rating = float(lead.get("Rating") or 0)
    license_status = str(lead.get("License Status", "")).strip()
    thriving_tier = str(lead.get("Thriving Tier", "")).strip()
    revenue_tier = str(lead.get("Revenue Tier", "")).strip()
    record_status_category = official_record_value(lead, "Official Status Category", "Colorado Status Category")
    opportunity_score = int(lead.get("Opportunity Score") or 0)
    web_presence = str(lead.get("Web Presence Status", "")).strip()
    has_contact = bool(lead.get("Phone") or lead.get("Email"))
    lead_category_text = machine.normalize_filter_text(
        " ".join(
            str(lead.get(key, "") or "")
            for key in (
                "Business Name",
                "Business Type",
                "Lead Rationale",
                "Opportunity Brief",
                "Thriving Signals",
                "Revenue Note",
                "License Target",
            )
        )
    )
    high_value_terms = {
        "custom home",
        "home builder",
        "luxury home",
        "design build",
        "general contractor",
        "real estate developer",
        "property developer",
        "construction",
        "architect",
        "interior designer",
        "remodel",
        "roofing",
    }

    score = 0
    reasons: list[str] = []

    if any(machine.normalize_filter_text(term) in lead_category_text for term in high_value_terms):
        score += 28
        reasons.append("high-value home/building category")
    if revenue_tier in {"High revenue", "Medium-high revenue"}:
        score += 18
        reasons.append(revenue_tier.lower())
    elif revenue_tier == "Medium revenue":
        score += 10
        reasons.append("medium public-volume signal")
    if license_status == "License verified":
        score += 16
        reasons.append("official license verified")
    elif license_status == "Likely licensed - review":
        score += 7
        reasons.append("possible official license match")
    if record_status_category == "Active":
        score += 8
        reasons.append("active official record")
    if thriving_tier in {"Thriving", "Established"}:
        score += 12
        reasons.append(f"{thriving_tier.lower()} demand signals")
    elif thriving_tier == "Growing":
        score += 7
        reasons.append("growing demand signals")
    if reviews >= 50:
        score += 12
        reasons.append(f"{reviews} Google reviews")
    elif reviews >= 10:
        score += 8
        reasons.append(f"{reviews} Google reviews")
    elif reviews >= 3:
        score += 4
        reasons.append(f"{reviews} Google reviews")
    if rating >= 4.5:
        score += 7
        reasons.append(f"{rating:.1f}-star rating")
    elif rating >= 3.5:
        score += 3
        reasons.append(f"{rating:.1f}-star rating")
    if web_presence in {"No website", "Broken site", "Weak site", "Basic site", "Directory only", "Social only"}:
        score += 7
        reasons.append("pitchable website gap")
    elif opportunity_score >= 18:
        score += 4
        reasons.append("website opportunity still present")
    if has_contact:
        score += 5
        reasons.append("public contact available")

    score = min(score, 100)
    if score >= 70:
        confidence = "Strong inferred fit"
    elif score >= 50:
        confidence = "Good inferred fit"
    elif score >= 30:
        confidence = "Possible inferred fit"
    else:
        confidence = "Weak/unknown fit"

    return {
        "Premium Fit Score": score,
        "Premium Fit Confidence": confidence,
        "Premium Fit Evidence": "; ".join(dict.fromkeys(reasons[:6])),
    }


def compute_website_quality_score(lead: dict) -> dict:
    """Derive Website Quality Score and grade from the Phase 3 Quality Score."""
    web_presence = str(lead.get("Web Presence Status", ""))

    if web_presence == "No website":
        return {"website_quality_score": 0, "website_grade": "F", "website_quality_details": "No website exists"}
    if web_presence == "Unknown web presence":
        return {
            "website_quality_score": 0,
            "website_grade": "Unknown",
            "website_quality_details": "Web presence could not be verified",
        }
    if web_presence in {"Social only", "Directory only"}:
        return {"website_quality_score": 5, "website_grade": "F", "website_quality_details": f"No owned website ({web_presence})"}
    if web_presence == "Broken site":
        return {"website_quality_score": 8, "website_grade": "F", "website_quality_details": "Website is broken/unreachable"}

    quality = int(lead.get("Quality Score") or 0)

    details: list[str] = []
    viewport = str(lead.get("Viewport Meta", ""))
    if viewport != "Found":
        details.append("not mobile-friendly")
    word_count = int(lead.get("Word Count") or 0)
    if word_count < 100:
        details.append(f"thin content ({word_count} words)")
    pagespeed_perf = int(lead.get("PageSpeed Performance Score") or 0)
    if pagespeed_perf and pagespeed_perf < 50:
        details.append(f"poor mobile speed ({pagespeed_perf}/100)")
    elif pagespeed_perf and pagespeed_perf < 75:
        details.append(f"mobile speed needs work ({pagespeed_perf}/100)")
    forms = int(lead.get("Form Count") or 0)
    cta = str(lead.get("CTA Terms", ""))
    if not forms and not cta:
        details.append("no forms or CTAs")
    phones_on_page = str(lead.get("On-Page Phones", ""))
    emails_on_page = str(lead.get("On-Page Emails", ""))
    if not phones_on_page and not emails_on_page:
        details.append("no contact info on page")
    tech_stack_score = _int_value(lead.get("Tech Stack Score"))
    tech_stack_signal = str(lead.get("Tech Stack Signal", "")).strip()
    if tech_stack_score >= 38:
        quality -= 10
        details.append(f"weak tech stack ({tech_stack_signal or tech_stack_score})")
    elif tech_stack_score >= 22:
        quality -= 5
        details.append(f"missing tech stack signals ({tech_stack_signal or tech_stack_score})")

    quality = max(0, min(quality, 100))

    if quality >= 80:
        grade = "A"
    elif quality >= 60:
        grade = "B"
    elif quality >= 40:
        grade = "C"
    elif quality >= 20:
        grade = "D"
    else:
        grade = "F"

    return {
        "website_quality_score": quality,
        "website_grade": grade,
        "website_quality_details": "; ".join(details[:6]) if details else "Site meets basic quality standards",
    }


def compute_opportunity_score(lead: dict, lead_score: int) -> dict:
    """Compute an Opportunity Score that estimates room for improvement and sales angle strength."""
    opp = 0
    parts: list[str] = []
    web_presence = str(lead.get("Web Presence Status", ""))
    wqs = int(lead.get("Website Quality Score") or 0)
    grade = str(lead.get("Website Grade", ""))

    if web_presence == "No website":
        opp += 40
        parts.append("No website +40")
    elif web_presence == "Unknown web presence":
        parts.append("Unknown web presence +0")
    elif web_presence == "Broken site":
        opp += 35
        parts.append("Broken site +35")
    elif web_presence == "Social only":
        opp += 32
        parts.append("Social-only +32")
    elif web_presence == "Directory only":
        opp += 28
        parts.append("Directory-only +28")
    elif web_presence == "Weak site":
        if wqs <= 25:
            opp += 30
            parts.append(f"Very weak site (quality {wqs}) +30")
        else:
            opp += 20
            parts.append(f"Weak site (quality {wqs}) +20")
    elif web_presence == "Basic site":
        if wqs < 35:
            opp += 22
            parts.append(f"Basic but poor site (quality {wqs}) +22")
        elif wqs < 55:
            opp += 12
            parts.append(f"Basic site with gaps (quality {wqs}) +12")
        else:
            opp += 3
            parts.append(f"Functional basic site (quality {wqs}) +3")
    else:
        parts.append("Established web presence +0")

    cta_terms = str(lead.get("CTA Terms", "")).strip()
    booking_terms = str(lead.get("Booking Terms", "")).strip()
    form_count = int(lead.get("Form Count") or 0)
    on_page_phones = str(lead.get("On-Page Phones", "")).strip()
    on_page_emails = str(lead.get("On-Page Emails", "")).strip()
    viewport_meta = str(lead.get("Viewport Meta", "")).strip()
    word_count = int(lead.get("Word Count") or 0)

    has_site = web_presence not in {"No website", "Unknown web presence", "Social only", "Directory only", "Broken site"}
    if has_site:
        if not cta_terms:
            opp += 8
            parts.append("No CTA terms +8")
        if not booking_terms and form_count == 0:
            opp += 8
            parts.append("No booking/quote flow +8")
        elif not booking_terms:
            opp += 3
            parts.append("No booking terms (form exists) +3")
        if not on_page_phones and not on_page_emails and form_count == 0:
            opp += 8
            parts.append("No contact path on page +8")
        if viewport_meta != "Found":
            opp += 4
            parts.append("No mobile viewport +4")
        if word_count < 100:
            opp += 2
            parts.append(f"Thin content ({word_count} words) +2")

    outdated = str(lead.get("Outdated Design Markers", "")).strip()
    if outdated and has_site:
        opp += 6
        parts.append("Outdated design +6")

    tech_stack_score = _int_value(lead.get("Tech Stack Score"))
    tech_stack_signal = str(lead.get("Tech Stack Signal", "")).strip()
    tech_stack_strong = str(lead.get("Tech Stack Strong Signals", "")).strip()
    if has_site and tech_stack_score >= 38:
        opp += 10
        parts.append(f"Weak tech stack ({tech_stack_signal or tech_stack_score}) +10")
    elif has_site and tech_stack_score >= 22:
        opp += 5
        parts.append(f"Missing tech stack signals ({tech_stack_signal or tech_stack_score}) +5")
    elif has_site and tech_stack_signal == "Modern stack signals present" and tech_stack_strong:
        opp -= 6
        parts.append("Modern conversion/measurement stack -6")

    thriving_tier = str(lead.get("Thriving Tier", ""))
    if thriving_tier == "Thriving" and web_presence in {"No website", "Broken site", "Social only", "Directory only", "Weak site"}:
        opp += 12
        parts.append("Thriving business with weak web +12")
    elif thriving_tier == "Established" and web_presence in {"No website", "Broken site", "Social only", "Directory only"}:
        opp += 8
        parts.append("Established business with no/broken web +8")
    elif thriving_tier in {"Thriving", "Established"} and has_site and wqs < 35:
        opp += 6
        parts.append("Strong business with poor site +6")

    strong_signals = 0
    if str(lead.get("SSL Status", "")).startswith("HTTPS") or str(lead.get("Resolved Website URL", "")).startswith("https://"):
        strong_signals += 1
    if viewport_meta == "Found":
        strong_signals += 1
    if cta_terms:
        strong_signals += 1
    if booking_terms:
        strong_signals += 1
    if form_count >= 1:
        strong_signals += 1
    if on_page_phones or on_page_emails:
        strong_signals += 1
    if int(lead.get("Internal Link Count") or 0) >= 8:
        strong_signals += 1
    if int(lead.get("Image Count") or 0) >= 5:
        strong_signals += 1
    if word_count >= 300:
        strong_signals += 1
    page_title = str(lead.get("Page Title", "")).strip()
    meta_desc = str(lead.get("Meta Description", "")).strip()
    if page_title and len(page_title) >= 8 and meta_desc:
        strong_signals += 1
    if str(lead.get("Google Analytics", "")) == "Detected" or str(lead.get("Facebook Pixel", "")) == "Detected":
        strong_signals += 1
    if str(lead.get("Booking Platforms", "")).strip() and str(lead.get("Booking Platforms", "")).strip() != "None detected":
        strong_signals += 1

    contact_form = str(lead.get("Contact Page Has Form", ""))
    services_ok = str(lead.get("Services Described", ""))
    if contact_form == "Yes":
        strong_signals += 1
    if services_ok == "Yes":
        strong_signals += 1

    disqualified = False
    if has_site and strong_signals >= 8 and wqs >= 60:
        disqualified = True
        penalty = 40
        opp -= penalty
        parts.append(f"DISQUALIFIED: already-strong site ({strong_signals}/14 signals, quality {wqs}) -{penalty}")

    suppressed = False
    if has_site and not disqualified:
        if strong_signals >= 7 and wqs >= 50:
            suppress = 30
            opp -= suppress
            suppressed = True
            parts.append(f"Strong-site suppressor ({strong_signals}/14 signals, quality {wqs}) -{suppress}")
        elif strong_signals >= 6 and wqs >= 45:
            suppress = 20
            opp -= suppress
            suppressed = True
            parts.append(f"Moderate-site suppressor ({strong_signals}/14 signals, quality {wqs}) -{suppress}")
        elif strong_signals >= 5 and grade in {"A", "B"}:
            suppress = 12
            opp -= suppress
            suppressed = True
            parts.append(f"Mild-site suppressor ({strong_signals}/14 signals, grade {grade}) -{suppress}")

    opp = max(opp, 0)

    if disqualified:
        label = "Low opportunity despite high quality"
    elif suppressed and opp < 15:
        label = "Low opportunity despite high quality"
    elif suppressed:
        label = "Moderate opportunity (strong site)"
    elif opp >= 55:
        label = "High opportunity"
    elif opp >= 35:
        label = "Good opportunity"
    elif opp >= 18:
        label = "Moderate opportunity"
    else:
        label = "Low opportunity"

    return {
        "opportunity_score": opp,
        "opportunity_label": label,
        "opportunity_breakdown": "; ".join(parts) or "No opportunity modifiers applied",
    }


def _clean_parts(value: object, *, separators: tuple[str, ...] = (";", ",")) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    for separator in separators[1:]:
        text = text.replace(separator, separators[0])
    return [part.strip() for part in text.split(separators[0]) if part.strip()]


def _int_value(value: object) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _has_text(lead: dict, *keys: str) -> bool:
    return any(str(lead.get(key, "") or "").strip() for key in keys)


def compute_source_confidence_matrix(lead: dict) -> dict:
    """Summarize source evidence so automation can trust or recheck decisions."""
    web_presence = str(lead.get("Web Presence Status", "") or "").strip()
    no_website_evidence = str(lead.get("No Website Evidence", "") or "")
    verification_sources = _clean_parts(lead.get("Verification Sources", ""))
    provider_summary = str(lead.get("Provider Evidence Summary", "") or "")
    source_lines: list[str] = []
    sources_checked: list[str] = []
    score = 0
    website_support = 0
    identity_support = 0
    conflict_count = 0

    def add_source(
        name: str,
        status: str,
        summary: str,
        *,
        weight: int = 0,
        supports: str = "context",
        conflict: bool = False,
    ) -> None:
        nonlocal score, website_support, identity_support, conflict_count
        if name not in sources_checked:
            sources_checked.append(name)
        clean_summary = summary.strip()
        line = f"{name}: {status}"
        if clean_summary:
            line += f" - {clean_summary}"
        if line not in source_lines:
            source_lines.append(line)
        if conflict:
            conflict_count += 1
            score -= max(8, abs(weight))
            return
        if weight > 0:
            score += weight
            if supports == "website":
                website_support += weight
            elif supports == "identity":
                identity_support += weight

    google_place_id = str(lead.get("Google Place ID", "") or "").strip()
    if google_place_id:
        add_source("Google Places", "Matched", "place ID and listing data present", weight=18, supports="identity")
        google_absence = "Google Places" in verification_sources or "Google Places" in no_website_evidence
        if web_presence == "No website" and google_absence:
            add_source("Google Places", "Website absence", "matched listing shows no website", weight=20, supports="website")
        elif _has_text(lead, "Google Place URL", "Google Hours", "Google Review Snippets"):
            add_source("Google Places", "Details enriched", "hours/reviews/profile fields available", weight=5)

    search_providers = str(lead.get("Search Providers", "") or "").strip()
    discovery_sources = str(lead.get("Discovery Sources Attempted", "") or "").strip()
    raw_results = _int_value(lead.get("Raw Result Count"))
    if search_providers or discovery_sources or raw_results:
        add_source(
            "Public search",
            "Checked",
            f"{raw_results} raw result(s)" if raw_results else search_providers or discovery_sources,
            weight=5,
        )
        lowered_absence = no_website_evidence.lower()
        if web_presence == "No website" and any(token in lowered_absence for token in ("public", "no official", "no likely owned", "no owned")):
            add_source("Public search", "No owned site", "public discovery did not find a likely owned domain", weight=14, supports="website")

    dataforseo_status = str(lead.get("DataForSEO Status", "") or "").strip()
    dataforseo_owned = str(lead.get("DataForSEO Owned Domains", "") or "").strip()
    dataforseo_failure = str(lead.get("DataForSEO Failure Reason", "") or "").strip()
    if dataforseo_status:
        if dataforseo_status == "Found owned domain" or dataforseo_owned:
            add_source(
                "DataForSEO",
                "Owned domain found",
                dataforseo_owned or "SERP provider found a likely owned domain",
                weight=16,
                supports="website",
                conflict=web_presence in {"No website", "Unknown web presence"},
            )
        elif "error" in dataforseo_status.lower() or dataforseo_failure:
            add_source("DataForSEO", "Error", dataforseo_failure or dataforseo_status)
        else:
            add_source("DataForSEO", "No owned site", dataforseo_status, weight=12, supports="website")

    yelp_status = str(lead.get("Yelp Match Status", "") or "").strip()
    if yelp_status:
        if yelp_status == "Matched":
            confidence = _int_value(lead.get("Yelp Match Confidence"))
            reviews = str(lead.get("Yelp Review Count", "") or "").strip()
            add_source(
                "Yelp",
                "Matched",
                f"{confidence}/100 match" + (f", {reviews} reviews" if reviews else ""),
                weight=10 if confidence >= 65 else 5,
                supports="identity",
            )
        elif yelp_status == "Mismatch":
            add_source("Yelp", "Mismatch", str(lead.get("Yelp Failure Reason", "") or "weak candidate"), conflict=True)
        elif yelp_status == "No match":
            add_source("Yelp", "No match", "neutral; Yelp may omit businesses with no reviews")
        elif yelp_status != "Disabled":
            add_source("Yelp", yelp_status, str(lead.get("Yelp Failure Reason", "") or "checked"))

    official_status = official_record_value(lead, "Official Status Category", "Colorado Status Category")
    official_match = official_record_value(lead, "Official Match Confidence", "Colorado Match Confidence")
    official_source = official_record_value(lead, "Official Record Source")
    if official_status or official_match or official_source:
        if official_status == "Active":
            add_source("Official records", "Active match", official_source or official_record_label(lead), weight=18, supports="identity")
        elif official_status == "Compliance issue":
            add_source("Official records", "Compliance issue", official_source or official_record_label(lead), weight=6, supports="identity")
        elif official_match:
            add_source("Official records", f"{official_match} match", official_source or official_record_label(lead), weight=8, supports="identity")
        else:
            add_source("Official records", "Checked", official_source)

    license_status = str(lead.get("License Status", "") or "").strip()
    if license_status:
        if license_status == "License verified":
            add_source("License source", "Verified", str(lead.get("License Details", "") or ""), weight=12, supports="identity")
        elif license_status != "Not applicable":
            add_source("License source", license_status, str(lead.get("License Details", "") or ""))

    if _has_text(lead, "Domain Verification Summary", "Domain Checked", "Domain SSL Present", "Robots.txt Status", "Sitemap Status"):
        domain_summary = str(lead.get("Domain Verification Summary", "") or "").strip()
        if web_presence in {"Broken site", "Weak site", "Basic site", "Established website"}:
            add_source("Domain checks", "Verified domain signals", domain_summary, weight=12, supports="website")
        else:
            add_source("Domain checks", "Checked", domain_summary)

    if _has_text(lead, "Website Evidence Summary", "Audit Confidence", "Last Audited At", "Quality Score"):
        audit_summary = str(lead.get("Website Evidence Summary", "") or "").strip()
        if web_presence in {"Weak site", "Basic site", "Broken site"}:
            add_source("Website audit", "Measured live site", audit_summary, weight=22, supports="website")
        elif web_presence in {"Directory only", "Social only"}:
            add_source("Website audit", "Measured non-owned presence", audit_summary, weight=12, supports="website")
        else:
            add_source("Website audit", "Checked", audit_summary, weight=6)

    pagespeed_status = str(lead.get("PageSpeed Status", "") or "").strip()
    if pagespeed_status:
        perf = _int_value(lead.get("PageSpeed Performance Score"))
        summary = str(lead.get("PageSpeed Summary", "") or lead.get("Page Speed Signal", "") or "").strip()
        if pagespeed_status == "Measured":
            if web_presence in {"Weak site", "Basic site"} and perf >= 90:
                add_source("PageSpeed", "Strong performance", summary, weight=8, supports="website", conflict=True)
            elif perf and perf < 75:
                add_source("PageSpeed", "Measured weak performance", summary, weight=18, supports="website")
            else:
                add_source("PageSpeed", "Measured", summary, weight=10, supports="website")
        elif pagespeed_status == "Error":
            add_source("PageSpeed", "Error", str(lead.get("PageSpeed Error", "") or "API check failed"))

    contact_cross_reference = str(lead.get("Contact Cross-Reference", "") or "").strip()
    if contact_cross_reference:
        if contact_cross_reference == "Strong":
            add_source("Contact cross-reference", "Strong", str(lead.get("Cross-Reference Details", "") or ""), weight=8, supports="identity")
        elif contact_cross_reference == "Good":
            add_source("Contact cross-reference", "Good", str(lead.get("Cross-Reference Details", "") or ""), weight=5, supports="identity")
        elif contact_cross_reference == "Needs review":
            add_source("Contact cross-reference", "Needs review", str(lead.get("Cross-Reference Details", "") or ""), conflict=True)

    if provider_summary:
        add_source("Provider evidence", "Recorded", provider_summary, weight=4)

    if str(lead.get("Browser Fallback Used", "") or "").strip().lower() in {"yes", "true", "1"}:
        add_source("Browser fallback", "Used", str(lead.get("Browser Fallback Status", "") or ""), weight=4)

    score = max(0, min(100, score))
    tier = "High" if score >= 70 and conflict_count == 0 else "Medium" if score >= 45 and conflict_count <= 1 else "Low"
    assertion_status = "Strong"
    warnings: list[str] = []
    if web_presence == "No website" and website_support < 34:
        assertion_status = "Needs source confirmation"
        warnings.append("No-website claim needs another independent source")
        if tier == "High":
            tier = "Medium"
    elif web_presence in {"Weak site", "Basic site", "Broken site"} and website_support < 22:
        assertion_status = "Needs source confirmation"
        warnings.append("Website-quality claim needs a stronger live-site audit")
        if tier == "High":
            tier = "Medium"
    if conflict_count:
        assertion_status = "Conflicting evidence"
        warnings.append("At least one provider conflicts with the current website classification")
        tier = "Low" if conflict_count >= 2 else "Medium"

    return {
        "Source Confidence Score": score,
        "Source Confidence Tier": tier,
        "Source Confidence Matrix": "; ".join(source_lines),
        "Sources Checked": "; ".join(sources_checked),
        "Website Assertion Status": assertion_status,
        "Website Evidence Strength": website_support,
        "Identity Evidence Strength": identity_support,
        "Source Conflict Count": conflict_count,
        "Source Confidence Warnings": "; ".join(warnings),
    }


def build_decision_explanations(lead: dict) -> dict:
    web_presence = str(lead.get("Web Presence Status", "") or "").strip() or "Unknown web presence"
    opportunity_label = str(lead.get("Opportunity Label", "") or "").strip()
    review_bucket = str(lead.get("Review Bucket", "") or "").strip()
    source_tier = str(lead.get("Source Confidence Tier", "") or "").strip()
    source_warning = str(lead.get("Source Confidence Warnings", "") or "").strip()
    reviews = _int_value(lead.get("Reviews"))
    rating = lead.get("Rating") or ""
    contact = "email and phone" if lead.get("Email") and lead.get("Phone") else "email" if lead.get("Email") else "phone" if lead.get("Phone") else ""
    freshness = str(lead.get("Data Freshness", "") or lead.get("Last Verified At", "") or lead.get("Last Audited At", "") or "").strip()

    surfaced_parts = [part for part in (opportunity_label, web_presence, f"{source_tier.lower()} source confidence" if source_tier else "") if part]
    if reviews and rating:
        try:
            surfaced_parts.append(f"{reviews} reviews at {float(rating):.1f} stars")
        except (TypeError, ValueError):
            surfaced_parts.append(f"{reviews} reviews")
    elif reviews:
        surfaced_parts.append(f"{reviews} reviews")
    if contact:
        surfaced_parts.append(f"{contact} available")

    suppressed = ""
    opp_breakdown = str(lead.get("Opportunity Breakdown", "") or "")
    if "DISQUALIFIED" in opp_breakdown:
        suppressed = "Suppressed because the site already has strong quality signals"
    elif "suppressor" in opp_breakdown.lower() or "strong site" in opportunity_label.lower():
        suppressed = "Lower priority because the live site has enough strong signals to weaken the pitch"
    elif source_warning:
        suppressed = source_warning

    if source_warning or str(lead.get("Retry Recommended", "")).strip().lower() == "yes":
        next_action = "Recheck with another source before outreach"
    elif review_bucket in {"Hot lead", "High confidence", "Promising"} and contact:
        next_action = "Run agent review, then prepare outreach package"
    elif not contact:
        next_action = "Find a verified contact before outreach"
    elif review_bucket == "Needs review":
        next_action = "Open lead detail and review evidence"
    else:
        next_action = "Keep in backlog unless the client wants more volume"

    return {
        "Why Surfaced": "; ".join(surfaced_parts) or "Lead matched current scan criteria",
        "Why Suppressed": suppressed,
        "Evidence Freshness": freshness,
        "Next Best Action": next_action,
    }


def choose_review_bucket(lead: dict, score: int, review_flags: list[str]) -> str:
    web_presence = str(lead.get("Web Presence Status", ""))
    has_contact = bool(lead.get("Phone") or lead.get("Email"))
    business_reality = str(lead.get("Business Reality", ""))
    thriving_tier = str(lead.get("Thriving Tier", ""))
    wqs = int(lead.get("Website Quality Score") or 0)
    opp_score = int(lead.get("Opportunity Score") or 0)
    opp_label = str(lead.get("Opportunity Label", ""))

    if not has_contact:
        return "No contact"
    if web_presence == "Unknown web presence":
        return "Needs review" if score >= 30 else "Low priority"
    if business_reality == "Uncertain / weak match":
        return "Needs review" if score >= 30 else "Low priority"
    if opp_label == "Low opportunity despite high quality":
        return "Low priority"

    if (
        score >= 65
        and opp_score >= 40
        and web_presence in {"No website", "Broken site"}
        and thriving_tier in {"Thriving", "Established"}
        and not review_flags
    ):
        return "Hot lead"

    if score >= 60 and opp_score >= 30 and web_presence in {"No website", "Broken site", "Weak site"} and not review_flags:
        return "High confidence"

    if score >= 48 and opp_score >= 20 and web_presence in {"No website", "Broken site", "Social only", "Directory only"}:
        return "Promising"
    if score >= 48 and opp_score >= 20 and web_presence in {"Weak site", "Basic site"} and wqs < 45:
        return "Promising"

    if score >= 30:
        if web_presence in {"Weak site", "Basic site"} and wqs >= 50:
            return "Low priority"
        if opp_score < 12:
            return "Low priority"
        return "Needs review"
    return "Low priority"


def score_leads(machine: "LeadMachine", leads: list[dict]) -> list[dict]:
    machine.log("Stage 5/5: Score leads for outreach priority")

    for lead in leads:
        score = 0
        score_parts: list[str] = []
        rationale_parts: list[str] = []
        review_flags: list[str] = []
        cross_reference, cross_reference_details = machine.build_contact_cross_reference(lead)
        lead["Contact Cross-Reference"] = cross_reference
        lead["Cross-Reference Details"] = cross_reference_details
        license_result = machine.validate_business_license(lead)
        lead["License Target"] = license_result.get("target", "")
        lead["License Status"] = license_result.get("status", "")
        lead["License Confidence"] = license_result.get("confidence", "")
        lead["License Details"] = license_result.get("details", "")
        lead["License Verify Link"] = license_result.get("verify_url", "")
        web_presence = lead.get("Web Presence Status", "")
        rating = lead.get("Rating") or 0
        reviews = lead.get("Reviews") or 0
        age_days = lead.get("Business Age Days")
        record_status = official_record_value(lead, "Official Record Status", "Colorado Record Status").lower()
        record_status_display = official_record_value(lead, "Official Record Status", "Colorado Record Status")
        record_status_category = official_record_value(lead, "Official Status Category", "Colorado Status Category")
        record_match_type = official_record_value(lead, "Official Match Type", "Colorado Match Type")
        record_history_summary = official_record_value(lead, "Official History Summary", "Colorado History Summary")
        record_status_note = official_record_value(lead, "Official Status Note", "Colorado Status Note")
        record_label = official_record_label(lead)
        record_state_label = official_record_state_label(lead)
        email_source = str(lead.get("Email Source", "")).strip()
        city_area = str(lead.get("City/Area", "")).strip()
        seed_source = str(lead.get("Seed Source", "")).strip()
        web_details = str(lead.get("Web Presence Details", "")).strip()
        web_confidence = str(lead.get("Web Presence Confidence", "")).strip()
        website_signals = str(lead.get("Website Signals", "")).strip()
        website_failure_type = str(lead.get("Website Failure Type", "")).strip()

        thriving = machine.compute_thriving_signals(lead)
        lead["Thriving Score"] = thriving["thriving_score"]
        lead["Thriving Tier"] = thriving["thriving_tier"]
        lead["Thriving Signals"] = "; ".join(thriving["thriving_signals"][:5])

        revenue = machine.compute_revenue_tier(lead)
        lead["Revenue Tier"] = revenue["revenue_tier"]
        lead["Revenue Note"] = revenue["revenue_note"]

        site_quality = machine.compute_website_quality_score(lead)
        lead["Website Quality Score"] = site_quality["website_quality_score"]
        lead["Website Grade"] = site_quality["website_grade"]
        lead["Website Quality Details"] = site_quality["website_quality_details"]

        if web_presence == "No website":
            score += 40
            score_parts.append("No website verified +40")
            rationale_parts.append("No official website found")
            if thriving["thriving_tier"] == "Thriving":
                score += 20
                score_parts.append("Thriving business with no website +20")
                rationale_parts.append("HIGH-VALUE: thriving business with zero web presence")
            elif thriving["thriving_tier"] == "Established":
                score += 12
                score_parts.append("Established business with no website +12")
                rationale_parts.append("Established business operating without a website")
        elif web_presence == "Broken site":
            score += 30
            score_parts.append("Broken website +30")
            rationale_parts.append("Broken website detected")
            broken_count = int(lead.get("Broken Link Count") or 0)
            if broken_count >= 3:
                score += 5
                score_parts.append(f"Multiple broken links ({broken_count}) +5")
        elif web_presence == "Weak site":
            wqs = site_quality["website_quality_score"]
            if wqs <= 25:
                score += 28
                score_parts.append(f"Very weak website (quality {wqs}/100) +28")
                rationale_parts.append("Website is live but visibly poor quality")
            else:
                score += 18
                score_parts.append(f"Weak website (quality {wqs}/100) +18")
                rationale_parts.append("Website exists but has quality gaps")
            pagespeed_perf = int(lead.get("PageSpeed Performance Score") or 0)
            if pagespeed_perf and pagespeed_perf < 50:
                score += 8
                score_parts.append(f"Poor PageSpeed performance ({pagespeed_perf}/100) +8")
                rationale_parts.append(f"Mobile PageSpeed performance is poor at {pagespeed_perf}/100")
            elif pagespeed_perf and pagespeed_perf < 75:
                score += 4
                score_parts.append(f"PageSpeed needs improvement ({pagespeed_perf}/100) +4")
                rationale_parts.append(f"Mobile PageSpeed needs improvement at {pagespeed_perf}/100")
        elif web_presence == "Social only":
            score += 26
            score_parts.append("Social-only presence +26")
            rationale_parts.append("Only social-media pages found")
        elif web_presence == "Basic site":
            wqs = site_quality["website_quality_score"]
            if wqs >= 55:
                score += 5
                score_parts.append(f"Basic but functional website (quality {wqs}/100) +5")
                rationale_parts.append("Website is functional enough that the business may not see urgency")
                review_flags.append("Site is functional - may be hard sell")
            elif wqs >= 35:
                score += 12
                score_parts.append(f"Basic website with gaps (quality {wqs}/100) +12")
                rationale_parts.append("Website is live but has clear gaps")
            else:
                score += 20
                score_parts.append(f"Basic but poor website (quality {wqs}/100) +20")
                rationale_parts.append("Website is live but poor enough to justify replacement")
            pagespeed_perf = int(lead.get("PageSpeed Performance Score") or 0)
            if pagespeed_perf and pagespeed_perf < 50:
                score += 6
                score_parts.append(f"Poor PageSpeed performance ({pagespeed_perf}/100) +6")
                rationale_parts.append(f"Mobile PageSpeed performance is poor at {pagespeed_perf}/100")
            elif pagespeed_perf and pagespeed_perf < 75:
                score += 3
                score_parts.append(f"PageSpeed needs improvement ({pagespeed_perf}/100) +3")
                rationale_parts.append(f"Mobile PageSpeed needs improvement at {pagespeed_perf}/100")
        elif web_presence == "Directory only":
            score += 20
            score_parts.append("Directory-only presence +20")
            rationale_parts.append("Only directory listings found")
        elif web_presence == "Unknown web presence":
            review_flags.append("Unknown web presence - retry required")
            rationale_parts.append("Web presence could not be verified with enough evidence")

        outdated = str(lead.get("Outdated Design Markers", "")).strip()
        if outdated and web_presence in {"Weak site", "Basic site"}:
            score += 8
            score_parts.append(f"Outdated design ({outdated}) +8")
            rationale_parts.append(f"Outdated design: {outdated}")

        tech_stack_score = _int_value(lead.get("Tech Stack Score"))
        tech_stack_signal = str(lead.get("Tech Stack Signal", "")).strip()
        tech_stack_summary = str(lead.get("Tech Stack Summary", "")).strip()
        if web_presence in {"Weak site", "Basic site", "Real website"}:
            if tech_stack_score >= 38:
                score += 8
                score_parts.append(f"Weak tech stack ({tech_stack_score}/100) +8")
                rationale_parts.append(tech_stack_summary or tech_stack_signal or "Weak technology stack signals")
            elif tech_stack_score >= 22:
                score += 4
                score_parts.append(f"Missing tech stack signals ({tech_stack_score}/100) +4")
                rationale_parts.append(tech_stack_summary or tech_stack_signal or "Missing technology stack signals")
            elif tech_stack_signal == "Modern stack signals present":
                review_flags.append("Modern stack may lower website urgency")

        if lead.get("Phone"):
            score += 10
            score_parts.append("Phone available +10")
            rationale_parts.append("Phone number available")
        if lead.get("Email"):
            score += 15
            score_parts.append("Email available +15")
            rationale_parts.append(f"Email available via {email_source or 'lookup'}")
            if "guess" in email_source.lower():
                review_flags.append("Email is guessed")

        if cross_reference == "Strong":
            score += 4
            score_parts.append("Strong contact cross-reference +4")
        elif cross_reference == "Good":
            score += 2
            score_parts.append("Good contact cross-reference +2")
        elif cross_reference == "Needs review":
            review_flags.append("Contact cross-reference mismatch")
        yelp_status = str(lead.get("Yelp Match Status", "")).strip()
        try:
            identity_confidence = int(lead.get("Business Identity Confidence") or lead.get("Yelp Match Confidence") or 0)
        except (TypeError, ValueError):
            identity_confidence = 0
        if yelp_status == "Matched" and identity_confidence >= 65:
            score += 3
            score_parts.append("Yelp identity match +3")
            rationale_parts.append(f"Yelp match confidence {identity_confidence}/100")
        elif yelp_status == "Mismatch":
            review_flags.append("Yelp identity mismatch")
        if str(lead.get("DataForSEO Status", "")).strip() == "Found owned domain" and web_presence in {
            "No website",
            "Unknown web presence",
        }:
            review_flags.append("SERP provider found a possible owned domain")

        if rating >= 4.8:
            score += 12
            score_parts.append("Rating 4.8+ +12")
            rationale_parts.append(f"Strong rating: {rating:.1f} stars")
        elif rating >= 4.5:
            score += 8
            score_parts.append("Rating 4.5+ +8")
            rationale_parts.append(f"Strong rating: {rating:.1f} stars")
        elif rating >= machine.config.min_rating:
            score += 4
            score_parts.append(f"Rating {machine.config.min_rating}+ +4")
            rationale_parts.append(f"Rating cleared threshold: {rating:.1f} stars")

        if 10 <= reviews <= 250:
            score += 10
            score_parts.append("Reviews 10-250 +10")
            rationale_parts.append(f"{int(reviews)} reviews")
        elif 251 <= reviews <= 600:
            score += 5
            score_parts.append("Reviews 251-600 +5")
            rationale_parts.append(f"{int(reviews)} reviews")
        elif reviews > 600:
            score += 3
            score_parts.append("Reviews 600+ +3")
            rationale_parts.append(f"{int(reviews)} reviews (high-volume business)")

        if isinstance(age_days, int):
            if age_days >= 365 * 5:
                score += 10
                score_parts.append("Business age 5+ years +10")
            elif age_days >= 365 * 2:
                score += 6
                score_parts.append("Business age 2+ years +6")
            elif age_days >= machine.config.min_business_age_days:
                score += 3
                score_parts.append(f"Business age {machine.config.min_business_age_days}+ days +3")
            age_summary = machine.format_age_summary(age_days)
            if age_summary:
                rationale_parts.append(age_summary)

        if record_status_category == "Active" or "good standing" in record_status:
            score += 8
            score_parts.append("Official record active +8")
            rationale_parts.append(f"{record_label} is active")
        elif record_status_category == "Compliance issue" or "delinquent" in record_status or "noncompliant" in record_status:
            score -= 8
            score_parts.append("Official record issue -8")
            rationale_parts.append(f"{record_label} status: {record_status_display}")
        elif record_status_display:
            rationale_parts.append(f"{record_label} status: {record_status_display}")

        if record_match_type == "Possible DBA or trade-name mismatch":
            review_flags.append("Possible DBA or trade-name mismatch")
            rationale_parts.append(f"{record_label} may be under a different legal or trade name")

        license_status = str(lead.get("License Status", "")).strip()
        if license_status == "License verified":
            score += 6
            score_parts.append("Official license verified +6")
            rationale_parts.append(str(lead.get("License Details", "")))
        elif license_status == "Likely licensed - review":
            score += 2
            score_parts.append("Possible official license match +2")
            rationale_parts.append(str(lead.get("License Details", "")))
            review_flags.append("License match should be reviewed")
        elif license_status == "Manual review recommended":
            review_flags.append("Licensed profession check needs review")
            if lead.get("License Details"):
                rationale_parts.append(str(lead.get("License Details", "")))

        if (
            record_state_label in {"Colorado", "California"}
            and not lead.get("Formation Date")
            and not record_status_display
            and not record_status_note
        ):
            review_flags.append(f"No {record_state_label} record match")
        if seed_source == "Overture" and not rating and not reviews:
            review_flags.append("No Google review metrics")
        if web_confidence in {"Low", "Medium"}:
            review_flags.append(f"Web presence confidence: {web_confidence}")
        if str(lead.get("Retry Recommended", "")).strip() == "Yes":
            review_flags.append(f"Retry recommended: {lead.get('Retry Reason', '')}")
        if web_details and web_details not in rationale_parts:
            rationale_parts.append(web_details)
        if website_signals and website_signals not in rationale_parts:
            rationale_parts.append(f"Website signals: {website_signals}")
        if cross_reference_details and cross_reference_details not in rationale_parts:
            rationale_parts.append(f"Cross-reference: {cross_reference_details}")
        if record_history_summary and record_history_summary not in rationale_parts:
            rationale_parts.append(f"{record_label} filing history: {record_history_summary}")
        if website_failure_type and website_failure_type not in rationale_parts:
            rationale_parts.append(f"Website failure type: {website_failure_type}")

        source_confidence = compute_source_confidence_matrix(lead)
        lead.update(source_confidence)
        source_tier = str(source_confidence.get("Source Confidence Tier", ""))
        assertion_status = str(source_confidence.get("Website Assertion Status", ""))
        conflict_count = int(source_confidence.get("Source Conflict Count", 0) or 0)
        if source_tier == "Low" and web_presence in {
            "No website",
            "Broken site",
            "Weak site",
            "Basic site",
            "Directory only",
            "Social only",
        }:
            score -= 12
            score_parts.append("Low source confidence -12")
            review_flags.append("Low source confidence")
        elif assertion_status == "Needs source confirmation":
            score -= 5
            score_parts.append("Needs source confirmation -5")
            review_flags.append(assertion_status)
        if conflict_count:
            score -= min(18, conflict_count * 8)
            score_parts.append(f"Conflicting source evidence -{min(18, conflict_count * 8)}")
            review_flags.append("Conflicting source evidence")

        unique_rationale = list(dict.fromkeys(part for part in rationale_parts if part))
        unique_flags = list(dict.fromkeys(flag for flag in review_flags if flag))
        final_score = max(score, 0)
        business_reality, reality_confidence, reality_details = machine.evaluate_business_reality(
            lead,
            cross_reference=cross_reference,
        )

        opportunity_result = machine.compute_opportunity_score(lead, final_score)

        lead["Lead Score"] = final_score
        lead["Opportunity Score"] = opportunity_result["opportunity_score"]
        lead["Opportunity Label"] = opportunity_result["opportunity_label"]
        lead["Opportunity Breakdown"] = opportunity_result["opportunity_breakdown"]
        lead.update(machine.compute_premium_fit_confidence(lead))
        lead["Business Reality"] = business_reality
        lead["Reality Confidence"] = reality_confidence
        lead["Reality Details"] = reality_details
        lead["Review Bucket"] = machine.choose_review_bucket(lead, final_score, unique_flags)
        lead["Opportunity Brief"] = machine.build_opportunity_brief(lead, cross_reference=cross_reference)
        lead["Why Kept"] = machine.build_why_kept_summary(
            lead,
            business_reality=business_reality,
            reality_details=reality_details,
        )
        lead.update(build_decision_explanations(lead))
        lead["Lead Rationale"] = "; ".join(unique_rationale[:5]) or "Lead survived filtering and outreach checks"
        lead["Score Breakdown"] = "; ".join(score_parts) or "No score modifiers applied"
        lead["Review Flags"] = "; ".join(unique_flags)

    leads.sort(
        key=lambda lead: (
            -(lead.get("Opportunity Score") or 0),
            -(lead.get("Lead Score") or 0),
            -(lead.get("Rating") or 0),
            -(lead.get("Reviews") or 0),
        )
    )
    bucket_counts: dict[str, int] = {}
    for lead in leads:
        bucket = str(lead.get("Review Bucket", "")).strip() or "Unbucketed"
        bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1
    machine.record_stage_report(
        "scoring",
        "Score leads for outreach priority",
        scored=len(leads),
        hot_lead=bucket_counts.get("Hot lead", 0),
        high_confidence=bucket_counts.get("High confidence", 0),
        promising=bucket_counts.get("Promising", 0),
        needs_review=bucket_counts.get("Needs review", 0),
        low_priority=bucket_counts.get("Low priority", 0),
        no_contact=bucket_counts.get("No contact", 0),
    )
    return leads
