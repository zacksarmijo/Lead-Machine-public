from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import re
from typing import Any, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup


COLORADO_BUSINESS_ENTITIES_API = "https://data.colorado.gov/resource/4ykn-tg5h.json"
COLORADO_TRANSACTION_HISTORY_API = "https://data.colorado.gov/resource/casm-dbbj.json"
COLORADO_LICENSE_API = "https://data.colorado.gov/resource/7s5z-vewr.json"
CALIFORNIA_BUSINESS_KEYWORD_API = "https://calico.sos.ca.gov/cbc/v1/api/BusinessEntityKeywordSearch"
CALIFORNIA_BIZFILE_SEARCH_URL = "https://bizfileonline.sos.ca.gov/search/business"
CSLB_LICENSE_CHECK_URL = "https://www.cslb.ca.gov/OnlineServices/CheckLicenseII/CheckLicense.aspx"
CSLB_LICENSE_CHECK_BASE_URL = "https://www.cslb.ca.gov"

LICENSE_TARGETS = {
    "Dentistry": {"dentist", "dental", "orthodont", "periodont", "endodont", "oral surgery"},
    "Therapy / counseling": {
        "therapy",
        "therapist",
        "counseling",
        "counselling",
        "counselor",
        "counsellor",
        "psychology",
        "psychologist",
        "psychotherapy",
        "mental health",
        "behavioral health",
        "family therapy",
    },
    "Chiropractic": {"chiropractic", "chiropractor", "chiro"},
    "Engineering": {"engineer", "engineering"},
}

CALIFORNIA_CONTRACTOR_LICENSE_TERMS = {
    "adu",
    "builder",
    "cabinet",
    "concrete",
    "construction",
    "contractor",
    "custom home",
    "deck",
    "design build",
    "door",
    "drywall",
    "electric",
    "fence",
    "flooring",
    "framing",
    "general building",
    "general contractor",
    "hardscape",
    "home builder",
    "home remodeling",
    "hvac",
    "landscape",
    "luxury home",
    "masonry",
    "painting",
    "patio",
    "plumbing",
    "pool",
    "remodel",
    "renovation",
    "residential builder",
    "roof",
    "solar",
    "stucco",
    "tile",
    "window",
}


