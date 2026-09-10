from __future__ import annotations

"""PageSpeed Insights / CrUX enrichment for live website leads."""

from typing import TYPE_CHECKING, Any

import network

if TYPE_CHECKING:
    from lead_machine import LeadMachine


PAGESPEED_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
PAGESPEED_CATEGORIES = ("performance", "accessibility", "best-practices", "seo")
LIVE_WEBSITE_STATUSES = {"Real website", "Weak site", "Basic site", "Broken site"}


def _score(value: Any) -> int:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0
    if parsed <= 1:
        parsed *= 100
    return max(0, min(100, int(round(parsed))))


def _text(value: Any) -> str:
    return str(value or "").strip()


def _metric_display(audits: dict[str, Any], key: str) -> str:
    item = audits.get(key, {}) if isinstance(audits, dict) else {}
    if not isinstance(item, dict):
        return ""
    display = _text(item.get("displayValue"))
    if display:
        return display
    numeric = item.get("numericValue")
    if numeric in (None, ""):
        return ""
    try:
        if key == "cumulative-layout-shift":
            return f"{float(numeric):.3f}"
        return f"{int(round(float(numeric)))} ms"
    except (TypeError, ValueError):
        return _text(numeric)


def _field_metric(experience: dict[str, Any], key: str) -> tuple[str, str]:
    metrics = experience.get("metrics", {}) if isinstance(experience, dict) else {}
    metric = metrics.get(key, {}) if isinstance(metrics, dict) else {}
    if not isinstance(metric, dict):
        return "", ""
    category = _text(metric.get("category"))
    percentile = metric.get("percentile")
    if percentile in (None, ""):
        return category, ""
    if key == "CUMULATIVE_LAYOUT_SHIFT_SCORE":
        try:
            return category, f"{float(percentile) / 100:.3f}"
        except (TypeError, ValueError):
            return category, _text(percentile)
    try:
        return category, f"{int(percentile)} ms"
    except (TypeError, ValueError):
        return category, _text(percentile)


def _category_summary(result: dict[str, Any]) -> str:
    parts: list[str] = []
    for label, key in (
        ("Perf", "PageSpeed Performance Score"),
        ("A11y", "PageSpeed Accessibility Score"),
        ("Best", "PageSpeed Best Practices Score"),
        ("SEO", "PageSpeed SEO Score"),
    ):
        value = int(result.get(key) or 0)
        if value:
            parts.append(f"{label} {value}")
    return ", ".join(parts)


def _field_summary(result: dict[str, Any]) -> str:
    parts: list[str] = []
    for label, category_key, value_key in (
        ("LCP", "PageSpeed CrUX LCP Category", "PageSpeed CrUX LCP"),
        ("INP", "PageSpeed CrUX INP Category", "PageSpeed CrUX INP"),
        ("CLS", "PageSpeed CrUX CLS Category", "PageSpeed CrUX CLS"),
    ):
        category = _text(result.get(category_key))
        value = _text(result.get(value_key))
        if category or value:
            parts.append(f"{label} {value} {category}".strip())
    return "; ".join(parts)


def _speed_signal(result: dict[str, Any]) -> str:
    status = _text(result.get("PageSpeed Status"))
    if status != "Measured":
        error = _text(result.get("PageSpeed Error"))
        return f"PageSpeed {status.lower()}" + (f": {error}" if error else "")

    performance = int(result.get("PageSpeed Performance Score") or 0)
    if performance >= 90:
        label = "Good"
    elif performance >= 50:
        label = "Needs improvement"
    else:
        label = "Poor"

    summary = _category_summary(result)
    field = _field_summary(result)
    crux = _text(result.get("PageSpeed CrUX Overall"))
    pieces = [f"PageSpeed mobile {label.lower()} ({performance}/100)"]
    if summary:
        pieces.append(summary)
    if crux and crux != "NONE":
        pieces.append(f"CrUX {crux}")
    if field:
        pieces.append(field)
    return "; ".join(pieces)


