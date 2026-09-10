"""Static design-quality review for generated website mockups."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None  # type: ignore


DESIGN_REVIEW_FILE = "design_review.json"

_GENERIC_HEADLINES = (
    "welcome to",
    "transform your business",
    "experience excellence",
    "quality you can trust",
    "your trusted partner",
)
_WEAK_CTA_LABELS = {
    "learn more",
    "get started",
    "discover more",
    "read more",
    "click here",
}
_PLACEHOLDER_PHRASES = (
    "lorem ipsum",
    "your text here",
    "placeholder",
    "coming soon",
)
_INVENTED_CLAIMS = (
    "trusted by thousands",
    "award-winning",
    "guaranteed results",
    "10,000+",
    "100% satisfaction",
)
_PHONE_RE = re.compile(r"(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}")
_HEX_RE = re.compile(r"#[0-9a-fA-F]{6}\b")


@dataclass
class DesignReviewIssue:
    severity: str
    rule: str
    message: str
    section_id: str = ""
    recommendation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DesignReviewReport:
    version: int
    passed: bool
    score: int
    summary: str
    issues: list[DesignReviewIssue] = field(default_factory=list)
    suggested_regeneration_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "passed": self.passed,
            "score": self.score,
            "summary": self.summary,
            "issues": [issue.to_dict() for issue in self.issues],
            "suggested_regeneration_notes": list(self.suggested_regeneration_notes),
        }


def _read_html(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _soup(html: str) -> Any:
    if BeautifulSoup is None:
        return None
    return BeautifulSoup(html or "", "html.parser")


def _text(html: str, soup: Any = None) -> str:
    if soup is not None:
        return re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    cleaned = re.sub(r"<script\b.*?</script>", " ", html or "", flags=re.I | re.S)
    cleaned = re.sub(r"<style\b.*?</style>", " ", cleaned, flags=re.I | re.S)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _heading_texts(html: str, soup: Any = None) -> list[str]:
    if soup is not None:
        return [tag.get_text(" ", strip=True) for tag in soup.find_all(re.compile(r"^h[1-6]$"))]
    return [
        re.sub(r"<[^>]+>", " ", match.group(1)).strip()
        for match in re.finditer(r"<h[1-6][^>]*>(.*?)</h[1-6]>", html or "", re.I | re.S)
    ]


def _h1_count(html: str, soup: Any = None) -> int:
    if soup is not None:
        return len(soup.find_all("h1"))
    return len(re.findall(r"<h1\b", html or "", flags=re.I))


def _cta_labels(html: str, soup: Any = None) -> list[str]:
    labels: list[str] = []
    if soup is not None:
        for tag in soup.find_all(["a", "button"]):
            label = tag.get_text(" ", strip=True)
            if label:
                labels.append(label)
        return labels
    for match in re.finditer(r"<(?:a|button)\b[^>]*>(.*?)</(?:a|button)>", html or "", re.I | re.S):
        label = re.sub(r"<[^>]+>", " ", match.group(1))
        label = re.sub(r"\s+", " ", label).strip()
        if label:
            labels.append(label)
    return labels


def _known_phone(lead: dict[str, Any] | None, marketing_brief: dict[str, Any] | None) -> str:
    lead = lead if isinstance(lead, dict) else {}
    data = lead.get("data") if isinstance(lead.get("data"), dict) else {}
    for value in (
        lead.get("phone"),
        lead.get("primary_phone"),
        data.get("Phone"),
        data.get("Primary Phone"),
        data.get("Phone Number"),
    ):
        text = str(value or "").strip()
        if text:
            return text
    contact = (
        (marketing_brief or {})
        .get("analytics_strategy", {})
        .get("contact_channels", {})
    )
    if isinstance(contact, dict) and contact.get("phone_available"):
        return "known_phone"
    return ""


def _business_and_location(
    lead: dict[str, Any] | None,
    marketing_brief: dict[str, Any] | None,
    site_design_brief: dict[str, Any] | None,
) -> tuple[str, str]:
    lead = lead if isinstance(lead, dict) else {}
    data = lead.get("data") if isinstance(lead.get("data"), dict) else {}
    business = str(
        (marketing_brief or {}).get("business_name")
        or lead.get("business_name")
        or data.get("Business Name")
        or data.get("Name")
        or ""
    ).strip()
    location = str(
        (marketing_brief or {}).get("location")
        or lead.get("city_area")
        or data.get("City/Area")
        or data.get("City")
        or ""
    ).strip()
    if not location and isinstance(site_design_brief, dict):
        site_dna = site_design_brief.get("site_dna")
        if isinstance(site_dna, dict):
            location = str(site_dna.get("location") or "").strip()
    return business, location


def _section_for_text(html: str, needle: str) -> str:
    if not needle:
        return ""
    index = html.lower().find(needle.lower())
    if index < 0:
        return ""
    prefix = html[:index]
    matches = list(
        re.finditer(
            r'data-summit-section=["\']([^"\']+)["\']',
            prefix,
            flags=re.I,
        )
    )
    return matches[-1].group(1) if matches else ""


def _has_nested_card(soup: Any, html: str) -> bool:
    if soup is not None:
        def is_card(tag: Any) -> bool:
            classes = tag.get("class") or []
            joined = " ".join(classes).lower()
            return "card" in joined or "rounded" in joined and "shadow" in joined

        for tag in soup.find_all(True):
            if is_card(tag) and tag.find(is_card):
                return True
        return False
    return bool(re.search(r'class=["\'][^"\']*card[^"\']*["\'][\s\S]+class=["\'][^"\']*card', html or "", re.I))


def _add_issue(
    issues: list[DesignReviewIssue],
    severity: str,
    rule: str,
    message: str,
    recommendation: str,
    section_id: str = "",
) -> None:
    issues.append(
        DesignReviewIssue(
            severity=severity,
            rule=rule,
            message=message,
            section_id=section_id,
            recommendation=recommendation,
        )
    )


def review_generated_website(
    html_path: Path,
    *,
    lead: dict[str, Any] | None = None,
    marketing_brief: dict[str, Any] | None = None,
    site_design_brief: dict[str, Any] | None = None,
) -> DesignReviewReport:
    html = _read_html(Path(html_path))
    soup = _soup(html)
    page_text = _text(html, soup)
    text_lower = page_text.lower()
    issues: list[DesignReviewIssue] = []

    if not html:
        _add_issue(
            issues,
            "error",
            "empty_html",
            "No HTML could be read for design review.",
            "Regenerate the mockup before design review.",
        )
    if _h1_count(html, soup) != 1:
        _add_issue(
            issues,
            "warning",
            "one_visible_h1",
            "The page should have exactly one visible H1.",
            "Use one specific H1 and demote other large headings.",
        )

    headings = _heading_texts(html, soup)
    for heading in headings[:6]:
        lowered = heading.lower()
        if any(phrase in lowered for phrase in _GENERIC_HEADLINES):
            _add_issue(
                issues,
                "warning",
                "generic_headline",
                f"Generic headline detected: {heading[:120]}",
                "Replace with category-specific, local, or service-specific headline copy.",
                _section_for_text(html, heading),
            )
            break

    labels = _cta_labels(html, soup)
    weak_labels = [label for label in labels if label.strip().lower() in _WEAK_CTA_LABELS]
    strong_cta = [
        label
        for label in labels
        if re.search(r"\b(call|quote|schedule|book|reserve|contact|menu|appointment|consultation|visit|order)\b", label, re.I)
    ]
    if not labels or (weak_labels and not strong_cta):
        _add_issue(
            issues,
            "warning",
            "weak_cta",
            "Primary CTAs are missing or too generic.",
            "Use a concrete CTA such as Call, Request a Quote, Book, Reserve, or Schedule.",
        )

    phone = _known_phone(lead, marketing_brief)
    if phone:
        phone_digits = re.sub(r"\D+", "", phone)
        html_digits = re.sub(r"\D+", "", html)
        has_tel = "tel:" in html.lower()
        if phone_digits and phone_digits not in html_digits or not has_tel:
            _add_issue(
                issues,
                "warning",
                "visible_phone_when_known",
                "A known phone number is not clearly visible as a tel link.",
                "Show the phone in the hero/header or final CTA using a tel link.",
            )
        elif phone == "known_phone" and not _PHONE_RE.search(page_text):
            _add_issue(
                issues,
                "warning",
                "visible_phone_when_known",
                "Phone availability is known but no phone-like text appears on the page.",
                "Surface the captured phone number when available.",
            )

    business, location = _business_and_location(lead, marketing_brief, site_design_brief)
    if business and business.lower() not in text_lower:
        _add_issue(
            issues,
            "warning",
            "business_name_missing",
            "The business name is not visible in page text.",
            "Include the business name in the hero or navigation.",
        )
    if location and location.lower() not in text_lower:
        _add_issue(
            issues,
            "warning",
            "local_signal_present",
            "The location or service area is not visible in page text.",
            "Include the city, area, or service-region signal before the footer.",
        )

    if not re.search(r"\b(review|testimonial|trusted|licensed|insured|certified|family|local|serving|proof|results)\b", text_lower):
        _add_issue(
            issues,
            "warning",
            "missing_trust_or_proof",
            "No clear trust, proof, or reassurance signal was detected.",
            "Add factual proof from scraped services, process, location, or credentials.",
        )

    for phrase in _PLACEHOLDER_PHRASES:
        if phrase in text_lower:
            _add_issue(
                issues,
                "error",
                "placeholder_copy",
                f"Placeholder copy detected: {phrase}",
                "Remove placeholder copy and regenerate with real scraped facts.",
                _section_for_text(html, phrase),
            )
            break

    for phrase in _INVENTED_CLAIMS:
        if phrase in text_lower:
            _add_issue(
                issues,
                "warning",
                "invented_claims",
                f"Potential invented claim detected: {phrase}",
                "Use only claims found in source data or remove the claim.",
                _section_for_text(html, phrase),
            )
            break

    card_count = len(re.findall(r'class=["\'][^"\']*(?:card|shadow|rounded-[a-z0-9-]+)[^"\']*["\']', html or "", re.I))
    grid_count = len(re.findall(r'grid-cols-|class=["\'][^"\']*\bgrid\b', html or "", re.I))
    if card_count >= 14 or grid_count >= 7:
        _add_issue(
            issues,
            "warning",
            "too_many_same_shaped_cards",
            "The page appears to rely heavily on repeated card/grid layouts.",
            "Vary section rhythm with bands, feature rows, proof strips, or editorial layouts.",
        )
    if _has_nested_card(soup, html):
        _add_issue(
            issues,
            "warning",
            "nested_cards",
            "A card-inside-card composition was detected.",
            "Flatten nested card layouts unless the nested element is a real control.",
        )

    long_paragraphs = re.findall(r"<p\b[^>]*>(.*?)</p>", html or "", re.I | re.S)
    if any(len(re.sub(r"<[^>]+>", " ", para)) > 520 for para in long_paragraphs):
        _add_issue(
            issues,
            "warning",
            "text_density_risk",
            "At least one paragraph is long enough to create mobile scanning risk.",
            "Split dense copy into shorter paragraphs, bullets, or callout rows.",
        )

    colors = {color.lower() for color in _HEX_RE.findall(html)}
    if 0 < len(colors) <= 2:
        _add_issue(
            issues,
            "info",
            "monochrome_palette_risk",
            "Only one or two hex colors were detected.",
            "Check that the design has enough neutral, accent, and surface contrast.",
        )

    errors = sum(1 for issue in issues if issue.severity == "error")
    warnings = sum(1 for issue in issues if issue.severity == "warning")
    infos = sum(1 for issue in issues if issue.severity == "info")
    score = max(0, min(100, 100 - errors * 25 - warnings * 8 - infos * 2))
    passed = errors == 0
    if errors:
        summary = f"Design review found {errors} blocking issue(s) and {warnings} warning(s)."
    elif warnings:
        summary = f"Design review passed with {warnings} warning(s)."
    else:
        summary = "Design review passed with no major issues."
    notes = [
        f"{issue.rule}: {issue.recommendation}"
        for issue in issues
        if issue.severity in {"error", "warning"} and issue.recommendation
    ][:10]
    return DesignReviewReport(
        version=1,
        passed=passed,
        score=score,
        summary=summary,
        issues=issues,
        suggested_regeneration_notes=notes,
    )


def save_design_review(report: DesignReviewReport, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / DESIGN_REVIEW_FILE
    path.write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path
