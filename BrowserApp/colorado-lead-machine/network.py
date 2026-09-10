from __future__ import annotations

"""Network helpers for the Colorado lead machine."""

import ipaddress
import socket
from typing import TYPE_CHECKING, Any, Optional
from urllib.parse import urljoin, urlparse

import requests

if TYPE_CHECKING:
    from lead_machine import LeadMachine


_HOST_SAFETY_CACHE: dict[str, bool] = {}


def _hostname_resolves_public(hostname: str) -> bool:
    cached = _HOST_SAFETY_CACHE.get(hostname)
    if cached is not None:
        return cached

    try:
        answers = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror:
        # Let the actual request surface DNS failures later; this check is
        # about blocking obviously unsafe resolved targets.
        _HOST_SAFETY_CACHE[hostname] = True
        return True

    saw_address = False
    for answer in answers:
        raw_ip = answer[4][0]
        try:
            resolved_ip = ipaddress.ip_address(raw_ip)
        except ValueError:
            continue
        saw_address = True
        if not resolved_ip.is_global:
            _HOST_SAFETY_CACHE[hostname] = False
            return False

    result = True if not saw_address else True
    _HOST_SAFETY_CACHE[hostname] = result
    return result


def is_safe_web_url(url: str) -> bool:
    parsed = urlparse(str(url).strip())
    if parsed.scheme not in {"http", "https"}:
        return False
    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        return False
    if hostname == "localhost" or hostname.endswith(".local"):
        return False
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return _hostname_resolves_public(hostname)
    return address.is_global


def create_session(headers: dict[str, str]) -> requests.Session:
    session = requests.Session()
    session.headers.update(headers)
    return session


def get_session(machine: "LeadMachine") -> requests.Session:
    session = getattr(machine._session_local, "session", None)
    if session is None:
        session = machine._create_session()
        machine._session_local.session = session
    return session


def request(machine: "LeadMachine", method: str, url: str, **kwargs) -> requests.Response:
    kwargs.setdefault("verify", True)
    return machine.session.request(method.upper(), url, **kwargs)


def safe_web_request(
    machine: "LeadMachine",
    method: str,
    url: str,
    *,
    timeout: tuple[float, float] | int | float | None = None,
    max_redirects: int = 4,
) -> requests.Response:
    current_method = method.upper()
    current_url = str(url).strip()
    history: list[requests.Response] = []
    redirect_codes = {301, 302, 303, 307, 308}

    for _ in range(max_redirects + 1):
        if not is_safe_web_url(current_url):
            raise ValueError(f"Unsafe or unsupported URL blocked: {current_url}")

        response = machine._request(
            current_method,
            current_url,
            timeout=timeout,
            allow_redirects=False,
        )
        response.url = current_url

        headers = getattr(response, "headers", {}) or {}
        redirect_target = str(headers.get("Location", "")).strip() if hasattr(headers, "get") else ""
        if response.status_code in redirect_codes and redirect_target:
            next_url = urljoin(current_url, redirect_target)
            if not is_safe_web_url(next_url):
                raise ValueError(f"Unsafe redirect blocked: {current_url} -> {next_url}")
            history.append(response)
            current_url = next_url
            if response.status_code == 303 and current_method != "HEAD":
                current_method = "GET"
            continue

        response.history = history
        return response

    raise requests.exceptions.TooManyRedirects(f"Exceeded redirect limit while fetching {url}")


def url_variations(url: str) -> list[str]:
    """Generate URL variations to try when the original fails."""
    variations: list[str] = [url]
    parsed = urlparse(url)
    host = parsed.hostname or ""
    scheme = parsed.scheme or "https"

    if host.startswith("www."):
        no_www = url.replace("://www.", "://", 1)
        if no_www not in variations:
            variations.append(no_www)
    else:
        with_www = url.replace("://", "://www.", 1)
        if with_www not in variations:
            variations.append(with_www)

    if scheme == "https":
        http_var = url.replace("https://", "http://", 1)
        if http_var not in variations:
            variations.append(http_var)
    elif scheme == "http":
        https_var = url.replace("http://", "https://", 1)
        if https_var not in variations:
            variations.append(https_var)

    for candidate in list(variations):
        if not candidate.endswith("/") and "/" not in urlparse(candidate).path.lstrip("/"):
            slashed = candidate + "/"
            if slashed not in variations:
                variations.append(slashed)

    return variations


