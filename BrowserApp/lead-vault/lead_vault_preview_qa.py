"""Preview QA for generated website mockups.

Captures desktop/mobile screenshots with Playwright when available and
records lightweight runtime/layout checks. The module is intentionally
optional: if Playwright or browser binaries are missing, it writes a
skipped report instead of breaking generation or Studio.
"""
from __future__ import annotations

import json
import mimetypes
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlparse


PREVIEW_QA_DIR = "preview_qa"
PREVIEW_QA_FILE = "preview_qa.json"
PREVIEW_QA_VERSION = 1
DESKTOP_VIEWPORT = {"name": "desktop", "width": 1440, "height": 1000, "is_mobile": False}
MOBILE_VIEWPORT = {"name": "mobile", "width": 390, "height": 844, "is_mobile": True}
PREVIEW_ORIGIN = "https://preview.invalid"
PREVIEW_CSP = (
    "default-src 'self' data: blob:; script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; connect-src 'none'; frame-src 'none'; "
    "object-src 'none'; base-uri 'none'; form-action 'none'"
)


def _route_preview_asset(route: Any, asset_root: Path) -> None:
    """Serve only this generated bundle; never give its scripts file:// access."""
    try:
        request = route.request
        parsed = urlparse(request.url)
        if (request.method not in ("GET", "HEAD")
                or f"{parsed.scheme}://{parsed.netloc}" != PREVIEW_ORIGIN):
            route.abort("blockedbyclient")
            return
        relative = unquote(parsed.path).lstrip("/")
        if "\\" in relative or "\x00" in relative or ":" in relative:
            route.abort("blockedbyclient")
            return
        root = asset_root.resolve()
        target = (root / relative).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            route.abort("blockedbyclient")
            return
        route.fulfill(
            status=200,
            headers={
                "Content-Type": mimetypes.guess_type(target.name)[0] or "application/octet-stream",
                "Content-Security-Policy": PREVIEW_CSP,
                "X-Content-Type-Options": "nosniff",
            },
            body=target.read_bytes() if request.method != "HEAD" else b"",
        )
    except (OSError, ValueError):
        route.abort("blockedbyclient")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _issue(
    severity: str,
    rule: str,
    message: str,
    *,
    viewport: str = "",
) -> dict[str, Any]:
    return {
        "severity": severity,
        "source": "preview_qa",
        "rule": rule,
        "message": message,
        "viewport": viewport,
    }


def _png_nonblank(path: Path) -> bool | None:
    try:
        from PIL import Image, ImageStat  # type: ignore
    except ImportError:
        return None
    try:
        with Image.open(path) as image:
            if image.width < 8 or image.height < 8:
                return False
            stat = ImageStat.Stat(image.convert("RGB"))
            extrema = stat.extrema
    except OSError:
        return False
    return any(high > low for low, high in extrema)


def _playwright_message_attr(message: Any, name: str) -> str:
    value = getattr(message, name, "")
    if callable(value):
        try:
            value = value()
        except Exception:
            value = ""
    return str(value or "")


def _format_playwright_error(exc: Exception) -> str:
    raw = str(exc or "").replace("\r\n", "\n")
    first_line = next((line.strip() for line in raw.split("\n") if line.strip()), "")
    if "Executable doesn't exist" in raw and (
        "playwright install" in raw or "download new browsers" in raw
    ):
        return (
            f"{first_line} Run: python -m playwright install chromium"
            if first_line
            else "Playwright browser binaries are missing. Run: python -m playwright install chromium"
        )
    return " ".join(line.strip() for line in raw.split("\n") if line.strip())[:1000]


def _is_missing_playwright_browser(exc: Exception) -> bool:
    raw = str(exc or "")
    return "Executable doesn't exist" in raw and (
        "playwright install" in raw or "download new browsers" in raw
    )


