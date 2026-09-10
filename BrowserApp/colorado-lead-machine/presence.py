from __future__ import annotations

"""Presence and URL helper functions for the Colorado lead machine."""

import re
import time
from typing import TYPE_CHECKING
from urllib.parse import quote_plus, urlparse

from bs4 import BeautifulSoup
import requests

from lead_machine_presence_config import (
    DIRECTORY_DOMAINS,
    DIRECTORY_LABELS,
    LINK_HUB_DOMAINS,
    MARKETPLACE_DOMAINS,
    PARKED_SITE_MARKERS,
    PARKED_TEXT_ONLY_MARKERS,
    SOCIAL_DOMAINS,
    TEMPLATE_BUILDER_MARKERS,
)

if TYPE_CHECKING:
    from lead_machine import LeadMachine


BUSINESS_DOMAIN_JUNK = {
    "google.com",
    "goo.gl",
    "bit.ly",
    "t.co",
    "youtu.be",
    "youtube.com",
    "apple.com",
    "play.google.com",
    "apps.apple.com",
    "mailto",
    "pinterest.com",
    "reddit.com",
    "tumblr.com",
    "medium.com",
    "wikipedia.org",
    "amazon.com",
}

WEB_PRESENCE_DEFAULT_DETAILS = {
    "No website": "No official website discovered from listing or search",
    "Unknown web presence": "Web presence could not be confirmed with enough evidence",
    "Directory only": "Only directory/listing sites were found",
    "Social only": "Only social-media pages were found",
    "Broken site": "The website link did not load a real business website, or it landed on a parked or placeholder page",
    "Weak site": "The website loads, but it has quality gaps that may hurt trust, calls, or bookings",
    "Basic site": "The website loads and covers some basics, but is missing elements that could improve trust, leads, or conversions",
    "Real website": "Standalone website responded successfully",
}


def _clean_attempt(result: dict[str, object], *, raw_result_count: int = 0, links: list[str] | None = None) -> dict[str, object]:
    return {
        "provider": str(result.get("provider", "")),
        "query": str(result.get("query", "")),
        "url": str(result.get("url", "")),
        "final_url": str(result.get("final_url", "")),
        "ok": bool(result.get("ok")),
        "status_code": int(result.get("status_code") or 0),
        "error_type": str(result.get("error_type", "")),
        "error_message": str(result.get("error_message", "")),
        "blocked": bool(result.get("blocked")),
        "timeout": bool(result.get("timeout")),
        "body_length": int(result.get("body_length") or 0),
        "raw_result_count": int(raw_result_count or 0),
        "retry_recommended": bool(result.get("retry_recommended")),
        "attempted_urls": list(result.get("attempted_urls") or []),
        "http_statuses": list(result.get("http_statuses") or []),
        "result_urls": list(links or [])[:8],
    }


def _summarize_discovery_attempts(attempts: list[dict[str, object]]) -> dict[str, object]:
    providers: list[str] = []
    queries: list[str] = []
    urls: list[str] = []
    statuses: list[str] = []
    failures: list[str] = []
    source_labels: list[str] = []
    raw_count = 0
    retry_reasons: list[str] = []

    for attempt in attempts:
        provider = str(attempt.get("provider", "")).strip()
        query = str(attempt.get("query", "")).strip()
        if provider:
            providers.append(provider)
            source_labels.append(provider)
        if query:
            queries.append(query)
        for url in attempt.get("attempted_urls", []) or []:
            if url:
                urls.append(str(url))
        for url in attempt.get("result_urls", []) or []:
            if url:
                urls.append(str(url))
        for status in attempt.get("http_statuses", []) or []:
            if status:
                statuses.append(str(status))
        raw_count += int(attempt.get("raw_result_count") or 0)
        error_type = str(attempt.get("error_type", "")).strip()
        error_message = str(attempt.get("error_message", "")).strip()
        if error_type or error_message:
            failures.append(": ".join(part for part in [provider, error_type or error_message] if part))
        if attempt.get("retry_recommended"):
            retry_reasons.append(error_type or error_message or provider or "retryable discovery issue")

    dedupe = lambda values: list(dict.fromkeys(value for value in values if str(value).strip()))
    retry_reasons = dedupe(retry_reasons)
    return {
        "providers": dedupe(providers),
        "queries": dedupe(queries),
        "urls": dedupe(urls),
        "statuses": dedupe(statuses),
        "failures": dedupe(failures),
        "raw_count": raw_count,
        "retry_recommended": bool(retry_reasons),
        "retry_reason": "; ".join(retry_reasons[:4]),
        "source_labels": dedupe(source_labels),
    }


def _get_website_evidence_defaults() -> dict[str, object]:
    from lead_machine import WEBSITE_EVIDENCE_DEFAULTS

    return WEBSITE_EVIDENCE_DEFAULTS


def check_directory(machine: "LeadMachine", url: str) -> str:
    lowered = url.lower().strip()
    if not lowered:
        return ""
    for directory_domain in DIRECTORY_DOMAINS:
        if directory_domain in lowered:
            return DIRECTORY_LABELS.get(directory_domain, f"3rd-party listing ({directory_domain})")
    return ""


def is_social_url(machine: "LeadMachine", url: str) -> bool:
    domain = machine.normalize_domain(url)
    return any(domain == social or domain.endswith(f".{social}") for social in SOCIAL_DOMAINS)


def is_link_hub_url(machine: "LeadMachine", url: str) -> bool:
    domain = machine.normalize_domain(url)
    return any(domain == hub or domain.endswith(f".{hub}") for hub in LINK_HUB_DOMAINS)


def is_marketplace_url(machine: "LeadMachine", url: str) -> bool:
    domain = machine.normalize_domain(url)
    return any(domain == market or domain.endswith(f".{market}") for market in MARKETPLACE_DOMAINS)


def extract_links_from_page(machine: "LeadMachine", html: str, base_url: str) -> list[str]:
    if not html:
        return []
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        return []
    links: list[str] = []
    base_domain = machine.normalize_domain(base_url)
    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"]).strip()
        if not href or href.startswith(("javascript:", "#", "mailto:", "tel:")):
            continue
        if not href.startswith("http"):
            if href.startswith("/"):
                parsed_base = urlparse(base_url)
                href = f"{parsed_base.scheme}://{parsed_base.netloc}{href}"
            else:
                continue
        link_domain = machine.normalize_domain(href)
        if link_domain and link_domain != base_domain:
            links.append(href)
    return links


def extract_website_from_social_bio(machine: "LeadMachine", social_url: str) -> str:
    domain = machine.normalize_domain(social_url)
    try:
        if "facebook.com" in domain:
            return machine._extract_facebook_website(social_url)
        if "instagram.com" in domain:
            return machine._extract_instagram_website(social_url)
        if "linkedin.com" in domain:
            return machine._extract_linkedin_website(social_url)
    except Exception:
        pass
    return ""


def extract_facebook_website(machine: "LeadMachine", fb_url: str) -> str:
    about_url = fb_url.rstrip("/") + "/about"
    html, final_url = machine.fetch_page(about_url, timeout=8)
    if not html:
        html, final_url = machine.fetch_page(fb_url, timeout=8)
    if not html:
        return ""
    outbound = machine.extract_links_from_page(html, final_url or fb_url)
    for link in outbound:
        if not machine.is_social_url(link) and not machine.check_directory(link) and not machine.is_link_hub_url(link):
            if machine._looks_like_business_domain(link):
                return link
    for link in outbound:
        if machine.is_link_hub_url(link):
            hub_site = machine._follow_link_hub(link)
            if hub_site:
                return hub_site
    return ""


def extract_instagram_website(machine: "LeadMachine", ig_url: str) -> str:
    html, final_url = machine.fetch_page(ig_url, timeout=8)
    if not html:
        return ""
    outbound = machine.extract_links_from_page(html, final_url or ig_url)
    for link in outbound:
        if machine.is_link_hub_url(link):
            hub_site = machine._follow_link_hub(link)
            if hub_site:
                return hub_site
        if not machine.is_social_url(link) and not machine.check_directory(link) and not machine.is_link_hub_url(link):
            if machine._looks_like_business_domain(link):
                return link
    return ""


def extract_linkedin_website(machine: "LeadMachine", li_url: str) -> str:
    html, final_url = machine.fetch_page(li_url, timeout=8)
    if not html:
        return ""
    outbound = machine.extract_links_from_page(html, final_url or li_url)
    for link in outbound:
        if not machine.is_social_url(link) and not machine.check_directory(link) and not machine.is_link_hub_url(link):
            if machine._looks_like_business_domain(link):
                return link
    return ""


def follow_link_hub(machine: "LeadMachine", hub_url: str) -> str:
    html, final_url = machine.fetch_page(hub_url, timeout=8)
    if not html:
        return ""
    outbound = machine.extract_links_from_page(html, final_url or hub_url)
    for link in outbound:
        if (
            not machine.is_social_url(link)
            and not machine.check_directory(link)
            and not machine.is_link_hub_url(link)
            and not machine.is_marketplace_url(link)
            and machine._looks_like_business_domain(link)
        ):
            return link
    return ""


