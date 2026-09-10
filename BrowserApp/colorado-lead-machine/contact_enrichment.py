from __future__ import annotations

"""Contact enrichment helpers for the Colorado lead machine."""

import random
import re
import time
from typing import TYPE_CHECKING, Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from lead_machine_presence_config import JUNK_EMAIL_DOMAINS

if TYPE_CHECKING:
    from lead_machine import LeadMachine


EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", re.IGNORECASE)

_NON_BUSINESS_EMAIL_DOMAINS = {
    "google.",
    "yelp.",
    "facebook.",
    "yellowpages.",
    "tripadvisor.",
    "bbb.org",
    "linkedin.",
    "instagram.",
    "twitter.",
    "duckduckgo.",
}

_KNOWN_SITE_FIELDS = (
    "Official Website",
    "Resolved Website URL",
    "Seed Website",
    "Domain Checked",
)

_ROLE_PREFIX_PRIORITY = (
    "info",
    "contact",
    "hello",
    "office",
    "admin",
    "support",
    "sales",
    "service",
    "booking",
    "appointments",
)


def _contact_counts(leads: list[dict]) -> tuple[int, int]:
    phone_only = sum(1 for lead in leads if lead.get("Phone") and not lead.get("Email"))
    no_contact = sum(1 for lead in leads if not lead.get("Phone") and not lead.get("Email"))
    return phone_only, no_contact


def clean_email(machine: "LeadMachine", email: str) -> Optional[str]:
    lowered = email.lower().strip().rstrip(".,;:)'\"")
    if not EMAIL_RE.fullmatch(lowered):
        return None
    domain = lowered.split("@", 1)[1]
    if domain in JUNK_EMAIL_DOMAINS:
        return None
    if len(lowered) > 80 or len(lowered) < 6:
        return None
    if any(token in lowered for token in ["example", "test@", "your@", "name@", "email@"]):
        return None
    if not machine._has_mx_record(domain):
        return None
    return lowered


