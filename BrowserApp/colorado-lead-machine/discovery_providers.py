from __future__ import annotations

"""Optional external discovery and enrichment providers."""

import re
import socket
import ssl
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional
from urllib.parse import urlparse

if TYPE_CHECKING:
    from lead_machine import LeadMachine


DATAFORSEO_ENGINES = ("google", "bing")
YELP_BASE = "https://api.yelp.com/v3"
RDAP_BASE = "https://rdap.org/domain"

_OWNED_URL_BLOCKED_DOMAINS = {
    "google.com",
    "goo.gl",
    "yelp.com",
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "twitter.com",
    "x.com",
    "youtube.com",
    "youtu.be",
    "tripadvisor.com",
    "yellowpages.com",
    "bbb.org",
    "mapquest.com",
    "apple.com",
    "apps.apple.com",
    "play.google.com",
    "duckduckgo.com",
}

_BUSINESS_TOKEN_STOPWORDS = {
    "the",
    "and",
    "for",
    "llc",
    "inc",
    "co",
    "company",
    "services",
    "service",
    "colorado",
    "california",
}

_ADDRESS_REPLACEMENTS = {
    " street ": " st ",
    " avenue ": " ave ",
    " road ": " rd ",
    " boulevard ": " blvd ",
    " drive ": " dr ",
    " lane ": " ln ",
    " court ": " ct ",
    " suite ": " ste ",
}


def normalize_phone(value: object) -> str:
    digits = re.sub(r"\D+", "", str(value or ""))
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    if len(digits) == 10:
        return f"+1{digits}"
    return digits


def normalize_address(value: object) -> str:
    normalized = f" {re.sub(r'[^a-z0-9]+', ' ', str(value or '').lower()).strip()} "
    for old, new in _ADDRESS_REPLACEMENTS.items():
        normalized = normalized.replace(old, new)
    return re.sub(r"\s+", " ", normalized).strip()


def _city_from_lead(machine: "LeadMachine", lead: dict) -> str:
    return machine.city_from_area(lead.get("City/Area", ""))


def _state_code_from_lead(machine: "LeadMachine", lead: dict) -> str:
    return machine.state_code_from_area(lead.get("City/Area", ""))


def _business_tokens(machine: "LeadMachine", name: str) -> list[str]:
    tokens = machine.normalize_filter_text(name).split()
    return [token for token in tokens if len(token) >= 4 and token not in _BUSINESS_TOKEN_STOPWORDS]


def identity_match_score(
    machine: "LeadMachine",
    lead: dict,
    candidate_name: str,
    candidate_address: str = "",
    candidate_phone: str = "",
) -> int:
    score = machine._business_name_match_score(
        str(lead.get("Business Name", "")),
        candidate_name,
        exact_score=72,
        prefix_score=58,
        contains_score=45,
    )
    lead_phone = normalize_phone(lead.get("Phone", ""))
    candidate_phone_normalized = normalize_phone(candidate_phone)
    if lead_phone and candidate_phone_normalized:
        score += 22 if lead_phone == candidate_phone_normalized else -10

    lead_address = normalize_address(lead.get("Address", ""))
    candidate_address_normalized = normalize_address(candidate_address)
    if lead_address and candidate_address_normalized:
        lead_tokens = [token for token in lead_address.split() if len(token) >= 4 or token.isdigit()]
        overlap = sum(1 for token in lead_tokens[:6] if token in candidate_address_normalized.split())
        score += min(overlap * 5, 22)

    city = machine.normalize_filter_text(_city_from_lead(machine, lead))
    if city and city in machine.normalize_filter_text(candidate_address):
        score += 8

    return max(0, min(score, 100))


