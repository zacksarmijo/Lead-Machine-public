"""Request boundaries for the single-user, loopback-only desktop application.

This is not authentication for an Internet deployment. Keep the listener on
loopback: local programs and other users of this computer remain trusted.
"""
from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send


_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_PREVIEW_PATH = re.compile(r"^/api/ai/website-package/[^/]+/(?:mockup|files/.+)$")
PREVIEW_CSP = "sandbox allow-scripts; base-uri 'none'; form-action 'none'; object-src 'none'; frame-ancestors 'self'"
_APP_CSP = (
    "default-src 'self'; script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https: http:; "
    "connect-src 'self'; object-src 'none'; base-uri 'none'; "
    "frame-ancestors 'none'; form-action 'self'"
)


def _is_loopback(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        return address.is_loopback
    except ValueError:
        return False


def _origin(value: str) -> tuple[str, str, int] | None:
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return None
        if parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
            return None
        return parsed.scheme, parsed.hostname.lower(), parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        return None


class LocalOnlyMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        client = scope.get("client")
        host_headers = headers.getlist("host")
        request_origin = _origin(f"{scope.get('scheme', 'http')}://{host_headers[0]}") if len(host_headers) == 1 else None
        if not client or not _is_loopback(client[0]) or not request_origin or request_origin[1] not in _LOCAL_HOSTS:
            await PlainTextResponse("Only local connections and localhost hosts are allowed.", status_code=403)(scope, receive, send)
            return

        method = scope["method"]
        path = scope.get("path", "")
        # Sandboxed preview pages have an opaque origin. They may read preview
        # assets, but can never use that exception to call the application's API.
        preview_asset = method in {"GET", "HEAD"} and bool(_PREVIEW_PATH.fullmatch(path))
        origin_headers = headers.getlist("origin")
        origin = origin_headers[0] if len(origin_headers) == 1 else None
        bad_origin = bool(origin_headers) and (
            len(origin_headers) != 1 or (_origin(origin or "") != request_origin and not (preview_asset and origin == "null"))
        )
        cross_site = headers.get("sec-fetch-site", "").lower() not in {"", "none", "same-origin"}
        if bad_origin or (cross_site and not preview_asset):
            await PlainTextResponse("Cross-origin requests are not allowed.", status_code=403)(scope, receive, send)
            return
        # Browser forms and no-cors fetches cannot use application/json. This also
        # protects older browsers that do not send Fetch Metadata headers.
        if method not in _SAFE_METHODS and headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            await PlainTextResponse("Application requests must use application/json.", status_code=415)(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                response_headers = MutableHeaders(scope=message)
                response_headers.setdefault("X-Content-Type-Options", "nosniff")
                response_headers.setdefault("Referrer-Policy", "no-referrer")
                response_headers.setdefault("Cache-Control", "no-store")
                response_headers.setdefault("Content-Security-Policy", PREVIEW_CSP if preview_asset else _APP_CSP)
            await send(message)

        await self.app(scope, receive, send_with_headers)
