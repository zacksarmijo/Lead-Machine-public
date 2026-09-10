"""Deterministic marketing brief builder for enhanced website generation."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MARKETING_BRIEF_FILE = "marketing_brief.json"

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)


@dataclass
class MarketingBrief:
    version: int
    lead_key: str
    business_name: str
    business_type: str
    location: str
    primary_audience: str
    primary_conversion_goal: str
    positioning: dict[str, Any] = field(default_factory=dict)
    page_strategy: dict[str, Any] = field(default_factory=dict)
    copy_strategy: dict[str, Any] = field(default_factory=dict)
    seo_strategy: dict[str, Any] = field(default_factory=dict)
    analytics_strategy: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _clean_text(value: Any, max_chars: int = 240) -> str:
    text = _URL_RE.sub("", str(value or "").strip())
    text = re.sub(r"\s+", " ", text)
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."


def _clean_list(value: Any, *, limit: int = 12, max_chars: int = 160) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _clean_text(item, max_chars=max_chars)
        if not text:
            continue
        norm = text.lower()
        if norm in seen:
            continue
        seen.add(norm)
        out.append(text)
        if len(out) >= limit:
            break
    return out


def _data(lead: dict[str, Any]) -> dict[str, Any]:
    data = lead.get("data")
    return data if isinstance(data, dict) else {}


def _first(*values: Any) -> str:
    for value in values:
        text = _clean_text(value)
        if text:
            return text
    return ""


def _lead_key(lead: dict[str, Any]) -> str:
    return _first(lead.get("lead_key"), lead.get("key"))


def _business_name(lead: dict[str, Any], scraped: dict[str, Any]) -> str:
    data = _data(lead)
    return _first(
        scraped.get("business_name"),
        lead.get("business_name"),
        data.get("Business Name"),
        data.get("Name"),
        "This business",
    )


def _business_type(lead: dict[str, Any], scraped: dict[str, Any]) -> str:
    data = _data(lead)
    return _first(
        lead.get("business_type"),
        data.get("Business Type"),
        data.get("Category"),
        scraped.get("category"),
        "local business",
    )


def _location(lead: dict[str, Any], scraped: dict[str, Any]) -> str:
    data = _data(lead)
    return _first(
        lead.get("city_area"),
        data.get("City/Area"),
        data.get("City"),
        scraped.get("address"),
        scraped.get("location"),
    )


def _terms(*values: str) -> set[str]:
    terms: set[str] = set()
    for value in values:
        lowered = str(value or "").lower()
        if lowered:
            terms.add(lowered)
        for token in re.split(r"[^a-z0-9]+", lowered):
            if len(token) >= 3:
                terms.add(token)
    return terms


def _goal_for_type(business_type: str) -> tuple[str, list[str]]:
    terms = _terms(business_type)
    if {"plumber", "roofer", "hvac", "electrician", "contractor", "repair"}.intersection(terms):
        return "call and quote requests", ["Call Now", "Request a Quote", "Schedule Service"]
    if {"dentist", "chiropractor", "medspa", "healthcare"}.intersection(terms):
        return "appointment requests", ["Book an Appointment", "Request a Consultation", "Call the Office"]
    if {"restaurant", "cafe", "bakery", "hospitality"}.intersection(terms):
        return "menu views, reservations, and visits", ["View Menu", "Reserve a Table", "Get Directions"]
    if {"law", "lawyer", "realtor", "estate", "accountant", "consultant"}.intersection(terms):
        return "consultation requests", ["Request a Consultation", "Contact the Team", "Start a Conversation"]
    return "qualified contact requests", ["Contact Us", "Request Information", "Call Today"]


def _schema_types(business_type: str) -> list[str]:
    terms = _terms(business_type)
    if {"restaurant", "cafe", "bakery"}.intersection(terms):
        return ["LocalBusiness", "Restaurant"]
    if "dentist" in terms:
        return ["LocalBusiness", "Dentist"]
    if {"chiropractor", "medspa", "healthcare"}.intersection(terms):
        return ["LocalBusiness", "MedicalBusiness"]
    if {"law", "lawyer"}.intersection(terms):
        return ["LocalBusiness", "LegalService"]
    if {"realtor", "estate"}.intersection(terms):
        return ["LocalBusiness", "RealEstateAgent"]
    return ["LocalBusiness"]


def build_marketing_brief(
    lead: dict[str, Any],
    scraped: dict[str, Any],
    site_plan: dict[str, Any],
) -> MarketingBrief:
    business_name = _business_name(lead, scraped)
    business_type = _business_type(lead, scraped)
    location = _location(lead, scraped)
    services = _clean_list(scraped.get("services"), limit=10)
    headings = _clean_list(scraped.get("headings"), limit=8)
    phones = _clean_list(scraped.get("phones"), limit=3)
    emails = _clean_list(scraped.get("emails"), limit=3)
    goal, ctas = _goal_for_type(business_type)
    pages = site_plan.get("pages") if isinstance(site_plan.get("pages"), list) else []
    page_titles = [
        _clean_text(page.get("title") if isinstance(page, dict) else page, 80)
        for page in pages[:8]
    ]
    page_titles = [title for title in page_titles if title]
    audience = (
        f"Local customers in {location}"
        if location
        else f"Local customers looking for {business_type}"
    )
    service_phrase = services[0] if services else business_type
    local_modifier = f" in {location}" if location else ""

    positioning = {
        "one_liner": f"{business_name} helps local customers with {service_phrase}{local_modifier}.",
        "value_proposition": (
            f"A clearer website should make {goal} easy while reusing only verified public facts."
        ),
        "differentiators": (services[:4] or headings[:4]),
        "objections": [
            "Can I contact them quickly?",
            "Do they serve my area?",
            "Do they offer the specific service I need?",
        ],
    }
    page_strategy = {
        "recommended_pages": page_titles or ["Home", "Services", "Contact"],
        "primary_page_goal": goal,
        "internal_linking_notes": [
            "Route service mentions toward the primary contact action.",
            "Keep location and contact details reachable from every page preview.",
        ],
    }
    copy_strategy = {
        "headline_angles": [
            f"{service_phrase} for {location}" if location else f"{service_phrase} from {business_name}",
            f"Clear next steps for {goal}",
            f"Local {business_type} with straightforward contact options",
        ],
        "cta_labels": ctas,
        "proof_points": services[:5] + headings[:3],
        "words_to_use": [business_name, business_type] + ([location] if location else []) + services[:5],
        "words_to_avoid": [
            "award-winning",
            "guaranteed results",
            "trusted by thousands",
            "lorem ipsum",
        ],
    }
    local_keywords = []
    if location:
        local_keywords.append(f"{business_type} {location}")
        local_keywords.extend(f"{service} {location}" for service in services[:4])
    else:
        local_keywords.extend(services[:5])
    seo_strategy = {
        "title_template": f"{business_name} | {business_type}{local_modifier}",
        "meta_description_template": (
            f"Contact {business_name} for {service_phrase}{local_modifier}. "
            "Review services, contact options, and next steps."
        ),
        "local_keywords": _clean_list(local_keywords, limit=8),
        "schema_types": _schema_types(business_type),
    }
    analytics_strategy = {
        "conversion_events": ["primary_cta_click", "contact_form_submit"],
        "cta_events": [
            "hero_primary_cta_click",
            "sticky_or_header_cta_click",
            "final_cta_click",
        ],
        "form_events": ["contact_form_start", "contact_form_submit"],
        "contact_channels": {
            "phone_available": bool(phones),
            "email_available": bool(emails),
        },
    }
    return MarketingBrief(
        version=1,
        lead_key=_lead_key(lead),
        business_name=business_name,
        business_type=business_type,
        location=location,
        primary_audience=audience,
        primary_conversion_goal=goal,
        positioning=positioning,
        page_strategy=page_strategy,
        copy_strategy=copy_strategy,
        seo_strategy=seo_strategy,
        analytics_strategy=analytics_strategy,
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


def write_marketing_brief(brief: MarketingBrief, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / MARKETING_BRIEF_FILE
    path.write_text(
        json.dumps(brief.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def load_marketing_brief(output_dir: Path, lead_key: str = "") -> dict[str, Any] | None:
    path = Path(output_dir) / MARKETING_BRIEF_FILE
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if lead_key and str(data.get("lead_key") or "") not in {"", str(lead_key)}:
        return None
    return data


def build_prompt_marketing_brief(
    brief: MarketingBrief | dict[str, Any],
) -> dict[str, Any]:
    raw = brief.to_dict() if isinstance(brief, MarketingBrief) else dict(brief or {})
    payload = {
        "version": raw.get("version", 1),
        "business_name": _clean_text(raw.get("business_name"), 120),
        "business_type": _clean_text(raw.get("business_type"), 120),
        "location": _clean_text(raw.get("location"), 120),
        "primary_audience": _clean_text(raw.get("primary_audience"), 180),
        "primary_conversion_goal": _clean_text(raw.get("primary_conversion_goal"), 120),
        "positioning": {
            "one_liner": _clean_text((raw.get("positioning") or {}).get("one_liner"), 220),
            "value_proposition": _clean_text((raw.get("positioning") or {}).get("value_proposition"), 220),
            "differentiators": _clean_list((raw.get("positioning") or {}).get("differentiators"), limit=5),
            "objections": _clean_list((raw.get("positioning") or {}).get("objections"), limit=5),
        },
        "copy_strategy": {
            "headline_angles": _clean_list((raw.get("copy_strategy") or {}).get("headline_angles"), limit=5),
            "cta_labels": _clean_list((raw.get("copy_strategy") or {}).get("cta_labels"), limit=5),
            "proof_points": _clean_list((raw.get("copy_strategy") or {}).get("proof_points"), limit=6),
            "words_to_use": _clean_list((raw.get("copy_strategy") or {}).get("words_to_use"), limit=10),
            "words_to_avoid": _clean_list((raw.get("copy_strategy") or {}).get("words_to_avoid"), limit=8),
        },
        "seo_strategy": {
            "title_template": _clean_text((raw.get("seo_strategy") or {}).get("title_template"), 160),
            "meta_description_template": _clean_text((raw.get("seo_strategy") or {}).get("meta_description_template"), 220),
            "local_keywords": _clean_list((raw.get("seo_strategy") or {}).get("local_keywords"), limit=8),
            "schema_types": _clean_list((raw.get("seo_strategy") or {}).get("schema_types"), limit=5, max_chars=80),
        },
        "analytics_strategy": {
            "conversion_events": _clean_list((raw.get("analytics_strategy") or {}).get("conversion_events"), limit=5, max_chars=80),
            "cta_events": _clean_list((raw.get("analytics_strategy") or {}).get("cta_events"), limit=6, max_chars=80),
            "form_events": _clean_list((raw.get("analytics_strategy") or {}).get("form_events"), limit=4, max_chars=80),
        },
    }
    encoded = json.dumps(payload, ensure_ascii=False)
    if _URL_RE.search(encoded):
        encoded = _URL_RE.sub("", encoded)
        payload = json.loads(encoded)
    return payload