def try_fetch(
    machine: "LeadMachine",
    url: str,
    timeout: tuple[float, float] | int | float | None = None,
) -> tuple[requests.Response | None, Exception | None]:
    """Attempt a single GET request."""
    if not is_safe_web_url(url):
        return None, ValueError(f"Unsafe or unsupported URL blocked: {url}")
    try:
        response = machine._safe_web_request(
            "get",
            url,
            timeout=timeout or machine._DEFAULT_FETCH_TIMEOUT,
        )
        return response, None
    except Exception as exc:
        return None, exc


def _exception_kind(exc: Exception) -> str:
    if isinstance(exc, requests.exceptions.ConnectTimeout | requests.exceptions.ReadTimeout | requests.exceptions.Timeout):
        return "timeout"
    if isinstance(exc, requests.exceptions.SSLError):
        return "ssl_error"
    if isinstance(exc, requests.exceptions.TooManyRedirects):
        return "too_many_redirects"
    if isinstance(exc, requests.exceptions.ConnectionError):
        return "connection_error"
    if isinstance(exc, ValueError):
        return "unsafe_url"
    return type(exc).__name__ or "request_error"


def _looks_blocked(status_code: int, body: str) -> bool:
    lowered = (body or "").lower()
    if status_code in {401, 403, 429}:
        return True
    return any(
        marker in lowered
        for marker in [
            "captcha",
            "unusual traffic",
            "access denied",
            "cloudflare",
            "cf-ray",
            "verify you are human",
            "temporarily blocked",
        ]
    )


def _retry_recommended(error_type: str, status_code: int, body_length: int, blocked: bool, timeout: bool) -> bool:
    if timeout or blocked:
        return True
    if error_type in {"connection_error", "too_many_redirects", "empty_body", "truncated_body"}:
        return True
    if status_code in {408, 429, 500, 502, 503, 504}:
        return True
    if status_code == 200 and body_length < 200:
        return True
    return False


def _result(
    *,
    ok: bool,
    url: str,
    final_url: str = "",
    status_code: int = 0,
    html: str = "",
    error_type: str = "",
    error_message: str = "",
    provider: str = "",
    query: str = "",
    attempted_urls: list[str] | None = None,
    http_statuses: list[int] | None = None,
    elapsed_ms: int = 0,
) -> dict[str, Any]:
    body_length = len(html or "")
    timeout = error_type == "timeout"
    blocked = _looks_blocked(status_code, html)
    if ok and status_code == 200 and body_length == 0:
        ok = False
        error_type = "empty_body"
        error_message = error_message or "HTTP 200 returned an empty response body"
    elif ok and status_code == 200 and body_length < 200:
        error_type = error_type or "truncated_body"
        error_message = error_message or f"HTTP 200 response body was very small ({body_length} bytes)"
    elif not ok and not error_type and status_code:
        error_type = "http_status"
        error_message = error_message or f"HTTP {status_code}"
    retry = _retry_recommended(error_type, status_code, body_length, blocked, timeout)
    return {
        "ok": bool(ok),
        "url": url,
        "final_url": final_url or url,
        "status_code": int(status_code or 0),
        "error_type": error_type,
        "error_message": error_message,
        "blocked": blocked,
        "timeout": timeout,
        "body_length": body_length,
        "provider": provider,
        "query": query,
        "attempted_urls": list(attempted_urls or ([url] if url else [])),
        "http_statuses": [int(status) for status in (http_statuses or ([status_code] if status_code else []))],
        "retry_recommended": retry,
        "elapsed_ms": int(elapsed_ms or 0),
        "html": html,
    }


def fetch_page_result(
    machine: "LeadMachine",
    url: str,
    timeout: int | float | tuple[float, float] = 8,
    *,
    provider: str = "",
    query: str = "",
) -> dict[str, Any]:
    """Fetch a page and return a structured diagnostic result.

    This is intentionally verbose because lead quality depends on knowing the
    difference between "nothing exists" and "our fetch/search failed."
    """
    cleaned = str(url or "").strip()
    if not is_safe_web_url(cleaned):
        return _result(
            ok=False,
            url=cleaned,
            error_type="unsafe_url",
            error_message=f"Unsafe or unsupported URL blocked: {cleaned}",
            provider=provider,
            query=query,
        )
    try:
        response = machine._safe_web_request("get", cleaned, timeout=timeout)
        body = response.text or ""
        status_code = int(response.status_code or 0)
        history_statuses = [int(resp.status_code or 0) for resp in getattr(response, "history", [])]
        elapsed_ms = int(round(response.elapsed.total_seconds() * 1000)) if getattr(response, "elapsed", None) else 0
        ok = status_code == 200 and bool(body)
        error_type = "" if ok else "http_status"
        error_message = "" if ok else f"HTTP {status_code}"
        return _result(
            ok=ok,
            url=cleaned,
            final_url=response.url or cleaned,
            status_code=status_code,
            html=body,
            error_type=error_type,
            error_message=error_message,
            provider=provider,
            query=query,
            attempted_urls=[cleaned, response.url] if response.url and response.url != cleaned else [cleaned],
            http_statuses=[*history_statuses, status_code],
            elapsed_ms=elapsed_ms,
        )
    except Exception as exc:
        return _result(
            ok=False,
            url=cleaned,
            error_type=_exception_kind(exc),
            error_message=str(exc)[:240],
            provider=provider,
            query=query,
        )