def _top_opportunities(audits: dict[str, Any], limit: int = 4) -> str:
    rows: list[tuple[float, str]] = []
    if not isinstance(audits, dict):
        return ""
    for audit in audits.values():
        if not isinstance(audit, dict):
            continue
        details = audit.get("details", {})
        score = audit.get("score")
        title = _text(audit.get("title"))
        if not title or score in (None, ""):
            continue
        try:
            numeric_score = float(score)
        except (TypeError, ValueError):
            continue
        savings = 0.0
        if isinstance(details, dict):
            savings = float(details.get("overallSavingsMs") or details.get("overallSavingsBytes") or 0)
        if savings > 0 and numeric_score < 0.9:
            rows.append((savings, title))
    rows.sort(reverse=True)
    return "; ".join(title for _, title in rows[:limit])


def should_run_pagespeed(machine: "LeadMachine", lead: dict) -> bool:
    if not bool(getattr(machine.config, "enable_pagespeed_checks", False)):
        return False
    status = _text(lead.get("Web Presence Status"))
    if status not in LIVE_WEBSITE_STATUSES:
        return False
    url = _text(lead.get("Resolved Website URL") or lead.get("Official Website"))
    if not url or not network.is_safe_web_url(url):
        return False
    return True


def run_pagespeed_for_lead(machine: "LeadMachine", lead: dict) -> dict[str, Any]:
    url = _text(lead.get("Resolved Website URL") or lead.get("Official Website"))
    strategy = _text(getattr(machine.config, "pagespeed_strategy", "mobile")).lower() or "mobile"
    if strategy not in {"mobile", "desktop"}:
        strategy = "mobile"
    if not url:
        return {"PageSpeed Status": "Skipped", "PageSpeed Error": "No live URL available"}
    if not network.is_safe_web_url(url):
        return {"PageSpeed Status": "Skipped", "PageSpeed Error": "Unsafe or unsupported URL"}

    params: list[tuple[str, str]] = [
        ("url", url),
        ("strategy", strategy),
        ("utm_source", "summit-lead-machine"),
        ("utm_campaign", "lead-quality-audit"),
    ]
    for category in PAGESPEED_CATEGORIES:
        params.append(("category", category))
    api_key = _text(getattr(machine.config, "pagespeed_api_key", "") or getattr(machine.config, "google_maps_api_key", ""))
    if api_key:
        params.append(("key", api_key))

    try:
        response = machine._request("get", PAGESPEED_ENDPOINT, params=params, timeout=(8, 90))
        if response.status_code >= 400:
            return {
                "PageSpeed Status": "Error",
                "PageSpeed Strategy": strategy,
                "PageSpeed Error": f"HTTP {response.status_code}: {_text(response.text)[:180]}",
            }
        payload = response.json()
    except Exception as exc:
        return {
            "PageSpeed Status": "Error",
            "PageSpeed Strategy": strategy,
            "PageSpeed Error": str(exc)[:220],
        }

    lighthouse = payload.get("lighthouseResult", {}) if isinstance(payload, dict) else {}
    categories = lighthouse.get("categories", {}) if isinstance(lighthouse, dict) else {}
    audits = lighthouse.get("audits", {}) if isinstance(lighthouse, dict) else {}
    loading = payload.get("loadingExperience", {}) if isinstance(payload, dict) else {}
    origin_loading = payload.get("originLoadingExperience", {}) if isinstance(payload, dict) else {}

    def category_score(name: str) -> int:
        category = categories.get(name, {}) if isinstance(categories, dict) else {}
        return _score(category.get("score")) if isinstance(category, dict) else 0

    crux_lcp_category, crux_lcp = _field_metric(loading, "LARGEST_CONTENTFUL_PAINT_MS")
    crux_inp_category, crux_inp = _field_metric(loading, "INTERACTION_TO_NEXT_PAINT")
    crux_cls_category, crux_cls = _field_metric(loading, "CUMULATIVE_LAYOUT_SHIFT_SCORE")
    crux_fcp_category, crux_fcp = _field_metric(loading, "FIRST_CONTENTFUL_PAINT_MS")
    crux_ttfb_category, crux_ttfb = _field_metric(loading, "EXPERIMENTAL_TIME_TO_FIRST_BYTE")

    result: dict[str, Any] = {
        "PageSpeed Status": "Measured",
        "PageSpeed Strategy": strategy,
        "PageSpeed Final URL": _text(lighthouse.get("finalUrl") or payload.get("id") or url),
        "PageSpeed Analysis Timestamp": _text(payload.get("analysisUTCTimestamp") or lighthouse.get("fetchTime")),
        "PageSpeed Lighthouse Version": _text(lighthouse.get("lighthouseVersion")),
        "PageSpeed Performance Score": category_score("performance"),
        "PageSpeed Accessibility Score": category_score("accessibility"),
        "PageSpeed Best Practices Score": category_score("best-practices"),
        "PageSpeed SEO Score": category_score("seo"),
        "PageSpeed FCP": _metric_display(audits, "first-contentful-paint"),
        "PageSpeed LCP": _metric_display(audits, "largest-contentful-paint"),
        "PageSpeed Speed Index": _metric_display(audits, "speed-index"),
        "PageSpeed TBT": _metric_display(audits, "total-blocking-time"),
        "PageSpeed CLS": _metric_display(audits, "cumulative-layout-shift"),
        "PageSpeed Interactive": _metric_display(audits, "interactive"),
        "PageSpeed CrUX Overall": _text(loading.get("overall_category")),
        "PageSpeed Origin CrUX Overall": _text(origin_loading.get("overall_category")),
        "PageSpeed CrUX FCP": crux_fcp,
        "PageSpeed CrUX FCP Category": crux_fcp_category,
        "PageSpeed CrUX LCP": crux_lcp,
        "PageSpeed CrUX LCP Category": crux_lcp_category,
        "PageSpeed CrUX INP": crux_inp,
        "PageSpeed CrUX INP Category": crux_inp_category,
        "PageSpeed CrUX CLS": crux_cls,
        "PageSpeed CrUX CLS Category": crux_cls_category,
        "PageSpeed CrUX TTFB": crux_ttfb,
        "PageSpeed CrUX TTFB Category": crux_ttfb_category,
        "PageSpeed Opportunities": _top_opportunities(audits),
        "PageSpeed Error": "",
    }
    result["PageSpeed Field Summary"] = _field_summary(result)
    result["PageSpeed Summary"] = _category_summary(result)
    result["Page Speed Signal"] = _speed_signal(result)
    return result