def looks_like_business_domain(machine: "LeadMachine", url: str) -> bool:
    domain = machine.normalize_domain(url)
    if not domain:
        return False
    if domain in BUSINESS_DOMAIN_JUNK or any(domain.endswith(f".{junk}") for junk in BUSINESS_DOMAIN_JUNK):
        return False
    if machine.is_social_url(url) or machine.is_marketplace_url(url):
        return False
    return True


def social_platform_name(machine: "LeadMachine", url: str) -> str:
    domain = machine.normalize_domain(url)
    if "instagram.com" in domain:
        return "Instagram"
    if "facebook.com" in domain:
        return "Facebook"
    if "x.com" in domain or "twitter.com" in domain:
        return "X"
    if "tiktok.com" in domain:
        return "TikTok"
    if "nextdoor.com" in domain:
        return "Nextdoor"
    if "alignable.com" in domain:
        return "Alignable"
    if "linkedin.com" in domain:
        return "LinkedIn"
    return domain or "Social"


def social_handle(machine: "LeadMachine", url: str) -> str:
    parsed = urlparse(url.strip() if "://" in url else f"https://{url.strip()}")
    parts = [part for part in parsed.path.split("/") if part]
    if not parts:
        return ""
    if parts[0].lower() in {"company", "in", "pages"} and len(parts) >= 2:
        parts = parts[1:]
    handle = parts[0].strip()
    if not handle or handle.lower() in {"home", "profile", "business", "pages", "pg"}:
        return ""
    cleaned = handle.strip("@/")
    if not cleaned:
        return ""
    return cleaned


def format_social_profile(machine: "LeadMachine", url: str) -> str:
    platform = machine.social_platform_name(url)
    handle = machine.social_handle(url)
    if handle:
        prefix = "/" if platform == "Facebook" else "@"
        return f"{platform}: {prefix}{handle}"
    return f"{platform} profile"


def join_social_profiles(machine: "LeadMachine", profiles: list[str]) -> str:
    formatted: list[str] = []
    seen: set[str] = set()
    for profile in profiles[:6]:
        label = machine.format_social_profile(profile)
        if label not in seen:
            seen.add(label)
            formatted.append(label)
    return "; ".join(formatted)


def join_social_profile_urls(machine: "LeadMachine", profiles: list[str]) -> str:
    return ", ".join(profiles[:6])


def looks_parked_or_placeholder(machine: "LeadMachine", html: str) -> bool:
    lowered = html.lower()
    if any(marker in lowered for marker in PARKED_SITE_MARKERS):
        return True
    visible = machine._visible_text(html).lower()
    if any(marker in visible for marker in PARKED_TEXT_ONLY_MARKERS):
        if len(visible.split()) < 80:
            return True
    return False


def detect_template_builder(html: str, resolved_url: str) -> str:
    lowered = html.lower()
    combined = f"{lowered} {resolved_url.lower()}"
    for builder, markers in TEMPLATE_BUILDER_MARKERS.items():
        if any(marker in combined for marker in markers):
            return builder
    return ""


def classify_placeholder_reason(machine: "LeadMachine", html: str, resolved_url: str) -> tuple[str, str]:
    lowered = html.lower()
    visible = machine._visible_text(html).lower()
    domain = machine.normalize_domain(resolved_url) or resolved_url

    if any(marker in lowered for marker in ["domain for sale", "buy this domain", "parked free", "this domain is parked"]):
        return (
            f"This web address appears to be parked or listed for sale, so visitors are likely seeing a generic holding page instead of a real business website ({domain})",
            "parked domain or for-sale page",
        )
    if any(marker in visible for marker in ["website coming soon", "coming soon", "under construction"]):
        return (
            "This page looks like a coming-soon or under-construction page, so customers are not landing on a finished business website yet",
            "coming-soon or under-construction page",
        )
    if "default web site page" in lowered:
        return (
            "This domain is showing the hosting company's default starter page instead of the business website",
            "default hosting page",
        )
    return (
        "The website is landing on a holding page instead of a usable business website",
        "holding or placeholder page",
    )


def visible_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all(("script", "style", "noscript")):
        tag.decompose()
    return soup.get_text(" ", strip=True)


def text_word_count(html: str) -> int:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all(("script", "style", "noscript", "template")):
        tag.decompose()
    for tag in soup.find_all(True):
        if not getattr(tag, "attrs", None):
            continue
        style_attr = str(tag.attrs.get("style", "")).lower()
        aria_hidden = str(tag.attrs.get("aria-hidden", "")).lower()
        hidden_attr = tag.attrs.get("hidden")
        if (
            "display:none" in style_attr.replace(" ", "")
            or "visibility:hidden" in style_attr.replace(" ", "")
            or aria_hidden == "true"
            or hidden_attr is not None and hidden_attr is not False
        ):
            tag.decompose()
    text = soup.get_text(" ", strip=True)
    return len(re.findall(r"[A-Za-z0-9]{2,}", text))


def unique_phone_matches(text: str, phone_re: re.Pattern[str]) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for candidate in phone_re.findall(text):
        phone = re.sub(r"\s+", " ", str(candidate)).strip()
        normalized = re.sub(r"\D", "", phone)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        found.append(phone)
    return found


_INNER_PAGE_PATTERNS = {
    "contact": ["contact", "contact-us", "contact_us", "get-in-touch", "reach-us"],
    "about": ["about", "about-us", "about_us", "our-story", "who-we-are", "our-team", "team"],
    "services": ["services", "our-services", "what-we-do", "solutions", "products", "offerings", "menu"],
}


