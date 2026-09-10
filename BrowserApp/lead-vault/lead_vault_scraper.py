"""Lead site scraper — Phase 1 of website generator pipeline.

Fetches a single landing page and extracts assets the AI generator will
reuse: business name, services, contact info, photos, colors, fonts,
social links, and clean body text. Output is a JSON-serializable
ScrapedSite plus an on-disk asset bundle per lead_key.

Deliberately conservative:
- One page only (landing). No deep crawl.
- Respects robots.txt.
- Caps response size to avoid tarpits.
- Timeouts split between connect and read.
- SSL verification ON (unlike the audit path, which probes hostile hosts).
"""
from __future__ import annotations

import json
import ipaddress
import re
import socket
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

try:
    import requests
except ImportError:
    requests = None  # type: ignore

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None  # type: ignore

try:
    import trafilatura as _trafilatura
except ImportError:
    _trafilatura = None  # type: ignore


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 "
    "SummitLeadVaultScraper/1.0"
)
DEFAULT_TIMEOUT: tuple[float, float] = (5.0, 10.0)
MAX_RESPONSE_BYTES = 5 * 1024 * 1024  # 5 MB cap
MAX_REDIRECTS = 5

# Phone regex v2: requires at least one separator between digit groups to
# avoid matching raw 10-digit hash/UUID-looking strings. Accepts either
# (XXX) format with optional separator, or XXX with a separator,
# followed by XXX[-.\s]XXXX.
PHONE_RE = re.compile(
    r"(?:\+?1[-.\s])?"          # optional country code + separator
    r"(?:\(\d{3}\)\s*|\d{3}[-.\s])"  # (XXX)[space] OR XXX[sep]
    r"\d{3}[-.\s]\d{4}"          # XXX[sep]XXXX — separator REQUIRED
)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Obfuscated email: "name [at] domain [dot] com" — require brackets around
# "at" so we don't match plain English prose. "dot" may be bracketed OR
# a literal period (plain-word "dot" without brackets is too ambiguous).
OBFUSCATED_EMAIL_RE = re.compile(
    r"([A-Za-z0-9._%+-]+)\s*"
    r"[\(\[\{]\s*at\s*[\)\]\}]\s*"
    r"([A-Za-z0-9-]+)\s*"
    r"(?:[\(\[\{]\s*dot\s*[\)\]\}]|\.)\s*"
    r"([A-Za-z]{2,})",
    re.IGNORECASE,
)
# Professional suffix that indicates a person name, not a business name.
PERSON_TITLE_SUFFIX_RE = re.compile(
    r",?\s+(?:DDS|DMD|MD|Ph\.?D\.?|CPA|Esq\.?|JD|RN|LPN|DO|OD|DPT|DVM|LMT|LCSW|MFT|PA-C|NP)\b",
    re.IGNORECASE,
)
HEX_COLOR_RE = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b")
RGB_COLOR_RE = re.compile(r"rgba?\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}[^\)]*\)")

# Nav link text that cookie/consent banners drop into the same <nav>/<header>
# anchors used for real site navigation. Strip these before deciding whether
# extraction produced anything useful.
COOKIE_JUNK_WORDS = frozenset({
    "accept", "accept all", "accept cookies", "decline", "deny",
    "reject", "reject all", "cookies", "cookie settings", "ok", "okay",
    "got it", "close", "dismiss", "yes", "no", "consent", "i agree",
    "agree", "allow", "allow all", "manage", "manage cookies",
    "settings", "preferences", "privacy", "privacy policy",
    "terms", "terms of service", "learn more", "more info", "menu",
})


SOCIAL_DOMAINS = {
    "facebook": "facebook.com",
    "instagram": "instagram.com",
    "twitter": "twitter.com",
    "x": "x.com",
    "linkedin": "linkedin.com",
    "youtube": "youtube.com",
    "tiktok": "tiktok.com",
    "yelp": "yelp.com",
    "google_maps": "google.com/maps",
}

IMAGE_SKIP_HINTS = (
    "pixel.", "tracker", "spacer", "blank.", "1x1", "transparent",
    "favicon", "icon-", "emoji", "logo-spacer",
)

# Only consider these extensions real photos (after stripping querystring).
PHOTO_EXT_RE = re.compile(r"\.(jpe?g|png|webp|avif|gif)(\?|$)", re.IGNORECASE)

# CSS url() inside background-image / background shorthand.
CSS_BG_URL_RE = re.compile(
    r"background(?:-image)?\s*:\s*[^;}]*url\(\s*['\"]?([^'\")]+)['\"]?\s*\)",
    re.IGNORECASE,
)

# URL path fragments that usually point to real business content uploads.
# Matches get a preference bump in the photo ranking.
CONTENT_PATH_HINTS = (
    "/upload", "/uploads", "/media", "/images", "/photos", "/gallery",
    "/content", "/presentation/", "/presentation-asset",
    "/wp-content/uploads",
)

# URL path fragments typical of third-party platform chrome (icons,
# widgets, UI sprites). These come with iframe/frameset platforms like
# highnote, linktree, etc. and rarely represent the actual business.
PLATFORM_CHROME_HINTS = (
    "/static/", "/dist/", "/build/", "/_next/static", "/assets/icons",
    "/public/icons", "cdn.shopify.com/s/files/1/0757",  # Shopify chrome
)


@dataclass
class ScrapedSite:
    source_url: str = ""
    final_url: str = ""
    status_code: int = 0
    ok: bool = False
    error: str = ""
    title: str = ""
    meta_description: str = ""
    business_name: str = ""
    favicon_url: str = ""
    logo_url: str = ""
    services: list[str] = field(default_factory=list)
    headings: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)
    photos: list[str] = field(default_factory=list)
    colors: list[str] = field(default_factory=list)
    fonts: list[str] = field(default_factory=list)
    social_links: dict[str, str] = field(default_factory=dict)
    tech_hints: list[str] = field(default_factory=list)
    crawled_pages: list[dict[str, Any]] = field(default_factory=list)
    crawl_errors: list[dict[str, Any]] = field(default_factory=list)
    site_blueprint: dict[str, Any] = field(default_factory=dict)
    main_text: str = ""
    has_https: bool = False
    robots_allowed: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Public API ───────────────────────────────────────────────────────

FetchMode = str  # "auto" | "static" | "browser"
BROWSER_TIMEOUT_MS = 20_000
THIN_HTML_MIN_BODY_CHARS = 400
MAX_INNER_CRAWL_PAGES = 6
MAX_MERGED_MAIN_TEXT_CHARS = 12_000
INNER_CRAWL_DELAY_SECONDS = 0.5
CRAWL_SKIP_EXT_RE = re.compile(
    r"\.(pdf|zip|docx?|xlsx?|pptx?|mp4|mov|avi|mp3|wav|css|js|json|xml)(\?|$)",
    re.IGNORECASE,
)
CRAWL_SKIP_PATH_HINTS = (
    "privacy", "terms", "policy", "login", "sign-in", "signin", "cart",
    "checkout", "account", "wp-admin", "feed", "tag/", "author/",
)
CRAWL_TARGET_KEYWORDS = (
    ("contact", 120),
    ("book", 105),
    ("appointment", 105),
    ("services", 100),
    ("service", 95),
    ("certification", 94),
    ("backflow", 93),
    ("fire", 92),
    ("about", 90),
    ("resource", 86),
    ("faq", 84),
    ("team", 82),
    ("staff", 80),
    ("menu", 78),
    ("gallery", 76),
    ("photos", 74),
    ("portfolio", 72),
    ("pricing", 70),
    ("areas", 68),
    ("location", 66),
    ("hours", 64),
)