def _metrics_script() -> str:
    return """
() => {
  const root = document.documentElement;
  const body = document.body;
  const text = (body && body.innerText || '').trim();
  const runtimeAttrs = [
    '[data-motion]',
    '[data-bg]',
    '[data-parallax]',
    '[data-hover]'
  ];
  const q = (selector) => Array.from(document.querySelectorAll(selector));
  const reveal = q('[data-motion="reveal-up"]');
  const sticky = q('[data-motion="sticky-cta"]');
  const parallax = q('[data-parallax]');
  const consoleRuntime = !!window.SummitMotionRuntime;
  const rect = body ? body.getBoundingClientRect() : { width: 0, height: 0 };
  return {
    title: document.title || '',
    text_chars: text.length,
    image_count: q('img').length,
    runtime_loaded: consoleRuntime,
    runtime_html_class: root.classList.contains('summit-motion-js'),
    runtime_css: !!document.querySelector('link[data-summit-motion-runtime], link[href*="summit-motion.css"]'),
    runtime_js: !!document.querySelector('script[data-summit-motion-runtime], script[src*="summit-motion.js"]'),
    runtime_attr_count: runtimeAttrs.reduce((sum, selector) => sum + q(selector).length, 0),
    reveal_count: reveal.length,
    revealed_count: reveal.filter((el) => el.classList.contains('summit-motion-visible')).length,
    sticky_count: sticky.length,
    sticky_stuck_count: sticky.filter((el) => el.classList.contains('summit-motion-stuck')).length,
    parallax_count: parallax.length,
    parallax_active_count: parallax.filter((el) => {
      const style = getComputedStyle(el);
      return style.getPropertyValue('--summit-parallax-x').trim()
        || style.getPropertyValue('--summit-parallax-y').trim();
    }).length,
    body_width: Math.round(rect.width || 0),
    body_height: Math.round(rect.height || 0),
    viewport_width: window.innerWidth,
    viewport_height: window.innerHeight,
    scroll_width: root.scrollWidth,
    scroll_height: root.scrollHeight,
    horizontal_overflow_px: Math.max(0, root.scrollWidth - window.innerWidth),
  };
}
"""