def extract_site_evidence(
    machine: "LeadMachine",
    html: str,
    resolved_url: str,
    *,
    http_status: int | None = None,
    fetch_time_ms: int | None = None,
) -> dict[str, object]:
    lowered = html.lower()
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        soup = None
    title_text = ""
    meta_description = ""
    visible = ""
    internal_link_count = 0

    if soup:
        title_tag = soup.find("title")
        title_text = title_tag.get_text(" ", strip=True) if title_tag else ""
        meta_tag = soup.find("meta", attrs={"name": re.compile("^description$", re.IGNORECASE)})
        meta_description = str(meta_tag.get("content", "")).strip() if meta_tag else ""
        for tag_name in ("script", "style", "noscript"):
            for tag in soup.find_all(tag_name):
                tag.decompose()
        visible = soup.get_text(" ", strip=True)
        image_count = len([img for img in soup.find_all("img", src=True) if str(img.get("src", "")).strip()])
        form_count = len(soup.find_all("form"))
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href", "")).strip().lower()
            if not href or href.startswith(("javascript:", "#", "mailto:", "tel:")):
                continue
            if href.startswith("http") and not machine.domains_look_related(resolved_url, href):
                continue
            internal_link_count += 1
    else:
        title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        title_text = title_match.group(1).strip() if title_match else ""
        meta_match = re.search(
            r"<meta[^>]+name=[\"']description[\"'][^>]+content=[\"'](.*?)[\"']",
            html,
            re.IGNORECASE | re.DOTALL,
        )
        meta_description = meta_match.group(1).strip() if meta_match else ""
        visible = re.sub(r"<[^>]+>", " ", html)
        image_count = len(re.findall(r"<img\b", html, re.IGNORECASE))
        form_count = len(re.findall(r"<form\b", html, re.IGNORECASE))
        internal_link_count = len(re.findall(r"<a\b", html, re.IGNORECASE))

    word_count = machine.text_word_count(html)
    has_viewport = "viewport" in lowered
    phones = machine._unique_phone_matches(visible or html)
    emails = machine.extract_emails(html)

    cta_terms_master = [
        "call now",
        "contact us",
        "get started",
        "request quote",
        "get quote",
        "free estimate",
        "book now",
        "book online",
        "request service",
        "schedule",
        "appointment",
        "estimate",
    ]
    cta_terms = [term for term in cta_terms_master if term in lowered]
    booking_terms = [
        term
        for term in [
            "request quote",
            "get quote",
            "free estimate",
            "book now",
            "book online",
            "request service",
            "schedule",
            "appointment",
        ]
        if term in lowered
    ]

    broken_links: list[str] = []
    checked_links = 0
    if soup and resolved_url:
        seen_hrefs: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href", "")).strip()
            if not href or href.startswith(("javascript:", "#", "mailto:", "tel:")):
                continue
            if href.startswith("/"):
                parsed_base = urlparse(resolved_url)
                abs_url = f"{parsed_base.scheme}://{parsed_base.netloc}{href}"
            elif href.startswith("http"):
                abs_url = href
            else:
                continue
            if not machine.domains_look_related(resolved_url, abs_url):
                continue
            if abs_url in seen_hrefs:
                continue
            seen_hrefs.add(abs_url)
            if checked_links >= 15:
                break
            checked_links += 1
            try:
                link_resp, _link_exc = machine._try_fetch(abs_url, timeout=(3.0, 5.0))
                if link_resp is not None and link_resp.status_code in {404, 410, 500, 502, 503}:
                    broken_links.append(f"{href} (HTTP {link_resp.status_code})")
                elif link_resp is None:
                    broken_links.append(f"{href} (unreachable)")
            except Exception:
                pass
    broken_link_count = len(broken_links)
    broken_link_ratio = broken_link_count / max(checked_links, 1) if checked_links > 0 else 0.0

    outdated_markers: list[str] = []
    if re.search(r"<table\b[^>]*>\s*<tr\b[^>]*>\s*<td\b", html, re.IGNORECASE | re.DOTALL):
        table_count = len(re.findall(r"<table\b", html, re.IGNORECASE))
        if table_count >= 3:
            outdated_markers.append("table-based layout")
    if re.search(r"(\.swf|swfobject|flash|shockwave)", lowered):
        outdated_markers.append("Flash content detected")
    if re.search(r"<frameset|<frame\b|<iframe\b[^>]*width=['\"]100%", lowered):
        outdated_markers.append("frameset/frame layout")
    if re.search(r"<marquee|<blink|<center>", lowered):
        outdated_markers.append("deprecated HTML tags (marquee/blink/center)")
    copyright_match = re.search(r"(?:Â©|&copy;|copyright)\s*(\d{4})", lowered)
    if copyright_match:
        copyright_year = int(copyright_match.group(1))
        if copyright_year <= 2019:
            outdated_markers.append(f"copyright year {copyright_year}")
    if not has_viewport and word_count > 50:
        outdated_markers.append("no mobile/responsive design")

    has_google_analytics = bool(
        re.search(r"(google[_-]?analytics|gtag|UA-\d{4,}|G-[A-Z0-9]+|googletagmanager\.com|gtm\.js)", lowered)
    )
    has_facebook_pixel = bool(
        re.search(r"(fbq\(|facebook\.net/en_US/fbevents|connect\.facebook\.net)", lowered)
    )
    has_schema_markup = bool(
        re.search(r'(application/ld\+json|itemtype=["\']https?://schema\.org)', lowered)
    )
    has_robots_meta = bool(
        re.search(r'<meta\s[^>]*name=["\']robots["\']', lowered)
    )
    has_canonical = bool(
        re.search(r'<link\s[^>]*rel=["\']canonical["\']', lowered)
    )
    has_og_tags = bool(
        re.search(r'<meta\s[^>]*property=["\']og:', lowered)
    )

    booking_platforms_detected: list[str] = []
    booking_platform_markers = {
        "Calendly": ["calendly.com"],
        "Acuity Scheduling": ["acuityscheduling.com", "squareup.com/appointments"],
        "Square Appointments": ["squareup.com/appointments"],
        "Booksy": ["booksy.com"],
        "HouseCall Pro": ["housecallpro.com"],
        "ServiceTitan": ["servicetitan.com"],
        "Jobber": ["getjobber.com"],
        "Mindbody": ["mindbody.io", "mindbodyonline.com"],
        "Vagaro": ["vagaro.com"],
        "SimplyBook": ["simplybook.me"],
    }
    for platform, markers in booking_platform_markers.items():
        if any(marker in lowered for marker in markers):
            booking_platforms_detected.append(platform)

    social_links_found: list[str] = []
    social_link_domains = {
        "Facebook": ["facebook.com/", "fb.com/"],
        "Instagram": ["instagram.com/"],
        "Twitter/X": ["twitter.com/", "x.com/"],
        "LinkedIn": ["linkedin.com/"],
        "YouTube": ["youtube.com/", "youtu.be/"],
        "TikTok": ["tiktok.com/"],
        "Pinterest": ["pinterest.com/"],
        "Nextdoor": ["nextdoor.com/"],
    }
    for platform, domains in social_link_domains.items():
        if any(domain in lowered for domain in domains):
            social_links_found.append(platform)

    has_review_widgets = bool(
        re.search(r"(birdeye\.com|podium\.com|trustpilot\.com|yotpo\.com|google.*reviews?.*widget|elfsight.*review)", lowered)
    )
    has_chat_widget = bool(
        re.search(r"(tawk\.to|livechat|drift\.com|intercom|crisp\.chat|hubspot.*chat|tidio|zendesk.*chat)", lowered)
    )
    has_accessibility = bool(
        re.search(r'(aria-label|role=["\']navigation|role=["\']main|accessibilitywidget|accessibe\.com|userway\.org)', lowered)
    )

    if soup:
        imgs_with_alt = len([img for img in soup.find_all("img") if img.get("alt", "").strip()])
    else:
        imgs_with_alt = len(re.findall(r'<img\b[^>]*\balt=["\'][^"\']+["\']', html, re.IGNORECASE))

    snippet = re.sub(r"\s+", " ", visible).strip()
    if len(snippet) > 240:
        snippet = f"{snippet[:237].rstrip()}..."

    summary_parts: list[str] = []
    if http_status is not None:
        summary_parts.append(f"HTTP {http_status}")
    if fetch_time_ms:
        summary_parts.append(f"basic fetch {fetch_time_ms} ms")
    if title_text:
        summary_parts.append(f"title: {title_text}")
    if meta_description:
        summary_parts.append("meta description present")
    summary_parts.append(f"{word_count} words")
    summary_parts.append(f"{form_count} form(s)")
    summary_parts.append(f"{internal_link_count} internal link(s)")
    summary_parts.append(f"{image_count} image(s)")
    summary_parts.append("viewport meta found" if has_viewport else "no viewport meta")
    if phones:
        summary_parts.append(f"phone on page: {phones[0]}")
    if emails:
        summary_parts.append(f"email on page: {emails[0]}")
    if cta_terms:
        summary_parts.append(f"CTA terms: {', '.join(cta_terms[:4])}")
    if booking_terms:
        summary_parts.append(f"booking terms: {', '.join(booking_terms[:4])}")
    if has_google_analytics:
        summary_parts.append("Google Analytics detected")
    if has_facebook_pixel:
        summary_parts.append("Facebook Pixel detected")
    if has_schema_markup:
        summary_parts.append("schema.org markup found")
    if booking_platforms_detected:
        summary_parts.append(f"booking platform: {', '.join(booking_platforms_detected)}")
    if social_links_found:
        summary_parts.append(f"social links: {', '.join(social_links_found[:4])}")
    if has_review_widgets:
        summary_parts.append("review widget detected")
    if has_chat_widget:
        summary_parts.append("chat widget detected")
    if broken_link_count:
        summary_parts.append(f"{broken_link_count}/{checked_links} internal links broken")
    if outdated_markers:
        summary_parts.append(f"outdated design: {', '.join(outdated_markers[:3])}")

    return {
        "Resolved Website URL": resolved_url,
        "HTTP Status": str(http_status) if http_status is not None else "",
        "Fetch Time Ms": int(fetch_time_ms or 0),
        "Page Title": title_text,
        "Meta Description": meta_description,
        "Word Count": word_count,
        "Form Count": form_count,
        "Internal Link Count": internal_link_count,
        "Image Count": image_count,
        "On-Page Phones": ", ".join(phones[:3]),
        "On-Page Emails": ", ".join(emails[:3]),
        "CTA Terms": ", ".join(cta_terms[:6]),
        "Booking Terms": ", ".join(booking_terms[:6]),
        "Viewport Meta": "Found" if has_viewport else "Not found",
        "Google Analytics": "Detected" if has_google_analytics else "Not found",
        "Facebook Pixel": "Detected" if has_facebook_pixel else "Not found",
        "Schema Markup": "Found" if has_schema_markup else "Not found",
        "Open Graph Tags": "Found" if has_og_tags else "Not found",
        "Canonical Tag": "Found" if has_canonical else "Not found",
        "Robots Meta": "Found" if has_robots_meta else "Not found",
        "Booking Platforms": ", ".join(booking_platforms_detected) if booking_platforms_detected else "None detected",
        "Social Links": ", ".join(social_links_found) if social_links_found else "None found",
        "Review Widget": "Detected" if has_review_widgets else "Not found",
        "Chat Widget": "Detected" if has_chat_widget else "Not found",
        "Accessibility Indicators": "Found" if has_accessibility else "Not found",
        "Images With Alt Text": imgs_with_alt,
        "Broken Link Count": broken_link_count,
        "Broken Links Checked": checked_links,
        "Broken Link Ratio": round(broken_link_ratio, 2),
        "Broken Links": "; ".join(broken_links[:10]) if broken_links else "",
        "Outdated Design Markers": ", ".join(outdated_markers) if outdated_markers else "",
        "Website Evidence Summary": "; ".join(summary_parts),
        "Website Evidence Snippet": snippet,
        "_has_viewport": has_viewport,
        "_has_contact_cues": any(
            token in lowered for token in ["contact us", "contact", "mailto:", "tel:", "/contact", "/about", "/locations"]
        ),
        "_has_contact_info": bool(phones or emails),
        "_cta_terms": cta_terms,
        "_title_text": title_text.lower(),
    }


