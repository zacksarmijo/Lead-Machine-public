from __future__ import annotations

"""BuiltWith Free API enrichment for website technology stack signals."""

import threading
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

if TYPE_CHECKING:
    from lead_machine import LeadMachine


BUILTWITH_FREE_ENDPOINT = "https://api.builtwith.com/free1/api.json"
LIVE_WEBSITE_STATUSES = {"Real website", "Weak site", "Basic site", "Broken site"}
_REQUEST_LOCK = threading.Lock()
_LAST_REQUEST_AT = 0.0

DEFAULT_TECH_STACK_FIELDS: dict[str, Any] = {
    "BuiltWith Status": "",
    "BuiltWith Domain": "",
    "BuiltWith First Indexed": "",
    "BuiltWith Last Indexed": "",
    "BuiltWith Groups": "",
    "BuiltWith Category Summary": "",
    "Tech Stack Signal": "",
    "Tech Stack Score": 0,
    "Tech Stack Weak Signals": "",
    "Tech Stack Strong Signals": "",
    "Tech Stack Summary": "",
    "Tech Stack Last Checked": "",
    "Tech Stack Error": "",
}

ANALYTICS_GROUP_KEYWORDS = (
    "analytics",
    "tag",
    "tracking",
    "advertising",
    "marketing",
    "pixel",
    "conversion",
)
CONVERSION_CATEGORY_KEYWORDS = (
    "ab-testing",
    "analytics",
    "call-tracking",
    "chat",
    "conversion",
    "crm",
    "form",
    "lead",
    "marketing-automation",
    "pixel",
    "tag-management",
    "web-analytics",
)
CMS_GROUP_KEYWORDS = ("cms", "content-management", "blog", "website-builder", "web-builder")
WEAK_BUILDER_KEYWORDS = (
    "duda",
    "godaddy",
    "homestead",
    "jimdo",
    "sitebuilder",
    "squarespace",
    "weebly",
    "webflow",
    "wix",
    "wordpress",
    "website-builder",
)
MODERN_CONVERSION_HINTS = (
    "ab-testing",
    "analytics",
    "call-tracking",
    "chat",
    "conversion",
    "crm",
    "email-marketing",
    "form",
    "marketing-automation",
    "pixel",
    "tag-management",
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _safe_int(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _epoch_to_date(value: Any) -> str:
    epoch = _safe_int(value)
    if epoch <= 0:
        return ""
    try:
        return datetime.fromtimestamp(epoch, tz=timezone.utc).date().isoformat()
    except (OSError, OverflowError, ValueError):
        return ""


def _days_since_epoch(value: Any) -> int:
    epoch = _safe_int(value)
    if epoch <= 0:
        return 0
    now = int(time.time())
    return max(0, int((now - epoch) / 86400))


def _contains_any(value: str, keywords: tuple[str, ...]) -> bool:
    lowered = value.lower()
    return any(keyword in lowered for keyword in keywords)


def _domain_from_url(value: object) -> str:
    raw = _text(value)
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    host = (parsed.hostname or "").strip().lower()
    if not host:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host


def domain_for_lead(lead: dict) -> str:
    for key in ("Resolved Website URL", "Official Website"):
        domain = _domain_from_url(lead.get(key))
        if domain:
            return domain
    return ""


def should_run_tech_stack(machine: "LeadMachine", lead: dict) -> bool:
    if not bool(getattr(machine.config, "enable_builtwith_checks", False)):
        return False
    if not _text(getattr(machine.config, "builtwith_api_key", "")):
        return False
    if _text(lead.get("Web Presence Status")) not in LIVE_WEBSITE_STATUSES:
        return False
    return bool(domain_for_lead(lead))


def _wait_for_free_api_slot() -> None:
    global _LAST_REQUEST_AT
    with _REQUEST_LOCK:
        elapsed = time.monotonic() - _LAST_REQUEST_AT
        if elapsed < 1.05:
            time.sleep(1.05 - elapsed)
        _LAST_REQUEST_AT = time.monotonic()


def _iter_groups(payload: dict[str, Any]) -> list[dict[str, Any]]:
    lookup = payload.get("free1", payload)
    if not isinstance(lookup, dict):
        return []
    groups = lookup.get("groups", [])
    return [group for group in groups if isinstance(group, dict)]


def _result_lookup(payload: dict[str, Any]) -> dict[str, Any]:
    lookup = payload.get("free1", payload)
    return lookup if isinstance(lookup, dict) else {}


def _category_names(group: dict[str, Any]) -> list[str]:
    categories = group.get("categories", [])
    if not isinstance(categories, list):
        return []
    names: list[str] = []
    for category in categories:
        if not isinstance(category, dict):
            continue
        name = _text(category.get("name"))
        live = _safe_int(category.get("live"))
        dead = _safe_int(category.get("dead"))
        if name and (live > 0 or dead > 0):
            names.append(name)
    return names


def analyze_builtwith_payload(payload: dict[str, Any]) -> dict[str, Any]:
    lookup = _result_lookup(payload)
    groups = _iter_groups(payload)
    group_names: list[str] = []
    category_names: list[str] = []
    live_total = 0
    dead_total = 0
    latest_epoch = _safe_int(lookup.get("last"))
    oldest_epoch = _safe_int(lookup.get("first"))

    live_analytics = 0
    live_conversion = 0
    live_cms = 0
    weak_builder_hits: list[str] = []
    live_modern_conversion_hits: list[str] = []
    stale_cms_days = 0

    for group in groups:
        name = _text(group.get("name"))
        live = _safe_int(group.get("live"))
        dead = _safe_int(group.get("dead"))
        latest = _safe_int(group.get("latest"))
        oldest = _safe_int(group.get("oldest"))
        if name:
            group_names.append(name)
        live_total += live
        dead_total += dead
        latest_epoch = max(latest_epoch, latest)
        if oldest and (not oldest_epoch or oldest < oldest_epoch):
            oldest_epoch = oldest
        group_categories = _category_names(group)
        category_names.extend(group_categories)
        group_text = " ".join([name, *group_categories]).lower()

        if _contains_any(group_text, ANALYTICS_GROUP_KEYWORDS):
            live_analytics += live
        if _contains_any(group_text, CONVERSION_CATEGORY_KEYWORDS):
            live_conversion += live
        if _contains_any(group_text, CMS_GROUP_KEYWORDS):
            live_cms += live
            stale_cms_days = max(stale_cms_days, _days_since_epoch(latest or oldest))
        if live and _contains_any(group_text, WEAK_BUILDER_KEYWORDS):
            weak_builder_hits.extend([name, *group_categories])
        if live and _contains_any(group_text, MODERN_CONVERSION_HINTS):
            live_modern_conversion_hits.extend([name, *group_categories])

    weak_signals: list[str] = []
    strong_signals: list[str] = []
    score = 0

    if live_total <= 0:
        score += 18
        weak_signals.append("No live technologies were reported by BuiltWith")
    if live_cms <= 0:
        score += 10
        weak_signals.append("No live CMS/platform category detected")
    if live_analytics <= 0:
        score += 14
        weak_signals.append("No analytics or tracking category detected")
    else:
        strong_signals.append(f"{live_analytics} live analytics/tracking signal(s)")
    if live_conversion <= 0:
        score += 10
        weak_signals.append("No modern conversion stack category detected")
    else:
        strong_signals.append(f"{live_conversion} live conversion-stack signal(s)")
    if dead_total >= max(3, live_total):
        score += 8
        weak_signals.append(f"Dead technology count is high ({dead_total} dead vs {live_total} live)")
    if stale_cms_days >= 365 * 4:
        score += 8
        weak_signals.append("CMS/platform signal appears stale (4+ years since latest index)")
    elif stale_cms_days >= 365 * 2:
        score += 4
        weak_signals.append("CMS/platform signal appears dated (2+ years since latest index)")
    if weak_builder_hits:
        unique_builders = list(dict.fromkeys(hit for hit in weak_builder_hits if hit))
        score += 6
        weak_signals.append(f"Weak builder/CMS category detected: {', '.join(unique_builders[:4])}")
    if live_modern_conversion_hits and live_conversion >= 2:
        strong_signals.append("Modern conversion/measurement categories are present")

    score = max(0, min(score, 100))
    if score >= 38:
        signal = "Weak or outdated stack"
    elif score >= 22:
        signal = "Some missing stack signals"
    elif score > 0:
        signal = "Light stack gap"
    else:
        signal = "Modern stack signals present"

    group_summary = "; ".join(
        f"{_text(group.get('name'))} live {_safe_int(group.get('live'))}/dead {_safe_int(group.get('dead'))}"
        for group in groups
        if _text(group.get("name"))
    )
    category_summary = ", ".join(list(dict.fromkeys(category_names))[:18])
    summary_parts = [
        signal,
        f"{live_total} live / {dead_total} dead technologies",
    ]
    if weak_signals:
        summary_parts.append(weak_signals[0])
    elif strong_signals:
        summary_parts.append(strong_signals[0])

    return {
        "BuiltWith Status": "Measured",
        "BuiltWith Domain": _text(lookup.get("domain")),
        "BuiltWith First Indexed": _epoch_to_date(oldest_epoch),
        "BuiltWith Last Indexed": _epoch_to_date(latest_epoch),
        "BuiltWith Groups": group_summary[:900],
        "BuiltWith Category Summary": category_summary[:900],
        "Tech Stack Signal": signal,
        "Tech Stack Score": score,
        "Tech Stack Weak Signals": "; ".join(dict.fromkeys(weak_signals))[:900],
        "Tech Stack Strong Signals": "; ".join(dict.fromkeys(strong_signals))[:900],
        "Tech Stack Summary": "; ".join(summary_parts)[:900],
        "Tech Stack Last Checked": datetime.now().isoformat(timespec="seconds"),
        "Tech Stack Error": "",
    }


def run_builtwith_for_lead(machine: "LeadMachine", lead: dict) -> dict[str, Any]:
    domain = domain_for_lead(lead)
    if not domain:
        return {"BuiltWith Status": "Skipped", "Tech Stack Error": "No live website domain available"}
    api_key = _text(getattr(machine.config, "builtwith_api_key", ""))
    if not api_key:
        return {"BuiltWith Status": "Skipped", "BuiltWith Domain": domain, "Tech Stack Error": "BuiltWith API key missing"}

    params = {"KEY": api_key, "LOOKUP": domain}
    try:
        _wait_for_free_api_slot()
        response = machine._request("get", BUILTWITH_FREE_ENDPOINT, params=params, timeout=(8, 30))
        if response.status_code >= 400:
            return {
                "BuiltWith Status": "Error",
                "BuiltWith Domain": domain,
                "Tech Stack Error": f"HTTP {response.status_code}: {_text(response.text)[:180]}",
            }
        payload = response.json()
    except Exception as exc:
        return {
            "BuiltWith Status": "Error",
            "BuiltWith Domain": domain,
            "Tech Stack Error": str(exc)[:220],
        }

    result = analyze_builtwith_payload(payload if isinstance(payload, dict) else {})
    if not result.get("BuiltWith Domain"):
        result["BuiltWith Domain"] = domain
    return result


def enrich_leads_with_tech_stack(machine: "LeadMachine", leads: list[dict]) -> list[dict]:
    for lead in leads:
        lead.update(DEFAULT_TECH_STACK_FIELDS)

    if not bool(getattr(machine.config, "enable_builtwith_checks", False)):
        machine.record_stage_report("tech_stack", "BuiltWith tech stack signals", enabled=False, checked=0)
        return leads
    if not _text(getattr(machine.config, "builtwith_api_key", "")):
        machine.record_stage_report("tech_stack", "BuiltWith tech stack signals", enabled=True, checked=0, missing_key=True)
        return leads

    cap = max(0, int(getattr(machine.config, "builtwith_run_cap", 10) or 0))
    checked = 0
    measured = 0
    errors = 0
    skipped = 0
    weak_or_missing = 0
    for lead in leads:
        if checked >= cap:
            break
        if not should_run_tech_stack(machine, lead):
            skipped += 1
            continue
        checked += 1
        business_name = _text(lead.get("Business Name")) or "lead"
        machine.log(f"BuiltWith tech stack check {checked}/{cap}: {business_name}")
        result = run_builtwith_for_lead(machine, lead)
        lead.update({key: value for key, value in result.items() if value not in (None, "")})
        if result.get("BuiltWith Status") == "Measured":
            measured += 1
            if int(result.get("Tech Stack Score") or 0) >= 22:
                weak_or_missing += 1
        elif result.get("BuiltWith Status") == "Error":
            errors += 1

    machine.record_stage_report(
        "tech_stack",
        "BuiltWith tech stack signals",
        enabled=True,
        checked=checked,
        measured=measured,
        errors=errors,
        skipped=skipped,
        weak_or_missing=weak_or_missing,
        cap=cap,
    )
    return leads