def browser_fetch_page_result(
    machine: "LeadMachine",
    url: str,
    timeout_ms: int = 12000,
    *,
    provider: str = "browser",
    query: str = "",
) -> dict[str, Any]:
    """Optional Playwright fallback for JS-heavy or blocked pages."""
    cleaned = str(url or "").strip()
    if not is_safe_web_url(cleaned):
        return _result(
            ok=False,
            url=cleaned,
            error_type="unsafe_url",
            error_message=f"Unsafe or unsupported URL blocked: {cleaned}",
            provider=provider,
            query=query,
        )
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        return _result(
            ok=False,
            url=cleaned,
            error_type="browser_unavailable",
            error_message=f"Playwright unavailable: {str(exc)[:180]}",
            provider=provider,
            query=query,
        )
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(
                user_agent=machine.session.headers.get("User-Agent"),
                viewport={"width": 1366, "height": 900},
            )
            response = page.goto(cleaned, wait_until="domcontentloaded", timeout=timeout_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=3000)
            except Exception:
                pass
            html = page.content()
            final_url = page.url
            status_code = int(response.status or 0) if response else 0
            browser.close()
            return _result(
                ok=bool(html) and (not status_code or status_code < 400),
                url=cleaned,
                final_url=final_url,
                status_code=status_code,
                html=html,
                error_type="" if html else "empty_body",
                error_message="" if html else "Browser rendered an empty response body",
                provider=provider,
                query=query,
                attempted_urls=[cleaned, final_url] if final_url != cleaned else [cleaned],
                http_statuses=[status_code] if status_code else [],
            )
    except Exception as exc:
        return _result(
            ok=False,
            url=cleaned,
            error_type=_exception_kind(exc) if isinstance(exc, Exception) else "browser_error",
            error_message=str(exc)[:240],
            provider=provider,
            query=query,
        )


def should_try_variations(exc: Exception | None) -> bool:
    """Decide if URL variations are worth retrying after a failed attempt."""
    if exc is None:
        return True
    name = type(exc).__name__
    if isinstance(exc, requests.exceptions.ConnectionError):
        text = str(exc).lower()
        if "getaddrinfo failed" in text or "name or service not known" in text or "nodename nor servname" in text:
            return False
    if isinstance(exc, ValueError):
        return False
    if "Timeout" in name:
        return False
    return True


def fetch_with_fallbacks(machine: "LeadMachine", url: str) -> tuple[requests.Response | None, str, bool]:
    """Try the URL with a small fallback budget."""
    variations = machine._url_variations(url)
    primary = variations[0]
    if not is_safe_web_url(primary):
        return None, primary, False

    response, exc = machine._try_fetch(primary, timeout=machine._DEFAULT_FETCH_TIMEOUT)
    if response is not None and response.status_code < 400:
        return response, primary, False
    best = response

    if not machine._should_try_variations(exc):
        return best, primary, False

    for alt_url in variations[1:3]:
        alt_response, alt_exc = machine._try_fetch(alt_url, timeout=machine._SHORT_FETCH_TIMEOUT)
        if alt_response is not None and alt_response.status_code < 400:
            return alt_response, alt_url, True
        if best is None:
            best = alt_response
        if not machine._should_try_variations(alt_exc):
            break

    return best, primary, False


def fetch_page(machine: "LeadMachine", url: str, timeout: int = 8) -> tuple[Optional[str], Optional[str]]:
    result = fetch_page_result(machine, url, timeout)
    if result.get("ok") and int(result.get("status_code") or 0) == 200:
        return str(result.get("html") or ""), str(result.get("final_url") or url)
    return None, None