def discover_inner_page_urls(machine: "LeadMachine", html: str, resolved_url: str) -> dict[str, str]:
    """Find candidate inner page URLs from homepage nav links."""
    if not html:
        return {}
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        return {}

    parsed_base = urlparse(resolved_url)
    base_origin = f"{parsed_base.scheme}://{parsed_base.netloc}"
    found: dict[str, str] = {}

    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"]).strip()
        if not href or href.startswith(("javascript:", "#", "mailto:", "tel:")):
            continue

        if href.startswith("/"):
            abs_url = f"{base_origin}{href}"
        elif href.startswith("http"):
            if not machine.domains_look_related(resolved_url, href):
                continue
            abs_url = href
        else:
            abs_url = f"{base_origin}/{href}"

        path = urlparse(abs_url).path.strip("/").lower()
        link_text = anchor.get_text(" ", strip=True).lower()

        for page_type, patterns in _INNER_PAGE_PATTERNS.items():
            if page_type in found:
                continue
            if any(pattern == path or path.endswith(f"/{pattern}") for pattern in patterns):
                found[page_type] = abs_url
                break
            if any(pattern.replace("-", " ") in link_text or pattern.replace("_", " ") in link_text for pattern in patterns):
                found[page_type] = abs_url
                break

        if len(found) >= 3:
            break

    return found


def fetch_inner_page_evidence(machine: "LeadMachine", resolved_url: str, homepage_html: str) -> dict[str, object]:
    """Fetch up to 2 inner pages and extract targeted evidence."""
    inner_urls = machine._discover_inner_page_urls(homepage_html, resolved_url)
    result: dict[str, object] = {
        "Inner Pages Checked": 0,
        "Inner Page URLs": "",
        "Total Word Count": 0,
        "Contact Page Found": "",
        "Contact Page Has Form": "",
        "Services Described": "",
        "About Page Found": "",
    }

    if not inner_urls:
        return result

    priority_order = ["contact", "services", "about"]
    pages_to_fetch = []
    for page_type in priority_order:
        if page_type in inner_urls:
            pages_to_fetch.append((page_type, inner_urls[page_type]))
        if len(pages_to_fetch) >= 2:
            break

    checked_urls: list[str] = []
    inner_word_count = 0

    for page_type, url in pages_to_fetch:
        machine._check_stop()
        try:
            page_html, final_url = machine.fetch_page(url, timeout=8)
        except Exception:
            page_html = None
            final_url = None

        if not page_html:
            continue

        checked_urls.append(url)
        page_words = machine.text_word_count(page_html)
        inner_word_count += page_words

        if page_type == "contact":
            result["Contact Page Found"] = "Yes"
            try:
                soup = BeautifulSoup(page_html, "lxml")
                contact_forms = len(soup.find_all("form"))
            except Exception:
                contact_forms = len(re.findall(r"<form\b", page_html, re.IGNORECASE))
            result["Contact Page Has Form"] = "Yes" if contact_forms > 0 else "No"
        elif page_type == "services":
            result["Services Described"] = "Yes" if page_words >= 50 else "Thin"
        elif page_type == "about":
            result["About Page Found"] = "Yes"

    result["Inner Pages Checked"] = len(checked_urls)
    result["Inner Page URLs"] = ", ".join(checked_urls)
    result["Total Word Count"] = inner_word_count
    return result


def inspect_site_quality(
    machine: "LeadMachine",
    html: str,
    resolved_url: str,
    *,
    http_status: int | None = None,
    fetch_time_ms: int | None = None,
) -> tuple[str, str, str, dict[str, object]]:
    signals: list[str] = []
    strengths: list[str] = []
    issues: list[str] = []

    quality_score = 100
    bonus_budget_remaining = 10

    def add_strength(message: str) -> None:
        signals.append(message)
        strengths.append(message)

    def add_issue(message: str, penalty: int = 0) -> None:
        nonlocal quality_score
        signals.append(message)
        issues.append(message)
        quality_score -= penalty

    def add_bonus(message: str, bonus: int = 0) -> None:
        nonlocal quality_score, bonus_budget_remaining
        signals.append(message)
        strengths.append(message)
        applied = min(bonus, max(0, bonus_budget_remaining))
        bonus_budget_remaining -= applied
        quality_score += applied

    site_evidence = machine.extract_site_evidence(
        html,
        resolved_url,
        http_status=http_status,
        fetch_time_ms=fetch_time_ms,
    )

    inner_evidence = machine._fetch_inner_page_evidence(resolved_url, html)
    site_evidence.update(inner_evidence)
    homepage_words = int(site_evidence.get("Word Count") or 0)
    site_evidence["Total Word Count"] = homepage_words + int(inner_evidence.get("Total Word Count") or 0)

    title_text = str(site_evidence.get("_title_text", ""))
    nav_links = int(site_evidence.get("Internal Link Count") or 0)
    image_count = int(site_evidence.get("Image Count") or 0)
    form_count = int(site_evidence.get("Form Count") or 0)
    word_count = int(site_evidence.get("Word Count") or 0)
    has_contact_cues = bool(site_evidence.get("_has_contact_cues"))
    has_contact_info = bool(site_evidence.get("_has_contact_info"))
    cta_terms = list(site_evidence.get("_cta_terms", []))

    if bool(site_evidence.get("_has_viewport")):
        add_strength("site appears set up for phones and smaller screens")
    else:
        add_issue("site may not be set up well for phones and smaller screens", 10)

    if nav_links >= 5:
        add_strength(f"visitors can move through the site with {nav_links} real links or pages")
    else:
        add_issue(f"visitors only get {nav_links} real links or pages, so navigation feels thin", 10)

    if has_contact_cues:
        add_strength("site gives a clear way to contact or find the business")
    else:
        add_issue("site does not clearly show a contact page, location section, or about page", 12)

    if has_contact_info:
        add_strength("site shows a phone number or email on the page")
    else:
        add_issue("site does not show a phone number or email on the page", 10)

    if form_count > 0 or cta_terms:
        add_strength("site gives visitors a clear next step like quote, booking, or service request")
    else:
        add_issue("site does not give visitors a clear next step like quote, booking, or estimate", 12)

    if word_count >= 350:
        add_strength(f"site has enough written content to explain the business ({word_count} words)")
    elif word_count >= 150:
        add_issue(f"site has some written content but not much depth ({word_count} words)", 10)
    else:
        add_issue(f"site has very little written content ({word_count} words)", 18)

    if image_count >= 3:
        add_strength(f"site includes visual proof like team, project, or service photos ({image_count} images)")
    else:
        add_issue(f"site has few usable images, so there is little visual proof ({image_count} images)", 8)

    if title_text and title_text not in {"home", "welcome", "index"} and len(title_text) >= 8:
        add_strength("page title clearly describes the business")
    else:
        add_issue("page title is generic or missing", 5)

    has_analytics = site_evidence.get("Google Analytics") == "Detected" or site_evidence.get("Facebook Pixel") == "Detected"
    has_schema = site_evidence.get("Schema Markup") == "Found"
    has_booking_platform = site_evidence.get("Booking Platforms", "None detected") != "None detected"
    has_review_widget = site_evidence.get("Review Widget") == "Detected"
    has_chat = site_evidence.get("Chat Widget") == "Detected"
    social_links = site_evidence.get("Social Links", "None found")
    social_link_count = 0 if social_links == "None found" else len(str(social_links).split(", "))

    if has_analytics:
        add_bonus("site uses analytics tracking (Google Analytics or Facebook Pixel)", 3)
    if has_schema:
        add_bonus("site has structured data (schema.org markup) for search engines", 3)
    if has_booking_platform:
        platform_name = site_evidence.get("Booking Platforms", "")
        add_bonus(f"site integrates a booking platform ({platform_name})", 3)
    if has_review_widget:
        add_bonus("site displays customer reviews via a review widget", 3)
    if has_chat:
        add_bonus("site has a live chat widget for visitor engagement", 2)
    if social_link_count >= 3:
        add_bonus(f"site links to {social_link_count} social media profiles", 2)
    elif social_link_count == 0:
        add_issue("no social media links found on the site", 3)

    broken_link_count = int(site_evidence.get("Broken Link Count") or 0)
    outdated_markers = str(site_evidence.get("Outdated Design Markers", ""))
    if broken_link_count >= 3:
        add_issue(f"{broken_link_count} broken internal links found â€” visitors hitting dead ends", 10)
    elif broken_link_count >= 1:
        add_issue(f"{broken_link_count} broken internal link(s) found", 5)
    if outdated_markers:
        add_issue(f"outdated design elements: {outdated_markers}", 5)

    inner_pages_checked = int(site_evidence.get("Inner Pages Checked") or 0)
    contact_page_found = site_evidence.get("Contact Page Found") == "Yes"
    contact_has_form = site_evidence.get("Contact Page Has Form") == "Yes"
    services_described = str(site_evidence.get("Services Described", ""))
    about_page_found = site_evidence.get("About Page Found") == "Yes"

    if contact_has_form:
        add_bonus("dedicated contact page with a working form", 5)
    elif contact_page_found:
        add_strength("dedicated contact page exists")

    if services_described == "Yes":
        add_bonus("services page describes what the business offers", 5)
    elif services_described == "Thin":
        add_issue("services page exists but has very little content", 3)

    if about_page_found:
        add_bonus("about page helps visitors learn who they are dealing with", 3)

    if inner_pages_checked == 0 and nav_links >= 5:
        add_issue("inner pages could not be verified despite having navigation links", 5)

    if word_count < 200:
        quality_score = min(quality_score, 70)
    if word_count < 100:
        quality_score = min(quality_score, 55)

    quality_score = max(0, min(100, quality_score))
    site_evidence["Quality Score"] = quality_score

    if quality_score >= 80:
        quality = "Established"
        intro = "Website is live and covers the essentials well"
    elif quality_score >= 50:
        quality = "Basic"
        intro = "Website is live but missing a few things that can hurt trust or leads"
    else:
        quality = "Weak"
        intro = "Website is live but looks weak enough that it may be costing the business trust, calls, or bookings"

    issue_priority_markers = [
        "very little written content",
        "some written content but not much depth",
        "does not give visitors a clear next step",
        "does not clearly show a contact page",
        "does not show a phone number or email",
        "few usable images",
        "only get",
        "may not be set up well",
        "page title is generic or missing",
    ]
    prioritized_issues: list[str] = []
    for marker in issue_priority_markers:
        prioritized_issues.extend(issue for issue in issues if marker in issue and issue not in prioritized_issues)
    prioritized_issues.extend(issue for issue in issues if issue not in prioritized_issues)

    if quality == "Weak":
        summary_parts = prioritized_issues[:4] + strengths[:2]
    elif quality == "Basic":
        summary_parts = prioritized_issues[:3] + strengths[:3]
    else:
        summary_parts = strengths[:4] + issues[:2]

    signal_summary = "; ".join(summary_parts or signals[:6])
    details = f"{intro}: {signal_summary}"
    return quality, details, signal_summary, site_evidence