def extract_emails(machine: "LeadMachine", text: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for candidate in EMAIL_RE.findall(text):
        email = machine.clean_email(candidate)
        if email and email not in seen:
            seen.add(email)
            found.append(email)
    return found


def scrape_site(machine: "LeadMachine", base_url: str) -> tuple[Optional[str], Optional[str]]:
    pages = [
        base_url,
        base_url.rstrip("/") + "/contact",
        base_url.rstrip("/") + "/contact-us",
        base_url.rstrip("/") + "/about",
    ]
    for url in pages:
        machine._check_stop()
        fetch_result = machine.fetch_page_result(url, provider="Contact scrape")
        html = str(fetch_result.get("html") or "") if fetch_result.get("ok") else ""
        final_url = str(fetch_result.get("final_url") or url)
        if not html:
            continue
        soup = BeautifulSoup(html, "lxml")
        for anchor in soup.find_all("a", href=True):
            href = str(anchor["href"])
            if href.startswith("mailto:"):
                email = machine.clean_email(href.replace("mailto:", "").split("?")[0])
                if email:
                    return email, final_url
        emails = machine.extract_emails(html)
        if emails:
            return emails[0], final_url
        time.sleep(random.uniform(0.4, 1.0))
    return None, None


def _domain_from_url(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if "@" in text and not text.startswith(("http://", "https://")):
        text = text.split("@", 1)[1]
    candidate = text if "://" in text else f"https://{text}"
    parsed = urlparse(candidate)
    domain = (parsed.netloc or parsed.path).split("/", 1)[0].lower()
    domain = domain.split(":", 1)[0].strip(".")
    if domain.startswith("www."):
        domain = domain[4:]
    if not (5 < len(domain) < 80 and "." in domain):
        return ""
    if any(blocked in domain for blocked in _NON_BUSINESS_EMAIL_DOMAINS):
        return ""
    return domain


def _site_url_from_domain(domain: str) -> str:
    return f"https://{domain}"


def known_business_domains(lead: dict) -> list[str]:
    domains: list[str] = []
    seen: set[str] = set()
    for field in _KNOWN_SITE_FIELDS:
        domain = _domain_from_url(lead.get(field, ""))
        if domain and domain not in seen:
            seen.add(domain)
            domains.append(domain)
    return domains


def scrape_known_site_email(machine: "LeadMachine", lead: dict) -> tuple[Optional[str], Optional[str]]:
    for domain in known_business_domains(lead):
        machine._check_stop()
        email, source = machine.scrape_site(_site_url_from_domain(domain))
        if email:
            return email, f"Website scrape ({source or domain})"
    return None, None


def _hunter_error_message(payload: object) -> str:
    if not isinstance(payload, dict):
        return ""
    errors = payload.get("errors")
    if isinstance(errors, list) and errors:
        first = errors[0]
        if isinstance(first, dict):
            return str(first.get("details") or first.get("code") or first)[:80]
        return str(first)[:80]
    if isinstance(errors, dict):
        return str(errors.get("details") or errors.get("code") or errors)[:80]
    return ""


def _verification_rank(value: object) -> int:
    status = str(value or "").strip().lower()
    if status == "valid":
        return 0
    if status == "accept_all":
        return 1
    if status == "unknown":
        return 2
    return 3


def _hunter_email_rank(item: dict) -> tuple[int, int, int, int]:
    email = str(item.get("value") or "").lower()
    local_part = email.split("@", 1)[0]
    verification = item.get("verification") if isinstance(item.get("verification"), dict) else {}
    verification_status = verification.get("status", "") if isinstance(verification, dict) else ""
    email_type = str(item.get("type") or "").lower()
    try:
        confidence = int(float(item.get("confidence") or 0))
    except (TypeError, ValueError):
        confidence = 0
    role_rank = 0 if local_part in _ROLE_PREFIX_PRIORITY else 1
    type_rank = 0 if email_type == "generic" else 1
    return (_verification_rank(verification_status), type_rank, role_rank, -confidence)


def hunter_search_email(machine: "LeadMachine", lead: dict) -> tuple[Optional[str], Optional[str]]:
    api_key = str(getattr(machine.config, "hunter_api_key", "") or "").strip()
    if not api_key:
        return None, "Hunter API key missing"

    business_name = str(lead.get("Business Name", "") or "").strip()
    domains = known_business_domains(lead)
    params: dict[str, object] = {"api_key": api_key, "limit": 10}
    if domains:
        params["domain"] = domains[0]
    elif len(business_name) >= 3:
        params["company"] = business_name
    else:
        return None, "Hunter skipped: no business domain or company"

    try:
        response = machine._request(
            "get",
            "https://api.hunter.io/v2/domain-search",
            params=params,
            timeout=15,
        )
        if response.status_code == 451:
            return None, "Hunter privacy opt-out"
        payload = response.json()
        if response.status_code != 200:
            detail = _hunter_error_message(payload)
            return None, f"Hunter error {response.status_code}" + (f": {detail}" if detail else "")
        data = payload.get("data") if isinstance(payload, dict) else {}
        if not isinstance(data, dict):
            return None, "Hunter returned no data"
        candidates = [item for item in data.get("emails", []) if isinstance(item, dict)]
        for item in sorted(candidates, key=_hunter_email_rank):
            email = machine.clean_email(str(item.get("value") or ""))
            if not email:
                continue
            confidence = item.get("confidence")
            email_type = str(item.get("type") or "").strip()
            verification = item.get("verification") if isinstance(item.get("verification"), dict) else {}
            verification_status = str(verification.get("status") or "").strip() if isinstance(verification, dict) else ""
            source_domain = str(data.get("domain") or params.get("domain") or params.get("company") or "").strip()
            details = ", ".join(
                part
                for part in [
                    source_domain,
                    f"{confidence} confidence" if confidence not in ("", None) else "",
                    email_type,
                    verification_status,
                ]
                if part
            )
            return email, f"Hunter Domain Search ({details})" if details else "Hunter Domain Search"
        target = params.get("domain") or params.get("company")
        return None, f"Hunter no email found for {target}"
    except Exception as exc:
        return None, f"Hunter error: {str(exc)[:80]}"


def guess_domain_email(machine: "LeadMachine", name: str, address: str) -> tuple[Optional[str], Optional[str]]:
    slug = re.sub(r"[^a-z0-9]", "", name.lower())[:25]
    city_slug = re.sub(r"[^a-z]", "", (address.split(",")[0] if address else ""))[:10]
    candidates = [
        f"https://www.{slug}.com",
        f"https://{slug}.com",
        f"https://www.{slug}co.com",
        f"https://www.{slug}{city_slug}.com",
    ]
    for candidate in candidates[:2]:
        machine._check_stop()
        domain = urlparse(candidate).netloc.replace("www.", "")
        if not (5 < len(domain) < 40 and "." in domain):
            continue
        try:
            response = machine._safe_web_request("head", f"https://{domain}", timeout=4)
            if response.status_code < 400:
                return f"info@{domain}", f"guessed ({domain})"
        except Exception:
            continue
    return None, None


def find_email(machine: "LeadMachine", lead: dict) -> tuple[Optional[str], str]:
    name = str(lead.get("Business Name", "")).strip()
    address = str(lead.get("Address", "")).strip()
    failure_notes: list[str] = []

    existing = machine.clean_email(str(lead.get("Email", "") or ""))
    if existing:
        return existing, str(lead.get("Email Source", "") or "Existing lead email")

    email, source = machine.hunter_search_email(lead)
    if email:
        return email, source or "Hunter Domain Search"
    if source:
        failure_notes.append(source)
    if source == "Hunter privacy opt-out":
        return None, source

    time.sleep(random.uniform(machine.config.email_delay_min, machine.config.email_delay_max))

    email, source = machine.scrape_known_site_email(lead)
    if email:
        return email, source or "Website scrape"
    if source:
        failure_notes.append(source)

    time.sleep(random.uniform(machine.config.email_delay_min, machine.config.email_delay_max))

    email, _ = machine.guess_domain_email(name, address)
    if email:
        return email, "Guessed - verify first"

    return None, "; ".join(failure_notes[:4]) or "Not found"


def enrich_with_emails(machine: "LeadMachine", leads: list[dict]) -> list[dict]:
    if machine.config.skip_email_lookup:
        machine.log("Skipping email lookup.")
        phone_only, no_contact = _contact_counts(leads)
        machine.record_stage_report(
            "contact_enrichment",
            "Contact enrichment",
            skipped=True,
            emails_found=0,
            phone_only=phone_only,
            no_contact=no_contact,
        )
        return leads

    machine.log(f"Stage 5/5: Contact enrichment and lead scoring setup for {len(leads)} leads")
    found_count = 0
    for index, lead in enumerate(leads, start=1):
        machine._check_stop()
        machine.log(f"[{index}/{len(leads)}] {lead['Business Name']}")
        try:
            email, source = machine.find_email(lead)
        except Exception as exc:
            email, source = None, f"Error: {str(exc)[:60]}"
        lead["Email"] = email or ""
        lead["Email Source"] = source
        if email:
            found_count += 1
            machine.log(f"Email found: {email} ({source})")
        elif lead.get("Phone"):
            machine.log(f"No email found. Keeping phone: {lead['Phone']}")
        else:
            machine.log("No contact info found.")
        time.sleep(random.uniform(0.3, 0.8))

    pct = round(found_count / len(leads) * 100) if leads else 0
    phone_only, no_contact = _contact_counts(leads)
    machine.log(f"Email phase complete: {found_count}/{len(leads)} found ({pct}%)")
    machine.record_stage_report(
        "contact_enrichment",
        "Contact enrichment",
        skipped=False,
        emails_found=found_count,
        phone_only=phone_only,
        no_contact=no_contact,
        email_hit_rate_percent=pct,
    )
    return leads