def evaluate_viewport_metrics(
    metrics: dict[str, Any],
    *,
    viewport: str,
    screenshot_nonblank: bool | None,
    console_errors: list[str] | None = None,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if screenshot_nonblank is False:
        issues.append(_issue(
            "error",
            "blank_screenshot",
            "Screenshot appears blank or has no visual variation.",
            viewport=viewport,
        ))
    if int(metrics.get("body_height") or 0) < 120:
        issues.append(_issue(
            "error",
            "body_too_short",
            "Rendered body is too short to be a usable generated page.",
            viewport=viewport,
        ))
    if int(metrics.get("text_chars") or 0) < 80 and int(metrics.get("image_count") or 0) == 0:
        issues.append(_issue(
            "error",
            "content_too_sparse",
            "Rendered page has very little visible text and no images.",
            viewport=viewport,
        ))
    overflow = int(metrics.get("horizontal_overflow_px") or 0)
    if overflow > 16:
        issues.append(_issue(
            "warning",
            "horizontal_overflow",
            f"Viewport has {overflow}px horizontal overflow.",
            viewport=viewport,
        ))
    if int(metrics.get("runtime_attr_count") or 0):
        if not metrics.get("runtime_css") or not metrics.get("runtime_js"):
            issues.append(_issue(
                "error",
                "runtime_assets_missing",
                "Runtime attributes are present, but Summit runtime CSS/JS is missing.",
                viewport=viewport,
            ))
        if not metrics.get("runtime_loaded"):
            issues.append(_issue(
                "warning",
                "runtime_not_loaded",
                "Summit Motion Runtime did not expose window.SummitMotionRuntime.",
                viewport=viewport,
            ))
    if int(metrics.get("reveal_count") or 0) and int(metrics.get("revealed_count") or 0) == 0:
        issues.append(_issue(
            "warning",
            "reveal_not_visible",
            "Reveal elements exist but none were marked visible during preview QA.",
            viewport=viewport,
        ))
    errors = [item for item in (console_errors or []) if item]
    if errors:
        issues.append(_issue(
            "warning",
            "console_errors",
            "Console errors during preview: " + " | ".join(errors[:3]),
            viewport=viewport,
        ))
    return issues


def _save_report(report: dict[str, Any], output_dir: Path) -> Path:
    qa_dir = output_dir / PREVIEW_QA_DIR
    qa_dir.mkdir(parents=True, exist_ok=True)
    path = qa_dir / PREVIEW_QA_FILE
    path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def _skipped_report(html_path: Path, reason: str, output_dir: Path) -> dict[str, Any]:
    report = {
        "ok": True,
        "passed": None,
        "status": "skipped",
        "version": PREVIEW_QA_VERSION,
        "created_at": _utc_now_iso(),
        "html_path": str(html_path),
        "tool_runs": {"playwright": f"skipped: {reason}"},
        "viewports": [],
        "issues": [],
    }
    _save_report(report, output_dir)
    return report


def run_preview_qa(
    html_path: Path | str,
    output_dir: Path | str | None = None,
    *,
    timeout_ms: int = 15_000,
    playwright_factory: Any = None,
) -> dict[str, Any]:
    """Capture offline desktop/mobile previews of assets inside this bundle.

    External fonts, images, frames, API requests and WebSockets are intentionally
    unavailable. Remote assets must be bundled before visual QA.
    """
    path = Path(html_path)
    out_dir = Path(output_dir) if output_dir is not None else path.parent
    if not path.exists():
        report = {
            "ok": False,
            "passed": False,
            "status": "failed",
            "version": PREVIEW_QA_VERSION,
            "created_at": _utc_now_iso(),
            "html_path": str(path),
            "tool_runs": {"playwright": "not run"},
            "viewports": [],
            "issues": [_issue("error", "missing_html", f"HTML file not found: {path}")],
        }
        _save_report(report, out_dir)
        return report

    if playwright_factory is None:
        try:
            from playwright.sync_api import sync_playwright  # type: ignore
        except ImportError:
            return _skipped_report(path, "playwright package not installed", out_dir)
        playwright_factory = sync_playwright

    qa_dir = out_dir / PREVIEW_QA_DIR
    qa_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "ok": True,
        "passed": True,
        "status": "completed",
        "version": PREVIEW_QA_VERSION,
        "created_at": _utc_now_iso(),
        "html_path": str(path),
        "tool_runs": {"playwright": "ok"},
        "viewports": [],
        "issues": [],
        "network_policy": "offline: generated bundle assets only",
    }

    try:
        manager = playwright_factory()
        context_manager = manager if hasattr(manager, "__enter__") else nullcontext(manager)
        with context_manager as playwright:
            browser = playwright.chromium.launch(
                headless=True, chromium_sandbox=True,
                args=["--host-resolver-rules=MAP * ~NOTFOUND",
                      "--force-webrtc-ip-handling-policy=disable_non_proxied_udp"],
            )
            try:
                for viewport in (DESKTOP_VIEWPORT, MOBILE_VIEWPORT):
                    name = viewport["name"]
                    browser_context = browser.new_context(
                        viewport={
                            "width": viewport["width"],
                            "height": viewport["height"],
                        },
                        device_scale_factor=1,
                        is_mobile=bool(viewport["is_mobile"]),
                        service_workers="block",
                        accept_downloads=False,
                    )
                    try:
                        browser_context.route(
                            "**/*", lambda route: _route_preview_asset(route, path.parent)
                        )
                        browser_context.route_web_socket(
                            "**/*", lambda websocket: websocket.close()
                        )
                        page = browser_context.new_page()
                        console_errors: list[str] = []
                        def record_console_error(msg: Any) -> None:
                            if _playwright_message_attr(msg, "type") == "error":
                                console_errors.append(
                                    _playwright_message_attr(msg, "text")[:500]
                                )

                        page.on("console", record_console_error)
                        page.on(
                            "pageerror",
                            lambda exc: console_errors.append(str(exc)[:500]),
                        )
                        page.goto(
                            f"{PREVIEW_ORIGIN}/{quote(path.name)}",
                            wait_until="networkidle", timeout=timeout_ms,
                        )
                        page.wait_for_timeout(650)
                        page.mouse.move(viewport["width"] // 2, viewport["height"] // 3)
                        page.evaluate(
                            "() => window.scrollTo(0, Math.min(640, document.documentElement.scrollHeight))"
                        )
                        page.wait_for_timeout(250)
                        screenshot_name = f"{name}.png"
                        screenshot_path = qa_dir / screenshot_name
                        page.screenshot(path=str(screenshot_path), full_page=True)
                        metrics = page.evaluate(_metrics_script())
                        nonblank = _png_nonblank(screenshot_path)
                        viewport_issues = evaluate_viewport_metrics(
                            metrics,
                            viewport=name,
                            screenshot_nonblank=nonblank,
                            console_errors=console_errors,
                        )
                        report["viewports"].append({
                            "name": name,
                            "width": viewport["width"],
                            "height": viewport["height"],
                            "screenshot": f"{PREVIEW_QA_DIR}/{screenshot_name}",
                            "screenshot_bytes": screenshot_path.stat().st_size,
                            "screenshot_nonblank": nonblank,
                            "metrics": metrics,
                            "issue_count": len(viewport_issues),
                        })
                        report["issues"].extend(viewport_issues)
                    finally:
                        browser_context.close()
            finally:
                browser.close()
    except Exception as exc:
        error_message = _format_playwright_error(exc)
        if _is_missing_playwright_browser(exc):
            report["ok"] = True
            report["passed"] = None
            report["status"] = "skipped"
            report["tool_runs"]["playwright"] = f"skipped: {error_message}"
            report["issues"] = []
        else:
            report["ok"] = False
            report["passed"] = False
            report["status"] = "failed"
            report["tool_runs"]["playwright"] = f"failed: {error_message}"
            report["issues"].append(_issue(
                "error",
                "playwright_failed",
                f"Preview QA failed: {error_message}",
            ))

    if report.get("status") != "skipped":
        report["passed"] = not any(
            issue.get("severity") == "error" for issue in report.get("issues", [])
        )
    _save_report(report, out_dir)
    return report