def classify_seed_url_fast(machine: "LeadMachine", url: str) -> tuple[str, str]:
    cleaned = url.strip()
    if not cleaned:
        return "No website", ""
    if machine.is_social_url(cleaned):
        return "Social only", machine.normalize_domain(cleaned)
    directory_label = machine.check_directory(cleaned)
    if directory_label:
        return "Directory only", directory_label
    return "Website listed", machine.normalize_domain(cleaned)


def _retry_site_evidence(reason: str, site_evidence: dict[str, object] | None = None) -> dict[str, object]:
    evidence = dict(site_evidence or {})
    evidence["Retry Recommended"] = "Yes"
    evidence["Retry Reason"] = reason
    evidence["Failure Reasons"] = reason
    return evidence


def classify_request_exception(machine: "LeadMachine", exc: Exception, url: str) -> tuple[str, str, str, str, str]:
    if isinstance(exc, requests.exceptions.SSLError):
        return machine.make_web_result("Broken site", url, "Website failed SSL/TLS validation", "High", "ssl or tls error")
    if isinstance(exc, requests.exceptions.TooManyRedirects):
        return machine.make_web_result("Broken site", url, "Website entered a redirect loop", "Medium", "too many redirects")
    if isinstance(exc, requests.exceptions.ConnectTimeout):
        return machine.make_web_result(
            "Broken site",
            url,
            "Website connection timed out; this may be a temporary availability issue",
            "Low",
            "connection timeout; transient failure",
            site_evidence=_retry_site_evidence("connection timeout"),
        )
    if isinstance(exc, requests.exceptions.ReadTimeout):
        return machine.make_web_result(
            "Broken site",
            url,
            "Website loaded too slowly and timed out; this may be a temporary availability issue",
            "Low",
            "read timeout; transient failure",
            site_evidence=_retry_site_evidence("read timeout"),
        )
    if isinstance(exc, requests.exceptions.ConnectionError):
        return machine.make_web_result(
            "Broken site",
            url,
            "Website could not be reached reliably (DNS or connection failure); this may be temporary",
            "Low",
            "dns or connection failure; transient failure",
            site_evidence=_retry_site_evidence("dns or connection failure"),
        )
    return machine.make_web_result("Broken site", url, "Website request failed unexpectedly", "Medium", "request failure")


def browser_fallback_web_result(machine: "LeadMachine", url: str, reason: str) -> tuple[str, str, str, str, str] | None:
    if not getattr(machine.config, "enable_browser_fallback", True):
        return None
    browser_result = machine.browser_fetch_page_result(url, provider="Playwright fallback")
    html = str(browser_result.get("html") or "")
    if not browser_result.get("ok") or len(html.strip()) < 200:
        return machine.make_web_result(
            "Unknown web presence",
            url,
            f"Requests check was inconclusive ({reason}); browser fallback also failed: {browser_result.get('error_type') or 'empty body'}",
            "Low",
            str(browser_result.get("error_message") or "browser fallback failed"),
            site_evidence={
                "Browser Fallback Used": "Yes",
                "Browser Fallback Reason": reason,
                "Browser Fallback Status": str(browser_result.get("error_type") or "failed"),
                "Retry Recommended": "Yes",
                "Retry Reason": str(browser_result.get("error_type") or "browser fallback failed"),
            },
        )
    final_url = str(browser_result.get("final_url") or url)
    quality, details, signal_summary, site_evidence = machine.inspect_site_quality(
        html,
        final_url,
        http_status=int(browser_result.get("status_code") or 0) or None,
        fetch_time_ms=int(browser_result.get("elapsed_ms") or 0) or None,
    )
    site_evidence.update(
        {
            "Browser Fallback Used": "Yes",
            "Browser Fallback Reason": reason,
            "Browser Fallback Status": "Rendered",
        }
    )
    if quality == "Weak":
        status = "Weak site"
    elif quality == "Basic":
        status = "Basic site"
    else:
        status = "Real website"
    return machine.make_web_result(
        status,
        final_url,
        f"Browser fallback rendered the page after requests was inconclusive ({reason}); {details}",
        "Medium",
        f"browser fallback rendered page; {signal_summary}",
        site_evidence=site_evidence,
    )


