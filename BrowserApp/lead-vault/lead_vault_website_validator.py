"""Website validator — Phase 4 of website generator pipeline.

Runs three independent passes over a generated HTML mockup and returns
a merged report:

- htmlhint (external CLI installed under lead-vault/validator) — HTML
  structural and syntactic correctness.
- Structure checks (BeautifulSoup) — required tags and metadata.
- Accessibility / security checks (BeautifulSoup) — alt text, form
  labels, target=_blank noopener, empty buttons.

Heavier checks that require a headless browser (pa11y, lighthouse) are
intentionally deferred. They can be layered on top of this module later
without changing the public API.

The report is considered "passed" only if no `error`-severity issues
were found. Warnings do not block shipping.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None  # type: ignore


LEAD_VAULT_DIR = Path(__file__).resolve().parent
VALIDATOR_DIR = LEAD_VAULT_DIR / "validator"
HTMLHINT_CONFIG = VALIDATOR_DIR / ".htmlhintrc"
HTMLHINT_TIMEOUT_SECONDS = 60

# Browser CLI audits are skipped until they have an enforced network/file boundary.
SITE_DESIGN_BRIEF_FILE = "site_design_brief.json"
MOTION_RUNTIME_CSS_FILE = "summit-motion.css"
MOTION_RUNTIME_JS_FILE = "summit-motion.js"
_RUNTIME_ATTRS = ("data-motion", "data-bg", "data-parallax", "data-hover")
_PRIMITIVE_ATTR_EXPECTATIONS = {
    "reveal_up": ("data-motion", "reveal-up"),
    "gradient_mesh": ("data-bg", "gradient-mesh"),
    "parallax_image": ("data-parallax", ""),
    "sticky_cta": ("data-motion", "sticky-cta"),
    "cursor_spotlight": ("data-bg", "cursor-spotlight"),
    "water_attractor": ("data-bg", "water-attractor"),
}
_CUSTOM_MOTION_PATTERNS = (
    ("custom_intersection_observer", "IntersectionObserver"),
    ("custom_scroll_listener", "addEventListener(\"scroll"),
    ("custom_scroll_listener", "addEventListener('scroll"),
    ("custom_scroll_handler", ".onscroll"),
    ("custom_animation_frame", "requestAnimationFrame"),
)
_CUSTOM_RUNTIME_SELECTOR_RE = re.compile(
    r"[^{}@]*\[(?:data-motion|data-bg|data-parallax|data-hover)\b[^{]*"
    r"\{[^{}]*(?:opacity|transform|transition|animation|position|pointer-events|will-change)\s*:",
    re.IGNORECASE | re.DOTALL,
)
_ALPINE_USAGE_RE = re.compile(
    r"https://unpkg\.com/alpinejs|<script\b[^>]*\balpinejs\b|"
    r"\s(?:x-data|x-show|x-init|x-text|x-cloak|x-bind|x-on:[\w:.-]+)\b|"
    r"\s@[\w:.-]+\s*=",
    re.IGNORECASE,
)


@dataclass
class ValidationIssue:
    severity: str  # error | warning | info
    source: str    # htmlhint | structure | a11y | security | io
    rule: str
    message: str
    line: int = 0


@dataclass
class ValidationReport:
    passed: bool = True
    issues: list[ValidationIssue] = field(default_factory=list)
    tool_runs: dict[str, str] = field(default_factory=dict)

    @property
    def error_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == "warning")

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "tool_runs": dict(self.tool_runs),
            "issues": [asdict(issue) for issue in self.issues],
        }


# ── htmlhint ────────────────────────────────────────────────────────────

def _htmlhint_binary() -> Path | None:
    """Locate htmlhint: prefer the local install under validator/."""
    local_bin = VALIDATOR_DIR / "node_modules" / ".bin"
    for candidate in ("htmlhint.cmd", "htmlhint"):
        path = local_bin / candidate
        if path.exists():
            return path
    which = shutil.which("htmlhint")
    return Path(which) if which else None


def run_htmlhint(html_path: Path) -> tuple[list[ValidationIssue], str]:
    binary = _htmlhint_binary()
    if binary is None:
        return [], "skipped: htmlhint not installed (run npm install under lead-vault/validator)"
    cmd = [str(binary), "--format", "json"]
    if HTMLHINT_CONFIG.exists():
        cmd += ["--config", str(HTMLHINT_CONFIG)]
    cmd.append(str(html_path))
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=HTMLHINT_TIMEOUT_SECONDS,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        return [], f"timeout after {HTMLHINT_TIMEOUT_SECONDS}s"
    except OSError as exc:
        return [], f"spawn failed: {exc}"

    stdout = (proc.stdout or "").strip()
    if not stdout:
        return [], "ok"
    try:
        reports = json.loads(stdout)
    except json.JSONDecodeError:
        return [], f"unparsed output: {stdout[:160]}"

    issues: list[ValidationIssue] = []
    for file_report in reports if isinstance(reports, list) else [reports]:
        for msg in file_report.get("messages", []) or []:
            severity = "error" if msg.get("type") == "error" else "warning"
            rule = msg.get("rule") or {}
            rule_id = rule.get("id") if isinstance(rule, dict) else str(rule)
            issues.append(ValidationIssue(
                severity=severity,
                source="htmlhint",
                rule=str(rule_id or ""),
                message=str(msg.get("message") or ""),
                line=int(msg.get("line") or 0),
            ))
    return issues, "ok"


# ── pa11y (optional, WCAG 2.1 AA) ──────────────────────────────────────

def run_pa11y(html_path: Path) -> tuple[list[ValidationIssue], str]:
    """Skip the optional CLI: it executes untrusted HTML without isolation."""
    return [], (
        "skipped: pa11y browser lacks an enforced network/file boundary; "
        "static accessibility checks and isolated preview QA remain available"
    )


# ── lighthouse (optional, perf / a11y / best-practices / SEO) ──────────

def run_lighthouse(html_path: Path) -> tuple[list[ValidationIssue], str]:
    """Skip the optional CLI until it can run inside an enforced sandbox."""
    return [], (
        "skipped: lighthouse browser lacks an enforced network/file boundary; "
        "use isolated preview QA for local generated bundles"
    )


def _parse_soup(html: str):
    if BeautifulSoup is None:
        return None
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        return BeautifulSoup(html, "html.parser")


def run_structure_checks(html: str) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if BeautifulSoup is None:
        issues.append(ValidationIssue(
            severity="warning", source="structure", rule="bs4_missing",
            message="BeautifulSoup not installed — install beautifulsoup4",
        ))
        return issues

    head = html[:400].lower()
    if "<!doctype" not in head:
        issues.append(ValidationIssue(
            severity="error", source="structure", rule="doctype",
            message="Missing <!DOCTYPE html> at top of document",
        ))

    soup = _parse_soup(html)
    if soup is None:
        return issues

    html_tag = soup.find("html")
    if html_tag is None:
        issues.append(ValidationIssue(
            severity="error", source="structure", rule="html_tag",
            message="Missing <html> root element",
        ))
    elif not str(html_tag.get("lang") or "").strip():
        issues.append(ValidationIssue(
            severity="error", source="structure", rule="html_lang",
            message="<html> is missing lang attribute",
        ))

    if soup.find("head") is None:
        issues.append(ValidationIssue(
            severity="error", source="structure", rule="head",
            message="Missing <head>",
        ))

    title = soup.find("title")
    if title is None or not title.get_text(strip=True):
        issues.append(ValidationIssue(
            severity="error", source="structure", rule="title",
            message="Missing <title> or title is empty",
        ))

    viewport = soup.find("meta", attrs={"name": "viewport"})
    if viewport is None:
        issues.append(ValidationIssue(
            severity="error", source="structure", rule="meta_viewport",
            message="Missing <meta name=\"viewport\">",
        ))

    description = soup.find("meta", attrs={"name": "description"})
    if description is None or not str(description.get("content") or "").strip():
        issues.append(ValidationIssue(
            severity="warning", source="structure", rule="meta_description",
            message="Missing <meta name=\"description\">",
        ))

    csp = soup.find("meta", attrs={"http-equiv": "Content-Security-Policy"})
    if csp is None:
        csp = soup.find(
            "meta", attrs={"http-equiv": lambda v: v and v.lower() == "content-security-policy"}
        )
    if csp is None or not str(csp.get("content") or "").strip():
        issues.append(ValidationIssue(
            severity="warning", source="security", rule="csp_meta_missing",
            message="Missing <meta http-equiv=\"Content-Security-Policy\">",
        ))
    else:
        csp_content = str(csp.get("content") or "")
        if _ALPINE_USAGE_RE.search(html) and "'unsafe-eval'" not in csp_content.lower():
            issues.append(ValidationIssue(
                severity="error",
                source="security",
                rule="alpine_csp_blocks_runtime",
                message=(
                    "Generated HTML uses Alpine.js directives/runtime but the CSP "
                    "script-src does not include 'unsafe-eval', so Alpine "
                    "expressions fail in preview."
                ),
            ))

    body = soup.find("body")
    if body is None:
        issues.append(ValidationIssue(
            severity="error", source="structure", rule="body",
            message="Missing <body>",
        ))
        return issues

    h1s = body.find_all("h1")
    if not h1s:
        issues.append(ValidationIssue(
            severity="error", source="structure", rule="h1_missing",
            message="Page has no <h1>",
        ))
    elif len(h1s) > 1:
        issues.append(ValidationIssue(
            severity="warning", source="structure", rule="h1_multiple",
            message=f"Page has {len(h1s)} <h1> elements — prefer exactly one",
        ))

    return issues


# ── accessibility + security checks ────────────────────────────────────

def run_a11y_checks(html: str) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if BeautifulSoup is None:
        return issues
    soup = _parse_soup(html)
    if soup is None:
        return issues

    for img in soup.find_all("img"):
        alt = img.get("alt")
        if alt is None:
            src_hint = str(img.get("src") or "")[:60]
            issues.append(ValidationIssue(
                severity="error", source="a11y", rule="img_alt_missing",
                message=f"<img> missing alt attribute (src={src_hint})",
            ))

    for tag in soup.find_all(["input", "textarea", "select"]):
        input_type = str(tag.get("type") or "").lower()
        if input_type in {"hidden", "submit", "button", "reset", "image"}:
            continue
        tag_id = tag.get("id")
        has_label = bool(tag.get("aria-label") or tag.get("aria-labelledby"))
        if not has_label and tag_id:
            has_label = soup.find("label", attrs={"for": tag_id}) is not None
        if not has_label:
            parent_label = tag.find_parent("label")
            has_label = parent_label is not None
        if not has_label:
            name_hint = str(tag.get("name") or tag.get("id") or "")
            issues.append(ValidationIssue(
                severity="warning", source="a11y", rule="form_label_missing",
                message=f"<{tag.name}> has no associated label (name={name_hint})",
            ))

    for btn in soup.find_all("button"):
        has_text = bool(btn.get_text(strip=True))
        has_aria = bool(btn.get("aria-label") or btn.get("aria-labelledby"))
        if not has_text and not has_aria:
            issues.append(ValidationIssue(
                severity="warning", source="a11y", rule="button_accessible_name",
                message="<button> has no text content or aria-label",
            ))

    for anchor in soup.find_all("a", target="_blank"):
        rel = anchor.get("rel")
        if isinstance(rel, str):
            rel_tokens = rel.split()
        elif isinstance(rel, list):
            rel_tokens = rel
        else:
            rel_tokens = []
        if "noopener" not in rel_tokens and "noreferrer" not in rel_tokens:
            href_hint = str(anchor.get("href") or "")[:60]
            issues.append(ValidationIssue(
                severity="warning", source="security", rule="target_blank_noopener",
                message=f"<a target=\"_blank\"> without rel=\"noopener\" (href={href_hint})",
            ))

    for script in soup.find_all("script"):
        src = str(script.get("src") or "").strip()
        if not src:
            continue
        if src.startswith("http://") or src.startswith("https://"):
            if not script.get("integrity"):
                issues.append(ValidationIssue(
                    severity="warning", source="security",
                    rule="external_script_no_sri",
                    message=(
                        f"External <script src=\"{src[:80]}\"> has no integrity "
                        "(SRI) attribute — acceptable for local previews, "
                        "add SRI before hosting"
                    ),
                ))

    for handler_name in (
        "onclick", "onload", "onerror", "onmouseover", "onfocus",
        "onblur", "onchange", "onsubmit", "onkeydown", "onkeyup",
    ):
        for tag in soup.find_all(attrs={handler_name: True}):
            issues.append(ValidationIssue(
                severity="warning", source="security",
                rule="inline_event_handler",
                message=(
                    f"<{tag.name}> has inline {handler_name} handler — use "
                    "Alpine directives or addEventListener instead"
                ),
            ))

    return issues


# ── public entry points ────────────────────────────────────────────────

# Design contract checks keep the paid generation loop honest without
# making another model call.
def _load_design_brief(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _runtime_asset_present(soup, tag_name: str, attr_name: str, filename: str) -> bool:
    for tag in soup.find_all(tag_name):
        value = str(tag.get(attr_name) or "")
        if filename in value or tag.get("data-summit-motion-runtime"):
            return True
    return False


def _runtime_attr_count(soup) -> int:
    count = 0
    for attr in _RUNTIME_ATTRS:
        count += len(soup.find_all(attrs={attr: True}))
    return count


def _count_expected_primitive(soup, primitive_key: str) -> int:
    attr, value = _PRIMITIVE_ATTR_EXPECTATIONS.get(primitive_key, ("", ""))
    if not attr:
        return 0
    if value:
        return len(soup.find_all(attrs={attr: value}))
    return len(soup.find_all(attrs={attr: True}))


def _primitive_max_instances(brief: dict[str, Any], primitive_key: str) -> int | None:
    experience = brief.get("experience_dna")
    experience = experience if isinstance(experience, dict) else {}
    contracts = experience.get("primitive_contracts")
    contracts = contracts if isinstance(contracts, dict) else {}
    contract = contracts.get(primitive_key)
    contract = contract if isinstance(contract, dict) else {}
    performance = contract.get("performance")
    performance = performance if isinstance(performance, dict) else {}
    try:
        return int(performance.get("max_instances"))
    except (TypeError, ValueError):
        return None


def run_design_contract_checks(
    html: str,
    design_brief: dict[str, Any] | None,
) -> list[ValidationIssue]:
    """Validate that generated HTML honors the saved Site Design Brief."""
    issues: list[ValidationIssue] = []
    if BeautifulSoup is None:
        return issues
    soup = _parse_soup(html)
    if soup is None:
        return issues

    runtime_attr_count = _runtime_attr_count(soup)
    has_runtime_css = _runtime_asset_present(
        soup, "link", "href", MOTION_RUNTIME_CSS_FILE
    )
    has_runtime_js = _runtime_asset_present(
        soup, "script", "src", MOTION_RUNTIME_JS_FILE
    )
    if runtime_attr_count and (not has_runtime_css or not has_runtime_js):
        issues.append(ValidationIssue(
            severity="error",
            source="design_contract",
            rule="runtime_assets_missing",
            message=(
                "Runtime motion attributes are present, but summit-motion.css "
                "or summit-motion.js is missing from the HTML."
            ),
        ))

    if not design_brief:
        return issues

    if not has_runtime_css or not has_runtime_js:
        issues.append(ValidationIssue(
            severity="error",
            source="design_contract",
            rule="runtime_assets_missing_for_brief",
            message=(
                "A Site Design Brief exists, but the generated HTML is missing "
                "Summit Motion Runtime asset tags."
            ),
        ))

    business_name = str(design_brief.get("business_name") or "").strip()
    if business_name and business_name.lower() not in soup.get_text(" ", strip=True).lower():
        issues.append(ValidationIssue(
            severity="warning",
            source="design_contract",
            rule="business_name_missing",
            message=f"Generated page text does not include the business name: {business_name}",
        ))

    experience = design_brief.get("experience_dna")
    experience = experience if isinstance(experience, dict) else {}
    recommended = [
        str(item)
        for item in (experience.get("recommended_primitives") or [])
        if str(item) in _PRIMITIVE_ATTR_EXPECTATIONS
    ]
    blocked = [
        str(item)
        for item in (experience.get("blocked_primitives") or [])
        if str(item) in _PRIMITIVE_ATTR_EXPECTATIONS
    ]

    for primitive_key in blocked:
        count = _count_expected_primitive(soup, primitive_key)
        if count:
            issues.append(ValidationIssue(
                severity="error",
                source="design_contract",
                rule="blocked_primitive_used",
                message=(
                    f"Blocked motion primitive '{primitive_key}' appears "
                    f"{count} time(s) in the generated HTML."
                ),
            ))

    used_recommended = 0
    for primitive_key in recommended:
        count = _count_expected_primitive(soup, primitive_key)
        if count:
            used_recommended += 1
        else:
            issues.append(ValidationIssue(
                severity="warning",
                source="design_contract",
                rule="recommended_primitive_missing",
                message=(
                    f"Recommended motion primitive '{primitive_key}' was not "
                    "activated with its Summit runtime attribute."
                ),
            ))
        max_instances = _primitive_max_instances(design_brief, primitive_key)
        if max_instances is not None and count > max_instances:
            issues.append(ValidationIssue(
                severity="warning",
                source="design_contract",
                rule="primitive_budget_exceeded",
                message=(
                    f"Motion primitive '{primitive_key}' appears {count} times; "
                    f"brief budget is {max_instances}."
                ),
            ))

    if recommended and not used_recommended and runtime_attr_count == 0:
        issues.append(ValidationIssue(
            severity="warning",
            source="design_contract",
            rule="runtime_attributes_absent",
            message=(
                "The Site Design Brief recommended runtime primitives, but no "
                "Summit runtime attributes were found in the HTML."
            ),
        ))

    script_text = "\n".join(
        script.get_text(" ", strip=True) for script in soup.find_all("script")
    )
    for rule, needle in _CUSTOM_MOTION_PATTERNS:
        if needle.lower() in script_text.lower():
            issues.append(ValidationIssue(
                severity="warning",
                source="design_contract",
                rule=rule,
                message=(
                    f"Inline script contains {needle}; use Summit Motion Runtime "
                    "attributes for reveal, parallax, sticky CTA, spotlight, and water behavior."
                ),
            ))
            break

    style_text = "\n".join(
        style.get_text(" ", strip=True) for style in soup.find_all("style")
    )
    if _CUSTOM_RUNTIME_SELECTOR_RE.search(style_text):
        issues.append(ValidationIssue(
            severity="error",
            source="design_contract",
            rule="custom_runtime_motion_css",
            message=(
                "Inline CSS styles Summit runtime attributes directly. "
                "Generated HTML must use data-motion/data-bg/data-parallax/"
                "data-hover attributes only and let summit-motion.css own "
                "visibility, transform, sticky, and parallax behavior."
            ),
        ))
    for match in re.finditer(
        r"@keyframes\s+([A-Za-z0-9_-]+)",
        style_text,
        flags=re.IGNORECASE,
    ):
        name = match.group(1).lower()
        if any(token in name for token in ("reveal", "parallax", "spotlight", "sticky")):
            issues.append(ValidationIssue(
                severity="warning",
                source="design_contract",
                rule="custom_motion_keyframes",
                message=(
                    f"Custom motion keyframes '{match.group(1)}' overlap with "
                    "Summit Motion Runtime behavior."
                ),
            ))
            break

    page_text = soup.get_text(" ", strip=True).lower()
    for term in ("lorem ipsum", "placeholder", "todo:"):
        if term in page_text:
            issues.append(ValidationIssue(
                severity="warning",
                source="design_contract",
                rule="placeholder_content",
                message=f"Generated page still contains placeholder text: {term}",
            ))
            break

    return issues


def validate_html(
    html_path: Path | str,
    design_brief_path: Path | str | None = None,
) -> ValidationReport:
    path = Path(html_path)
    report = ValidationReport()

    if not path.exists():
        report.passed = False
        report.issues.append(ValidationIssue(
            severity="error", source="io", rule="missing_file",
            message=f"HTML file not found: {path}",
        ))
        return report

    try:
        html = path.read_text(encoding="utf-8")
    except OSError as exc:
        report.passed = False
        report.issues.append(ValidationIssue(
            severity="error", source="io", rule="read_failed",
            message=f"Could not read HTML file: {exc}",
        ))
        return report

    htmlhint_issues, htmlhint_status = run_htmlhint(path)
    report.tool_runs["htmlhint"] = htmlhint_status
    report.issues.extend(htmlhint_issues)

    report.tool_runs["structure"] = "ok"
    report.issues.extend(run_structure_checks(html))

    report.tool_runs["a11y"] = "ok"
    report.issues.extend(run_a11y_checks(html))

    pa11y_issues, pa11y_status = run_pa11y(path)
    report.tool_runs["pa11y"] = pa11y_status
    report.issues.extend(pa11y_issues)

    lighthouse_issues, lighthouse_status = run_lighthouse(path)
    report.tool_runs["lighthouse"] = lighthouse_status
    report.issues.extend(lighthouse_issues)

    brief_path = (
        Path(design_brief_path)
        if design_brief_path is not None
        else path.parent / SITE_DESIGN_BRIEF_FILE
    )
    design_brief = _load_design_brief(brief_path)
    report.tool_runs["design_contract"] = (
        "ok" if design_brief else f"skipped: {SITE_DESIGN_BRIEF_FILE} not found"
    )
    report.issues.extend(run_design_contract_checks(html, design_brief))

    report.passed = report.error_count == 0
    return report


def save_report(report: ValidationReport, output_dir: Path | str) -> Path:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "validation.json"
    path.write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path
