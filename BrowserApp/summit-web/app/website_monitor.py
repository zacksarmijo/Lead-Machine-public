from __future__ import annotations

"""Standalone website health and search-performance monitoring.

This module intentionally owns its own SQLite tables.  It does not read from or
write to the lead-generation pipeline, so a monitored site never becomes a lead
and its health score is always positive-facing (higher is healthier).
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import socket
import sqlite3
import time
from typing import Any, Callable, Iterable, Iterator
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup


PAGESPEED_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
DATAFORSEO_ENDPOINT = "https://api.dataforseo.com/v3/serp/google/organic/live/advanced"
PAGESPEED_CATEGORIES = ("performance", "accessibility", "best-practices", "seo")
MAX_RESPONSE_BYTES = 3_000_000
REDIRECT_CODES = {301, 302, 303, 307, 308}
VALID_SITE_TYPES = {"owned", "observed"}
VALID_DEVICES = {"desktop", "mobile"}
VALID_SEVERITIES = {"critical", "warning", "info"}


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _json_load(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    try:
        return json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _score(value: Any) -> int:
    parsed = _float(value)
    if 0 < parsed <= 1:
        parsed *= 100
    return max(0, min(100, int(round(parsed))))


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return _text(value).lower() not in {"", "0", "false", "no", "off", "none"}


def _normalize_host(value: str) -> str:
    host = (urlparse(value).hostname if "://" in value else value) or ""
    host = host.strip().lower().rstrip(".")
    return host[4:] if host.startswith("www.") else host


def _normalize_site_url(value: Any) -> str:
    raw = _text(value)
    if not raw:
        raise ValueError("Website URL is required")
    if "://" not in raw:
        raw = f"https://{raw}"
    parsed = urlparse(raw)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("Website URL must use http or https")
    if not parsed.hostname:
        raise ValueError("Website URL must include a valid hostname")
    if parsed.username or parsed.password:
        raise ValueError("Website URL cannot include credentials")
    hostname = parsed.hostname.lower().rstrip(".")
    if hostname == "localhost" or hostname.endswith(".localhost") or hostname.endswith(".local"):
        raise ValueError("Local or private websites cannot be monitored")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError("Local or private websites cannot be monitored")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Website URL contains an invalid port") from exc
    netloc = hostname
    if ":" in hostname and not hostname.startswith("["):
        netloc = f"[{hostname}]"
    if port is not None:
        netloc = f"{netloc}:{port}"
    path = parsed.path or "/"
    return urlunparse((parsed.scheme.lower(), netloc, path, "", "", ""))


def _clean_keywords(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values: Iterable[Any] = re.split(r"[\r\n,]+", value)
    elif isinstance(value, Iterable) and not isinstance(value, (bytes, dict)):
        values = value
    else:
        raise ValueError("Keywords must be a list or comma-separated text")
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in values:
        keyword = re.sub(r"\s+", " ", _text(item))
        if not keyword:
            continue
        if len(keyword) > 200:
            raise ValueError("Each keyword must be 200 characters or fewer")
        key = keyword.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(keyword)
    if len(cleaned) > 250:
        raise ValueError("A site can track at most 250 keywords")
    return cleaned


def _rank_value(item: dict[str, Any], key: str) -> int | None:
    value = item.get(key)
    if value in (None, ""):
        return None
    parsed = _int(value, -1)
    return parsed if parsed > 0 else None


class WebsiteMonitorStore:
    """SQLite-backed website monitor with injectable HTTP and DNS adapters."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        request_func: Callable[..., Any] | None = None,
        resolver: Callable[[str], Any] | None = None,
    ) -> None:
        self.db_path = str(db_path)
        self._request_func = request_func or requests.request
        self._resolver = resolver or self._default_resolver

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        if self.db_path != ":memory:":
            Path(self.db_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def ensure_ready(self) -> None:
        """Create monitor-owned tables without touching existing application data."""
        with self._connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS website_monitor_sites (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    url TEXT NOT NULL,
                    normalized_host TEXT NOT NULL,
                    site_type TEXT NOT NULL DEFAULT 'observed',
                    location TEXT NOT NULL DEFAULT '',
                    device TEXT NOT NULL DEFAULT 'mobile',
                    active INTEGER NOT NULL DEFAULT 1,
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS website_monitor_keywords (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    site_id INTEGER NOT NULL,
                    keyword TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (site_id) REFERENCES website_monitor_sites(id) ON DELETE CASCADE,
                    UNIQUE (site_id, keyword COLLATE NOCASE)
                );

                CREATE TABLE IF NOT EXISTS website_monitor_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    site_id INTEGER NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    status TEXT NOT NULL DEFAULT 'running',
                    overall_score INTEGER,
                    seo_score INTEGER,
                    technical_score INTEGER,
                    performance_score INTEGER,
                    visibility_score INTEGER,
                    previous_run_id INTEGER,
                    score_change INTEGER,
                    summary_json TEXT NOT NULL DEFAULT '{}',
                    error TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY (site_id) REFERENCES website_monitor_sites(id) ON DELETE CASCADE,
                    FOREIGN KEY (previous_run_id) REFERENCES website_monitor_runs(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS website_monitor_rank_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    site_id INTEGER NOT NULL,
                    keyword_id INTEGER,
                    keyword TEXT NOT NULL,
                    location TEXT NOT NULL DEFAULT '',
                    device TEXT NOT NULL DEFAULT 'mobile',
                    status TEXT NOT NULL,
                    rank_absolute INTEGER,
                    rank_group INTEGER,
                    previous_rank_absolute INTEGER,
                    rank_change INTEGER,
                    ranking_url TEXT NOT NULL DEFAULT '',
                    ranking_domain TEXT NOT NULL DEFAULT '',
                    result_count INTEGER NOT NULL DEFAULT 0,
                    top_competitors_json TEXT NOT NULL DEFAULT '[]',
                    error TEXT NOT NULL DEFAULT '',
                    captured_at TEXT NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES website_monitor_runs(id) ON DELETE CASCADE,
                    FOREIGN KEY (site_id) REFERENCES website_monitor_sites(id) ON DELETE CASCADE,
                    FOREIGN KEY (keyword_id) REFERENCES website_monitor_keywords(id) ON DELETE SET NULL,
                    UNIQUE (run_id, keyword_id)
                );

                CREATE TABLE IF NOT EXISTS website_monitor_page_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL UNIQUE,
                    site_id INTEGER NOT NULL,
                    url TEXT NOT NULL,
                    final_url TEXT NOT NULL DEFAULT '',
                    status_code INTEGER,
                    response_time_ms INTEGER,
                    content_type TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL DEFAULT '',
                    meta_description TEXT NOT NULL DEFAULT '',
                    h1_json TEXT NOT NULL DEFAULT '[]',
                    canonical_url TEXT NOT NULL DEFAULT '',
                    robots_meta TEXT NOT NULL DEFAULT '',
                    schema_json TEXT NOT NULL DEFAULT '{}',
                    word_count INTEGER NOT NULL DEFAULT 0,
                    internal_link_count INTEGER NOT NULL DEFAULT 0,
                    image_count INTEGER NOT NULL DEFAULT 0,
                    images_missing_alt INTEGER NOT NULL DEFAULT 0,
                    robots_txt_url TEXT NOT NULL DEFAULT '',
                    robots_txt_status INTEGER,
                    robots_txt_present INTEGER NOT NULL DEFAULT 0,
                    sitemap_url TEXT NOT NULL DEFAULT '',
                    sitemap_status INTEGER,
                    sitemap_present INTEGER NOT NULL DEFAULT 0,
                    fetch_error TEXT NOT NULL DEFAULT '',
                    page_json TEXT NOT NULL DEFAULT '{}',
                    pagespeed_json TEXT NOT NULL DEFAULT '{}',
                    captured_at TEXT NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES website_monitor_runs(id) ON DELETE CASCADE,
                    FOREIGN KEY (site_id) REFERENCES website_monitor_sites(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS website_monitor_issues (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    site_id INTEGER NOT NULL,
                    fingerprint TEXT NOT NULL,
                    category TEXT NOT NULL,
                    scope TEXT NOT NULL DEFAULT 'page',
                    code TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    title TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '',
                    recommendation TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'open',
                    first_run_id INTEGER,
                    last_run_id INTEGER,
                    resolved_run_id INTEGER,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    resolved_at TEXT,
                    FOREIGN KEY (site_id) REFERENCES website_monitor_sites(id) ON DELETE CASCADE,
                    FOREIGN KEY (first_run_id) REFERENCES website_monitor_runs(id) ON DELETE SET NULL,
                    FOREIGN KEY (last_run_id) REFERENCES website_monitor_runs(id) ON DELETE SET NULL,
                    FOREIGN KEY (resolved_run_id) REFERENCES website_monitor_runs(id) ON DELETE SET NULL,
                    UNIQUE (site_id, fingerprint)
                );

                CREATE INDEX IF NOT EXISTS idx_website_monitor_sites_active
                    ON website_monitor_sites(active, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_website_monitor_keywords_site
                    ON website_monitor_keywords(site_id, active, keyword);
                CREATE INDEX IF NOT EXISTS idx_website_monitor_runs_site
                    ON website_monitor_runs(site_id, id DESC);
                CREATE INDEX IF NOT EXISTS idx_website_monitor_rank_site
                    ON website_monitor_rank_snapshots(site_id, keyword_id, id DESC);
                CREATE INDEX IF NOT EXISTS idx_website_monitor_issues_site
                    ON website_monitor_issues(site_id, status, severity);
                """
            )

    # ------------------------------------------------------------------
    # Site configuration CRUD
    # ------------------------------------------------------------------
    def create_site(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.ensure_ready()
        if not isinstance(payload, dict):
            raise ValueError("Site payload must be an object")
        data = self._validated_site(payload, creating=True)
        keywords = _clean_keywords(payload.get("keywords", []))
        now = _utcnow()
        with self._connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO website_monitor_sites
                    (name, url, normalized_host, site_type, location, device, active, notes, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data["name"], data["url"], data["normalized_host"], data["site_type"],
                    data["location"], data["device"], int(data["active"]), data["notes"], now, now,
                ),
            )
            site_id = int(cursor.lastrowid)
            self._replace_keywords(conn, site_id, keywords, now)
        return self.get_site_detail(site_id)

    def update_site(self, site_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        self.ensure_ready()
        if not isinstance(payload, dict):
            raise ValueError("Site payload must be an object")
        with self._connection() as conn:
            current = conn.execute(
                "SELECT * FROM website_monitor_sites WHERE id = ?", (int(site_id),)
            ).fetchone()
            if current is None:
                raise ValueError(f"Monitored site {site_id} was not found")
            merged = dict(current)
            merged.update({key: value for key, value in payload.items() if key != "keywords"})
            data = self._validated_site(merged, creating=False)
            now = _utcnow()
            conn.execute(
                """
                UPDATE website_monitor_sites
                SET name = ?, url = ?, normalized_host = ?, site_type = ?, location = ?,
                    device = ?, active = ?, notes = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    data["name"], data["url"], data["normalized_host"], data["site_type"],
                    data["location"], data["device"], int(data["active"]), data["notes"], now,
                    int(site_id),
                ),
            )
            if "keywords" in payload:
                self._replace_keywords(conn, int(site_id), _clean_keywords(payload["keywords"]), now)
        return self.get_site_detail(int(site_id))

    def delete_site(self, site_id: int) -> dict[str, Any]:
        """Delete one explicitly selected monitor and all of its monitor-only history."""
        self.ensure_ready()
        with self._connection() as conn:
            row = conn.execute(
                "SELECT id, name, url FROM website_monitor_sites WHERE id = ?", (int(site_id),)
            ).fetchone()
            if row is None:
                raise ValueError(f"Monitored site {site_id} was not found")
            conn.execute("DELETE FROM website_monitor_sites WHERE id = ?", (int(site_id),))
        return {"deleted": True, "site_id": int(site_id), "name": row["name"], "url": row["url"]}

    def list_sites(self) -> list[dict[str, Any]]:
        self.ensure_ready()
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM website_monitor_sites ORDER BY active DESC, name COLLATE NOCASE, id"
            ).fetchall()
            return [self._site_summary(conn, row) for row in rows]

    def get_site_detail(self, site_id: int) -> dict[str, Any]:
        self.ensure_ready()
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM website_monitor_sites WHERE id = ?", (int(site_id),)
            ).fetchone()
            if row is None:
                raise ValueError(f"Monitored site {site_id} was not found")
            site = self._site_dict(conn, row)
            runs = self._history(conn, int(site_id), limit=60)
            latest = runs[0] if runs else None
            latest_run_id = int(latest["id"]) if latest else None
            site.update(
                {
                    "summary": self._site_summary(conn, row),
                    "latest_run": latest,
                    "history": runs,
                    "latest_page": self._page_for_run(conn, latest_run_id) if latest_run_id else None,
                    "latest_rankings": self._ranks_for_run(conn, latest_run_id) if latest_run_id else [],
                    "open_issues": self._issues(conn, int(site_id), "open"),
                    "resolved_issues": self._issues(conn, int(site_id), "resolved", limit=100),
                }
            )
            return site

    def get_site_summary(self, site_id: int) -> dict[str, Any]:
        """Return one compact site card without loading its full run history."""
        self.ensure_ready()
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM website_monitor_sites WHERE id = ?", (int(site_id),)
            ).fetchone()
            if row is None:
                raise ValueError(f"Monitored site {site_id} was not found")
            return self._site_summary(conn, row)

    def get_site_history(self, site_id: int, limit: int = 60) -> list[dict[str, Any]]:
        """Return newest-first health, page, and ranking snapshots for charting."""
        self.ensure_ready()
        with self._connection() as conn:
            exists = conn.execute(
                "SELECT 1 FROM website_monitor_sites WHERE id = ?", (int(site_id),)
            ).fetchone()
            if exists is None:
                raise ValueError(f"Monitored site {site_id} was not found")
            return self._history(conn, int(site_id), limit=limit)

    def get_summary(self) -> dict[str, Any]:
        self.ensure_ready()
        with self._connection() as conn:
            sites = conn.execute("SELECT * FROM website_monitor_sites ORDER BY name COLLATE NOCASE").fetchall()
            summaries = [self._site_summary(conn, row) for row in sites]
            latest_scores = [s["overall_score"] for s in summaries if s.get("overall_score") is not None]
            return {
                "site_count": len(summaries),
                "active_site_count": sum(1 for item in summaries if item["active"]),
                "owned_site_count": sum(1 for item in summaries if item["site_type"] == "owned"),
                "observed_site_count": sum(1 for item in summaries if item["site_type"] == "observed"),
                "open_issue_count": sum(int(item.get("open_issue_count") or 0) for item in summaries),
                "critical_issue_count": sum(int(item.get("critical_issue_count") or 0) for item in summaries),
                "average_health_score": (
                    int(round(sum(latest_scores) / len(latest_scores))) if latest_scores else None
                ),
                "sites": summaries,
            }

    def _validated_site(self, payload: dict[str, Any], *, creating: bool) -> dict[str, Any]:
        url = _normalize_site_url(payload.get("url"))
        name = re.sub(r"\s+", " ", _text(payload.get("name")))
        if not name:
            name = _normalize_host(url)
        if len(name) > 160:
            raise ValueError("Site name must be 160 characters or fewer")
        site_type = _text(payload.get("site_type", "observed")).lower() or "observed"
        if site_type not in VALID_SITE_TYPES:
            raise ValueError("site_type must be 'owned' or 'observed'")
        device = _text(payload.get("device", "mobile")).lower() or "mobile"
        if device not in VALID_DEVICES:
            raise ValueError("device must be 'desktop' or 'mobile'")
        location = re.sub(r"\s+", " ", _text(payload.get("location")))
        if len(location) > 200:
            raise ValueError("Location must be 200 characters or fewer")
        notes = _text(payload.get("notes"))
        if len(notes) > 10_000:
            raise ValueError("Notes must be 10,000 characters or fewer")
        active = _as_bool(payload.get("active", True if creating else payload.get("active")))
        return {
            "name": name,
            "url": url,
            "normalized_host": _normalize_host(url),
            "site_type": site_type,
            "location": location,
            "device": device,
            "active": active,
            "notes": notes,
        }

    def _replace_keywords(
        self, conn: sqlite3.Connection, site_id: int, keywords: list[str], now: str
    ) -> None:
        conn.execute(
            "UPDATE website_monitor_keywords SET active = 0, updated_at = ? WHERE site_id = ?",
            (now, site_id),
        )
        for keyword in keywords:
            existing = conn.execute(
                "SELECT id FROM website_monitor_keywords WHERE site_id = ? AND keyword = ? COLLATE NOCASE",
                (site_id, keyword),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE website_monitor_keywords SET keyword = ?, active = 1, updated_at = ? WHERE id = ?",
                    (keyword, now, int(existing["id"])),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO website_monitor_keywords(site_id, keyword, active, created_at, updated_at)
                    VALUES (?, ?, 1, ?, ?)
                    """,
                    (site_id, keyword, now, now),
                )

    # ------------------------------------------------------------------
    # Scan orchestration
    # ------------------------------------------------------------------
    def scan_site(self, site_id: int, settings: dict[str, Any] | None) -> dict[str, Any]:
        """Synchronously audit one public site and persist a comparable snapshot."""
        self.ensure_ready()
        settings = settings if isinstance(settings, dict) else {}
        site, keyword_rows, previous_run, previous_ranks = self._scan_inputs(int(site_id))
        if not site["active"]:
            raise ValueError("Inactive sites cannot be scanned until they are re-enabled")

        started_at = _utcnow()
        with self._connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO website_monitor_runs(site_id, started_at, status, previous_run_id, summary_json)
                VALUES (?, ?, 'running', ?, '{}')
                """,
                (int(site_id), started_at, previous_run["id"] if previous_run else None),
            )
            run_id = int(cursor.lastrowid)

        issues: list[dict[str, Any]] = []
        verified_scopes: set[str] = {"availability"}
        scan_errors: list[str] = []
        try:
            page, page_issues, page_verified = self._audit_homepage(site["url"])
            issues.extend(page_issues)
            verified_scopes.update(page_verified)
        except Exception as exc:  # network/parser failures are recorded, not allowed to corrupt the run
            error = _text(exc)[:500] or type(exc).__name__
            scan_errors.append(error)
            page = self._empty_page(site["url"], error)
            issues.append(
                self._issue(
                    "homepage_unavailable", "Homepage could not be audited", "critical", error,
                    "availability", "Confirm the site is online, publicly reachable, and using valid DNS/SSL.",
                    scope="availability",
                )
            )

        pagespeed = (
            {"status": "skipped", "reason": "Homepage could not be safely fetched"}
            if page.get("fetch_error")
            else self._run_pagespeed(site, settings)
        )
        page["pagespeed"] = pagespeed
        if pagespeed["status"] == "measured":
            verified_scopes.add("pagespeed")
            issues.extend(self._pagespeed_issues(pagespeed))
        elif pagespeed["status"] == "error":
            scan_errors.append(pagespeed.get("error") or "PageSpeed failed")
            issues.append(
                self._issue(
                    "pagespeed_error", "PageSpeed measurement failed", "warning",
                    pagespeed.get("error", ""), "integration",
                    "Retry the scan and verify the configured PageSpeed API key and quota.",
                    scope="pagespeed",
                )
            )

        rank_rows: list[dict[str, Any]] = []
        rank_provider_errors: list[str] = []
        for keyword_row in keyword_rows:
            keyword = keyword_row["keyword"]
            previous_rank = previous_ranks.get(keyword.casefold())
            rank = self._run_rank_check(site, keyword_row, settings)
            rank["previous_rank_absolute"] = previous_rank
            current_rank = rank.get("rank_absolute")
            rank["rank_change"] = (
                int(previous_rank) - int(current_rank)
                if previous_rank is not None and current_rank is not None
                else None
            )
            rank_rows.append(rank)
            scope = f"keyword:{keyword.casefold()}"
            if rank["status"] in {"found", "not_found"}:
                verified_scopes.add(scope)
                issues.extend(self._ranking_issues(rank, scope))
            elif rank["status"] == "error":
                rank_provider_errors.append(rank.get("error") or f"Ranking check failed for {keyword}")

        if rank_provider_errors:
            message = "; ".join(dict.fromkeys(rank_provider_errors))[:500]
            scan_errors.append(message)
            issues.append(
                self._issue(
                    "dataforseo_error", "Search ranking checks failed", "warning", message,
                    "integration", "Verify DataForSEO credentials, account balance, and location syntax.",
                    scope="dataforseo",
                )
            )
        elif keyword_rows and rank_rows and all(row["status"] in {"found", "not_found"} for row in rank_rows):
            verified_scopes.add("dataforseo")

        technical_score, seo_score, performance_score = self._health_scores(page, pagespeed)
        visibility_score = self._visibility_score(rank_rows)
        weighted: list[tuple[int, int]] = [
            (technical_score, 30),
            (seo_score, 30),
            (performance_score, 25),
        ]
        if visibility_score is not None:
            weighted.append((visibility_score, 15))
        overall_score = int(round(sum(value * weight for value, weight in weighted) / sum(w for _, w in weighted)))
        prior_score = previous_run.get("overall_score") if previous_run else None
        score_change = overall_score - int(prior_score) if prior_score is not None else None
        comparison = self._comparison(page, previous_run, rank_rows)
        status = "completed_with_errors" if scan_errors else "completed"
        completed_at = _utcnow()
        issues = self._dedupe_issues(issues)
        summary = {
            "health_direction": "higher_is_better",
            "scores": {
                "overall": overall_score,
                "technical": technical_score,
                "seo": seo_score,
                "performance": performance_score,
                "visibility": visibility_score,
            },
            "score_change": score_change,
            "homepage": {
                "status_code": page.get("status_code"),
                "response_time_ms": page.get("response_time_ms"),
                "title": page.get("title", ""),
                "fetch_error": page.get("fetch_error", ""),
            },
            "pagespeed_status": pagespeed.get("status"),
            "rankings": self._ranking_summary(rank_rows),
            "comparison": comparison,
            "issues": {
                "open_detected": len(issues),
                "critical": sum(1 for item in issues if item["severity"] == "critical"),
                "warning": sum(1 for item in issues if item["severity"] == "warning"),
                "info": sum(1 for item in issues if item["severity"] == "info"),
            },
        }

        with self._connection() as conn:
            self._insert_page_snapshot(conn, run_id, int(site_id), page, pagespeed, completed_at)
            for rank in rank_rows:
                self._insert_rank_snapshot(conn, run_id, int(site_id), rank, completed_at)
            self._reconcile_issues(conn, int(site_id), run_id, issues, verified_scopes, completed_at)
            conn.execute(
                """
                UPDATE website_monitor_runs
                SET completed_at = ?, status = ?, overall_score = ?, seo_score = ?, technical_score = ?,
                    performance_score = ?, visibility_score = ?, score_change = ?, summary_json = ?, error = ?
                WHERE id = ?
                """,
                (
                    completed_at, status, overall_score, seo_score, technical_score, performance_score,
                    visibility_score, score_change, _json_dump(summary), "; ".join(scan_errors)[:1000], run_id,
                ),
            )
        return self.get_site_detail(int(site_id))

    def _scan_inputs(
        self, site_id: int
    ) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any] | None, dict[str, int | None]]:
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM website_monitor_sites WHERE id = ?", (site_id,)).fetchone()
            if row is None:
                raise ValueError(f"Monitored site {site_id} was not found")
            site = dict(row)
            site["active"] = bool(site["active"])
            keyword_rows = [
                dict(item)
                for item in conn.execute(
                    """
                    SELECT id, keyword FROM website_monitor_keywords
                    WHERE site_id = ? AND active = 1 ORDER BY id
                    """,
                    (site_id,),
                ).fetchall()
            ]
            previous = conn.execute(
                """
                SELECT * FROM website_monitor_runs
                WHERE site_id = ? AND status != 'running'
                ORDER BY id DESC LIMIT 1
                """,
                (site_id,),
            ).fetchone()
            previous_dict = self._run_dict(previous) if previous else None
            previous_ranks: dict[str, int | None] = {}
            if previous:
                previous_dict["page"] = self._page_for_run(conn, int(previous["id"]))
                for rank in conn.execute(
                    "SELECT keyword, rank_absolute FROM website_monitor_rank_snapshots WHERE run_id = ?",
                    (int(previous["id"]),),
                ).fetchall():
                    previous_ranks[_text(rank["keyword"]).casefold()] = rank["rank_absolute"]
            return site, keyword_rows, previous_dict, previous_ranks

    # ------------------------------------------------------------------
    # Public-web audit and provider clients
    # ------------------------------------------------------------------
    @staticmethod
    def _default_resolver(hostname: str) -> list[str]:
        return list(
            dict.fromkeys(
                item[4][0]
                for item in socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
                if item and item[4]
            )
        )

    def _assert_public_url(self, value: str) -> str:
        url = _normalize_site_url(value)
        hostname = urlparse(url).hostname or ""
        try:
            resolved = self._resolver(hostname)
        except Exception as exc:
            raise ValueError(f"DNS lookup failed for {hostname}: {_text(exc)}") from exc
        addresses: list[str] = []
        for item in resolved or []:
            if isinstance(item, str):
                addresses.append(item)
            elif isinstance(item, tuple):
                candidate = item[4][0] if len(item) > 4 and isinstance(item[4], tuple) else item[0]
                addresses.append(_text(candidate))
        if not addresses:
            raise ValueError(f"DNS lookup returned no public addresses for {hostname}")
        for raw in addresses:
            try:
                address = ipaddress.ip_address(raw)
            except ValueError as exc:
                raise ValueError(f"DNS returned an invalid address for {hostname}") from exc
            if not address.is_global:
                raise ValueError(f"Blocked private or reserved address for {hostname}")
        return url

    def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        return self._request_func(method, url, **kwargs)

    def _fetch_public(self, url: str, *, accept: str = "text/html,*/*;q=0.8") -> tuple[Any, str, int]:
        current = self._assert_public_url(url)
        started = time.perf_counter()
        response: Any = None
        for _ in range(6):
            response = self._request(
                "get",
                current,
                headers={
                    "User-Agent": "Summit-Website-Monitor/1.0 (+public SEO health check)",
                    "Accept": accept,
                },
                timeout=(6, 25),
                allow_redirects=False,
            )
            status_code = _int(getattr(response, "status_code", 0))
            if status_code not in REDIRECT_CODES:
                elapsed_ms = int(round((time.perf_counter() - started) * 1000))
                response_elapsed = getattr(response, "elapsed", None)
                if response_elapsed is not None and hasattr(response_elapsed, "total_seconds"):
                    elapsed_ms = max(elapsed_ms, int(round(response_elapsed.total_seconds() * 1000)))
                return response, current, elapsed_ms
            location = _text(getattr(response, "headers", {}).get("Location"))
            if not location:
                break
            current = self._assert_public_url(urljoin(current, location))
        if response is None:
            raise RuntimeError("No HTTP response was received")
        raise RuntimeError("Website redirected too many times")

    @staticmethod
    def _response_text(response: Any) -> str:
        content = getattr(response, "content", None)
        if isinstance(content, bytes):
            raw = content[:MAX_RESPONSE_BYTES]
            encoding = _text(getattr(response, "encoding", "")) or "utf-8"
            try:
                return raw.decode(encoding, errors="replace")
            except LookupError:
                return raw.decode("utf-8", errors="replace")
        return _text(getattr(response, "text", ""))[:MAX_RESPONSE_BYTES]

    def _audit_homepage(
        self, url: str
    ) -> tuple[dict[str, Any], list[dict[str, Any]], set[str]]:
        response, final_url, elapsed_ms = self._fetch_public(url)
        status = _int(getattr(response, "status_code", 0))
        headers = getattr(response, "headers", {}) or {}
        content_type = _text(headers.get("Content-Type")).split(";", 1)[0].lower()
        html = self._response_text(response)
        soup = BeautifulSoup(html, "html.parser")
        title = _text(soup.title.get_text(" ", strip=True) if soup.title else "")
        description_tag = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
        meta_description = _text(description_tag.get("content") if description_tag else "")
        h1_values = [
            re.sub(r"\s+", " ", tag.get_text(" ", strip=True))
            for tag in soup.find_all("h1")
            if _text(tag.get_text(" ", strip=True))
        ]
        canonical_tag = soup.find("link", attrs={"rel": lambda value: value and "canonical" in value})
        canonical_url = urljoin(final_url, _text(canonical_tag.get("href"))) if canonical_tag else ""
        robots_values: list[str] = []
        for tag in soup.find_all("meta"):
            if _text(tag.get("name")).lower() in {"robots", "googlebot"}:
                content = _text(tag.get("content"))
                if content:
                    robots_values.append(content)
        robots_meta = ", ".join(dict.fromkeys(robots_values))

        schema_types: set[str] = set()
        valid_schema_blocks = 0
        for script in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
            try:
                payload = json.loads(script.string or script.get_text() or "")
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            valid_schema_blocks += 1
            self._collect_schema_types(payload, schema_types)

        for unwanted in soup(["script", "style", "noscript", "template", "svg"]):
            unwanted.decompose()
        visible_text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
        word_count = len(re.findall(r"\b[\w'-]+\b", visible_text, flags=re.UNICODE))
        page_host = _normalize_host(final_url)
        internal_links: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(final_url, _text(anchor.get("href")))
            parsed = urlparse(href)
            if parsed.scheme in {"http", "https"} and _normalize_host(href) == page_host:
                internal_links.add(urlunparse((parsed.scheme, parsed.netloc, parsed.path or "/", "", parsed.query, "")))
        images = soup.find_all("img")
        missing_alt = sum(1 for image in images if not _text(image.get("alt")))

        origin = urlparse(final_url)
        base = urlunparse((origin.scheme, origin.netloc, "/", "", "", ""))
        robots_url = urljoin(base, "robots.txt")
        sitemap_url = urljoin(base, "sitemap.xml")
        robots_status, robots_present, robots_error = self._probe_text_file(robots_url, "robots")
        sitemap_status, sitemap_present, sitemap_error = self._probe_text_file(sitemap_url, "sitemap")
        page: dict[str, Any] = {
            "url": url,
            "final_url": final_url,
            "status_code": status,
            "response_time_ms": elapsed_ms,
            "content_type": content_type,
            "title": title,
            "meta_description": meta_description,
            "h1": h1_values,
            "canonical_url": canonical_url,
            "robots_meta": robots_meta,
            "schema": {"valid_blocks": valid_schema_blocks, "types": sorted(schema_types)},
            "word_count": word_count,
            "internal_link_count": len(internal_links),
            "image_count": len(images),
            "images_missing_alt": missing_alt,
            "robots_txt_url": robots_url,
            "robots_txt_status": robots_status,
            "robots_txt_present": robots_present,
            "robots_txt_error": robots_error,
            "sitemap_url": sitemap_url,
            "sitemap_status": sitemap_status,
            "sitemap_present": sitemap_present,
            "sitemap_error": sitemap_error,
            "fetch_error": "",
        }
        return page, self._page_issues(page), {"page", "availability"}

    @staticmethod
    def _collect_schema_types(value: Any, output: set[str]) -> None:
        if isinstance(value, dict):
            schema_type = value.get("@type")
            if isinstance(schema_type, list):
                output.update(_text(item) for item in schema_type if _text(item))
            elif _text(schema_type):
                output.add(_text(schema_type))
            for child in value.values():
                WebsiteMonitorStore._collect_schema_types(child, output)
        elif isinstance(value, list):
            for child in value:
                WebsiteMonitorStore._collect_schema_types(child, output)

    def _probe_text_file(self, url: str, kind: str) -> tuple[int | None, bool, str]:
        try:
            response, _, _ = self._fetch_public(url, accept="text/plain,application/xml,text/xml,*/*;q=0.5")
            status = _int(getattr(response, "status_code", 0))
            body = self._response_text(response).lstrip().lower()
            if kind == "robots":
                present = status == 200 and bool(body)
            else:
                present = status == 200 and ("<urlset" in body or "<sitemapindex" in body)
            return status, present, ""
        except Exception as exc:
            return None, False, _text(exc)[:300]

    def _run_pagespeed(self, site: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
        api_key = _text(settings.get("pagespeed_api_key"))
        if not api_key or api_key == "********":
            return {"status": "skipped", "reason": "PageSpeed API key is not configured"}
        params: list[tuple[str, str]] = [
            ("url", site["url"]),
            ("strategy", site["device"]),
            ("key", api_key),
        ]
        params.extend(("category", item) for item in PAGESPEED_CATEGORIES)
        try:
            response = self._request("get", PAGESPEED_ENDPOINT, params=params, timeout=(8, 90))
            status_code = _int(getattr(response, "status_code", 0))
            if status_code >= 400 or status_code <= 0:
                raise RuntimeError(f"HTTP {status_code}: {self._response_text(response)[:180]}")
            payload = response.json()
            lighthouse = payload.get("lighthouseResult", {}) if isinstance(payload, dict) else {}
            categories = lighthouse.get("categories", {}) if isinstance(lighthouse, dict) else {}
            audits = lighthouse.get("audits", {}) if isinstance(lighthouse, dict) else {}
            if not isinstance(categories, dict) or not isinstance(categories.get("performance"), dict):
                message = _text(payload.get("error", {}).get("message")) if isinstance(payload, dict) else ""
                raise RuntimeError(message or "PageSpeed returned no Lighthouse categories")

            def category(name: str) -> int:
                value = categories.get(name, {}) if isinstance(categories, dict) else {}
                return _score(value.get("score")) if isinstance(value, dict) else 0

            result = {
                "status": "measured",
                "strategy": site["device"],
                "final_url": _text(lighthouse.get("finalUrl") or payload.get("id") or site["url"]),
                "analysis_timestamp": _text(payload.get("analysisUTCTimestamp") or lighthouse.get("fetchTime")),
                "performance_score": category("performance"),
                "accessibility_score": category("accessibility"),
                "best_practices_score": category("best-practices"),
                "seo_score": category("seo"),
                "fcp_ms": self._audit_numeric(audits, "first-contentful-paint"),
                "lcp_ms": self._audit_numeric(audits, "largest-contentful-paint"),
                "speed_index_ms": self._audit_numeric(audits, "speed-index"),
                "tbt_ms": self._audit_numeric(audits, "total-blocking-time"),
                "cls": self._audit_numeric(audits, "cumulative-layout-shift"),
                "inp_ms": self._field_percentile(payload.get("loadingExperience", {}), "INTERACTION_TO_NEXT_PAINT"),
                "crux_overall": _text((payload.get("loadingExperience", {}) or {}).get("overall_category")),
                "opportunities": self._pagespeed_opportunities(audits),
            }
            return result
        except Exception as exc:
            return {"status": "error", "strategy": site["device"], "error": _text(exc)[:500]}

    @staticmethod
    def _audit_numeric(audits: Any, key: str) -> float | int | None:
        item = audits.get(key, {}) if isinstance(audits, dict) else {}
        value = item.get("numericValue") if isinstance(item, dict) else None
        if value in (None, ""):
            return None
        parsed = _float(value)
        return round(parsed, 4) if key == "cumulative-layout-shift" else int(round(parsed))

    @staticmethod
    def _field_percentile(experience: Any, key: str) -> int | None:
        metrics = experience.get("metrics", {}) if isinstance(experience, dict) else {}
        metric = metrics.get(key, {}) if isinstance(metrics, dict) else {}
        value = metric.get("percentile") if isinstance(metric, dict) else None
        return _int(value) if value not in (None, "") else None

    @staticmethod
    def _pagespeed_opportunities(audits: Any) -> list[dict[str, Any]]:
        opportunities: list[dict[str, Any]] = []
        if not isinstance(audits, dict):
            return opportunities
        for key, audit in audits.items():
            if not isinstance(audit, dict) or audit.get("score") in (None, ""):
                continue
            details = audit.get("details", {}) if isinstance(audit.get("details"), dict) else {}
            savings_ms = _int(details.get("overallSavingsMs"))
            savings_bytes = _int(details.get("overallSavingsBytes"))
            if _float(audit.get("score"), 1) < 0.9 and (savings_ms > 0 or savings_bytes > 0):
                opportunities.append(
                    {
                        "id": key,
                        "title": _text(audit.get("title")),
                        "savings_ms": savings_ms,
                        "savings_bytes": savings_bytes,
                    }
                )
        opportunities.sort(key=lambda item: (item["savings_ms"], item["savings_bytes"]), reverse=True)
        return opportunities[:6]

    def _run_rank_check(
        self, site: dict[str, Any], keyword_row: dict[str, Any], settings: dict[str, Any]
    ) -> dict[str, Any]:
        keyword = keyword_row["keyword"]
        base = {
            "keyword_id": int(keyword_row["id"]),
            "keyword": keyword,
            "location": site["location"],
            "device": site["device"],
            "rank_absolute": None,
            "rank_group": None,
            "ranking_url": "",
            "ranking_domain": "",
            "result_count": 0,
            "top_competitors": [],
            "error": "",
        }
        login = _text(settings.get("dataforseo_login"))
        password = _text(settings.get("dataforseo_password"))
        if not login or not password or password == "********":
            return {**base, "status": "skipped", "error": "DataForSEO credentials are not configured"}
        task = {
            "keyword": keyword,
            "location_name": site["location"] or "United States",
            "language_code": "en",
            "device": site["device"],
            "depth": 100,
        }
        try:
            response = self._request(
                "post", DATAFORSEO_ENDPOINT, auth=(login, password), json=[task], timeout=(8, 50)
            )
            status_code = _int(getattr(response, "status_code", 0))
            if status_code != 200:
                raise RuntimeError(f"HTTP {status_code}: {self._response_text(response)[:180]}")
            payload = response.json()
            tasks = payload.get("tasks", []) if isinstance(payload, dict) else []
            if not tasks:
                raise RuntimeError("DataForSEO returned no task result")
            task_result = tasks[0]
            task_status = _int(task_result.get("status_code")) if isinstance(task_result, dict) else 0
            if task_status and task_status != 20000:
                raise RuntimeError(_text(task_result.get("status_message")) or f"DataForSEO task {task_status}")
            items = self._dataforseo_items(payload)
            organic = [item for item in items if _text(item.get("type")).lower() in {"", "organic"}]
            organic.sort(key=lambda item: _rank_value(item, "rank_absolute") or 1_000_000)
            target_host = site["normalized_host"]
            own: dict[str, Any] | None = None
            competitors: list[dict[str, Any]] = []
            seen_domains: set[str] = set()
            for item in organic:
                item_url = _text(item.get("url") or item.get("link"))
                domain = _normalize_host(item_url or _text(item.get("domain")))
                if not domain:
                    continue
                is_target = domain == target_host or domain.endswith(f".{target_host}")
                if is_target and own is None:
                    own = item
                    continue
                if is_target or domain in seen_domains or len(competitors) >= 5:
                    continue
                seen_domains.add(domain)
                competitors.append(
                    {
                        "domain": domain,
                        "rank_absolute": _rank_value(item, "rank_absolute"),
                        "url": item_url,
                        "title": _text(item.get("title")),
                    }
                )
            if own is None:
                return {**base, "status": "not_found", "result_count": len(organic), "top_competitors": competitors}
            ranking_url = _text(own.get("url") or own.get("link"))
            return {
                **base,
                "status": "found",
                "rank_absolute": _rank_value(own, "rank_absolute"),
                "rank_group": _rank_value(own, "rank_group"),
                "ranking_url": ranking_url,
                "ranking_domain": _normalize_host(ranking_url or _text(own.get("domain"))),
                "result_count": len(organic),
                "top_competitors": competitors,
            }
        except Exception as exc:
            return {**base, "status": "error", "error": _text(exc)[:500]}

    @staticmethod
    def _dataforseo_items(payload: Any) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []

        def flatten(values: Any) -> None:
            if not isinstance(values, list):
                return
            for item in values:
                if not isinstance(item, dict):
                    continue
                output.append(item)
                flatten(item.get("items"))

        for task in payload.get("tasks", []) if isinstance(payload, dict) else []:
            for result in task.get("result", []) if isinstance(task, dict) else []:
                flatten(result.get("items") if isinstance(result, dict) else None)
        return output

    # ------------------------------------------------------------------
    # Scoring, issues, and comparisons
    # ------------------------------------------------------------------
    def _page_issues(self, page: dict[str, Any]) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        add = issues.append
        status = page.get("status_code")
        if status != 200:
            add(self._issue("http_status", "Homepage does not return HTTP 200", "critical", f"HTTP {status}", "availability", "Restore a successful 200 response for the canonical homepage.", scope="availability"))
        if not _text(page.get("final_url")).startswith("https://"):
            add(self._issue("https_missing", "Homepage is not using HTTPS", "critical", page.get("final_url", ""), "technical", "Serve the site over HTTPS and redirect HTTP to the secure URL."))
        response_ms = _int(page.get("response_time_ms"))
        if response_ms > 3000:
            add(self._issue("slow_server_response", "Homepage response is slow", "warning", f"The HTML response took {response_ms} ms.", "performance", "Reduce server response time, caching delays, and redirect overhead."))
        title = _text(page.get("title"))
        if not title:
            add(self._issue("missing_title", "Page title is missing", "critical", "The homepage has no usable title element.", "seo", "Add a unique title that describes the primary service and market."))
        elif len(title) < 20 or len(title) > 65:
            add(self._issue("title_length", "Page title length needs review", "warning", f"The title is {len(title)} characters.", "seo", "Keep the title descriptive and generally within 20-65 characters."))
        description = _text(page.get("meta_description"))
        if not description:
            add(self._issue("missing_meta_description", "Meta description is missing", "warning", "No homepage meta description was found.", "seo", "Add a useful, page-specific search-result description."))
        elif len(description) < 70 or len(description) > 170:
            add(self._issue("meta_description_length", "Meta description length needs review", "info", f"The description is {len(description)} characters.", "seo", "Use a concise description, generally around 70-170 characters."))
        h1 = page.get("h1") or []
        if not h1:
            add(self._issue("missing_h1", "Homepage H1 is missing", "warning", "No visible H1 was found.", "seo", "Add one clear H1 that states the page's primary topic."))
        elif len(h1) > 1:
            add(self._issue("multiple_h1", "Homepage has multiple H1 headings", "info", f"Found {len(h1)} H1 headings.", "seo", "Use a deliberate heading hierarchy with one primary page heading."))
        robots_meta = _text(page.get("robots_meta")).lower()
        if "noindex" in robots_meta:
            add(self._issue("noindex", "Homepage is marked noindex", "critical", page.get("robots_meta", ""), "technical", "Remove noindex if this page should appear in search."))
        if not _text(page.get("canonical_url")):
            add(self._issue("missing_canonical", "Canonical URL is missing", "info", "No canonical link was found.", "technical", "Add a self-referencing canonical URL to the homepage."))
        if _int((page.get("schema") or {}).get("valid_blocks")) == 0:
            add(self._issue("missing_schema", "Structured data was not detected", "info", "No valid JSON-LD block was found.", "seo", "Add accurate Organization, LocalBusiness, or other applicable schema."))
        if _int(page.get("word_count")) < 200:
            add(self._issue("thin_content", "Homepage content is thin", "warning", f"Only {page.get('word_count', 0)} visible words were found.", "seo", "Add original content that clearly explains services, proof, locations, and next steps."))
        if _int(page.get("internal_link_count")) == 0:
            add(self._issue("no_internal_links", "No internal links were detected", "warning", "The homepage did not expose crawlable internal links.", "technical", "Link to important service, location, trust, and contact pages."))
        image_count = _int(page.get("image_count"))
        missing_alt = _int(page.get("images_missing_alt"))
        if missing_alt:
            add(self._issue("missing_image_alt", "Images are missing alt text", "info", f"{missing_alt} of {image_count} images have empty or missing alt text.", "seo", "Add meaningful alt text to informative images; leave decorative images intentionally empty."))
        if not page.get("robots_txt_present"):
            detail = page.get("robots_txt_error") or f"HTTP {page.get('robots_txt_status')}"
            add(self._issue("robots_txt_missing", "robots.txt was not confirmed", "info", detail, "technical", "Publish a valid /robots.txt and reference the sitemap when appropriate."))
        if not page.get("sitemap_present"):
            detail = page.get("sitemap_error") or f"HTTP {page.get('sitemap_status')}"
            add(self._issue("sitemap_missing", "XML sitemap was not confirmed", "warning", detail, "technical", "Publish a valid XML sitemap at /sitemap.xml and submit it to search engines."))
        return issues

    def _pagespeed_issues(self, result: dict[str, Any]) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        performance = _int(result.get("performance_score"))
        if performance < 50:
            issues.append(self._issue("pagespeed_performance_poor", "PageSpeed performance is poor", "critical", f"Performance score: {performance}/100", "performance", "Prioritize the largest PageSpeed opportunities and Core Web Vitals.", scope="pagespeed"))
        elif performance < 75:
            issues.append(self._issue("pagespeed_performance_weak", "PageSpeed performance needs improvement", "warning", f"Performance score: {performance}/100", "performance", "Address the largest render, image, script, and server bottlenecks.", scope="pagespeed"))
        if _int(result.get("seo_score")) < 80:
            issues.append(self._issue("pagespeed_seo_weak", "Lighthouse SEO score is weak", "warning", f"SEO score: {result.get('seo_score', 0)}/100", "seo", "Review the failed Lighthouse SEO audits.", scope="pagespeed"))
        if _int(result.get("accessibility_score")) < 80:
            issues.append(self._issue("pagespeed_accessibility_weak", "Accessibility score needs improvement", "warning", f"Accessibility score: {result.get('accessibility_score', 0)}/100", "accessibility", "Review contrast, labels, landmarks, semantics, and keyboard behavior.", scope="pagespeed"))
        return issues

    def _ranking_issues(self, rank: dict[str, Any], scope: str) -> list[dict[str, Any]]:
        keyword = rank["keyword"]
        current = rank.get("rank_absolute")
        previous = rank.get("previous_rank_absolute")
        if rank["status"] == "not_found":
            severity = "critical" if previous is not None else "warning"
            detail = f"'{keyword}' was not found in the first 100 organic results."
            if previous is not None:
                detail += f" It previously ranked at {previous}."
            return [self._issue("keyword_not_ranked", f"Keyword is not ranking: {keyword}", severity, detail, "rankings", "Review search intent, page relevance, indexability, internal links, and competitive coverage.", scope=scope)]
        if previous is not None and current is not None and int(current) - int(previous) >= 5:
            return [self._issue("keyword_rank_drop", f"Keyword ranking dropped: {keyword}", "warning", f"Rank changed from {previous} to {current}.", "rankings", "Check the ranking page, SERP changes, technical changes, and competitor gains.", scope=scope)]
        return []

    @staticmethod
    def _health_scores(page: dict[str, Any], pagespeed: dict[str, Any]) -> tuple[int, int, int]:
        if page.get("fetch_error"):
            technical = 0
            seo = 0
        else:
            technical = 100
            if page.get("status_code") != 200:
                technical -= 40
            if not _text(page.get("final_url")).startswith("https://"):
                technical -= 15
            if not page.get("canonical_url"):
                technical -= 8
            if "noindex" in _text(page.get("robots_meta")).lower():
                technical -= 30
            if not page.get("robots_txt_present"):
                technical -= 7
            if not page.get("sitemap_present"):
                technical -= 12
            if _int(page.get("internal_link_count")) == 0:
                technical -= 8
            if _int(page.get("response_time_ms")) > 3000:
                technical -= 10
            technical = max(0, technical)

            seo = 100
            title = _text(page.get("title"))
            description = _text(page.get("meta_description"))
            if not title:
                seo -= 25
            elif len(title) < 20 or len(title) > 65:
                seo -= 8
            if not description:
                seo -= 20
            elif len(description) < 70 or len(description) > 170:
                seo -= 6
            if not page.get("h1"):
                seo -= 15
            elif len(page["h1"]) > 1:
                seo -= 4
            if "noindex" in _text(page.get("robots_meta")).lower():
                seo -= 35
            if _int(page.get("word_count")) < 200:
                seo -= 12
            if _int((page.get("schema") or {}).get("valid_blocks")) == 0:
                seo -= 5
            images = _int(page.get("image_count"))
            missing = _int(page.get("images_missing_alt"))
            if images:
                seo -= min(10, int(round((missing / images) * 10)))
            seo = max(0, seo)

            if page.get("status_code") != 200:
                technical = min(technical, 25)
                seo = min(seo, 40)

        if pagespeed.get("status") == "measured":
            performance = _score(pagespeed.get("performance_score"))
        else:
            elapsed = _int(page.get("response_time_ms"), 99_999)
            if elapsed <= 500:
                performance = 100
            elif elapsed <= 1000:
                performance = 90
            elif elapsed <= 2000:
                performance = 75
            elif elapsed <= 3500:
                performance = 55
            elif elapsed <= 5000:
                performance = 35
            else:
                performance = 10 if not page.get("fetch_error") else 0
        if page.get("status_code") not in (None, 200):
            performance = min(performance, 30)
        return technical, seo, performance

    @staticmethod
    def _visibility_score(ranks: list[dict[str, Any]]) -> int | None:
        eligible = [row for row in ranks if row.get("status") in {"found", "not_found"}]
        if not eligible:
            return None
        values: list[int] = []
        for row in eligible:
            rank = row.get("rank_absolute")
            if rank is None:
                values.append(0)
            elif rank <= 3:
                values.append(100)
            elif rank <= 10:
                values.append(85)
            elif rank <= 20:
                values.append(65)
            elif rank <= 50:
                values.append(40)
            else:
                values.append(20)
        return int(round(sum(values) / len(values)))

    @staticmethod
    def _ranking_summary(ranks: list[dict[str, Any]]) -> dict[str, Any]:
        found = [int(row["rank_absolute"]) for row in ranks if row.get("rank_absolute") is not None]
        improved = sum(1 for row in ranks if row.get("rank_change") is not None and row["rank_change"] > 0)
        declined = sum(1 for row in ranks if row.get("rank_change") is not None and row["rank_change"] < 0)
        gained = sum(1 for row in ranks if row.get("previous_rank_absolute") is None and row.get("rank_absolute") is not None)
        lost = sum(1 for row in ranks if row.get("previous_rank_absolute") is not None and row.get("rank_absolute") is None and row.get("status") == "not_found")
        return {
            "tracked": len(ranks),
            "ranking": len(found),
            "not_ranking": sum(1 for row in ranks if row.get("status") == "not_found"),
            "average_rank": round(sum(found) / len(found), 1) if found else None,
            "top_3": sum(1 for rank in found if rank <= 3),
            "top_10": sum(1 for rank in found if rank <= 10),
            "improved": improved,
            "declined": declined,
            "gained": gained,
            "lost": lost,
        }

    def _comparison(
        self, page: dict[str, Any], previous_run: dict[str, Any] | None, ranks: list[dict[str, Any]]
    ) -> dict[str, Any]:
        if not previous_run:
            return {"has_previous": False, "page_changes": [], "rank_changes": []}
        page_changes: list[dict[str, Any]] = []
        previous_page = previous_run.get("page") or {}
        for field in ("status_code", "title", "meta_description", "canonical_url", "robots_meta"):
            before = previous_page.get(field)
            after = page.get(field)
            if before != after:
                page_changes.append({"field": field, "before": before, "after": after})
        rank_changes = [
            {
                "keyword": row["keyword"],
                "previous_rank": row.get("previous_rank_absolute"),
                "current_rank": row.get("rank_absolute"),
                "change": row.get("rank_change"),
            }
            for row in ranks
            if row.get("previous_rank_absolute") != row.get("rank_absolute")
        ]
        return {
            "has_previous": True,
            "previous_run_id": previous_run["id"],
            "page_changes": page_changes,
            "rank_changes": rank_changes,
        }

    @staticmethod
    def _issue(
        code: str,
        title: str,
        severity: str,
        detail: Any,
        category: str,
        recommendation: str,
        *,
        scope: str = "page",
    ) -> dict[str, Any]:
        severity = severity if severity in VALID_SEVERITIES else "warning"
        stable = f"{category}|{scope}|{code}".encode("utf-8", errors="replace")
        return {
            "fingerprint": hashlib.sha256(stable).hexdigest()[:32],
            "category": category,
            "scope": scope,
            "code": code,
            "severity": severity,
            "title": title,
            "detail": _text(detail),
            "recommendation": recommendation,
        }

    @staticmethod
    def _dedupe_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
        output: dict[str, dict[str, Any]] = {}
        priority = {"info": 1, "warning": 2, "critical": 3}
        for issue in issues:
            fingerprint = issue["fingerprint"]
            current = output.get(fingerprint)
            if current is None or priority[issue["severity"]] > priority[current["severity"]]:
                output[fingerprint] = issue
        return list(output.values())

    # ------------------------------------------------------------------
    # Persistence helpers and JSON-facing row conversion
    # ------------------------------------------------------------------
    def _insert_page_snapshot(
        self,
        conn: sqlite3.Connection,
        run_id: int,
        site_id: int,
        page: dict[str, Any],
        pagespeed: dict[str, Any],
        captured_at: str,
    ) -> None:
        page_payload = dict(page)
        page_payload.pop("pagespeed", None)
        conn.execute(
            """
            INSERT INTO website_monitor_page_snapshots
                (run_id, site_id, url, final_url, status_code, response_time_ms, content_type,
                 title, meta_description, h1_json, canonical_url, robots_meta, schema_json,
                 word_count, internal_link_count, image_count, images_missing_alt,
                 robots_txt_url, robots_txt_status, robots_txt_present,
                 sitemap_url, sitemap_status, sitemap_present, fetch_error,
                 page_json, pagespeed_json, captured_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id, site_id, page.get("url", ""), page.get("final_url", ""), page.get("status_code"),
                page.get("response_time_ms"), page.get("content_type", ""), page.get("title", ""),
                page.get("meta_description", ""), _json_dump(page.get("h1", [])),
                page.get("canonical_url", ""), page.get("robots_meta", ""),
                _json_dump(page.get("schema", {})), _int(page.get("word_count")),
                _int(page.get("internal_link_count")), _int(page.get("image_count")),
                _int(page.get("images_missing_alt")), page.get("robots_txt_url", ""),
                page.get("robots_txt_status"), int(bool(page.get("robots_txt_present"))),
                page.get("sitemap_url", ""), page.get("sitemap_status"),
                int(bool(page.get("sitemap_present"))), page.get("fetch_error", ""),
                _json_dump(page_payload), _json_dump(pagespeed), captured_at,
            ),
        )

    @staticmethod
    def _insert_rank_snapshot(
        conn: sqlite3.Connection,
        run_id: int,
        site_id: int,
        rank: dict[str, Any],
        captured_at: str,
    ) -> None:
        conn.execute(
            """
            INSERT INTO website_monitor_rank_snapshots
                (run_id, site_id, keyword_id, keyword, location, device, status,
                 rank_absolute, rank_group, previous_rank_absolute, rank_change,
                 ranking_url, ranking_domain, result_count, top_competitors_json, error, captured_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id, site_id, rank.get("keyword_id"), rank["keyword"], rank.get("location", ""),
                rank.get("device", "mobile"), rank["status"], rank.get("rank_absolute"),
                rank.get("rank_group"), rank.get("previous_rank_absolute"), rank.get("rank_change"),
                rank.get("ranking_url", ""), rank.get("ranking_domain", ""),
                _int(rank.get("result_count")), _json_dump(rank.get("top_competitors", [])),
                rank.get("error", ""), captured_at,
            ),
        )

    @staticmethod
    def _reconcile_issues(
        conn: sqlite3.Connection,
        site_id: int,
        run_id: int,
        issues: list[dict[str, Any]],
        verified_scopes: set[str],
        now: str,
    ) -> None:
        current_fingerprints = {issue["fingerprint"] for issue in issues}
        for issue in issues:
            existing = conn.execute(
                "SELECT id FROM website_monitor_issues WHERE site_id = ? AND fingerprint = ?",
                (site_id, issue["fingerprint"]),
            ).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE website_monitor_issues
                    SET category = ?, scope = ?, code = ?, severity = ?, title = ?, detail = ?,
                        recommendation = ?, status = 'open', last_run_id = ?, last_seen_at = ?,
                        resolved_run_id = NULL, resolved_at = NULL
                    WHERE id = ?
                    """,
                    (
                        issue["category"], issue["scope"], issue["code"], issue["severity"], issue["title"],
                        issue["detail"], issue["recommendation"], run_id, now, int(existing["id"]),
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO website_monitor_issues
                        (site_id, fingerprint, category, scope, code, severity, title, detail,
                         recommendation, status, first_run_id, last_run_id, first_seen_at, last_seen_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?)
                    """,
                    (
                        site_id, issue["fingerprint"], issue["category"], issue["scope"], issue["code"],
                        issue["severity"], issue["title"], issue["detail"], issue["recommendation"],
                        run_id, run_id, now, now,
                    ),
                )
        open_rows = conn.execute(
            "SELECT id, fingerprint, scope FROM website_monitor_issues WHERE site_id = ? AND status = 'open'",
            (site_id,),
        ).fetchall()
        for row in open_rows:
            if row["fingerprint"] not in current_fingerprints and row["scope"] in verified_scopes:
                conn.execute(
                    """
                    UPDATE website_monitor_issues
                    SET status = 'resolved', resolved_run_id = ?, resolved_at = ?
                    WHERE id = ?
                    """,
                    (run_id, now, int(row["id"])),
                )

    @staticmethod
    def _empty_page(url: str, error: str) -> dict[str, Any]:
        return {
            "url": url,
            "final_url": "",
            "status_code": None,
            "response_time_ms": None,
            "content_type": "",
            "title": "",
            "meta_description": "",
            "h1": [],
            "canonical_url": "",
            "robots_meta": "",
            "schema": {},
            "word_count": 0,
            "internal_link_count": 0,
            "image_count": 0,
            "images_missing_alt": 0,
            "robots_txt_url": "",
            "robots_txt_status": None,
            "robots_txt_present": False,
            "sitemap_url": "",
            "sitemap_status": None,
            "sitemap_present": False,
            "fetch_error": error,
        }

    def _site_dict(self, conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
        site = dict(row)
        site["active"] = bool(site["active"])
        keyword_rows = conn.execute(
            """
            SELECT id, keyword, active, created_at, updated_at
            FROM website_monitor_keywords
            WHERE site_id = ? AND active = 1 ORDER BY id
            """,
            (int(row["id"]),),
        ).fetchall()
        site["keywords"] = [item["keyword"] for item in keyword_rows]
        site["keyword_records"] = [
            {**dict(item), "active": bool(item["active"])} for item in keyword_rows
        ]
        site["keyword_count"] = len(keyword_rows)
        return site

    def _site_summary(self, conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
        site = self._site_dict(conn, row)
        latest = conn.execute(
            """
            SELECT * FROM website_monitor_runs
            WHERE site_id = ? AND status != 'running'
            ORDER BY id DESC LIMIT 1
            """,
            (int(row["id"]),),
        ).fetchone()
        issue_counts = conn.execute(
            """
            SELECT COUNT(*) AS open_count,
                   SUM(CASE WHEN severity = 'critical' THEN 1 ELSE 0 END) AS critical_count,
                   SUM(CASE WHEN severity = 'warning' THEN 1 ELSE 0 END) AS warning_count
            FROM website_monitor_issues WHERE site_id = ? AND status = 'open'
            """,
            (int(row["id"]),),
        ).fetchone()
        site.update(
            {
                "last_scanned_at": latest["completed_at"] if latest else None,
                "last_run_status": latest["status"] if latest else None,
                "overall_score": latest["overall_score"] if latest else None,
                "seo_score": latest["seo_score"] if latest else None,
                "technical_score": latest["technical_score"] if latest else None,
                "performance_score": latest["performance_score"] if latest else None,
                "visibility_score": latest["visibility_score"] if latest else None,
                "score_change": latest["score_change"] if latest else None,
                "open_issue_count": _int(issue_counts["open_count"] if issue_counts else 0),
                "critical_issue_count": _int(issue_counts["critical_count"] if issue_counts else 0),
                "warning_issue_count": _int(issue_counts["warning_count"] if issue_counts else 0),
            }
        )
        site.pop("keyword_records", None)
        return site

    def _history(self, conn: sqlite3.Connection, site_id: int, *, limit: int) -> list[dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT * FROM website_monitor_runs
            WHERE site_id = ? ORDER BY id DESC LIMIT ?
            """,
            (site_id, max(1, min(int(limit), 500))),
        ).fetchall()
        output: list[dict[str, Any]] = []
        for row in rows:
            run = self._run_dict(row)
            run["page"] = self._page_for_run(conn, int(row["id"]))
            run["rankings"] = self._ranks_for_run(conn, int(row["id"]))
            output.append(run)
        return output

    @staticmethod
    def _run_dict(row: sqlite3.Row | dict[str, Any] | None) -> dict[str, Any]:
        if row is None:
            return {}
        result = dict(row)
        result["summary"] = _json_load(result.pop("summary_json", "{}"), {})
        return result

    def _page_for_run(self, conn: sqlite3.Connection, run_id: int | None) -> dict[str, Any] | None:
        if not run_id:
            return None
        row = conn.execute(
            "SELECT * FROM website_monitor_page_snapshots WHERE run_id = ?", (int(run_id),)
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["h1"] = _json_load(result.pop("h1_json", "[]"), [])
        result["schema"] = _json_load(result.pop("schema_json", "{}"), {})
        result["page"] = _json_load(result.pop("page_json", "{}"), {})
        result["pagespeed"] = _json_load(result.pop("pagespeed_json", "{}"), {})
        result["robots_txt_present"] = bool(result["robots_txt_present"])
        result["sitemap_present"] = bool(result["sitemap_present"])
        return result

    @staticmethod
    def _ranks_for_run(conn: sqlite3.Connection, run_id: int) -> list[dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT * FROM website_monitor_rank_snapshots
            WHERE run_id = ? ORDER BY keyword COLLATE NOCASE
            """,
            (int(run_id),),
        ).fetchall()
        output: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["top_competitors"] = _json_load(item.pop("top_competitors_json", "[]"), [])
            output.append(item)
        return output

    @staticmethod
    def _issues(
        conn: sqlite3.Connection, site_id: int, status: str, *, limit: int = 500
    ) -> list[dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT * FROM website_monitor_issues
            WHERE site_id = ? AND status = ?
            ORDER BY CASE severity WHEN 'critical' THEN 1 WHEN 'warning' THEN 2 ELSE 3 END,
                     last_seen_at DESC, id DESC
            LIMIT ?
            """,
            (site_id, status, max(1, min(int(limit), 1000))),
        ).fetchall()
        return [dict(row) for row in rows]


__all__ = ["WebsiteMonitorStore"]