PAGE_ROLE_KEYWORDS = (
    ("auth", ("login", "log in", "sign in", "signin", "portal", "account", "pay bill")),
    ("contact", ("contact", "quote", "estimate", "appointment", "schedule", "book")),
    ("services", ("services", "service", "certification", "inspection", "testing", "backflow", "fire alarm", "design build")),
    ("about", ("about", "company", "team", "staff", "who we are")),
    ("resources", ("resources", "resource", "faq", "forms", "downloads", "blog", "news")),
    ("gallery", ("gallery", "photos", "portfolio", "projects", "work")),
    ("locations", ("areas", "locations", "service area", "where we serve")),
    ("pricing", ("pricing", "rates", "plans", "cost")),
    ("legal", ("privacy", "terms", "policy", "accessibility")),
)

BLUEPRINT_ROLE_ORDER = (
    "home", "services", "about", "contact", "resources", "gallery",
    "locations", "pricing", "auth", "legal", "other",
)


def _is_blocked_address(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return True
    return not ip.is_global or ip.is_multicast


def _url_security_error(url: str) -> str:
    raw_url = str(url or "").strip()
    try:
        raw_scheme = urlparse(raw_url).scheme.lower()
    except ValueError:
        return "Invalid URL"
    host_port_without_scheme = re.fullmatch(
        r"[A-Za-z0-9.-]+:\d+(?:[/?#].*)?",
        raw_url,
    )
    if raw_scheme and raw_scheme not in ("http", "https") and not host_port_without_scheme:
        return "URL must use http or https"

    try:
        parsed = urlparse(raw_url if "://" in raw_url else f"https://{raw_url}")
        hostname = (parsed.hostname or "").strip().rstrip(".").lower()
        port = parsed.port
    except (ValueError, TypeError):
        return "Invalid URL"

    if parsed.scheme.lower() not in ("http", "https"):
        return "URL must use http or https"

    if parsed.username is not None or parsed.password is not None:
        return "URLs containing credentials are blocked for safety"
    if not hostname:
        return "Invalid URL"
    if hostname == "localhost" or hostname.endswith(".localhost"):
        return "Localhost URLs are blocked for safety"
    if "." not in hostname and ":" not in hostname:
        return "Single-label/private hostnames are blocked for safety"
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        if _is_blocked_address(hostname):
            return "Private, local, and reserved network addresses are blocked for safety"

    try:
        resolved = socket.getaddrinfo(
            hostname,
            port or (443 if parsed.scheme.lower() == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except (OSError, socket.gaierror):
        return "Hostname could not be resolved safely"

    if not resolved:
        return "Hostname could not be resolved safely"

    for info in resolved:
        address = (info[4] or ("",))[0]
        if _is_blocked_address(address):
            return "Private, local, and reserved network addresses are blocked for safety"
    return ""


def _public_session():
    """No ambient credentials; validate and pin the actual connection address.

    Checking DNS only before requests.get leaves a DNS-rebinding window. These
    pools resolve at connection time and connect to an approved numeric address,
    while retaining the original hostname for Host and TLS certificate checks.
    """
    from urllib3 import HTTPConnectionPool, HTTPSConnectionPool
    from urllib3.connection import HTTPConnection, HTTPSConnection
    from urllib3.util.connection import create_connection

    class PublicConnectionMixin:
        def _new_conn(self):
            addresses = socket.getaddrinfo(self.host, self.port, type=socket.SOCK_STREAM)
            if not addresses or any(_is_blocked_address(info[4][0]) for info in addresses):
                raise OSError("Connection to a non-public address is blocked")
            last_error = None
            for info in addresses:
                try:
                    return create_connection(
                        (info[4][0], self.port),
                        self.timeout,
                        source_address=self.source_address,
                        socket_options=self.socket_options,
                    )
                except OSError as exc:
                    last_error = exc
            raise OSError("Public host connection failed") from last_error

    class PublicHTTPConnection(PublicConnectionMixin, HTTPConnection):
        pass

    class PublicHTTPSConnection(PublicConnectionMixin, HTTPSConnection):
        pass

    class PublicHTTPPool(HTTPConnectionPool):
        ConnectionCls = PublicHTTPConnection

    class PublicHTTPSPool(HTTPSConnectionPool):
        ConnectionCls = PublicHTTPSConnection

    class PublicAdapter(requests.adapters.HTTPAdapter):
        def init_poolmanager(self, *args, **kwargs):
            super().init_poolmanager(*args, **kwargs)
            self.poolmanager.pool_classes_by_scheme = {
                "http": PublicHTTPPool, "https": PublicHTTPSPool,
            }

    session = requests.Session()
    session.trust_env = False
    session.mount("http://", PublicAdapter())
    session.mount("https://", PublicAdapter())
    return session


def _request_public(url: str, timeout=DEFAULT_TIMEOUT):
    """Fetch a public URL, validating every redirect before contacting it."""
    current = url
    with _public_session() as session:
        for hop in range(MAX_REDIRECTS + 1):
            error = _url_security_error(current)
            if error:
                raise ValueError(error)
            response = session.get(
                current, timeout=timeout, allow_redirects=False, stream=True,
                headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
            )
            if response.status_code not in (301, 302, 303, 307, 308):
                return response
            location = response.headers.get("Location", "")
            response.close()
            if not location:
                raise ValueError("Redirect is missing its destination")
            if hop == MAX_REDIRECTS:
                raise ValueError("Too many redirects")
            current = urljoin(current, location)
    raise ValueError("Could not fetch public URL")


def _route_public_browser_request(route) -> None:
    """Keep browser subresources and redirects inside the same public boundary."""
    if route.request.method not in ("GET", "HEAD"):
        route.abort("blockedbyclient")
        return
    try:
        response = _request_public(route.request.url)
        try:
            body = _read_capped(response, MAX_RESPONSE_BYTES)
            # requests already decoded transport compression. Do not replay its
            # length/encoding, cookies, or authentication headers to Chromium.
            headers = {
                key: value for key, value in response.headers.items()
                if key.lower() not in {
                    "content-encoding", "content-length", "transfer-encoding",
                    "set-cookie", "www-authenticate", "proxy-authenticate",
                }
            }
            route.fulfill(status=response.status_code, headers=headers, body=body)
        finally:
            response.close()
    except Exception:
        route.abort("blockedbyclient")


def scrape_site(
    url: str,
    timeout: tuple[float, float] = DEFAULT_TIMEOUT,
    mode: FetchMode = "auto",
    smart_crawl: bool = True,
    _depth: int = 0,
) -> ScrapedSite:
    """Fetch a single page and extract reusable assets.

    mode:
      - "auto":    fast static fetch first; re-fetch with a real browser if
                   the response looks like an empty SPA shell. Default.
      - "static":  requests only. Fast. Fails on JS-rendered SPAs.
      - "browser": Playwright only. Slow but handles Wix/SPAs. Requires
                   `pip install playwright` and `playwright install chromium`.
    """
    if requests is None or BeautifulSoup is None:
        return ScrapedSite(
            source_url=url,
            error="Missing dependency: requests and/or beautifulsoup4 not installed",
        )

    cleaned = _normalize_url(url)
    if not cleaned:
        return ScrapedSite(source_url=url, error="Invalid URL")

    result = ScrapedSite(source_url=cleaned)
    security_error = _url_security_error(cleaned)
    if security_error:
        result.error = security_error
        return result

    allowed, robots_err = _robots_allowed(cleaned)
    result.robots_allowed = allowed
    if not allowed:
        result.error = f"Blocked by robots.txt ({robots_err or 'disallow'})"
        return result

    html = ""
    used_browser = False

    if mode in ("auto", "static"):
        html, static_err = _fetch_static(cleaned, timeout, result)
        if static_err and mode == "static":
            result.error = static_err
            return result
        if mode == "auto" and (static_err or _looks_like_spa_shell(html)):
            # Static path thin or failed — escalate to a real browser.
            browser_html, browser_err = _fetch_browser(cleaned, result)
            if browser_html:
                html = browser_html
                used_browser = True
            elif static_err:
                # Static failed and browser also failed — surface static err.
                result.error = static_err
                return result

    elif mode == "browser":
        browser_html, browser_err = _fetch_browser(cleaned, result)
        if not browser_html:
            result.error = browser_err or "Browser fetch returned empty HTML"
            return result
        html = browser_html
        used_browser = True

    else:
        result.error = f"Unknown fetch mode: {mode}"
        return result

    if not html:
        if not result.error:
            result.error = "Empty response body"
        return result

    # Frameset detection: legacy sites and link-in-bio wrappers (e.g.
    # highnote.io, linktr.ee shortcuts) embed real content in a <frame>.
    # Follow once — guarded by _depth to prevent redirect loops.
    frame_target = _detect_frame_target(html, result.final_url or cleaned)
    if frame_target and _depth < 1:
        inner = scrape_site(
            frame_target,
            timeout=timeout,
            mode=mode,
            smart_crawl=False,
            _depth=_depth + 1,
        )
        if inner.ok:
            # Preserve facts about the ENTRY site — the lead pitches their
            # own domain, not the embedded frame. has_https in particular
            # must reflect the source URL or audit pitch angles go wrong.
            inner.source_url = result.source_url
            inner.has_https = result.has_https
            inner.tech_hints.append(f"frameset wrapper -> {urlparse(frame_target).netloc}")
            return inner
        # If inner fetch failed, fall through and return what we have from the
        # wrapper — not great, but better than nothing.

    _extract_all(html, result)

    # Post-extract sparse fallback: _looks_like_spa_shell checks bulk text
    # length, but hybrid-rendered builders (GoDaddy, some Wix themes) ship
    # enough repeated hero text to pass that check while the nav/services
    # live in JS-rendered chunks. If extraction came back useless, escalate.
    if mode == "auto" and not used_browser and _extraction_too_sparse(result):
        browser_html, _browser_err = _fetch_browser(cleaned, result)
        if browser_html:
            fresh = ScrapedSite(
                source_url=result.source_url,
                final_url=result.final_url,
                status_code=result.status_code,
                has_https=result.has_https,
                robots_allowed=result.robots_allowed,
            )
            _extract_all(browser_html, fresh)
            fresh.tech_hints = _dedupe(
                result.tech_hints
                + fresh.tech_hints
                + ["sparse static -> browser fallback"]
            )[:12]
            result = fresh
            used_browser = True

    if used_browser and "rendered: browser" not in result.tech_hints:
        result.tech_hints.append("rendered: browser")

    if smart_crawl and _depth == 0:
        _crawl_inner_pages(html, result, timeout=timeout, mode=mode)

    result.site_blueprint = _build_site_blueprint(html, result)
    result.ok = True
    return result


def _extract_all(html: str, result: ScrapedSite) -> None:
    """Run every extractor against the given html into `result`."""
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        soup = BeautifulSoup(html, "html.parser")

    _extract_meta(soup, result)
    _extract_contact(html, soup, result)
    _extract_media(soup, result)
    _extract_design(html, soup, result)
    _extract_nav_and_headings(soup, result)
    _extract_social(soup, result)
    _extract_tech_hints(html, soup, result)
    _extract_body_text(html, soup, result)


def _detect_frame_target(html: str, base_url: str) -> str:
    """If HTML is a frameset wrapper, return the first frame src absolute URL."""
    lowered = html.lower()
    if "<frameset" not in lowered and "<frame " not in lowered:
        return ""
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        soup = BeautifulSoup(html, "html.parser")
    frame = soup.find("frame")
    if not frame:
        return ""
    src = (frame.get("src") or "").strip()
    if not src:
        return ""
    return urljoin(base_url, src)


def _fetch_static(
    url: str,
    timeout: tuple[float, float],
    result: ScrapedSite,
) -> tuple[str, str]:
    """Requests-based fetch. Mutates result.status_code/final_url/has_https.

    Returns (html, error). html is empty on failure.
    """
    try:
        resp = _request_public(url, timeout)
    except Exception as exc:
        return "", f"{type(exc).__name__}: {exc}"

    result.status_code = resp.status_code
    result.final_url = str(resp.url or url)
    result.has_https = result.final_url.lower().startswith("https://")
    redirect_security_error = _url_security_error(result.final_url)
    if redirect_security_error:
        resp.close()
        return "", redirect_security_error

    if resp.status_code >= 400:
        resp.close()
        return "", f"HTTP {resp.status_code}"

    try:
        body = _read_capped(resp, MAX_RESPONSE_BYTES)
    except Exception as exc:
        return "", f"Read failed: {exc}"
    finally:
        resp.close()

    if not body:
        return "", "Empty response body"

    return _decode_html(body, resp.headers.get("Content-Type", "")), ""


def _fetch_browser(url: str, result: ScrapedSite) -> tuple[str, str]:
    """Playwright-based fetch. Runs headless Chromium to render JS.

    Returns (html, error). Requires `playwright` package + installed browser
    binaries (`playwright install chromium`).
    """
    try:
        from playwright.sync_api import sync_playwright, Error as PlaywrightError
    except ImportError:
        return "", (
            "Playwright not installed. Run: pip install playwright && "
            "playwright install chromium"
        )

    # Resolve the main document before starting Chromium so relative links use
    # its final public URL. The route handler never delegates redirects to it.
    try:
        initial = _request_public(result.final_url or url)
        try:
            navigation_url = str(initial.url or url)
        finally:
            initial.close()
    except Exception as exc:
        return "", f"Browser navigation blocked: {type(exc).__name__}"

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True, chromium_sandbox=True,
                args=["--host-resolver-rules=MAP * ~NOTFOUND",
                      "--force-webrtc-ip-handling-policy=disable_non_proxied_udp"],
            )
            try:
                context = browser.new_context(
                    user_agent=USER_AGENT,
                    viewport={"width": 1366, "height": 900},
                    locale="en-US",
                    service_workers="block",
                    accept_downloads=False,
                )
                context.route("**/*", _route_public_browser_request)
                context.route_web_socket("**/*", lambda websocket: websocket.close())
                page = context.new_page()
                response = page.goto(
                    navigation_url, wait_until="networkidle", timeout=BROWSER_TIMEOUT_MS
                )
                if response is not None:
                    result.status_code = response.status
                    result.final_url = str(response.url or url)
                    result.has_https = result.final_url.lower().startswith("https://")
                    redirect_security_error = _url_security_error(result.final_url)
                    if redirect_security_error:
                        return "", redirect_security_error
                    if response.status >= 400:
                        return "", f"HTTP {response.status}"
                # Give lazy-mounted frameworks a beat after networkidle
                try:
                    page.wait_for_timeout(500)
                except Exception:
                    pass
                html = page.content()
                return html or "", ""
            finally:
                browser.close()
    except PlaywrightError as exc:
        return "", f"Playwright error: {exc}"
    except Exception as exc:
        return "", f"Browser fetch failed: {type(exc).__name__}: {exc}"


def _looks_like_spa_shell(html: str) -> bool:
    """Heuristic: does the static HTML look like an empty SPA frame?

    Triggers a browser re-fetch in auto mode. Conservative — false negatives
    are fine (we just keep the static result), false positives waste time
    spinning up a browser.
    """
    if not html:
        return True
    if len(html) < 800:
        return True
    lowered = html.lower()
    spa_markers = (
        'id="root"></div>',
        "id='root'></div>",
        'id="app"></div>',
        "id='app'></div>",
        'id="__next"',
        "data-reactroot",
        'ng-version="',
        "<!-- wix -->",
        "thunderbolt-elements",  # Wix runtime
    )
    if any(marker in lowered for marker in spa_markers):
        return True
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        soup = BeautifulSoup(html, "html.parser")
    # Strip non-content tags before measuring body text
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    body_text = (soup.body.get_text(" ", strip=True) if soup.body else "").strip()
    return len(body_text) < THIN_HTML_MIN_BODY_CHARS


def _extraction_too_sparse(result: ScrapedSite) -> bool:
    """True if extracted fields are too thin to ship to the generator.

    Catches hybrid-rendered builder sites (e.g. GoDaddy Website Builder)
    where the static shell has enough bulk text to pass _looks_like_spa_shell
    but the real nav and services are painted in by JS.
    """
    real_services = [
        s for s in result.services
        if s.strip().lower() not in COOKIE_JUNK_WORDS
    ]
    sparse_nav = len(real_services) < 3
    few_photos = len(result.photos) < 2
    repetitive_body = _body_text_is_repetitive(result.main_text)
    return sparse_nav and (few_photos or repetitive_body)


def _body_text_is_repetitive(text: str) -> bool:
    """True if a single line dominates extracted body text.

    Catches placeholder-only pages that repeat the hero heading 5-10x.
    """
    if not text:
        return True
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if len(lines) < 4:
        return True
    from collections import Counter
    counts = Counter(lines)
    top = counts.most_common(1)[0][1]
    return top >= max(3, len(lines) // 3)


def _discover_inner_page_urls(
    html: str,
    base_url: str,
    limit: int = MAX_INNER_CRAWL_PAGES,
) -> list[str]:
    """Find same-site high-value pages for a tiny lead-evidence crawl."""
    if not html or not base_url:
        return []
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        soup = BeautifulSoup(html, "html.parser")

    base = urlparse(base_url)
    base_host = (base.hostname or "").lower()
    if not base_host:
        return []

    home_path = (base.path or "/").rstrip("/") or "/"
    scored: dict[str, tuple[int, int, str]] = {}
    order = 0
    for anchor in soup.find_all("a", href=True):
        raw_href = str(anchor.get("href") or "").strip()
        if not raw_href or raw_href.lower().startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        absolute = urljoin(base_url, raw_href)
        parsed = urlparse(absolute)
        if parsed.scheme.lower() not in ("http", "https"):
            continue
        if (parsed.hostname or "").lower() != base_host:
            continue
        if CRAWL_SKIP_EXT_RE.search(parsed.path or ""):
            continue
        path_lower = (parsed.path or "/").lower()
        if any(hint in path_lower for hint in CRAWL_SKIP_PATH_HINTS):
            continue
        normalized = urlunparse(parsed._replace(fragment="", query=""))
        normalized_path = (urlparse(normalized).path or "/").rstrip("/") or "/"
        if normalized_path == home_path:
            continue

        text = anchor.get_text(" ", strip=True).lower()
        haystack = f"{path_lower} {text}".replace("_", " ").replace("-", " ")
        score = 0
        for keyword, weight in CRAWL_TARGET_KEYWORDS:
            if keyword in haystack:
                score = max(score, weight)
        if score <= 0:
            continue
        existing = scored.get(normalized)
        if existing is None or score > existing[0]:
            scored[normalized] = (score, order, normalized)
        order += 1

    ranked = sorted(scored.values(), key=lambda item: (-item[0], item[1]))
    return [url for _score, _order, url in ranked[:limit]]


def _fetch_inner_page_html(
    url: str,
    timeout: tuple[float, float],
    mode: FetchMode,
) -> tuple[str, ScrapedSite, str]:
    """Fetch one inner page for smart crawl without mutating the parent."""
    page = ScrapedSite(source_url=url)
    allowed, robots_err = _robots_allowed(url)
    page.robots_allowed = allowed
    if not allowed:
        return "", page, f"Blocked by robots.txt ({robots_err or 'disallow'})"

    if mode == "browser":
        html, err = _fetch_browser(url, page)
        return html, page, err

    html, err = _fetch_static(url, timeout, page)
    if mode == "auto" and (err or _looks_like_spa_shell(html)):
        browser_html, browser_err = _fetch_browser(url, page)
        if browser_html:
            if "rendered: browser" not in page.tech_hints:
                page.tech_hints.append("rendered: browser")
            return browser_html, page, ""
        if err:
            return "", page, err
        return html, page, browser_err
    return html, page, err


def _merge_scraped_page(parent: ScrapedSite, child: ScrapedSite) -> None:
    parent.services = _dedupe(parent.services + child.services)[:24]
    parent.headings = _dedupe(parent.headings + child.headings)[:36]
    parent.phones = _dedupe(parent.phones + child.phones)[:10]
    parent.emails = _dedupe(parent.emails + child.emails)[:10]
    parent.photos = _dedupe(parent.photos + child.photos)[:40]
    parent.colors = _dedupe(parent.colors + child.colors)[:12]
    parent.fonts = _dedupe(parent.fonts + child.fonts)[:10]
    parent.tech_hints = _dedupe(parent.tech_hints + child.tech_hints)[:16]
    for key, value in child.social_links.items():
        parent.social_links.setdefault(key, value)

    child_text = (child.main_text or "").strip()
    if child_text and child_text not in parent.main_text:
        combined = (parent.main_text.rstrip() + "\n\n" + child_text).strip()
        parent.main_text = combined[:MAX_MERGED_MAIN_TEXT_CHARS]


def _crawl_inner_pages(
    homepage_html: str,
    result: ScrapedSite,
    *,
    timeout: tuple[float, float],
    mode: FetchMode,
) -> None:
    base_url = result.final_url or result.source_url
    urls = _discover_inner_page_urls(homepage_html, base_url)
    if not urls:
        return

    for index, url in enumerate(urls):
        if index:
            time.sleep(INNER_CRAWL_DELAY_SECONDS)
        html, page_meta, err = _fetch_inner_page_html(url, timeout, mode)
        if err or not html:
            result.crawl_errors.append({
                "url": url,
                "error": str(err or "empty response")[:240],
                "status_code": page_meta.status_code,
            })
            continue

        final_url = page_meta.final_url or url
        if _is_auth_or_private_url(final_url):
            result.crawl_errors.append({
                "url": final_url,
                "error": "Skipped auth/private redirect",
                "status_code": page_meta.status_code,
            })
            continue

        child = ScrapedSite(
            source_url=url,
            final_url=final_url,
            status_code=page_meta.status_code,
            has_https=final_url.lower().startswith("https://"),
            robots_allowed=page_meta.robots_allowed,
        )
        _extract_all(html, child)
        _merge_scraped_page(result, child)
        result.crawled_pages.append({
            "url": child.final_url or url,
            "status_code": child.status_code,
            "title": child.title,
            "text_chars": len(child.main_text or ""),
        })

    if result.crawled_pages and "smart crawl: inner pages" not in result.tech_hints:
        result.tech_hints.append("smart crawl: inner pages")


def _build_site_blueprint(homepage_html: str, result: ScrapedSite) -> dict[str, Any]:
    """Summarize site shape for future multi-page generation decisions."""
    base_url = result.final_url or result.source_url
    pages = _extract_site_blueprint_pages(homepage_html, base_url, result)
    skipped_pages = _extract_site_blueprint_skipped_pages(homepage_html, base_url)
    form_summary = _extract_form_summary(homepage_html)
    role_counts: dict[str, int] = {}
    for page in pages:
        role = str(page.get("role") or "other")
        role_counts[role] = role_counts.get(role, 0) + 1

    observed_roles = [
        role for role in BLUEPRINT_ROLE_ORDER
        if role_counts.get(role)
    ]
    auth_detected = bool(role_counts.get("auth"))
    legal_detected = bool(role_counts.get("legal"))
    content_page_count = sum(
        count for role, count in role_counts.items()
        if role not in {"home", "legal", "auth"}
    )
    multi_page_detected = content_page_count >= 2 or len(pages) >= 4

    recommended_pages = _recommended_pages_from_roles(observed_roles, result)
    risk_flags: list[str] = []
    if auth_detected:
        risk_flags.append("auth_or_portal_detected")
    if form_summary.get("auth_forms"):
        risk_flags.append("auth_form_detected")
    if form_summary.get("forms"):
        risk_flags.append("forms_detected_no_submission")
    if legal_detected:
        risk_flags.append("legal_pages_detected")
    if multi_page_detected:
        risk_flags.append("multi_page_site_detected")
    if not result.phones and not result.emails:
        risk_flags.append("contact_info_missing")
    if len(result.main_text or "") < 400:
        risk_flags.append("thin_content")

    if auth_detected or multi_page_detected:
        generator_fit = "multi_page_blueprint_needed"
    elif content_page_count <= 1:
        generator_fit = "single_page_mockup_ok"
    else:
        generator_fit = "review_needed"

    return {
        "version": 1,
        "base_url": base_url,
        "page_count_observed": len(pages),
        "content_page_count": content_page_count,
        "observed_roles": observed_roles,
        "role_counts": role_counts,
        "pages": pages[:24],
        "skipped_pages": skipped_pages[:24],
        "forms": form_summary,
        "recommended_pages": recommended_pages,
        "auth_detected": auth_detected,
        "multi_page_detected": multi_page_detected,
        "generator_fit": generator_fit,
        "risk_flags": risk_flags,
    }


def _extract_site_blueprint_pages(
    homepage_html: str,
    base_url: str,
    result: ScrapedSite,
) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_page(url: str, label: str, role: str, source: str, crawled: bool = False) -> None:
        normalized = _normalize_blueprint_url(url)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        pages.append({
            "url": normalized,
            "label": (label or role.title())[:120],
            "role": role or "other",
            "source": source,
            "crawled": bool(crawled),
        })

    add_page(base_url, result.business_name or result.title or "Home", "home", "homepage", True)

    try:
        soup = BeautifulSoup(homepage_html, "lxml")
    except Exception:
        soup = BeautifulSoup(homepage_html, "html.parser")

    base_host = (urlparse(base_url).hostname or "").lower()
    home_path = (urlparse(base_url).path or "/").rstrip("/") or "/"
    for anchor in soup.find_all("a", href=True):
        raw_href = str(anchor.get("href") or "").strip()
        if not raw_href or raw_href.lower().startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        absolute = urljoin(base_url, raw_href)
        parsed = urlparse(absolute)
        if parsed.scheme.lower() not in ("http", "https"):
            continue
        if base_host and (parsed.hostname or "").lower() != base_host:
            continue
        if CRAWL_SKIP_EXT_RE.search(parsed.path or ""):
            continue
        normalized = _normalize_blueprint_url(absolute)
        if not normalized:
            continue
        normalized_path = (urlparse(normalized).path or "/").rstrip("/") or "/"
        if normalized_path == home_path:
            continue
        label = anchor.get_text(" ", strip=True) or normalized_path.strip("/") or "Page"
        role = _classify_page_role(normalized, label)
        add_page(normalized, label, role, "homepage_link")

    crawled_by_url = {
        _normalize_blueprint_url(str((page or {}).get("url") or "")): page
        for page in result.crawled_pages
        if isinstance(page, dict)
    }
    for normalized, page in crawled_by_url.items():
        if not normalized:
            continue
        label = str(page.get("title") or urlparse(normalized).path.strip("/") or "Page")
        role = _classify_page_role(normalized, label)
        if normalized in seen:
            for existing in pages:
                if existing.get("url") == normalized:
                    existing["crawled"] = True
                    if label and not existing.get("label"):
                        existing["label"] = label[:120]
                    break
        else:
            add_page(normalized, label, role, "smart_crawl", True)

    pages.sort(key=lambda page: (
        BLUEPRINT_ROLE_ORDER.index(page["role"])
        if page.get("role") in BLUEPRINT_ROLE_ORDER else len(BLUEPRINT_ROLE_ORDER),
        0 if page.get("crawled") else 1,
        str(page.get("label") or "").lower(),
    ))
    return pages


def _extract_site_blueprint_skipped_pages(
    homepage_html: str,
    base_url: str,
) -> list[dict[str, str]]:
    """Record public-audit crawl boundaries without fetching skipped URLs."""
    if not homepage_html or not base_url:
        return []
    try:
        soup = BeautifulSoup(homepage_html, "lxml")
    except Exception:
        soup = BeautifulSoup(homepage_html, "html.parser")

    base_host = (urlparse(base_url).hostname or "").lower()
    skipped: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(url: str, label: str, reason: str) -> None:
        normalized = _normalize_blueprint_url(url)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        skipped.append({
            "url": normalized,
            "label": (label or urlparse(normalized).path.strip("/") or "Page")[:120],
            "reason": reason,
        })

    for anchor in soup.find_all("a", href=True):
        raw_href = str(anchor.get("href") or "").strip()
        if not raw_href:
            continue
        href_lower = raw_href.lower()
        if href_lower.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        absolute = urljoin(base_url, raw_href)
        parsed = urlparse(absolute)
        if parsed.scheme.lower() not in ("http", "https"):
            continue
        label = anchor.get_text(" ", strip=True)
        if base_host and (parsed.hostname or "").lower() != base_host:
            add(absolute, label, "external_domain_recorded_not_crawled")
            continue
        if CRAWL_SKIP_EXT_RE.search(parsed.path or ""):
            add(absolute, label, "non_html_asset_skipped")
            continue
        role = _classify_page_role(absolute, label)
        path_lower = (parsed.path or "/").lower()
        if role == "auth" or _is_auth_or_private_url(absolute):
            add(absolute, label, "auth_or_private_area_detected_not_crawled")
        elif role == "legal" or any(hint in path_lower for hint in ("privacy", "terms", "policy")):
            add(absolute, label, "legal_policy_page_recorded_not_crawled")

    return skipped[:24]


def _extract_form_summary(homepage_html: str) -> dict[str, Any]:
    """Inventory forms without submitting or interacting with them."""
    if not homepage_html:
        return {"forms": 0, "auth_forms": 0, "contact_forms": 0, "form_types": []}
    try:
        soup = BeautifulSoup(homepage_html, "lxml")
    except Exception:
        soup = BeautifulSoup(homepage_html, "html.parser")

    form_types: list[str] = []
    auth_forms = 0
    contact_forms = 0
    for form in soup.find_all("form"):
        text = form.get_text(" ", strip=True).lower()
        action = str(form.get("action") or "").lower()
        input_names = " ".join(
            str(inp.get("name") or inp.get("id") or inp.get("type") or "")
            for inp in form.find_all(["input", "textarea", "select"])
        ).lower()
        haystack = f"{text} {action} {input_names}"
        if any(token in haystack for token in ("password", "login", "sign in", "signin", "account")):
            form_types.append("auth")
            auth_forms += 1
        elif any(token in haystack for token in ("contact", "quote", "estimate", "message", "email", "phone")):
            form_types.append("contact")
            contact_forms += 1
        else:
            form_types.append("other")

    return {
        "forms": len(form_types),
        "auth_forms": auth_forms,
        "contact_forms": contact_forms,
        "form_types": _dedupe(form_types)[:6],
    }


def _classify_page_role(url: str, label: str = "") -> str:
    parsed = urlparse(url or "")
    path = (parsed.path or "/").strip("/").replace("-", " ").replace("_", " ")
    haystack = f"{path} {label or ''}".lower()
    if not path:
        return "home"
    for role, keywords in PAGE_ROLE_KEYWORDS:
        if any(keyword in haystack for keyword in keywords):
            return role
    return "other"


def _is_auth_or_private_url(url: str) -> bool:
    parsed = urlparse(url or "")
    haystack = f"{parsed.path or ''} {parsed.query or ''}".lower()
    return any(
        hint in haystack
        for hint in (
            "login", "sign-in", "signin", "account", "portal",
            "checkout", "cart", "password",
        )
    )


def _normalize_blueprint_url(url: str) -> str:
    if not url:
        return ""
    try:
        parsed = urlparse(url)
    except Exception:
        return ""
    if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
        return ""
    return urlunparse(parsed._replace(fragment="", query="")).rstrip("/") or url


def _recommended_pages_from_roles(
    observed_roles: list[str],
    result: ScrapedSite,
) -> list[dict[str, str]]:
    recommendations: list[dict[str, str]] = []

    def add(role: str, title: str, reason: str) -> None:
        if any(item["role"] == role for item in recommendations):
            return
        recommendations.append({"role": role, "title": title, "reason": reason})

    add("home", "Home", "Primary brand and conversion entry point.")
    if "services" in observed_roles or result.services:
        add("services", "Services", "Service detail deserves separate page structure.")
    if "about" in observed_roles:
        add("about", "About", "Existing site has company credibility content.")
    if "resources" in observed_roles:
        add("resources", "Resources", "Existing site has informational or support content.")
    if "gallery" in observed_roles:
        add("gallery", "Gallery", "Existing site has visual proof or project content.")
    if "locations" in observed_roles:
        add("locations", "Service Areas", "Existing site references location/service-area content.")
    add("contact", "Contact", "Contact and quote flow should stay easy to find.")
    if "auth" in observed_roles:
        add("auth", "Client Portal / Sign In", "Detected account or sign-in flow; needs real integration planning.")
    if "legal" in observed_roles:
        add("legal", "Legal", "Detected policy or terms pages that should be preserved.")
    return recommendations[:10]


def save_scraped_assets(lead_key: str, scraped: ScrapedSite, base_dir: Path | str) -> Path:
    """Persist scraped payload under base_dir/scraped_assets/{lead_key}/.

    Returns the directory path. Writes:
      - scrape.json (full ScrapedSite dict)
      - main_text.txt (clean body text)
    """
    base = Path(base_dir) / "scraped_assets" / _safe_key(lead_key)
    base.mkdir(parents=True, exist_ok=True)

    json_path = base / "scrape.json"
    json_path.write_text(
        json.dumps(scraped.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    if scraped.main_text:
        (base / "main_text.txt").write_text(scraped.main_text, encoding="utf-8")

    return base


# ── Internals ────────────────────────────────────────────────────────

def _normalize_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    try:
        parsed = urlparse(raw)
        if not parsed.hostname:
            return ""
    except ValueError:
        return ""
    # Drop fragment, keep the rest as-is
    return urlunparse(parsed._replace(fragment=""))


def _safe_key(lead_key: str) -> str:
    return re.sub(r"[^A-Za-z0-9_\-]+", "_", lead_key or "unknown")[:120]


def _robots_allowed(url: str) -> tuple[bool, str]:
    """Check robots.txt. Permissive on fetch failure (log, don't block)."""
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    rp = RobotFileParser()
    rp.set_url(robots_url)
    try:
        response = _request_public(robots_url)
        try:
            if response.status_code in (401, 403):
                return False, "robots access denied"
            if response.status_code >= 400:
                return True, "robots unavailable"
            body = _read_capped(response, 512 * 1024)
        finally:
            response.close()
        rp.parse(body.decode("utf-8", errors="replace").splitlines())
    except ValueError as exc:
        return False, f"unsafe robots fetch: {exc}"
    except Exception as exc:
        return True, f"robots fetch failed: {type(exc).__name__}"
    try:
        return rp.can_fetch(USER_AGENT, url), ""
    except Exception:
        return True, "robots parse failed"


def _read_capped(resp, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    for chunk in resp.iter_content(chunk_size=16 * 1024):
        if not chunk:
            continue
        total += len(chunk)
        if total > max_bytes:
            chunks.append(chunk[: max_bytes - (total - len(chunk))])
            break
        chunks.append(chunk)
    return b"".join(chunks)


def _decode_html(body: bytes, content_type: str) -> str:
    # Try charset from header, fall back to utf-8 with replace
    encoding = "utf-8"
    if content_type and "charset=" in content_type.lower():
        try:
            encoding = content_type.lower().split("charset=", 1)[1].split(";", 1)[0].strip() or "utf-8"
        except Exception:
            encoding = "utf-8"
    try:
        return body.decode(encoding, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def _extract_meta(soup, result: ScrapedSite) -> None:
    if soup.title and soup.title.string:
        result.title = soup.title.string.strip()[:200]

    meta_desc = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
    if meta_desc and meta_desc.get("content"):
        result.meta_description = meta_desc["content"].strip()[:400]

    og_site = soup.find("meta", attrs={"property": "og:site_name"})
    og_title = soup.find("meta", attrs={"property": "og:title"})
    h1 = soup.find("h1")
    h1_text = (h1.get_text(" ", strip=True) if h1 else "")[:120]

    business_candidate = ""
    if og_site and og_site.get("content"):
        business_candidate = og_site["content"].strip()
    elif h1_text and 3 <= len(h1_text) <= 60 and not PERSON_TITLE_SUFFIX_RE.search(h1_text):
        # Prefer H1 for sites with no og:site_name. Skip H1 when it reads
        # as a person name ("Dr. Jane Doe, DDS") — fall through to title.
        business_candidate = h1_text
    elif og_title and og_title.get("content"):
        business_candidate = og_title["content"].strip()
    elif result.title:
        business_candidate = result.title.split("|")[0].split("–")[0].split("-")[0].strip()
    # Strip trademark/registered symbols common in footers.
    business_candidate = re.sub(r"[®™©]", "", business_candidate).strip()
    result.business_name = business_candidate[:120]

    icon = soup.find("link", rel=re.compile("icon", re.I))
    if icon and icon.get("href"):
        result.favicon_url = urljoin(result.final_url or result.source_url, icon["href"].strip())


def _extract_contact(html: str, soup, result: ScrapedSite) -> None:
    text_blob = soup.get_text(" ", strip=True)

    phones_raw = PHONE_RE.findall(text_blob) + PHONE_RE.findall(html)
    emails_raw = EMAIL_RE.findall(text_blob) + EMAIL_RE.findall(html)

    # Deobfuscate "name [at] domain [dot] com" style addresses.
    for m in OBFUSCATED_EMAIL_RE.finditer(text_blob):
        local, domain, tld = m.groups()
        emails_raw.append(f"{local}@{domain}.{tld}")

    # Also check tel: and mailto: links
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.lower().startswith("tel:"):
            phones_raw.append(href[4:])
        elif href.lower().startswith("mailto:"):
            emails_raw.append(href[7:].split("?", 1)[0])

    result.phones = _dedupe([_clean_phone(p) for p in phones_raw if _clean_phone(p)])[:6]
    result.emails = _dedupe([e.strip().lower() for e in emails_raw if "@" in e])[:6]


def _clean_phone(raw: str) -> str:
    """Normalize + validate a US phone number. Rejects junk matches.

    NANP rules: area code and exchange code must each start with 2-9.
    Additional filters catch common regex false-positives:
      - 555 prefix (fictional / telemarketing-only range)
      - all same digit
      - obvious sequential runs (0123456789, 1234567890)
    """
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return ""
    area, exchange, line = digits[0:3], digits[3:6], digits[6:10]

    # NANP: area + exchange codes must start with digit 2-9.
    if area[0] in "01" or exchange[0] in "01":
        return ""
    # N11 codes aren't valid phone numbers (211, 311, 411, 511, 611, 711, 811, 911).
    if area[1:] == "11":
        return ""
    # 555 exchange = reserved / fictional
    if exchange == "555":
        return ""
    # All same digit (e.g. 1111111111, 8888888888)
    if len(set(digits)) == 1:
        return ""
    # Sequential runs
    if digits in ("0123456789", "1234567890", "9876543210"):
        return ""
    return f"({area}) {exchange}-{line}"


def _extract_media(soup, result: ScrapedSite) -> None:
    base_url = result.final_url or result.source_url

    # Logo guess: <img> with "logo" in src/alt/class, prefer header
    logo = ""
    for img in soup.find_all("img"):
        src = (img.get("src") or "").strip()
        alt = (img.get("alt") or "").lower()
        cls = " ".join(img.get("class") or []).lower()
        if not src:
            continue
        if "logo" in src.lower() or "logo" in alt or "logo" in cls:
            logo = urljoin(base_url, src)
            break

    # Fallback: first <img> inside <header>, else first logo-sized <img>
    # near the top (30-400w × 30-200h). Restrict to same-host URLs to
    # avoid grabbing third-party widgets (Facebook badges, tracker pixels).
    base_host = urlparse(base_url).netloc.lower()

    def _same_host(abs_url: str) -> bool:
        try:
            host = urlparse(abs_url).netloc.lower()
        except Exception:
            return False
        return not host or host == base_host

    if not logo:
        header = soup.find("header")
        if header:
            first = header.find("img", src=True)
            if first:
                abs_logo = urljoin(base_url, first["src"].strip())
                if _same_host(abs_logo):
                    logo = abs_logo
    if not logo:
        for img in soup.find_all("img"):
            src = (img.get("src") or "").strip()
            if not src:
                continue
            if any(hint in src.lower() for hint in IMAGE_SKIP_HINTS):
                continue
            w = _safe_int(img.get("width"))
            h = _safe_int(img.get("height"))
            if not (w and h and 30 <= w <= 400 and 30 <= h <= 200):
                continue
            abs_logo = urljoin(base_url, src)
            if not _same_host(abs_logo):
                continue
            logo = abs_logo
            break
    result.logo_url = logo

    # Rank: content-path > generic > platform-chrome. Dedupe on URL.
    # Multi-source: <img src/srcset/data-*>, <picture><source>, <a href> to
    # images, inline style="background-image:...", and <style> blocks.
    # Modern themes lazy-load everything, so plain <img src> catches almost
    # nothing on a real site.
    scored: list[tuple[int, str]] = []
    seen: set[str] = set()

    def _consider(raw: str, *, allow_any_ext: bool = False) -> None:
        if not raw:
            return
        raw = raw.strip()
        if not raw or raw.lower().startswith(("data:", "javascript:", "#")):
            return
        # srcset entries arrive as "url 1024w" — split off descriptor.
        raw = raw.split()[0]
        if not raw:
            return
        if any(hint in raw.lower() for hint in IMAGE_SKIP_HINTS):
            return
        abs_url = urljoin(base_url, raw)
        if abs_url in seen:
            return
        if not allow_any_ext and not PHOTO_EXT_RE.search(abs_url):
            return
        seen.add(abs_url)
        url_lower = abs_url.lower()
        if any(hint in url_lower for hint in CONTENT_PATH_HINTS):
            score = 2
        elif any(hint in url_lower for hint in PLATFORM_CHROME_HINTS):
            score = 0
        else:
            score = 1
        scored.append((score, abs_url))

    def _consider_srcset(value: str) -> None:
        for item in (value or "").split(","):
            _consider(item.strip())

    for img in soup.find_all("img"):
        width = _safe_int(img.get("width"))
        height = _safe_int(img.get("height"))
        if width and height and width < 80 and height < 80:
            continue
        for attr in (
            "src", "data-src", "data-lazy-src", "data-original",
            "data-img-url", "data-image", "data-bg", "data-large_image",
            "data-full",
        ):
            _consider(img.get(attr, ""))
        for attr in ("srcset", "data-srcset", "data-lazy-srcset"):
            _consider_srcset(img.get(attr, ""))

    for source in soup.find_all("source"):
        for attr in ("srcset", "data-srcset"):
            _consider_srcset(source.get(attr, ""))
        _consider(source.get("src", ""))

    # Gallery plugins wrap thumb <img> in an <a href="full-size.jpg">.
    for anchor in soup.find_all("a", href=True):
        _consider(anchor["href"])

    for tag in soup.find_all(style=True):
        for m in CSS_BG_URL_RE.finditer(tag.get("style", "")):
            _consider(m.group(1))

    for style_tag in soup.find_all("style"):
        css = style_tag.string or ""
        if "background" in css.lower():
            for m in CSS_BG_URL_RE.finditer(css):
                _consider(m.group(1))

    # Sort by score desc, preserve in-page order within same score bucket.
    scored.sort(key=lambda s: -s[0])
    result.photos = [url for _score, url in scored[:30]]


def _extract_design(html: str, soup, result: ScrapedSite) -> None:
    # Colors: from inline styles + <style> blocks
    color_source = ""
    for style in soup.find_all("style"):
        if style.string:
            color_source += style.string + "\n"
    for tag in soup.find_all(style=True):
        color_source += tag.get("style", "") + "\n"

    hex_colors = HEX_COLOR_RE.findall(color_source)
    rgb_colors = RGB_COLOR_RE.findall(color_source)
    # Normalize + dedupe, keep most common 8
    from collections import Counter
    counts = Counter([c.lower() for c in hex_colors] + [c.lower() for c in rgb_colors])
    result.colors = [c for c, _ in counts.most_common(8)]

    # Fonts: google fonts links and font-family declarations
    fonts: list[str] = []
    for link in soup.find_all("link", href=True):
        href = link["href"]
        if "fonts.googleapis.com" in href or "fonts.gstatic.com" in href:
            m = re.search(r"family=([^&:]+)", href)
            if m:
                fonts.append(m.group(1).replace("+", " "))
    family_matches = re.findall(r"font-family:\s*([^;\"'}]+)", color_source, flags=re.I)
    for raw in family_matches:
        first = raw.split(",")[0].strip().strip("'\"")
        if first and len(first) < 40:
            fonts.append(first)
    result.fonts = _dedupe(fonts)[:6]


def _extract_nav_and_headings(soup, result: ScrapedSite) -> None:
    services: list[str] = []
    for nav in soup.find_all(["nav", "header"]):
        for a in nav.find_all("a"):
            text = a.get_text(" ", strip=True)
            if text and 2 <= len(text) <= 40:
                services.append(text)

    # Legacy fallback: pre-HTML5 sites have no <nav>/<header>. Collect
    # same-site anchors with short text — old menus are bare <a> tags with
    # relative hrefs laid out by tables/divs.
    if not services:
        base_host = urlparse(result.final_url or result.source_url).netloc.lower()
        for a in soup.find_all("a", href=True):
            text = a.get_text(" ", strip=True)
            if not (text and 2 <= len(text) <= 40):
                continue
            href = a["href"].strip()
            href_lower = href.lower()
            if href_lower.startswith(("mailto:", "tel:", "javascript:", "#")):
                continue
            if href_lower.startswith(("http://", "https://")):
                if urlparse(href).netloc.lower() != base_host:
                    continue
            services.append(text)
            if len(services) >= 12:
                break

    result.services = _dedupe(services)[:12]

    headings: list[str] = []
    for tag in soup.find_all(["h1", "h2", "h3"]):
        text = tag.get_text(" ", strip=True)
        if text and len(text) <= 200:
            headings.append(text)
    result.headings = headings[:20]


def _extract_social(soup, result: ScrapedSite) -> None:
    social: dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        lower = href.lower()
        for key, domain in SOCIAL_DOMAINS.items():
            if domain in lower and key not in social:
                social[key] = href
    result.social_links = social


def _extract_tech_hints(html: str, soup, result: ScrapedSite) -> None:
    hints: list[str] = []
    lowered = html.lower()
    if "wp-content" in lowered or "wordpress" in lowered:
        hints.append("WordPress")
    if "shopify" in lowered:
        hints.append("Shopify")
    if "wix.com" in lowered:
        hints.append("Wix")
    if "squarespace" in lowered:
        hints.append("Squarespace")
    if "webflow" in lowered:
        hints.append("Webflow")
    if "network solutions" in lowered or "networksolutions.com" in lowered:
        hints.append("Network Solutions hosting (legacy)")
    if "<frameset" in lowered or "<frame " in lowered:
        hints.append("frameset layout (pre-HTML5)")

    # Doctype check: scan only the first 500 chars for performance.
    head_slice = lowered[:500]
    if "<!doctype" in head_slice and "<!doctype html>" not in head_slice:
        hints.append("legacy doctype (pre-HTML5)")
    elif "<!doctype" not in head_slice:
        hints.append("no doctype declared")

    # Mobile viewport absent = not mobile-responsive
    if not soup.find("meta", attrs={"name": re.compile("^viewport$", re.I)}):
        hints.append("no viewport meta (not mobile-responsive)")

    # Outdated jQuery — pre-3.x is deprecated, security risk
    jquery_match = re.search(r"jquery[-./]?(\d+)\.(\d+)", lowered)
    if jquery_match:
        major = int(jquery_match.group(1))
        if major < 3:
            hints.append(f"jQuery {major}.x (outdated)")

    # Flash content (deprecated end of 2020)
    if ".swf" in lowered or ("<embed" in lowered and "flash" in lowered):
        hints.append("Flash content (deprecated)")

    generator = soup.find("meta", attrs={"name": re.compile("^generator$", re.I)})
    if generator and generator.get("content"):
        hints.append(f"generator: {generator['content'].strip()[:80]}")
    result.tech_hints = _dedupe(hints)[:10]


def _extract_body_text(html: str, soup, result: ScrapedSite) -> None:
    trafilatura_text = _extract_main_text_with_trafilatura(html, result.final_url or result.source_url)
    if trafilatura_text:
        result.main_text = trafilatura_text[:8000]
        if "text: trafilatura" not in result.tech_hints:
            result.tech_hints.append("text: trafilatura")
        return

    # Strip non-content tags
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    main = soup.find("main") or soup.find("article") or soup.body or soup
    text = main.get_text("\n", strip=True) if main else ""
    # Collapse excessive whitespace, cap at 8k chars
    cleaned = re.sub(r"\n{3,}", "\n\n", text)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    result.main_text = cleaned[:8000]


def _extract_main_text_with_trafilatura(html: str, url: str = "") -> str:
    """Use Trafilatura for cleaner main-content text when available."""
    if _trafilatura is None or not html:
        return ""
    try:
        extracted = _trafilatura.extract(
            html,
            url=url or None,
            include_comments=False,
            include_tables=False,
            favor_precision=True,
        )
    except Exception:
        return ""
    text = re.sub(r"\n{3,}", "\n\n", str(extracted or "").strip())
    text = re.sub(r"[ \t]+", " ", text)
    return text


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = (item or "").strip()
        if not key:
            continue
        norm = key.lower()
        if norm in seen:
            continue
        seen.add(norm)
        out.append(key)
    return out


def _safe_int(value: Any) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0