def classify_known_web_presence(machine: "LeadMachine", url: str) -> tuple[str, str, str, str, str]:
    cleaned = url.strip()
    if not cleaned:
        return machine.make_web_result("No website", "", "No website listed in seed data", "Medium", "no listed URL")

    if machine.is_social_url(cleaned):
        domain = machine.normalize_domain(cleaned)
        return machine.make_web_result("Social only", cleaned, f"Only social profile found: {domain}", "High", domain)

    if machine.is_marketplace_url(cleaned):
        domain = machine.normalize_domain(cleaned)
        return machine.make_web_result("Directory only", cleaned, f"Marketplace/default platform page: {domain}", "High", f"marketplace ({domain})")

    if machine.is_link_hub_url(cleaned):
        real_site = machine._follow_link_hub(cleaned)
        if real_site:
            return machine.classify_known_web_presence(real_site)
        domain = machine.normalize_domain(cleaned)
        return machine.make_web_result("Social only", cleaned, f"Link-in-bio page with no website link: {domain}", "Medium", f"link hub only ({domain})")

    directory_label = machine.check_directory(cleaned)
    if directory_label:
        return machine.make_web_result("Directory only", cleaned, f"Only directory result found: {directory_label}", "High", directory_label)

    try:
        retried_transient = False
        response, tried_url, was_fallback = machine._fetch_with_fallbacks(cleaned)
        if response is None:
            return machine.make_web_result(
                "Broken site",
                cleaned,
                "Website could not be reached after multiple attempts and URL variations",
                "Low",
                "unreachable after retries and fallbacks",
                site_evidence=_retry_site_evidence("unreachable after retries and URL fallbacks"),
            )
        resolved_url = response.url or tried_url
        fetch_time_ms = int(round(response.elapsed.total_seconds() * 1000)) if getattr(response, "elapsed", None) else 0
        redirect_note = ""
        if resolved_url and resolved_url != cleaned:
            redirect_note = f"redirected to {machine.normalize_domain(resolved_url)}"

        if machine.is_social_url(resolved_url):
            domain = machine.normalize_domain(resolved_url)
            detail = f"Website URL redirects to social profile: {domain}"
            if redirect_note:
                detail = f"{detail} ({redirect_note})"
            return machine.make_web_result("Social only", resolved_url, detail, "High", f"redirects to social profile; {domain}")

        redirected_directory = machine.check_directory(resolved_url)
        if redirected_directory:
            detail = f"Website URL redirects to directory listing: {redirected_directory}"
            if redirect_note:
                detail = f"{detail} ({redirect_note})"
            return machine.make_web_result(
                "Directory only",
                resolved_url,
                detail,
                "High",
                f"redirects to directory listing; {redirected_directory}",
            )

        if response.status_code in {404, 410}:
            detail = f"Website returned HTTP {response.status_code} (page missing or removed)"
            if redirect_note:
                detail = f"{detail}; {redirect_note}"
            site_evidence = machine.extract_site_evidence(
                response.text,
                resolved_url,
                http_status=response.status_code,
                fetch_time_ms=fetch_time_ms,
            )
            return machine.make_web_result(
                "Broken site",
                resolved_url,
                detail,
                "High",
                f"http {response.status_code}; dead page",
                site_evidence=site_evidence,
            )
        if response.status_code in {401, 403}:
            site_evidence = machine.extract_site_evidence(
                response.text,
                resolved_url,
                http_status=response.status_code,
                fetch_time_ms=fetch_time_ms,
            )
            has_html_content = len(response.text or "") > 500
            fallback_result = browser_fallback_web_result(machine, resolved_url, f"HTTP {response.status_code}")
            if fallback_result:
                return fallback_result
            site_evidence = _retry_site_evidence(f"http {response.status_code} blocked automated check", site_evidence)
            if response.status_code == 403 and has_html_content:
                detail = "Website exists but blocks automated visitors (HTTP 403); likely has Cloudflare or firewall protection"
                if redirect_note:
                    detail = f"{detail}; {redirect_note}"
                return machine.make_web_result(
                    "Weak site",
                    resolved_url,
                    detail,
                    "Medium",
                    f"access denied but site exists; {machine.normalize_domain(resolved_url)}",
                    site_evidence=site_evidence,
                )
            detail = f"Website blocked visitors with HTTP {response.status_code} (access denied)"
            if redirect_note:
                detail = f"{detail}; {redirect_note}"
            return machine.make_web_result(
                "Broken site",
                resolved_url,
                detail,
                "High",
                f"access denied; {machine.normalize_domain(resolved_url)}",
                site_evidence=site_evidence,
            )
        if response.status_code == 429:
            detail = "Website blocked the automated check with HTTP 429 (rate limited)"
            if retried_transient:
                detail = f"{detail} after retry"
            if redirect_note:
                detail = f"{detail}; {redirect_note}"
            site_evidence = machine.extract_site_evidence(
                response.text,
                resolved_url,
                http_status=response.status_code,
                fetch_time_ms=fetch_time_ms,
            )
            site_evidence = _retry_site_evidence("http 429 rate limited automated check", site_evidence)
            return machine.make_web_result(
                "Unknown web presence",
                resolved_url,
                detail,
                "Low",
                "rate limited automated request; retry needed",
                site_evidence=site_evidence,
            )
        if response.status_code == 408:
            detail = "Website returned HTTP 408 (request timeout); this may be temporary"
            if retried_transient:
                detail = f"{detail} after retry"
            if redirect_note:
                detail = f"{detail}; {redirect_note}"
            site_evidence = machine.extract_site_evidence(
                response.text,
                resolved_url,
                http_status=response.status_code,
                fetch_time_ms=fetch_time_ms,
            )
            site_evidence = _retry_site_evidence("http 408 request timeout", site_evidence)
            return machine.make_web_result(
                "Unknown web presence",
                resolved_url,
                detail,
                "Low",
                "http 408; transient timeout",
                site_evidence=site_evidence,
            )
        if response.status_code >= 500:
            import time as _time

            _time.sleep(1)
            retry_resp, _retry_exc = machine._try_fetch(resolved_url, timeout=machine._SHORT_FETCH_TIMEOUT)
            if retry_resp is not None and retry_resp.status_code < 400:
                response = retry_resp
                resolved_url = retry_resp.url or resolved_url
                fetch_time_ms = int(round(retry_resp.elapsed.total_seconds() * 1000)) if getattr(retry_resp, "elapsed", None) else 0
            else:
                detail = f"Website returned server error HTTP {response.status_code}"
                if redirect_note:
                    detail = f"{detail}; {redirect_note}"
                site_evidence = machine.extract_site_evidence(
                    response.text,
                    resolved_url,
                    http_status=response.status_code,
                    fetch_time_ms=fetch_time_ms,
                )
                site_evidence = _retry_site_evidence(f"http {response.status_code} server error", site_evidence)
                return machine.make_web_result(
                    "Broken site",
                    resolved_url,
                    detail,
                    "Low",
                    f"http {response.status_code}; server error",
                    site_evidence=site_evidence,
                )
        if response.status_code >= 400:
            detail = f"Website returned HTTP {response.status_code}"
            if retried_transient:
                detail = f"{detail} after retry"
            if redirect_note:
                detail = f"{detail}; {redirect_note}"
            site_evidence = machine.extract_site_evidence(
                response.text,
                resolved_url,
                http_status=response.status_code,
                fetch_time_ms=fetch_time_ms,
            )
            return machine.make_web_result(
                "Broken site",
                resolved_url,
                detail,
                "Medium",
                f"http {response.status_code}; review needed",
                site_evidence=site_evidence,
            )
        if machine.looks_parked_or_placeholder(response.text):
            detail, parked_signal = machine.classify_placeholder_reason(response.text, resolved_url)
            if redirect_note:
                detail = f"{detail}; {redirect_note}"
            site_evidence = machine.extract_site_evidence(
                response.text,
                resolved_url,
                http_status=response.status_code,
                fetch_time_ms=fetch_time_ms,
            )
            return machine.make_web_result(
                "Broken site",
                resolved_url,
                detail,
                "High",
                parked_signal,
                site_evidence=site_evidence,
            )

        body_text = response.text or ""
        if len(body_text.strip()) < 200:
            fallback_result = browser_fallback_web_result(machine, resolved_url, "empty or truncated response body")
            if fallback_result:
                return fallback_result
            detail = (
                f"Website returned HTTP {response.status_code} but response body was "
                f"empty or unusable ({len(body_text)} bytes); fetch may have been truncated"
            )
            if redirect_note:
                detail = f"{detail}; {redirect_note}"
            site_evidence = machine.extract_site_evidence(
                body_text,
                resolved_url,
                http_status=response.status_code,
                fetch_time_ms=fetch_time_ms,
            )
            site_evidence = _retry_site_evidence("empty or truncated response body", site_evidence)
            return machine.make_web_result(
                "Unknown web presence",
                resolved_url,
                detail,
                "Low",
                "empty or truncated response body; transient failure",
                site_evidence=site_evidence,
            )

        template_builder = machine.detect_template_builder(response.text, resolved_url)
        quality, details, signal_summary, site_evidence = machine.inspect_site_quality(
            response.text,
            resolved_url,
            http_status=response.status_code,
            fetch_time_ms=fetch_time_ms,
        )
        if template_builder:
            details = f"Built on {template_builder}; {details}"
            signal_summary = f"template builder ({template_builder}); {signal_summary}"
            quality = "Weak"
        if redirect_note:
            details = f"{details}; {redirect_note}"
            signal_summary = f"{signal_summary}; {redirect_note}"
        if response.history and not machine.domains_look_related(cleaned, resolved_url):
            details = f"{details}; redirected from {machine.normalize_domain(cleaned)} to {machine.normalize_domain(resolved_url)}"
            signal_summary = f"{signal_summary}; redirected from {machine.normalize_domain(cleaned)} to {machine.normalize_domain(resolved_url)}"
        if quality == "Weak":
            status = "Weak site"
        elif quality == "Basic":
            status = "Basic site"
        else:
            status = "Real website"
        return machine.make_web_result(
            status,
            resolved_url,
            details,
            "High",
            signal_summary,
            site_evidence=site_evidence,
        )
    except Exception as exc:
        return machine.classify_request_exception(exc, cleaned)


def extract_search_result_links(machine: "LeadMachine", html: str, limit: int = 8) -> list[str]:
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        return []
    links: list[str] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        if not href.startswith("http"):
            continue
        if "duckduckgo.com" in href or "google." in href:
            continue
        cleaned = machine.clean_profile_url(href)
        if cleaned in seen:
            continue
        seen.add(cleaned)
        links.append(cleaned)
        if len(links) >= limit:
            break
    return links


def search_public_links(machine: "LeadMachine", query: str, limit: int = 8) -> list[str]:
    result = search_public_links_with_diagnostics(machine, query, limit=limit)
    return list(result["links"])


def search_public_links_with_diagnostics(machine: "LeadMachine", query: str, limit: int = 8) -> dict[str, object]:
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    fetch_result = machine.fetch_page_result(url, timeout=10, provider="DuckDuckGo HTML", query=query)
    html = str(fetch_result.get("html") or "")
    if not fetch_result.get("ok") or not html:
        attempt = _clean_attempt(fetch_result)
        return {"links": [], "attempt": attempt}
    links = machine.extract_search_result_links(html, limit=limit)
    attempt = _clean_attempt(fetch_result, raw_result_count=len(links), links=links)
    if not links:
        attempt["error_type"] = str(attempt.get("error_type") or "no_results")
        attempt["error_message"] = "Search returned HTML but no usable result links"
    return {"links": links, "attempt": attempt}