def parse_formation_date(text: str) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    except Exception:
        pass
    for pattern in [r"(\d{2}/\d{2}/\d{4})", r"([A-Z][a-z]+ \d{1,2}, \d{4})"]:
        match = re.search(pattern, text)
        if not match:
            continue
        value = match.group(1)
        for fmt in ("%m/%d/%Y", "%B %d, %Y"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
    return None


def colorado_match_assessment(machine: Any, business_name: str, row: dict, score: int) -> tuple[str, str]:
    target_name = machine.normalize_business_name(business_name)
    candidate_name = machine.normalize_business_name(str(row.get("entityname", "")))
    if target_name and candidate_name == target_name:
        return "Exact legal-name match", "High"
    if score >= 80:
        return "Strong business-name match", "High"
    if score >= 50:
        return "Moderate business-name match", "Medium"
    if score >= 30:
        return "Possible DBA or trade-name mismatch", "Low"
    return "No reliable Colorado match", "Low"


def fetch_colorado_entity_candidates(machine: Any, name: str, city: str) -> list[dict]:
    tokens = machine.query_business_name_tokens(name)
    if not tokens:
        return []

    city_clause = machine.build_soql_upper_equals_clause("principalcity", city)
    token_clauses = machine.build_soql_like_clauses(["entityname"], tokens, limit=3)
    where_parts = [clause for clause in [city_clause, *token_clauses] if clause]
    params = {
        "$select": "entityid,entityname,principalcity,entitystatus,entitytype,entityformdate",
        "$where": " AND ".join(where_parts),
        "$limit": 12,
    }

    try:
        response = machine._request("get", COLORADO_BUSINESS_ENTITIES_API, params=params, timeout=10)
        rows = response.json() if response.status_code == 200 else []
    except Exception:
        rows = []

    if rows:
        return rows if isinstance(rows, list) else []

    fallback_where = " AND ".join(token_clauses)
    fallback_params = {
        "$select": "entityid,entityname,principalcity,entitystatus,entitytype,entityformdate",
        "$where": fallback_where,
        "$limit": 20,
    }
    try:
        response = machine._request("get", COLORADO_BUSINESS_ENTITIES_API, params=fallback_params, timeout=10)
        rows = response.json() if response.status_code == 200 else []
        return rows if isinstance(rows, list) else []
    except Exception:
        return []


def score_colorado_entity_match(machine: Any, business_name: str, city: str, row: dict) -> int:
    candidate_name = str(row.get("entityname", ""))
    city_normalized = machine.normalize_filter_text(city)
    candidate_city = machine.normalize_filter_text(str(row.get("principalcity", "")))

    score = machine._business_name_match_score(
        business_name,
        candidate_name,
        exact_score=100,
        prefix_score=70,
        contains_score=50,
    )
    if city_normalized and candidate_city == city_normalized:
        score += 10
    return score


def pick_best_colorado_entity(machine: Any, business_name: str, city: str, rows: list[dict]) -> tuple[Optional[dict], int]:
    scored: list[tuple[int, dict]] = []
    for row in rows:
        scored.append((machine.score_colorado_entity_match(business_name, city, row), row))
    if not scored:
        return None, 0
    scored.sort(key=lambda item: item[0], reverse=True)
    best_score, best_row = scored[0]
    if best_score < 35:
        return None, best_score
    return best_row, best_score


def license_target_for_lead(lead: dict) -> str:
    haystack = " ".join(
        [
            str(lead.get("Business Name", "")),
            str(lead.get("Business Type", "")),
            str(lead.get("Lead Rationale", "")),
            str(lead.get("Opportunity Brief", "")),
        ]
    ).lower()
    for label, keywords in LICENSE_TARGETS.items():
        if any(keyword in haystack for keyword in keywords):
            return label
    return ""


def fetch_colorado_license_candidates(machine: Any, name: str, city: str, license_target: str) -> list[dict]:
    tokens = machine.query_business_name_tokens(name)
    if not tokens or not city:
        return []

    city_clause = machine.build_soql_upper_equals_clause("city", city)
    token_filters = machine.build_soql_like_clauses(["entityname", "lastname", "firstname"], tokens, limit=3)
    where_parts = [clause for clause in [city_clause, *token_filters] if clause]
    params = {
        "$select": (
            "lastname,firstname,middlename,entityname,city,licensetype,subcategory,licensenumber,"
            "licensestatusdescription,specialty,title,linktoverifylicense,linktoviewhealthcareprofile"
        ),
        "$where": " AND ".join(where_parts),
        "$limit": 12,
    }

    try:
        response = machine._request("get", COLORADO_LICENSE_API, params=params, timeout=10)
        rows = response.json() if response.status_code == 200 else []
    except Exception:
        rows = []

    return rows if isinstance(rows, list) else []


def score_colorado_license_match(machine: Any, business_name: str, city: str, row: dict) -> int:
    entity_name = str(row.get("entityname", "")).strip()
    holder_name = " ".join(
        part
        for part in [
            str(row.get("firstname", "")).strip(),
            str(row.get("middlename", "")).strip(),
            str(row.get("lastname", "")).strip(),
        ]
        if part
    ).strip()
    candidate_name = entity_name or holder_name
    city_normalized = machine.normalize_filter_text(city)
    row_city = machine.normalize_filter_text(str(row.get("city", "")))
    status = str(row.get("licensestatusdescription", "")).strip().lower()

    score = machine._business_name_match_score(
        business_name,
        candidate_name,
        exact_score=90,
        prefix_score=64,
        contains_score=42,
    )
    if city_normalized and row_city == city_normalized:
        score += 10
    if "active" in status or "good standing" in status:
        score += 6
    return score


def pick_best_colorado_license(machine: Any, business_name: str, city: str, rows: list[dict]) -> tuple[Optional[dict], int]:
    scored: list[tuple[int, dict]] = []
    for row in rows:
        scored.append((machine.score_colorado_license_match(business_name, city, row), row))
    if not scored:
        return None, 0
    scored.sort(key=lambda item: item[0], reverse=True)
    best_score, best_row = scored[0]
    return best_row, best_score


def validate_colorado_license(machine: Any, lead: dict) -> dict:
    state_code = machine.state_code_from_area(lead.get("City/Area", ""))
    if state_code and state_code != "CO":
        return {
            "target": "",
            "status": "Not applicable",
            "confidence": "",
            "details": "",
            "verify_url": "",
        }

    target = machine.license_target_for_lead(lead)
    if not target:
        return {
            "target": "",
            "status": "Not applicable",
            "confidence": "",
            "details": "",
            "verify_url": "",
        }

    city = machine.city_from_area(lead.get("City/Area", ""))
    rows = machine.fetch_colorado_license_candidates(str(lead.get("Business Name", "")), city, target)
    best_match, best_score = machine.pick_best_colorado_license(str(lead.get("Business Name", "")), city, rows)

    if not best_match:
        return {
            "target": target,
            "status": "Manual review recommended",
            "confidence": "Low",
            "details": (
                f"{target} businesses often involve Colorado licensing, but no direct name match was found in the "
                "official license dataset"
            ),
            "verify_url": "",
        }

    entity_name = str(best_match.get("entityname", "")).strip()
    holder_name = " ".join(
        part
        for part in [
            str(best_match.get("firstname", "")).strip(),
            str(best_match.get("middlename", "")).strip(),
            str(best_match.get("lastname", "")).strip(),
        ]
        if part
    ).strip()
    display_name = entity_name or holder_name or "license holder"
    status = str(best_match.get("licensestatusdescription", "")).strip() or "Unknown"
    verify_url = str(best_match.get("linktoverifylicense", "")).strip() or str(
        best_match.get("linktoviewhealthcareprofile", "")
    ).strip()

    if best_score >= 60 and "active" in status.lower():
        return {
            "target": target,
            "status": "License verified",
            "confidence": "High",
            "details": f"Official Colorado {target.lower()} license match found for {display_name} ({status})",
            "verify_url": verify_url,
        }
    if best_score >= 35:
        return {
            "target": target,
            "status": "Likely licensed - review",
            "confidence": "Medium",
            "details": f"Possible Colorado {target.lower()} license match found for {display_name} ({status})",
            "verify_url": verify_url,
        }
    return {
        "target": target,
        "status": "Manual review recommended",
        "confidence": "Low",
        "details": (
            f"{target} appears relevant, but the best official license match was weak ({display_name}, {status})"
        ),
        "verify_url": verify_url,
    }


def california_contractor_license_target_for_lead(lead: dict) -> str:
    haystack = " ".join(
        [
            str(lead.get("Business Name", "")),
            str(lead.get("Business Type", "")),
            str(lead.get("Lead Rationale", "")),
            str(lead.get("Opportunity Brief", "")),
            str(lead.get("Thriving Signals", "")),
            str(lead.get("Revenue Note", "")),
        ]
    ).lower()
    return "CSLB contractor" if any(term in haystack for term in CALIFORNIA_CONTRACTOR_LICENSE_TERMS) else ""


def _extract_hidden_form_fields(html: str) -> dict[str, str]:
    soup = BeautifulSoup(html or "", "lxml")
    fields: dict[str, str] = {}
    for field in soup.find_all("input", {"type": "hidden"}):
        name = str(field.get("name", "")).strip()
        if name:
            fields[name] = str(field.get("value", "") or "")
    return fields


def _extract_cslb_license_rows(html: str) -> list[dict]:
    soup = BeautifulSoup(html or "", "lxml")
    rows: list[dict] = []
    for license_link in soup.find_all("a", id=re.compile(r"^MainContent_dlMain_hlLicense_\d+$")):
        link_id = str(license_link.get("id", ""))
        match = re.search(r"_(\d+)$", link_id)
        if not match:
            continue
        index = match.group(1)

        def field_text(name: str) -> str:
            field = soup.find(id=f"MainContent_dlMain_{name}_{index}")
            return field.get_text(" ", strip=True) if field else ""

        href = str(license_link.get("href", "") or "").strip()
        rows.append(
            {
                "business_name": field_text("lblName"),
                "name_type": field_text("lblType"),
                "license_number": license_link.get_text(" ", strip=True),
                "city": field_text("lblCity"),
                "license_status": field_text("lblLicenseStatus"),
                "detail_url": urljoin(CSLB_LICENSE_CHECK_BASE_URL, href) if href else CSLB_LICENSE_CHECK_URL,
            }
        )
    return rows


def fetch_california_contractor_license_candidates(machine: Any, name: str, city: str) -> list[dict]:
    normalized_name = machine.normalize_business_name(name)
    normalized_city = machine.normalize_filter_text(city)
    if not normalized_name:
        return []

    cache_key = f"cslb|{normalized_name}|{normalized_city}"
    with machine.co_record_cache_lock:
        cached = machine.co_record_cache.get(cache_key)
        if isinstance(cached, list):
            return cached

    tokens = machine.query_business_name_tokens(name)
    search_terms: list[str] = []
    for term in [normalized_name, " ".join(tokens[:4]) if tokens else "", " ".join(tokens[:2]) if len(tokens) > 2 else ""]:
        clean_term = term.strip()
        if clean_term and clean_term not in search_terms:
            search_terms.append(clean_term)

    rows: list[dict] = []
    for search_term in search_terms:
        if not search_term:
            continue
        try:
            initial = machine._request("get", CSLB_LICENSE_CHECK_URL, timeout=15)
            hidden_fields = _extract_hidden_form_fields(initial.text)
            payload = {
                **hidden_fields,
                "__EVENTTARGET": "",
                "__EVENTARGUMENT": "",
                "__LASTFOCUS": "",
                "ctl00$MainContent$NextName": search_term[:35],
                "ctl00$MainContent$Contractor_Business_Name_Button": " ",
            }
            response = machine._request(
                "post",
                CSLB_LICENSE_CHECK_URL,
                data=payload,
                timeout=20,
                headers={"Referer": CSLB_LICENSE_CHECK_URL},
            )
            if response.status_code == 200:
                rows = _extract_cslb_license_rows(response.text)
        except Exception:
            rows = []
        if rows:
            break

    with machine.co_record_cache_lock:
        machine.co_record_cache[cache_key] = rows
    return rows


def score_california_contractor_license_match(machine: Any, business_name: str, city: str, row: dict) -> int:
    candidate_name = str(row.get("business_name", ""))
    city_normalized = machine.normalize_filter_text(city)
    row_city = machine.normalize_filter_text(str(row.get("city", "")))
    status = str(row.get("license_status", "")).strip().lower()
    target_meaningful = machine.meaningful_business_name_tokens(business_name)
    candidate_meaningful = machine.meaningful_business_name_tokens(candidate_name)
    city_matches = bool(city_normalized and row_city == city_normalized)

    score = machine._business_name_match_score(
        business_name,
        candidate_name,
        exact_score=90,
        prefix_score=64,
        contains_score=42,
    )
    if city_matches:
        score += 10
    elif target_meaningful:
        missing_meaningful = target_meaningful - candidate_meaningful
        score -= len(missing_meaningful) * 20
    if "active" in status:
        score += 6
    elif any(marker in status for marker in ["expired", "inactive", "suspended", "revoked"]):
        score -= 4
    return max(score, 0)


def pick_best_california_contractor_license(machine: Any, business_name: str, city: str, rows: list[dict]) -> tuple[Optional[dict], int]:
    scored: list[tuple[int, dict]] = []
    for row in rows:
        scored.append((machine.score_california_contractor_license_match(business_name, city, row), row))
    if not scored:
        return None, 0
    scored.sort(key=lambda item: item[0], reverse=True)
    best_score, best_row = scored[0]
    return best_row, best_score


def validate_california_contractor_license(machine: Any, lead: dict) -> dict:
    state_code = machine.state_code_from_area(lead.get("City/Area", ""))
    if state_code and state_code != "CA":
        return {
            "target": "",
            "status": "Not applicable",
            "confidence": "",
            "details": "",
            "verify_url": "",
        }

    target = machine.california_contractor_license_target_for_lead(lead)
    if not target:
        return {
            "target": "",
            "status": "Not applicable",
            "confidence": "",
            "details": "",
            "verify_url": "",
        }

    city = machine.city_from_area(lead.get("City/Area", ""))
    rows = machine.fetch_california_contractor_license_candidates(str(lead.get("Business Name", "")), city)
    best_match, best_score = machine.pick_best_california_contractor_license(
        str(lead.get("Business Name", "")),
        city,
        rows,
    )

    if not best_match:
        return {
            "target": target,
            "status": "Manual review recommended",
            "confidence": "Low",
            "details": "California contractor category detected, but no direct CSLB business-name match was found",
            "verify_url": CSLB_LICENSE_CHECK_URL,
        }

    display_name = str(best_match.get("business_name", "")).strip() or "contractor"
    status = str(best_match.get("license_status", "")).strip() or "Unknown"
    license_number = str(best_match.get("license_number", "")).strip()
    verify_url = str(best_match.get("detail_url", "")).strip() or CSLB_LICENSE_CHECK_URL
    city_name = str(best_match.get("city", "")).strip()
    target_name = machine.normalize_business_name(str(lead.get("Business Name", "")))
    candidate_name = machine.normalize_business_name(display_name)
    lead_city = machine.normalize_filter_text(city)
    match_city = machine.normalize_filter_text(city_name)
    exact_name_match = bool(target_name and candidate_name == target_name)
    city_matches = bool(lead_city and match_city == lead_city)
    detail_bits = [display_name]
    if license_number:
        detail_bits.append(f"license {license_number}")
    if city_name:
        detail_bits.append(city_name)
    detail_text = ", ".join(detail_bits)

    if best_score >= 60 and "active" in status.lower() and (exact_name_match or city_matches):
        return {
            "target": target,
            "status": "License verified",
            "confidence": "High",
            "details": f"Official CSLB license match found for {detail_text} ({status})",
            "verify_url": verify_url,
        }
    if best_score >= 35:
        return {
            "target": target,
            "status": "Likely licensed - review",
            "confidence": "Medium",
            "details": f"Possible CSLB license match found for {detail_text} ({status})",
            "verify_url": verify_url,
        }
    return {
        "target": target,
        "status": "Manual review recommended",
        "confidence": "Low",
        "details": f"CSLB returned a weak possible match for {detail_text} ({status})",
        "verify_url": verify_url,
    }


def validate_business_license(machine: Any, lead: dict) -> dict:
    state_code = machine.state_code_from_area(lead.get("City/Area", ""))
    if state_code == "CA":
        return machine.validate_california_contractor_license(lead)
    if state_code == "CO" or not state_code:
        return machine.validate_colorado_license(lead)
    return {
        "target": "",
        "status": "Not applicable",
        "confidence": "",
        "details": "",
        "verify_url": "",
    }


def fetch_colorado_transaction_history(machine: Any, entity_id: str) -> list[dict]:
    if not entity_id:
        return []
    params = {
        "$select": "historydes,comment,receiveddate,effectivedate,name",
        "$where": f"entityid = {machine.soql_string_literal(entity_id)}",
        "$order": "effectivedate DESC",
        "$limit": 8,
    }
    try:
        response = machine._request("get", COLORADO_TRANSACTION_HISTORY_API, params=params, timeout=10)
        rows = response.json() if response.status_code == 200 else []
        return rows if isinstance(rows, list) else []
    except Exception:
        return []


def categorize_colorado_status(status: str, history_rows: list[dict]) -> tuple[str, str]:
    lowered = status.lower().strip()
    history_text = " ".join(str(row.get("historydes", "")) for row in history_rows).lower()

    likely_closed_markers = [
        "dissolved",
        "withdrawn",
        "terminated",
        "revoked",
        "merged",
        "canceled",
        "cancelled",
    ]
    compliance_markers = ["delinquent", "noncompliant", "non-compliant", "expired"]

    if any(marker in lowered for marker in likely_closed_markers) or any(marker in history_text for marker in likely_closed_markers):
        return "Likely closed", "Official status/history indicates dissolution, withdrawal, termination, or revocation"
    if "good standing" in lowered:
        return "Active", "Official Colorado record is in good standing"
    if any(marker in lowered for marker in compliance_markers):
        return "Compliance issue", "Official record shows delinquent/noncompliant/expired status, which is not the same as confirmed closure"
    return "Review", "Official Colorado record found, but status needs review"


def summarize_colorado_history(history_rows: list[dict]) -> tuple[str, str]:
    if not history_rows:
        return "", ""
    latest = history_rows[0]
    latest_label = str(latest.get("historydes", "")).strip()
    latest_date = str(latest.get("effectivedate", "") or latest.get("receiveddate", "")).strip()
    latest_summary = f"{latest_label} ({latest_date[:10]})" if latest_label and latest_date else latest_label

    summary_parts: list[str] = []
    for row in history_rows[:3]:
        label = str(row.get("historydes", "")).strip()
        date_value = str(row.get("effectivedate", "") or row.get("receiveddate", "")).strip()
        if label and date_value:
            summary_parts.append(f"{label} ({date_value[:10]})")
        elif label:
            summary_parts.append(label)
    return latest_summary, "; ".join(summary_parts)


def lookup_colorado_business_record(machine: Any, name: str, city: str) -> dict:
    normalized_name = machine.normalize_business_name(name)
    normalized_city = machine.normalize_filter_text(city)
    if not normalized_name and not normalized_city:
        return {}

    cache_key = f"{normalized_name}|{normalized_city}"
    with machine.co_record_cache_lock:
        if cache_key in machine.co_record_cache:
            return machine.co_record_cache[cache_key]

    result = {
        "match_found": False,
        "match_score": 0,
        "match_type": "No official Colorado match",
        "match_confidence": "",
        "formation_date": "",
        "age_days": "",
        "entity_id": "",
        "status": "",
        "status_category": "",
        "status_note": "",
        "latest_transaction": "",
        "history_summary": "",
        "detail_url": "",
    }

    entity_rows = machine.fetch_colorado_entity_candidates(name, city)
    best_match, best_score = machine.pick_best_colorado_entity(name, city, entity_rows)
    if not best_match:
        if entity_rows:
            fallback_row = max(
                entity_rows,
                key=lambda row: machine.score_colorado_entity_match(name, city, row),
            )
            fallback_score = machine.score_colorado_entity_match(name, city, fallback_row)
            match_type, match_confidence = machine.colorado_match_assessment(name, fallback_row, fallback_score)
            if match_type == "Possible DBA or trade-name mismatch":
                result["match_type"] = match_type
                result["match_confidence"] = match_confidence
                result["match_score"] = fallback_score
                result["status_note"] = (
                    "Official Colorado entity search found a partial name match that may reflect a DBA or trade-name mismatch"
                )
        with machine.co_record_cache_lock:
            machine.co_record_cache[cache_key] = result
        return result

    entity_id = str(best_match.get("entityid", "")).strip()
    formation_date = machine.parse_formation_date(str(best_match.get("entityformdate", "")))
    age_days = (datetime.now() - formation_date).days if formation_date else ""
    status = str(best_match.get("entitystatus", "")).strip()
    history_rows = machine.fetch_colorado_transaction_history(entity_id)
    status_category, status_note = machine.categorize_colorado_status(status, history_rows)
    latest_transaction, history_summary = machine.summarize_colorado_history(history_rows)
    match_type, match_confidence = machine.colorado_match_assessment(name, best_match, best_score)

    result = {
        "match_found": bool(formation_date or entity_id),
        "match_score": best_score,
        "match_type": match_type,
        "match_confidence": match_confidence,
        "formation_date": formation_date.strftime("%Y-%m-%d") if formation_date else "",
        "age_days": age_days,
        "entity_id": entity_id,
        "status": status,
        "status_category": status_category,
        "status_note": status_note,
        "latest_transaction": latest_transaction,
        "history_summary": history_summary,
        "detail_url": "",
    }
    with machine.co_record_cache_lock:
        machine.co_record_cache[cache_key] = result
    return result


def california_match_assessment(machine: Any, business_name: str, row: dict, score: int) -> tuple[str, str]:
    target_name = machine.normalize_business_name(business_name)
    candidate_name = machine.normalize_business_name(str(row.get("EntityName", "")))
    if target_name and candidate_name == target_name:
        return "Exact legal-name match", "High"
    if score >= 80:
        return "Strong business-name match", "High"
    if score >= 50:
        return "Moderate business-name match", "Medium"
    if score >= 30:
        return "Possible DBA or trade-name mismatch", "Low"
    return "No reliable California match", "Low"


def _extract_california_entity_rows(payload: object) -> list[dict]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    rows = payload.get("EntityData") or payload.get("entityData") or payload.get("records") or []
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def fetch_california_entity_candidates(machine: Any, name: str, city: str) -> list[dict]:
    key = str(getattr(machine.config, "california_sos_api_key", "") or "").strip()
    if not key:
        return []

    tokens = machine.query_business_name_tokens(name)
    if not tokens:
        return []

    search_terms = [" ".join(tokens[:4])]
    if len(tokens) > 2:
        search_terms.append(" ".join(tokens[:2]))

    rows: list[dict] = []
    seen_ids: set[str] = set()
    headers = {"Ocp-Apim-Subscription-Key": key}
    for search_term in search_terms:
        if not search_term:
            continue
        params = {"search-term": search_term}
        try:
            response = machine._request(
                "get",
                CALIFORNIA_BUSINESS_KEYWORD_API,
                params=params,
                headers=headers,
                timeout=15,
            )
            payload = response.json() if response.status_code == 200 else {}
        except Exception:
            payload = {}

        for row in _extract_california_entity_rows(payload):
            entity_id = str(row.get("EntityID", "") or row.get("entityId", "")).strip()
            dedupe_key = entity_id or str(row.get("EntityName", "")).strip().lower()
            if not dedupe_key or dedupe_key in seen_ids:
                continue
            seen_ids.add(dedupe_key)
            rows.append(row)
        if rows:
            break
    return rows


def score_california_entity_match(machine: Any, business_name: str, city: str, row: dict) -> int:
    candidate_name = str(row.get("EntityName", ""))
    city_normalized = machine.normalize_filter_text(city)
    candidate_cities = [
        machine.normalize_filter_text(str(row.get(field, "")))
        for field in ["EntityCity", "MailingCity", "AgentCity"]
    ]
    status = str(row.get("StatusDescription", "")).strip().lower()

    score = machine._business_name_match_score(
        business_name,
        candidate_name,
        exact_score=100,
        prefix_score=70,
        contains_score=50,
    )
    if city_normalized and city_normalized in candidate_cities:
        score += 10
    if "active" in status:
        score += 4
    return score


def pick_best_california_entity(machine: Any, business_name: str, city: str, rows: list[dict]) -> tuple[Optional[dict], int]:
    scored: list[tuple[int, dict]] = []
    for row in rows:
        scored.append((machine.score_california_entity_match(business_name, city, row), row))
    if not scored:
        return None, 0
    scored.sort(key=lambda item: item[0], reverse=True)
    best_score, best_row = scored[0]
    if best_score < 35:
        return None, best_score
    return best_row, best_score


def categorize_california_status(status: str) -> tuple[str, str]:
    lowered = status.lower().strip()
    likely_closed_markers = [
        "dissolved",
        "canceled",
        "cancelled",
        "terminated",
        "forfeited",
        "surrendered",
        "merged",
    ]
    compliance_markers = ["suspended", "delinquent", "ftb", "inactive"]

    if any(marker in lowered for marker in likely_closed_markers):
        return "Likely closed", "Official California record indicates dissolution, cancellation, forfeiture, or surrender"
    if "active" in lowered:
        return "Active", "Official California Secretary of State record is active"
    if any(marker in lowered for marker in compliance_markers):
        return "Compliance issue", "Official California record shows suspension, tax issue, or inactive status"
    return "Review", "Official California record found, but status needs review"


def lookup_california_business_record(machine: Any, name: str, city: str) -> dict:
    normalized_name = machine.normalize_business_name(name)
    normalized_city = machine.normalize_filter_text(city)
    if not normalized_name and not normalized_city:
        return {}

    cache_key = f"ca|{normalized_name}|{normalized_city}"
    with machine.co_record_cache_lock:
        if cache_key in machine.co_record_cache:
            return machine.co_record_cache[cache_key]

    result = {
        "record_state": "CA",
        "source": "California Secretary of State",
        "match_found": False,
        "match_score": 0,
        "match_type": "No official California match",
        "match_confidence": "",
        "formation_date": "",
        "age_days": "",
        "entity_id": "",
        "status": "",
        "status_category": "",
        "status_note": "",
        "latest_transaction": "",
        "history_summary": "",
        "detail_url": CALIFORNIA_BIZFILE_SEARCH_URL,
    }

    key = str(getattr(machine.config, "california_sos_api_key", "") or "").strip()
    if not key:
        result["match_type"] = "California records not configured"
        result["status_note"] = "California official record lookup requires a California SOS CALICO API subscription key"
        with machine.co_record_cache_lock:
            machine.co_record_cache[cache_key] = result
        return result

    entity_rows = machine.fetch_california_entity_candidates(name, city)
    best_match, best_score = machine.pick_best_california_entity(name, city, entity_rows)
    if not best_match:
        if entity_rows:
            fallback_row = max(
                entity_rows,
                key=lambda row: machine.score_california_entity_match(name, city, row),
            )
            fallback_score = machine.score_california_entity_match(name, city, fallback_row)
            match_type, match_confidence = machine.california_match_assessment(name, fallback_row, fallback_score)
            if match_type == "Possible DBA or trade-name mismatch":
                result["match_type"] = match_type
                result["match_confidence"] = match_confidence
                result["match_score"] = fallback_score
                result["status_note"] = (
                    "Official California entity search found a partial name match that may reflect a DBA or trade-name mismatch"
                )
        with machine.co_record_cache_lock:
            machine.co_record_cache[cache_key] = result
        return result

    entity_id = str(best_match.get("EntityID", "")).strip()
    formation_date = machine.parse_formation_date(str(best_match.get("FilingDate", "")))
    age_days = (datetime.now() - formation_date).days if formation_date else ""
    status = str(best_match.get("StatusDescription", "")).strip()
    status_category, status_note = machine.categorize_california_status(status)
    latest_transaction = f"Initial filing ({formation_date.strftime('%Y-%m-%d')})" if formation_date else ""
    match_type, match_confidence = machine.california_match_assessment(name, best_match, best_score)

    result = {
        "record_state": "CA",
        "source": "California Secretary of State",
        "match_found": bool(formation_date or entity_id),
        "match_score": best_score,
        "match_type": match_type,
        "match_confidence": match_confidence,
        "formation_date": formation_date.strftime("%Y-%m-%d") if formation_date else "",
        "age_days": age_days,
        "entity_id": entity_id,
        "status": status,
        "status_category": status_category,
        "status_note": status_note,
        "latest_transaction": latest_transaction,
        "history_summary": latest_transaction,
        "detail_url": CALIFORNIA_BIZFILE_SEARCH_URL,
    }
    with machine.co_record_cache_lock:
        machine.co_record_cache[cache_key] = result
    return result


def apply_official_record_to_lead(machine: Any, lead: dict, record: dict, state_code: str) -> None:
    state_name = machine.state_name_for_code(state_code) or state_code
    source = record.get("source", f"{state_name} Secretary of State" if state_name else "")
    lead["Official Record Source"] = source
    lead["Official Record State"] = state_code
    lead["Official Match Type"] = record.get("match_type", "")
    lead["Official Match Confidence"] = record.get("match_confidence", "")
    lead["Formation Date"] = record.get("formation_date", "")
    lead["Business Age Days"] = record.get("age_days", "")
    lead["Official Record Status"] = record.get("status", "")
    lead["Official Status Category"] = record.get("status_category", "")
    lead["Official Status Note"] = record.get("status_note", "")
    lead["Official Latest Filing"] = record.get("latest_transaction", "")
    lead["Official History Summary"] = record.get("history_summary", "")
    lead["Official Entity ID"] = record.get("entity_id", "")
    lead["Official Detail URL"] = record.get("detail_url", "")

    if state_code == "CO":
        lead["Colorado Match Type"] = record.get("match_type", "")
        lead["Colorado Match Confidence"] = record.get("match_confidence", "")
        lead["Colorado Record Status"] = record.get("status", "")
        lead["Colorado Status Category"] = record.get("status_category", "")
        lead["Colorado Status Note"] = record.get("status_note", "")
        lead["Colorado Latest Filing"] = record.get("latest_transaction", "")
        lead["Colorado History Summary"] = record.get("history_summary", "")
        lead["Colorado Entity ID"] = record.get("entity_id", "")


def enrich_with_colorado_records(machine: Any, leads: list[dict]) -> list[dict]:
    machine.log("Stage 4/5: Enrich with official business records")
    targeted_recheck = machine.is_targeted_recheck()
    kept: list[dict] = []
    recent_business_skipped = 0
    matched_records = 0
    likely_closed_skipped = 0
    recent_business_retained = 0
    likely_closed_retained = 0
    record_queue: list[tuple[dict, str, str]] = []
    checked_by_state = {"CO": 0, "CA": 0}
    unsupported_state_leads = 0

    for lead in leads:
        machine._check_stop()
        city_area = str(lead.get("City/Area", "")).strip()
        state_code = machine.state_code_from_area(city_area)
        if state_code not in {"CO", "CA"}:
            unsupported_state_leads += 1
            kept.append(lead)
            continue
        city_name = machine.city_from_area(city_area)
        checked_by_state[state_code] += 1
        record_queue.append((lead, city_name, state_code))

    total_record_leads = len(record_queue)
    if total_record_leads:
        workers = max(1, min(machine.config.record_lookup_workers, total_record_leads))
        state_summary = ", ".join(
            f"{count} {state}" for state, count in checked_by_state.items() if count
        )
        machine.log(f"Stage 4 will check {total_record_leads} official records ({state_summary}) using {workers} worker(s)")

        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_map = {}
            for lead, city_name, state_code in record_queue:
                lookup = (
                    machine.lookup_colorado_business_record
                    if state_code == "CO"
                    else machine.lookup_california_business_record
                )
                future = executor.submit(lookup, lead["Business Name"], city_name)
                future_map[future] = (lead, city_name, state_code)

            completed = 0
            for future in as_completed(future_map):
                machine._check_stop()
                completed += 1
                lead, _city_name, state_code = future_map[future]
                state_name = machine.state_name_for_code(state_code) or state_code
                try:
                    record = future.result()
                except Exception:
                    record = {}

                if completed == 1 or completed % 25 == 0 or completed == total_record_leads:
                    machine.log(
                        f"Stage 4 progress: {completed}/{total_record_leads} | matched records: {matched_records} | "
                        f"recent skipped: {recent_business_skipped}"
                    )

                if record.get("match_found"):
                    matched_records += 1

                machine.apply_official_record_to_lead(lead, record, state_code)

                if record.get("status_category") == "Likely closed":
                    if targeted_recheck:
                        likely_closed_retained += 1
                        machine.log(
                            f"Retained likely closed business for targeted recheck: {lead['Business Name']} | "
                            f"{record.get('status') or record.get('latest_transaction') or state_name + ' official record'}"
                        )
                    else:
                        likely_closed_skipped += 1
                        machine.log(
                            f"Skipped likely closed business: {lead['Business Name']} | "
                            f"{record.get('status') or record.get('latest_transaction') or state_name + ' official record'}"
                        )
                        continue

                age_days = record.get("age_days")
                if isinstance(age_days, int) and age_days < machine.config.min_business_age_days:
                    if targeted_recheck:
                        recent_business_retained += 1
                        machine.log(
                            f"Retained recent business for targeted recheck: {lead['Business Name']} | formed {record.get('formation_date', 'unknown')}"
                        )
                    else:
                        recent_business_skipped += 1
                        machine.log(
                            f"Skipped recent business: {lead['Business Name']} | formed {record.get('formation_date', 'unknown')}"
                        )
                        continue

                kept.append(lead)

    machine.log(
        f"Records stage complete. Kept: {len(kept)} | Matched records: {matched_records} | "
        f"Recent businesses skipped: {recent_business_skipped} | Likely closed skipped: {likely_closed_skipped}"
        + (
            f" | Checked CO: {checked_by_state['CO']} | Checked CA: {checked_by_state['CA']}"
            if total_record_leads
            else ""
        )
        + (
            f" | Recent retained for recheck: {recent_business_retained} | Likely closed retained for recheck: {likely_closed_retained}"
            if targeted_recheck and (recent_business_retained or likely_closed_retained)
            else ""
        )
    )
    machine.record_stage_report(
        "records",
        "Enrich with official business records",
        kept=len(kept),
        checked_official_record_leads=total_record_leads,
        checked_colorado_leads=checked_by_state["CO"],
        checked_california_leads=checked_by_state["CA"],
        unsupported_state_leads=unsupported_state_leads,
        record_lookup_workers=max(1, min(machine.config.record_lookup_workers, total_record_leads)) if total_record_leads else 0,
        matched_records=matched_records,
        recent_businesses_skipped=recent_business_skipped,
        likely_closed_skipped=likely_closed_skipped,
        recent_businesses_retained_for_recheck=recent_business_retained,
        likely_closed_retained_for_recheck=likely_closed_retained,
    )
    return kept