def enrich_leads_with_pagespeed(machine: "LeadMachine", leads: list[dict]) -> list[dict]:
    if not bool(getattr(machine.config, "enable_pagespeed_checks", False)):
        machine.record_stage_report("pagespeed", "PageSpeed / CrUX enrichment", enabled=False, checked=0)
        return leads

    cap = max(0, int(getattr(machine.config, "pagespeed_run_cap", 10) or 0))
    checked = 0
    measured = 0
    errors = 0
    skipped = 0
    for lead in leads:
        machine._check_stop()
        if checked >= cap:
            break
        if not should_run_pagespeed(machine, lead):
            skipped += 1
            continue
        checked += 1
        business_name = _text(lead.get("Business Name")) or "lead"
        machine.log(f"PageSpeed check {checked}/{cap}: {business_name}")
        result = run_pagespeed_for_lead(machine, lead)
        lead.update({key: value for key, value in result.items() if value not in (None, "")})
        if result.get("PageSpeed Status") == "Measured":
            measured += 1
        elif result.get("PageSpeed Status") == "Error":
            errors += 1

    machine.record_stage_report(
        "pagespeed",
        "PageSpeed / CrUX enrichment",
        enabled=True,
        checked=checked,
        measured=measured,
        errors=errors,
        skipped=skipped,
        cap=cap,
    )
    return leads