def discover_public_profiles(machine: "LeadMachine", name: str, city: str) -> tuple[str, list[str], str]:
    linkedin_queries = [
        f'site:linkedin.com "{name}" "{city}"',
        f'site:linkedin.com/in "{name}" "{city}" owner',
        f'site:linkedin.com/company "{name}" "{city}"',
    ]
    social_queries = [
        f'"{name}" "{city}" facebook instagram',
    ]
    linkedin_url = ""
    social_profiles: list[str] = []
    seen_social: set[str] = set()

    for query in linkedin_queries:
        links = machine.search_public_links(query, limit=8)
        if not links:
            continue
        for href in links:
            cleaned = machine.clean_profile_url(href)
            if machine.is_linkedin_url(cleaned):
                if not linkedin_url:
                    linkedin_url = cleaned
            elif machine.is_social_url(cleaned):
                if cleaned not in seen_social:
                    seen_social.add(cleaned)
                    social_profiles.append(cleaned)
        if linkedin_url:
            break

    for query in social_queries:
        links = machine.search_public_links(query, limit=8)
        if not links:
            continue
        for href in links:
            cleaned = machine.clean_profile_url(href)
            if machine.is_linkedin_url(cleaned):
                if not linkedin_url:
                    linkedin_url = cleaned
            elif machine.is_social_url(cleaned):
                if cleaned not in seen_social:
                    seen_social.add(cleaned)
                    social_profiles.append(cleaned)
            if len(social_profiles) >= 4:
                break

    detail_parts: list[str] = []
    if linkedin_url:
        is_personal = "/in/" in linkedin_url
        detail_parts.append(
            f"LinkedIn {'personal profile' if is_personal else 'company page'} found via profile search"
        )
    if social_profiles:
        detail_parts.append(f"Social profiles found via profile search: {len(social_profiles)}")
    if not detail_parts:
        detail_parts.append("No LinkedIn or social profiles found in profile search")

    return linkedin_url, social_profiles, "; ".join(detail_parts)


def discover_presence_bundle(machine: "LeadMachine", name: str, city: str) -> dict[str, object]:
    results: list[tuple[str, str, str, str, str]] = []
    social_profiles: list[str] = []
    linkedin_url = ""
    profile_parts: list[str] = []
    discovery_sources: list[str] = []
    discovery_attempts: list[dict[str, object]] = []
    no_website_evidence: list[str] = []
    provider_evidence: list[str] = []
    social_bio_sources_checked: list[str] = []
    dataforseo_summary: dict[str, object] = {}
    seen_urls: set[str] = set()
    search_context = machine.search_context_from_area(city)

    def collect_link(href: str) -> None:
        nonlocal linkedin_url
        cleaned = machine.clean_profile_url(href)
        if cleaned in seen_urls:
            return
        seen_urls.add(cleaned)
        if machine.is_social_url(cleaned):
            if machine.is_linkedin_url(cleaned):
                if not linkedin_url:
                    linkedin_url = cleaned
            elif cleaned not in social_profiles:
                social_profiles.append(cleaned)
        elif machine.is_link_hub_url(cleaned):
            hub_site = machine._follow_link_hub(cleaned)
            if hub_site and hub_site not in seen_urls:
                seen_urls.add(hub_site)
                results.append(machine.classify_known_web_presence(hub_site))
                discovery_sources.append(f"link hub ({machine.normalize_domain(cleaned)})")
        else:
            results.append(machine.classify_known_web_presence(cleaned))

    bundle_start = time.time()
    budget_seconds = 45.0

    def budget_left() -> bool:
        return (time.time() - bundle_start) < budget_seconds

    def have_real_site() -> bool:
        if not results:
            return False
        best = machine.choose_web_presence_result(*results)
        return bool(best) and best[0] not in {"No website", "Unknown web presence", "Directory only", "Social only"}

    machine._check_stop()
    query1 = f'"{name}" "{search_context}" official website'
    search1 = search_public_links_with_diagnostics(machine, query1, limit=8)
    discovery_attempts.append(dict(search1.get("attempt", {})))
    links1 = list(search1.get("links", []))
    if links1:
        before_count = len(results)
        for href in links1:
            if not budget_left():
                break
            collect_link(href)
            if len(results) >= 3:
                break
        discovery_sources.append("search: official website")
        if len(results) == before_count:
            no_website_evidence.append("official-website search returned no owned domain")
    elif discovery_attempts[-1].get("ok"):
        no_website_evidence.append("official-website search returned no usable owned-domain result")

    if budget_left() and not have_real_site():
        machine._check_stop()
        query2 = f'"{name}" "{search_context}" site'
        search2 = search_public_links_with_diagnostics(machine, query2, limit=8)
        discovery_attempts.append(dict(search2.get("attempt", {})))
        links2 = list(search2.get("links", []))
        if links2:
            before_count = len(results)
            for href in links2:
                if not budget_left():
                    break
                collect_link(href)
                if len(results) >= 5:
                    break
            discovery_sources.append("search: broad site query")
            if len(results) == before_count:
                no_website_evidence.append("broad site search returned no owned domain")
        elif discovery_attempts[-1].get("ok"):
            no_website_evidence.append("broad site search returned no usable owned-domain result")

    if budget_left() and not have_real_site():
        machine._check_stop()
        dataforseo_summary = dict(machine.dataforseo_serp_discovery(name, search_context, limit=12))
        if dataforseo_summary.get("enabled"):
            discovery_attempts.extend(
                dict(item)
                for item in list(dataforseo_summary.get("attempts", []))
                if isinstance(item, dict)
            )
            provider_evidence.extend(str(item) for item in list(dataforseo_summary.get("provider_evidence", [])) if str(item).strip())
            owned_urls = [str(item) for item in list(dataforseo_summary.get("owned_urls", [])) if str(item).strip()]
            if owned_urls:
                before_count = len(results)
                for href in owned_urls[:4]:
                    if not budget_left():
                        break
                    collect_link(href)
                discovery_sources.append("DataForSEO SERP")
                if len(results) == before_count:
                    no_website_evidence.append("DataForSEO SERP returned candidate URLs but no usable owned domain")
            else:
                no_website_evidence.extend(
                    str(item)
                    for item in list(dataforseo_summary.get("no_website_evidence", []))
                    if str(item).strip()
                )

    if budget_left() and not have_real_site():
        machine._check_stop()
        targeted_linkedin, targeted_social_profiles, targeted_profile_details = machine.discover_public_profiles(
            name,
            search_context,
        )
        if targeted_linkedin and not linkedin_url:
            linkedin_url = targeted_linkedin
        for profile in targeted_social_profiles:
            if profile not in social_profiles:
                social_profiles.append(profile)
        if targeted_profile_details and "No LinkedIn or social profiles found" not in targeted_profile_details:
            profile_parts.append(targeted_profile_details)
            discovery_sources.append("search: profile discovery")

    if budget_left() and not have_real_site():
        bio_sources_to_check: list[str] = []
        for profile in social_profiles:
            if "facebook.com" in profile.lower():
                bio_sources_to_check.insert(0, profile)
            elif "instagram.com" in profile.lower():
                bio_sources_to_check.append(profile)
        if linkedin_url:
            bio_sources_to_check.append(linkedin_url)
        for bio_url in bio_sources_to_check[:3]:
            if not budget_left():
                break
            machine._check_stop()
            social_bio_sources_checked.append(bio_url)
            discovered_site = machine.extract_website_from_social_bio(bio_url)
            if discovered_site and discovered_site not in seen_urls:
                seen_urls.add(discovered_site)
                result = machine.classify_known_web_presence(discovered_site)
                results.append(result)
                platform = machine.social_platform_name(bio_url)
                discovery_sources.append(f"social bio: {platform}")
                profile_parts.append(f"Website found in {platform} bio: {machine.normalize_domain(discovered_site)}")
            else:
                platform = machine.social_platform_name(bio_url)
                no_website_evidence.append(f"{platform} bio did not expose an owned domain")

    if not results:
        attempt_summary = _summarize_discovery_attempts(discovery_attempts)
        confidence = "Medium" if no_website_evidence and not attempt_summary["retry_recommended"] else "Low"
        detail = (
            "No owned website was confirmed in public discovery, but the app needs another independent source "
            "before calling this a true no-website business"
        )
        if attempt_summary["failures"]:
            detail = f"{detail}; discovery issues: {'; '.join(attempt_summary['failures'][:3])}"
        web_result = machine.make_web_result(
            "Unknown web presence",
            "",
            detail,
            confidence,
            "public discovery did not find an owned domain; confirmation still required",
        )
    else:
        web_result = machine.choose_web_presence_result(*results)

    if linkedin_url:
        profile_parts.insert(0, "LinkedIn found")
    if social_profiles:
        profile_parts.insert(1 if linkedin_url else 0, f"Social profiles: {len(social_profiles)}")

    return {
        "web_result": web_result,
        "linkedin_url": linkedin_url,
        "social_profiles": social_profiles,
        "profile_details": "; ".join(profile_parts) or "No social or LinkedIn profiles found in search results",
        "discovery_sources": discovery_sources,
        "discovery_attempts": discovery_attempts,
        "no_website_evidence": no_website_evidence,
        "provider_evidence": provider_evidence,
        "social_bio_sources_checked": social_bio_sources_checked,
        "dataforseo_summary": dataforseo_summary,
    }