def _domain_from_url(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    if not parsed.scheme:
        parsed = urlparse(f"https://{str(url or '').strip()}")
    return (parsed.hostname or "").lower().removeprefix("www.")


def _is_blocked_owned_domain(domain: str) -> bool:
    return any(domain == blocked or domain.endswith(f".{blocked}") for blocked in _OWNED_URL_BLOCKED_DOMAINS)


def owned_url_confidence(
    machine: "LeadMachine",
    business_name: str,
    url: str,
    *,
    title: str = "",
    snippet: str = "",
) -> int:
    domain = _domain_from_url(url)
    if not domain or _is_blocked_owned_domain(domain):
        return 0
    if machine.is_social_url(url) or machine.check_directory(url) or machine.is_marketplace_url(url):
        return 0
    if machine.is_link_hub_url(url):
        return 0

    normalized_domain = machine.normalize_filter_text(domain.replace(".", " "))
    context = machine.normalize_filter_text(f"{title} {snippet}")
    tokens = _business_tokens(machine, business_name)
    if not tokens:
        return 35

    domain_hits = sum(1 for token in tokens if token in normalized_domain)
    context_hits = sum(1 for token in tokens if token in context)
    if domain_hits >= 2:
        return 85
    if domain_hits == 1 and context_hits >= 1:
        return 78
    if context_hits >= 2:
        return 68
    if domain_hits == 1:
        return 58
    if context_hits == 1:
        return 48
    return 35


def _attempt(
    *,
    provider: str,
    query: str,
    endpoint: str,
    ok: bool,
    status_code: int = 0,
    error_type: str = "",
    error_message: str = "",
    raw_result_count: int = 0,
    result_urls: list[str] | None = None,
    retry_recommended: bool = False,
) -> dict[str, object]:
    return {
        "provider": provider,
        "query": query,
        "url": endpoint,
        "final_url": endpoint,
        "ok": ok,
        "status_code": int(status_code or 0),
        "error_type": error_type,
        "error_message": error_message,
        "blocked": status_code in {401, 403, 429},
        "timeout": error_type == "timeout",
        "body_length": 0,
        "raw_result_count": int(raw_result_count or 0),
        "retry_recommended": retry_recommended,
        "attempted_urls": [endpoint],
        "http_statuses": [int(status_code)] if status_code else [],
        "result_urls": list(result_urls or [])[:12],
    }


def _flatten_serp_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        flattened.append(item)
        nested = item.get("items")
        if isinstance(nested, list):
            flattened.extend(_flatten_serp_items(nested))
    return flattened


def _extract_dataforseo_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for task in payload.get("tasks", []) if isinstance(payload, dict) else []:
        for result in task.get("result", []) if isinstance(task, dict) else []:
            result_items = result.get("items", []) if isinstance(result, dict) else []
            if isinstance(result_items, list):
                items.extend(_flatten_serp_items(result_items))
    return items


def dataforseo_serp_discovery(machine: "LeadMachine", business_name: str, city: str, limit: int = 12) -> dict[str, object]:
    login = str(getattr(machine.config, "dataforseo_login", "") or "").strip()
    password = str(getattr(machine.config, "dataforseo_password", "") or "").strip()
    if not login or not password:
        return {"enabled": False, "owned_urls": [], "attempts": [], "no_website_evidence": [], "provider_evidence": []}

    query_location = machine.search_context_from_area(city)
    query = f'"{business_name}" "{query_location}" official website'
    owned_urls: list[str] = []
    attempts: list[dict[str, object]] = []
    provider_evidence: list[str] = []
    no_website_evidence: list[str] = []
    result_count = 0
    failures: list[str] = []

    location_name = machine.dataforseo_location_name(city)
    for engine in DATAFORSEO_ENGINES:
        endpoint = f"https://api.dataforseo.com/v3/serp/{engine}/organic/live/advanced"
        provider = f"DataForSEO {engine.title()} Organic"
        try:
            response = machine._request(
                "post",
                endpoint,
                auth=(login, password),
                json=[
                    {
                        "keyword": query,
                        "location_name": location_name,
                        "language_code": "en",
                        "device": "desktop",
                        "depth": 20,
                    }
                ],
                timeout=35,
            )
            status_code = int(response.status_code or 0)
            payload = response.json() if status_code == 200 else {}
            items = _extract_dataforseo_items(payload)
            result_urls: list[str] = []
            for item in items[:limit]:
                url = str(item.get("url") or item.get("link") or "").strip()
                if not url and item.get("domain"):
                    url = f"https://{item.get('domain')}"
                if not url:
                    continue
                result_urls.append(url)
                confidence = owned_url_confidence(
                    machine,
                    business_name,
                    url,
                    title=str(item.get("title", "")),
                    snippet=str(item.get("description") or item.get("snippet") or ""),
                )
                if confidence >= 55 and url not in owned_urls:
                    owned_urls.append(url)
                    provider_evidence.append(f"{provider} found likely owned domain ({confidence}/100): {machine.normalize_domain(url)}")
            result_count += len(items)
            if status_code != 200:
                error_message = str(getattr(response, "text", ""))[:180] or f"HTTP {status_code}"
                failures.append(f"{provider}: {error_message}")
                attempts.append(
                    _attempt(
                        provider=provider,
                        query=query,
                        endpoint=endpoint,
                        ok=False,
                        status_code=status_code,
                        error_type="http_status",
                        error_message=error_message,
                        retry_recommended=status_code in {408, 429, 500, 502, 503, 504},
                    )
                )
            else:
                attempts.append(
                    _attempt(
                        provider=provider,
                        query=query,
                        endpoint=endpoint,
                        ok=True,
                        status_code=status_code,
                        raw_result_count=len(items),
                        result_urls=result_urls,
                    )
                )
        except Exception as exc:
            error_text = str(exc)[:180]
            failures.append(f"{provider}: {error_text}")
            attempts.append(
                _attempt(
                    provider=provider,
                    query=query,
                    endpoint=endpoint,
                    ok=False,
                    error_type=type(exc).__name__ or "provider_error",
                    error_message=error_text,
                    retry_recommended=True,
                )
            )

    if not owned_urls and any(attempt.get("ok") for attempt in attempts):
        no_website_evidence.append("DataForSEO SERP search found no likely owned domain")

    return {
        "enabled": True,
        "owned_urls": owned_urls,
        "attempts": attempts,
        "no_website_evidence": no_website_evidence,
        "provider_evidence": provider_evidence,
        "result_count": result_count,
        "failures": failures,
        "retry_recommended": any(bool(attempt.get("retry_recommended")) for attempt in attempts),
        "retry_reason": "; ".join(failures[:3]),
        "queries": [query],
    }


def _yelp_headers(machine: "LeadMachine") -> dict[str, str]:
    return {"Authorization": f"Bearer {str(getattr(machine.config, 'yelp_api_key', '')).strip()}"}


def _compact_yelp_address(location: dict[str, Any]) -> str:
    if not isinstance(location, dict):
        return ""
    display = location.get("display_address")
    if isinstance(display, list) and display:
        return ", ".join(str(part) for part in display if part)
    parts = [location.get("address1"), location.get("city"), location.get("state"), location.get("zip_code")]
    return ", ".join(str(part) for part in parts if part)


def _yelp_candidate_address(candidate: dict[str, Any]) -> str:
    return _compact_yelp_address(candidate.get("location", {}) if isinstance(candidate.get("location"), dict) else {})


def _yelp_search_candidates(machine: "LeadMachine", lead: dict) -> tuple[list[dict[str, Any]], str, int, str]:
    key = str(getattr(machine.config, "yelp_api_key", "") or "").strip()
    if not key:
        return [], "disabled", 0, ""

    name = str(lead.get("Business Name", "")).strip()
    city = _city_from_lead(machine, lead)
    state_code = _state_code_from_lead(machine, lead) or "CO"
    address = str(lead.get("Address", "")).split(",", 1)[0].strip()
    phone = normalize_phone(lead.get("Phone", ""))

    endpoint = f"{YELP_BASE}/businesses/matches"
    if name and address and city:
        params: dict[str, object] = {
            "name": name,
            "address1": address,
            "city": city,
            "state": state_code,
            "country": "US",
            "limit": 3,
            "match_threshold": "default",
        }
        if phone:
            params["phone"] = phone
    else:
        endpoint = f"{YELP_BASE}/businesses/search"
        params = {
            "term": name,
            "location": str(lead.get("Address") or lead.get("City/Area") or "United States"),
            "limit": 3,
        }

    response = machine._request("get", endpoint, headers=_yelp_headers(machine), params=params, timeout=15)
    status_code = int(response.status_code or 0)
    if status_code != 200:
        return [], endpoint, status_code, str(getattr(response, "text", ""))[:180]
    payload = response.json()
    businesses = payload.get("businesses", []) if isinstance(payload, dict) else []
    return [item for item in businesses if isinstance(item, dict)], endpoint, status_code, ""


def yelp_enrich_lead(machine: "LeadMachine", lead: dict) -> dict[str, object]:
    if not str(getattr(machine.config, "yelp_api_key", "") or "").strip():
        return {"Yelp Match Status": "Disabled"}

    try:
        candidates, endpoint, status_code, error_message = _yelp_search_candidates(machine, lead)
    except Exception as exc:
        return {
            "Yelp Match Status": "Error",
            "Yelp Failure Reason": str(exc)[:180],
            "Retry Recommended": "Yes",
            "Retry Reason": f"Yelp error: {str(exc)[:120]}",
        }

    if error_message:
        retry = status_code in {408, 429, 500, 502, 503, 504}
        return {
            "Yelp Match Status": "Error",
            "Yelp Failure Reason": error_message,
            "Yelp Source Endpoint": endpoint,
            "Retry Recommended": "Yes" if retry else str(lead.get("Retry Recommended", "")),
            "Retry Reason": f"Yelp HTTP {status_code}" if retry else str(lead.get("Retry Reason", "")),
        }
    if not candidates:
        return {"Yelp Match Status": "No match", "Yelp Source Endpoint": endpoint}

    best = max(
        candidates,
        key=lambda candidate: identity_match_score(
            machine,
            lead,
            str(candidate.get("name", "")),
            _yelp_candidate_address(candidate),
            str(candidate.get("phone") or candidate.get("display_phone") or ""),
        ),
    )
    score = identity_match_score(
        machine,
        lead,
        str(best.get("name", "")),
        _yelp_candidate_address(best),
        str(best.get("phone") or best.get("display_phone") or ""),
    )
    if score < 55:
        return {
            "Yelp Match Status": "Mismatch",
            "Yelp Match Confidence": score,
            "Yelp Failure Reason": f"Best Yelp candidate scored {score}/100",
            "Yelp Source Endpoint": endpoint,
        }

    business_id = str(best.get("id", "")).strip()
    details: dict[str, Any] = dict(best)
    reviews: list[dict[str, Any]] = []
    if business_id:
        try:
            detail_response = machine._request(
                "get",
                f"{YELP_BASE}/businesses/{business_id}",
                headers=_yelp_headers(machine),
                timeout=15,
            )
            if detail_response.status_code == 200:
                detail_payload = detail_response.json()
                if isinstance(detail_payload, dict):
                    details.update(detail_payload)
        except Exception:
            pass
        try:
            review_response = machine._request(
                "get",
                f"{YELP_BASE}/businesses/{business_id}/reviews",
                headers=_yelp_headers(machine),
                timeout=15,
            )
            if review_response.status_code == 200:
                review_payload = review_response.json()
                payload_reviews = review_payload.get("reviews", []) if isinstance(review_payload, dict) else []
                reviews = [review for review in payload_reviews if isinstance(review, dict)]
        except Exception:
            pass

    categories = details.get("categories", []) if isinstance(details.get("categories"), list) else []
    category_titles = [str(category.get("title", "")) for category in categories if isinstance(category, dict) and category.get("title")]
    photos = details.get("photos", []) if isinstance(details.get("photos"), list) else []
    hours_payload = details.get("hours", []) if isinstance(details.get("hours"), list) else []
    hours_summary = ""
    if hours_payload and isinstance(hours_payload[0], dict):
        open_items = hours_payload[0].get("open", [])
        if isinstance(open_items, list):
            hours_summary = "; ".join(
                f"day {item.get('day')}: {item.get('start')}-{item.get('end')}"
                for item in open_items[:7]
                if isinstance(item, dict)
            )

    return {
        "Yelp Match Status": "Matched",
        "Yelp Match Confidence": score,
        "Yelp Business ID": business_id,
        "Yelp URL": str(details.get("url", "")),
        "Yelp Rating": details.get("rating", ""),
        "Yelp Review Count": details.get("review_count", ""),
        "Yelp Price": str(details.get("price", "")),
        "Yelp Categories": ", ".join(category_titles[:5]),
        "Yelp Phone": str(details.get("display_phone") or details.get("phone") or ""),
        "Yelp Address": _yelp_candidate_address(details),
        "Yelp Hours": hours_summary,
        "Yelp Photo Count": len(photos),
        "Yelp Photos": ", ".join(str(photo) for photo in photos[:3]),
        "Yelp Review Snippets": " || ".join(str(review.get("text", "")).strip()[:220] for review in reviews[:3] if review.get("text")),
        "Yelp Source Endpoint": endpoint,
    }


def _ssl_certificate_info(domain: str) -> tuple[str, str]:
    try:
        context = ssl.create_default_context()
        with socket.create_connection((domain, 443), timeout=4) as sock:
            with context.wrap_socket(sock, server_hostname=domain) as wrapped:
                cert = wrapped.getpeercert() or {}
        not_after = str(cert.get("notAfter", ""))
        return "Yes", not_after
    except Exception:
        return "No", ""


def _rdap_age_days(machine: "LeadMachine", domain: str) -> tuple[str, str]:
    if not getattr(machine.config, "enable_rdap_checks", False):
        return "", ""
    try:
        response = machine._request("get", f"{RDAP_BASE}/{domain}", timeout=8)
        if response.status_code != 200:
            return "", f"RDAP HTTP {response.status_code}"
        payload = response.json()
        events = payload.get("events", []) if isinstance(payload, dict) else []
        registration_dates: list[datetime] = []
        for event in events:
            if not isinstance(event, dict):
                continue
            action = str(event.get("eventAction", "")).lower()
            if action not in {"registration", "domain registration"}:
                continue
            raw_date = str(event.get("eventDate", "")).strip()
            if not raw_date:
                continue
            try:
                parsed = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
            except ValueError:
                continue
            registration_dates.append(parsed)
        if not registration_dates:
            return "", ""
        oldest = min(registration_dates)
        age = datetime.now(timezone.utc) - oldest.astimezone(timezone.utc)
        return str(max(age.days, 0)), ""
    except Exception as exc:
        return "", str(exc)[:120]


def verify_domain(machine: "LeadMachine", url: str) -> dict[str, object]:
    if not getattr(machine.config, "enable_domain_checks", True):
        return {}
    domain = _domain_from_url(url)
    if not domain:
        return {"Domain Verification Summary": "No domain to verify"}

    a_record = False
    aaaa_record = False
    dns_error = ""
    try:
        answers = socket.getaddrinfo(domain, 443, socket.AF_UNSPEC, socket.SOCK_STREAM)
        for answer in answers:
            if answer[0] == socket.AF_INET:
                a_record = True
            elif answer[0] == socket.AF_INET6:
                aaaa_record = True
    except Exception as exc:
        dns_error = str(exc)[:160]

    ssl_present, ssl_expires = _ssl_certificate_info(domain) if (a_record or aaaa_record) else ("No", "")
    robots = machine.fetch_page_result(f"https://{domain}/robots.txt", timeout=5, provider="Domain robots") if (a_record or aaaa_record) else {}
    sitemap = machine.fetch_page_result(f"https://{domain}/sitemap.xml", timeout=5, provider="Domain sitemap") if (a_record or aaaa_record) else {}
    rdap_age, rdap_error = _rdap_age_days(machine, domain)
    summary_bits = [
        f"domain={domain}",
        f"a={'yes' if a_record else 'no'}",
        f"aaaa={'yes' if aaaa_record else 'no'}",
        f"ssl={ssl_present.lower()}",
    ]
    if int(robots.get("status_code") or 0):
        summary_bits.append(f"robots={robots.get('status_code')}")
    if int(sitemap.get("status_code") or 0):
        summary_bits.append(f"sitemap={sitemap.get('status_code')}")
    if rdap_age:
        summary_bits.append(f"domain_age_days={rdap_age}")

    return {
        "Domain Checked": domain,
        "Domain A Record": "Yes" if a_record else "No",
        "Domain AAAA Record": "Yes" if aaaa_record else "No",
        "Domain DNS Error": dns_error,
        "Domain MX/Address Record": "Yes" if machine._has_mx_record(domain) else "No",
        "Domain SSL Present": ssl_present,
        "Domain SSL Expires": ssl_expires,
        "Robots.txt Status": str(robots.get("status_code", "")) if robots else "",
        "Sitemap Status": str(sitemap.get("status_code", "")) if sitemap else "",
        "Domain RDAP Age Days": rdap_age,
        "Domain RDAP Error": rdap_error,
        "Domain Verification Summary": "; ".join(summary_bits),
    }


def append_provider_evidence(lead: dict, source: str, summary: str) -> None:
    if not summary:
        return
    existing = [part.strip() for part in str(lead.get("Provider Evidence Summary", "")).split(";") if part.strip()]
    item = f"{source}: {summary}"
    lead["Provider Evidence Summary"] = "; ".join(dict.fromkeys([*existing, item]))


def enrich_with_provider_sources(machine: "LeadMachine", leads: list[dict]) -> list[dict]:
    yelp_enabled = bool(str(getattr(machine.config, "yelp_api_key", "") or "").strip())
    domain_checks = bool(getattr(machine.config, "enable_domain_checks", True))
    yelp_matched = 0
    domain_checked = 0

    for lead in leads:
        machine._check_stop()
        normalized_phone = normalize_phone(lead.get("Phone", ""))
        normalized_address = normalize_address(lead.get("Address", ""))
        lead["Normalized Phone"] = normalized_phone
        lead["Normalized Address"] = normalized_address

        if yelp_enabled:
            yelp_result = yelp_enrich_lead(machine, lead)
            lead.update({key: value for key, value in yelp_result.items() if value not in {"", None}})
            status = str(yelp_result.get("Yelp Match Status", ""))
            if status == "Matched":
                yelp_matched += 1
                append_provider_evidence(
                    lead,
                    "Yelp",
                    f"matched at {yelp_result.get('Yelp Match Confidence', 0)}/100 with {yelp_result.get('Yelp Review Count', '')} reviews",
                )
                if not lead.get("Phone") and yelp_result.get("Yelp Phone"):
                    lead["Phone"] = yelp_result.get("Yelp Phone", "")
                if yelp_result.get("Yelp Match Confidence"):
                    lead["Business Identity Confidence"] = max(
                        int(lead.get("Business Identity Confidence") or 0),
                        int(yelp_result.get("Yelp Match Confidence") or 0),
                    )
            elif status in {"Mismatch", "Error"}:
                append_provider_evidence(lead, "Yelp", str(yelp_result.get("Yelp Failure Reason", status)))

        website = str(lead.get("Official Website") or lead.get("Seed Website") or "").strip()
        if domain_checks and website and not (
            machine.is_social_url(website) or machine.check_directory(website) or machine.is_link_hub_url(website)
        ):
            domain_result = verify_domain(machine, website)
            if domain_result:
                lead.update(domain_result)
                domain_checked += 1
                append_provider_evidence(lead, "Domain", str(domain_result.get("Domain Verification Summary", "")))

    machine.record_stage_report(
        "provider_enrichment",
        "External provider enrichment",
        yelp_enabled=yelp_enabled,
        yelp_matched=yelp_matched,
        domain_checks_enabled=domain_checks,
        domains_checked=domain_checked,
    )
    return leads