def verify_web_presence(machine: "LeadMachine", leads: list[dict]) -> list[dict]:
    total_leads = len(leads)
    machine.log(f"Stage 3/5: Verify web presence quality for {total_leads} leads")
    targeted_recheck = machine.is_targeted_recheck()
    machine._web_result_evidence.clear()
    kept: list[dict] = []
    counts = {
        "No website": 0,
        "Unknown web presence": 0,
        "Directory only": 0,
        "Social only": 0,
        "Broken site": 0,
        "Weak site": 0,
        "Basic site": 0,
        "Real website": 0,
    }
    retained_real_website_for_recheck = 0
    retained_real_website_for_focus = 0
    keep_real_websites_for_focus = machine.keeps_real_websites_for_opportunity_focus()
    stage_start = time.time()

    for idx, lead in enumerate(leads, start=1):
        machine._check_stop()
        lead_start = time.time()
        business_name = str(lead.get("Business Name", ""))[:40]
        raw_site = str(lead.get("Seed Website", "") or lead.get("Official Website", "")).strip()
        city = machine.search_context_from_area(lead.get("City/Area", ""))
        social_profiles: list[str] = []
        linkedin_url = ""

        if raw_site and machine.is_social_url(raw_site):
            cleaned_profile = machine.clean_profile_url(raw_site)
            if machine.is_linkedin_url(cleaned_profile):
                linkedin_url = cleaned_profile
            else:
                social_profiles.append(cleaned_profile)

        if raw_site and machine.is_link_hub_url(raw_site):
            real_site = machine._follow_link_hub(raw_site)
            if real_site:
                raw_site = real_site

        initial_result = (
            machine.classify_known_web_presence(raw_site)
            if raw_site
            else machine.make_web_result("No website", "", "No website listed in seed data", "Medium", "no listed URL")
        )
        discovered_result = machine.make_web_result("Unknown web presence", "", "", "Low", "")
        discovery_sources: list[str] = []
        discovery_attempts: list[dict[str, object]] = []
        no_website_evidence: list[str] = []
        provider_evidence: list[str] = []
        social_bio_sources_checked: list[str] = []
        dataforseo_summary: dict[str, object] = {}
        if initial_result[0] in {"No website", "Unknown web presence", "Directory only", "Social only"}:
            discovered_bundle = machine.discover_presence_bundle(lead["Business Name"], city)
            discovered_result = discovered_bundle["web_result"]
            discovery_sources = list(discovered_bundle.get("discovery_sources", []))
            discovery_attempts = [dict(item) for item in list(discovered_bundle.get("discovery_attempts", []))]
            no_website_evidence = [str(item) for item in list(discovered_bundle.get("no_website_evidence", [])) if str(item).strip()]
            provider_evidence = [str(item) for item in list(discovered_bundle.get("provider_evidence", [])) if str(item).strip()]
            social_bio_sources_checked = [
                str(item)
                for item in list(discovered_bundle.get("social_bio_sources_checked", []))
                if str(item).strip()
            ]
            dataforseo_summary = dict(discovered_bundle.get("dataforseo_summary", {}))
            if discovered_bundle["linkedin_url"] and not linkedin_url:
                linkedin_url = str(discovered_bundle["linkedin_url"])
            for profile in discovered_bundle["social_profiles"]:
                cleaned_profile = str(profile)
                if cleaned_profile not in social_profiles:
                    social_profiles.append(cleaned_profile)

        status, website, evidence, confidence, signals = machine.choose_web_presence_result(initial_result, discovered_result)
        site_evidence = dict(_get_website_evidence_defaults())
        site_evidence.update(machine._web_result_evidence.get((status, website, evidence, confidence, signals), {}))
        lead["Web Presence Status"] = status
        lead["Official Website"] = website
        lead["Web Presence Confidence"] = confidence
        lead["Website Signals"] = signals
        lead["Website Failure Type"] = machine.website_failure_type(status, evidence, signals)
        lead["LinkedIn Profile"] = linkedin_url
        lead["Social Profiles"] = machine.join_social_profiles(social_profiles)
        lead["Social Profile URLs"] = machine.join_social_profile_urls(social_profiles)
        lead["Discovery Sources"] = "; ".join(discovery_sources) if discovery_sources else ""
        lead["Web Presence Details"] = evidence or WEB_PRESENCE_DEFAULT_DETAILS.get(status, "")
        lead.update(site_evidence)
        attempt_summary = _summarize_discovery_attempts(discovery_attempts)
        if discovery_attempts:
            lead["Discovery Sources Attempted"] = "; ".join(attempt_summary["source_labels"])
            lead["Search Queries"] = " | ".join(attempt_summary["queries"])
            lead["Search Providers"] = "; ".join(attempt_summary["providers"])
            lead["Raw Result Count"] = attempt_summary["raw_count"]
            lead["URLs Attempted"] = "; ".join(attempt_summary["urls"][:12])
            lead["HTTP Statuses"] = "; ".join(attempt_summary["statuses"])
            lead["Failure Reasons"] = "; ".join(attempt_summary["failures"][:6])
            if attempt_summary["retry_recommended"]:
                lead["Retry Recommended"] = "Yes"
                lead["Retry Reason"] = str(attempt_summary["retry_reason"])
        if no_website_evidence:
            lead["No Website Evidence"] = "; ".join(dict.fromkeys(no_website_evidence))
            verification_sources = [*attempt_summary["source_labels"], *discovery_sources]
            lead["Verification Sources"] = "; ".join(dict.fromkeys(source for source in verification_sources if source))
        if provider_evidence:
            lead["Provider Evidence Summary"] = "; ".join(dict.fromkeys(provider_evidence))
        if social_bio_sources_checked:
            lead["Social Bio Sources Checked"] = "; ".join(dict.fromkeys(social_bio_sources_checked))
        if dataforseo_summary:
            owned_domains = [
                machine.normalize_domain(str(url))
                for url in list(dataforseo_summary.get("owned_urls", []))
                if str(url).strip()
            ]
            failures = [str(item) for item in list(dataforseo_summary.get("failures", [])) if str(item).strip()]
            lead["DataForSEO Status"] = (
                "Found owned domain"
                if owned_domains
                else "No owned domain"
                if dataforseo_summary.get("enabled") and not failures
                else "Error"
            )
            lead["DataForSEO Queries"] = " | ".join(str(item) for item in list(dataforseo_summary.get("queries", [])) if str(item).strip())
            lead["DataForSEO Owned Domains"] = "; ".join(dict.fromkeys(owned_domains))
            lead["DataForSEO Result Count"] = int(dataforseo_summary.get("result_count") or 0)
            lead["DataForSEO Failure Reason"] = "; ".join(failures[:4])
        machine.apply_website_opportunity_audit(lead)

        if status in {"Directory only", "Social only"} and not lead.get("Listed On"):
            lead["Listed On"] = evidence
        if status == "Broken site" and not lead.get("Website Status"):
            lead["Website Status"] = "Website listed"

        counts[status] = counts.get(status, 0) + 1

        if status == "Real website":
            if targeted_recheck:
                retained_real_website_for_recheck += 1
                machine.log(f"Retained real website for targeted recheck: {lead['Business Name']} | {website}")
            elif keep_real_websites_for_focus:
                retained_real_website_for_focus += 1
                machine.log(f"Retained real website for {machine.opportunity_focus_label()}: {lead['Business Name']} | {website}")
            else:
                machine.log(f"Filtered out real website: {lead['Business Name']} | {website}")
                continue

        kept.append(lead)

        lead_ms = int((time.time() - lead_start) * 1000)
        if lead_ms >= 30000:
            machine.log(f"Slow lead in Stage 3: {business_name} took {lead_ms / 1000:.1f}s ({status})")
        if idx == 1 or idx % 25 == 0 or idx == total_leads:
            elapsed = time.time() - stage_start
            rate = idx / elapsed if elapsed > 0 else 0
            eta_sec = (total_leads - idx) / rate if rate > 0 else 0
            machine.log(
                f"Stage 3 progress: {idx}/{total_leads} | "
                f"no_site={counts['No website']} unknown={counts['Unknown web presence']} social={counts['Social only']} "
                f"broken={counts['Broken site']} weak={counts['Weak site']} "
                f"basic={counts['Basic site']} real={counts['Real website']} | "
                f"elapsed {elapsed:.0f}s, eta {eta_sec:.0f}s"
            )

    retained_real_website = retained_real_website_for_recheck + retained_real_website_for_focus
    removed_real_website = max(0, counts["Real website"] - retained_real_website)
    machine.log(
        f"Web presence stage complete. Kept: {len(kept)} | "
        f"No website: {counts['No website']} | Unknown: {counts['Unknown web presence']} | Directory only: {counts['Directory only']} | "
        f"Social only: {counts['Social only']} | Broken site: {counts['Broken site']} | "
        f"Weak site: {counts['Weak site']} | Basic site: {counts['Basic site']} | "
        f"Real website removed: {removed_real_website}"
        + (f" | Real website retained for recheck: {retained_real_website_for_recheck}" if retained_real_website_for_recheck else "")
        + (f" | Real website retained for focus: {retained_real_website_for_focus}" if retained_real_website_for_focus else "")
    )
    machine.record_stage_report(
        "web_presence",
        "Verify web presence quality",
        kept=len(kept),
        no_website=counts["No website"],
        unknown_web_presence=counts["Unknown web presence"],
        directory_only=counts["Directory only"],
        social_only=counts["Social only"],
        broken_site=counts["Broken site"],
        weak_site=counts["Weak site"],
        basic_site=counts["Basic site"],
        real_website_removed=removed_real_website,
        real_website_retained_for_recheck=retained_real_website_for_recheck,
        real_website_retained_for_focus=retained_real_website_for_focus,
    )
    return kept
