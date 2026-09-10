from __future__ import annotations

from contextlib import contextmanager
import json
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
WEBSITE_AUDIT_DIR = REPO_ROOT / "colorado-lead-machine"
if str(WEBSITE_AUDIT_DIR) not in sys.path:
    sys.path.insert(0, str(WEBSITE_AUDIT_DIR))

from shared_schema import ensure_column as ensure_schema_column, ensure_shared_schema
from trigger_detection import build_trigger_intelligence
from website_audit import build_opportunity_thesis, derive_pitch_family


DEFAULT_DB_PATH = Path.home() / "Documents" / "Colorado Lead Machine" / "lead_machine.db"

PIPELINE_STATUSES = (
    "Needs review",
    "Approved",
    "Outreach-ready",
    "Contacted",
    "Responded",
    "Do not contact",
    "Archived",
)

LEAD_SIGNALS = (
    "No go",
    "In contact",
    "Won site",
)

VIEW_FILTERS = (
    "All leads",
    "Actionable only",
    "Ready to contact",
    "High confidence",
    "Promising",
    "Needs review",
    "Low priority",
    "No contact",
    "Approved",
    "Outreach-ready",
    "Contacted",
    "Responded",
    "Do not contact",
    "Archived",
)

ACTIVITY_TYPES = (
    "Review",
    "Research",
    "Website check",
    "Call note",
    "Email note",
    "General",
)

GENERIC_SIMILARITY_TOKENS = {
    "and",
    "auto",
    "business",
    "co",
    "colorado",
    "company",
    "group",
    "inc",
    "llc",
    "local",
    "llp",
    "ltd",
    "of",
    "services",
    "shop",
    "solutions",
    "studio",
    "the",
}


class LeadVaultError(Exception):
    pass


def default_source_db_path() -> Path:
    return DEFAULT_DB_PATH


class LeadVaultStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self._queue_summary_json_supported: bool | None = None

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    @contextmanager
    def _managed_connection(self) -> sqlite3.Connection:
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        ensure_schema_column(conn, table, column, definition)

    def _ensure_lead_tracker_state_schema(self, conn: sqlite3.Connection) -> None:
        for column, definition in {
            "pipeline_status": "TEXT NOT NULL DEFAULT 'Needs review'",
            "ready_to_contact": "INTEGER NOT NULL DEFAULT 0",
            "do_not_contact": "INTEGER NOT NULL DEFAULT 0",
            "lead_owner": "TEXT NOT NULL DEFAULT ''",
            "next_action": "TEXT NOT NULL DEFAULT ''",
            "lead_signal": "TEXT NOT NULL DEFAULT ''",
            "work_bucket": "TEXT NOT NULL DEFAULT ''",
            "tags": "TEXT NOT NULL DEFAULT ''",
            "opportunity_summary": "TEXT NOT NULL DEFAULT ''",
            "personalization_notes": "TEXT NOT NULL DEFAULT ''",
            "outreach_angle": "TEXT NOT NULL DEFAULT ''",
            "draft_message": "TEXT NOT NULL DEFAULT ''",
            "updated_at": "TEXT NOT NULL DEFAULT ''",
        }.items():
            self._ensure_column(conn, "lead_tracker_state", column, definition)

    def ensure_ready(self) -> None:
        if not self.db_path.exists():
            raise LeadVaultError(f"Database not found: {self.db_path}")
        with self._managed_connection() as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='lead_history'"
            ).fetchone()
            if not row:
                raise LeadVaultError("This database does not contain lead_history. Pick lead_machine.db from the Colorado app.")
            ensure_shared_schema(conn)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS lead_tracker_state (
                    lead_key TEXT PRIMARY KEY,
                    pipeline_status TEXT NOT NULL DEFAULT 'Needs review',
                    ready_to_contact INTEGER NOT NULL DEFAULT 0,
                    do_not_contact INTEGER NOT NULL DEFAULT 0,
                    lead_owner TEXT NOT NULL DEFAULT '',
                    next_action TEXT NOT NULL DEFAULT '',
                    lead_signal TEXT NOT NULL DEFAULT '',
                    work_bucket TEXT NOT NULL DEFAULT '',
                    tags TEXT NOT NULL DEFAULT '',
                    opportunity_summary TEXT NOT NULL DEFAULT '',
                    personalization_notes TEXT NOT NULL DEFAULT '',
                    outreach_angle TEXT NOT NULL DEFAULT '',
                    draft_message TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS lead_activity_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    lead_key TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    activity_type TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    details TEXT NOT NULL DEFAULT ''
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_lead_activity_log_key ON lead_activity_log (lead_key, created_at DESC)"
            )
            self._ensure_lead_tracker_state_schema(conn)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS outreach_drafts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    lead_key TEXT NOT NULL,
                    business_name TEXT NOT NULL DEFAULT '',
                    recipient_email TEXT NOT NULL DEFAULT '',
                    subject TEXT NOT NULL DEFAULT '',
                    body_plain TEXT NOT NULL DEFAULT '',
                    body_html TEXT NOT NULL DEFAULT '',
                    preview_url TEXT NOT NULL DEFAULT '',
                    preview_file_path TEXT NOT NULL DEFAULT '',
                    export_channel TEXT NOT NULL DEFAULT '',
                    export_status TEXT NOT NULL DEFAULT 'pending',
                    export_error TEXT NOT NULL DEFAULT '',
                    generated_at TEXT NOT NULL DEFAULT '',
                    exported_at TEXT NOT NULL DEFAULT ''
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_outreach_drafts_lead ON outreach_drafts (lead_key, generated_at DESC)"
            )

    def list_scans(self) -> list[dict[str, Any]]:
        self.ensure_ready()
        with self._managed_connection() as conn:
            rows = conn.execute(
                """
                SELECT
                    r.id,
                    r.started_at,
                    r.finished_at,
                    r.status,
                    r.seed_mode,
                    r.search_areas_json,
                    COUNT(rl.lead_key) AS lead_count
                FROM runs r
                LEFT JOIN run_leads rl ON rl.run_id = r.id
                GROUP BY r.id, r.started_at, r.finished_at, r.status, r.seed_mode, r.search_areas_json
                ORDER BY r.id DESC
                """
            ).fetchall()

        scans: list[dict[str, Any]] = []
        for row in rows:
            try:
                search_areas = json.loads(row[5] or "[]")
            except Exception:
                search_areas = []
            area_preview = ""
            if search_areas:
                if len(search_areas) == 1:
                    area_preview = str(search_areas[0])
                else:
                    area_preview = f"{search_areas[0]} + {len(search_areas) - 1} more"
            scans.append(
                {
                    "run_id": row[0],
                    "started_at": row[1] or "",
                    "finished_at": row[2] or "",
                    "status": row[3] or "",
                    "seed_mode": row[4] or "",
                    "search_areas": search_areas,
                    "lead_count": row[6] or 0,
                    "label": f"Scan {row[0]} | {(row[1] or '')[:16].replace('T', ' ')} | {area_preview or 'No areas'} | {row[6] or 0} leads",
                }
            )
        return scans

    def get_run_monitor_report(self, run_id: int, *, preview_limit: int = 4) -> dict[str, Any]:
        self.ensure_ready()
        with self._managed_connection() as conn:
            row = conn.execute(
                """
                SELECT
                    r.id,
                    r.started_at,
                    r.finished_at,
                    r.status,
                    r.seed_mode,
                    r.search_areas_json,
                    r.report_json,
                    COUNT(rl.lead_key) AS lead_count
                FROM runs r
                LEFT JOIN run_leads rl ON rl.run_id = r.id
                WHERE r.id = ?
                GROUP BY r.id, r.started_at, r.finished_at, r.status, r.seed_mode, r.search_areas_json, r.report_json
                """,
                (int(run_id),),
            ).fetchone()

        if not row:
            return {}

        try:
            report = json.loads(row[6] or "{}")
        except Exception:
            report = {}
        if not isinstance(report, dict):
            report = {}

        report_search_areas = report.get("search_areas", [])
        if isinstance(report_search_areas, list):
            search_areas = [str(item).strip() for item in report_search_areas if str(item).strip()]
        else:
            try:
                parsed_search_areas = json.loads(row[5] or "[]")
            except Exception:
                parsed_search_areas = []
            search_areas = [str(item).strip() for item in parsed_search_areas if str(item).strip()]

        summary = report.get("summary", {})
        if not isinstance(summary, dict):
            summary = {}
        summary = dict(summary)
        summary.setdefault("actionable_leads", int(row[7] or 0))

        raw_stages = report.get("stages", {})
        stages: dict[str, dict[str, Any]] = {}
        if isinstance(raw_stages, dict):
            for key, value in raw_stages.items():
                if not isinstance(value, dict):
                    continue
                metrics = value.get("metrics", {})
                if not isinstance(metrics, dict):
                    metrics = {}
                stages[str(key)] = {
                    "label": str(value.get("label", key) or key),
                    "metrics": dict(metrics),
                }

        raw_monitor = report.get("monitor", {})
        if not isinstance(raw_monitor, dict):
            raw_monitor = {}

        def _safe_int(value: Any, default: int = 0) -> int:
            try:
                return int(value or 0)
            except (TypeError, ValueError):
                return default

        limit = max(1, int(preview_limit))

        def _preview_rows(value: Any) -> list[dict[str, Any]]:
            if not isinstance(value, list):
                return []
            preview: list[dict[str, Any]] = []
            for item in value[:limit]:
                if isinstance(item, dict):
                    preview.append(item)
            return preview

        monitor = {
            "saved_scan_id": _safe_int(raw_monitor.get("saved_scan_id")),
            "latest_run_id": _safe_int(raw_monitor.get("latest_run_id"), int(row[0] or 0)),
            "previous_run_id": _safe_int(raw_monitor.get("previous_run_id")),
            "latest_started_at": str(raw_monitor.get("latest_started_at", "")),
            "latest_finished_at": str(raw_monitor.get("latest_finished_at", "")),
            "latest_status": str(raw_monitor.get("latest_status", "")),
            "latest_seed_mode": str(raw_monitor.get("latest_seed_mode", "")),
            "latest_result_count": _safe_int(raw_monitor.get("latest_result_count"), int(row[7] or 0)),
            "new_count": _safe_int(raw_monitor.get("new_count")),
            "removed_count": _safe_int(raw_monitor.get("removed_count")),
            "changed_count": _safe_int(raw_monitor.get("changed_count")),
            "new_leads": _preview_rows(raw_monitor.get("new_leads", [])),
            "removed_leads": _preview_rows(raw_monitor.get("removed_leads", [])),
            "changed_leads": _preview_rows(raw_monitor.get("changed_leads", [])),
        }

        return {
            "run_id": int(row[0] or 0),
            "started_at": str(report.get("started_at", row[1] or "")),
            "finished_at": str(report.get("finished_at", row[2] or "")),
            "status": str(report.get("status", row[3] or "")),
            "seed_mode": str(report.get("seed_mode", row[4] or "")),
            "search_areas": search_areas,
            "lead_count": int(row[7] or 0),
            "saved_scan_id": _safe_int(report.get("saved_scan_id")),
            "run_reason": str(report.get("run_reason", "")),
            "summary": summary,
            "stages": stages,
            "monitor": monitor,
            "has_report": bool(report),
            "has_monitor": bool(raw_monitor),
        }

    def list_buckets(self, run_id: int | None = None) -> list[dict[str, Any]]:
        self.ensure_ready()
        query = """
            SELECT
                COALESCE(ts.work_bucket, '') AS work_bucket,
                COUNT(*) AS lead_count
            FROM lead_history lh
            LEFT JOIN lead_tracker_state ts ON ts.lead_key = lh.lead_key
        """
        params: list[Any] = []
        if run_id is not None:
            query += " INNER JOIN run_leads rl ON rl.lead_key = lh.lead_key AND rl.run_id = ?"
            params.append(run_id)
        query += """
            GROUP BY COALESCE(ts.work_bucket, '')
            ORDER BY CASE WHEN TRIM(COALESCE(ts.work_bucket, '')) = '' THEN 1 ELSE 0 END,
                     lead_count DESC,
                     COALESCE(ts.work_bucket, '') COLLATE NOCASE
        """
        with self._managed_connection() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [
            {"bucket_name": str(row[0] or "").strip(), "lead_count": int(row[1] or 0)}
            for row in rows
        ]

    def list_lead_lists(self) -> list[dict[str, Any]]:
        self.ensure_ready()
        with self._managed_connection() as conn:
            rows = conn.execute(
                """
                SELECT
                    ll.id,
                    ll.name,
                    ll.created_at,
                    ll.updated_at,
                    COUNT(llm.lead_key) AS lead_count
                FROM lead_lists ll
                LEFT JOIN lead_list_members llm ON llm.list_id = ll.id
                GROUP BY ll.id, ll.name, ll.created_at, ll.updated_at
                ORDER BY ll.name COLLATE NOCASE
                """
            ).fetchall()
        return [
            {
                "list_id": int(row[0]),
                "name": str(row[1] or ""),
                "created_at": str(row[2] or ""),
                "updated_at": str(row[3] or ""),
                "lead_count": int(row[4] or 0),
            }
            for row in rows
        ]

    def ensure_lead_list(self, name: str) -> int:
        self.ensure_ready()
        cleaned_name = str(name or "").strip()
        if not cleaned_name:
            raise LeadVaultError("Enter a list name first.")
        now = datetime.now().isoformat(timespec="seconds")
        with self._managed_connection() as conn:
            existing = conn.execute(
                "SELECT id FROM lead_lists WHERE LOWER(name) = LOWER(?)",
                (cleaned_name,),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE lead_lists SET updated_at = ? WHERE id = ?",
                    (now, existing[0]),
                )
                return int(existing[0])
            cursor = conn.execute(
                """
                INSERT INTO lead_lists (name, created_at, updated_at)
                VALUES (?, ?, ?)
                """,
                (cleaned_name, now, now),
            )
            return int(cursor.lastrowid)

    def add_leads_to_list(self, lead_keys: list[str], list_name: str) -> tuple[int, int]:
        self.ensure_ready()
        cleaned_keys = [lead_key for lead_key in lead_keys if lead_key]
        if not cleaned_keys:
            return 0, 0
        list_id = self.ensure_lead_list(list_name)
        now = datetime.now().isoformat(timespec="seconds")
        added = 0
        with self._managed_connection() as conn:
            for lead_key in cleaned_keys:
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO lead_list_members (list_id, lead_key, added_at)
                    VALUES (?, ?, ?)
                    """,
                    (list_id, lead_key, now),
                )
                if cursor.rowcount:
                    added += 1
            conn.execute(
                "UPDATE lead_lists SET updated_at = ? WHERE id = ?",
                (now, list_id),
            )
        return list_id, added

    def remove_leads_from_list(self, lead_keys: list[str], list_name: str) -> int:
        self.ensure_ready()
        cleaned_keys = [lead_key for lead_key in lead_keys if lead_key]
        cleaned_name = str(list_name or "").strip()
        if not cleaned_keys or not cleaned_name:
            return 0
        now = datetime.now().isoformat(timespec="seconds")
        removed = 0
        with self._managed_connection() as conn:
            existing = conn.execute(
                "SELECT id FROM lead_lists WHERE LOWER(name) = LOWER(?)",
                (cleaned_name,),
            ).fetchone()
            if not existing:
                return 0
            list_id = int(existing[0])
            for lead_key in cleaned_keys:
                cursor = conn.execute(
                    "DELETE FROM lead_list_members WHERE list_id = ? AND lead_key = ?",
                    (list_id, lead_key),
                )
                if cursor.rowcount:
                    removed += 1
            conn.execute(
                "UPDATE lead_lists SET updated_at = ? WHERE id = ?",
                (now, list_id),
            )
        return removed

    # ── Pinned Leads helpers ──────────────────────────

    _PINNED_LIST_NAME = "Pinned Leads"

    def ensure_pinned_list(self) -> int:
        return self.ensure_lead_list(self._PINNED_LIST_NAME)

    def get_pinned_keys(self, lead_keys: list[str] | None = None) -> set[str]:
        """Return the set of lead_keys that are in the Pinned Leads list.
        If *lead_keys* is None, return ALL pinned keys."""
        self.ensure_ready()
        list_id = self.ensure_pinned_list()
        with self._managed_connection() as conn:
            if lead_keys is None:
                rows = conn.execute(
                    "SELECT lead_key FROM lead_list_members WHERE list_id = ?",
                    (list_id,),
                ).fetchall()
            else:
                if not lead_keys:
                    return set()
                placeholders = ", ".join("?" for _ in lead_keys)
                rows = conn.execute(
                    f"SELECT lead_key FROM lead_list_members WHERE list_id = ? AND lead_key IN ({placeholders})",
                    (list_id, *lead_keys),
                ).fetchall()
        return {str(row[0]) for row in rows}

    def pinned_count(self) -> int:
        self.ensure_ready()
        list_id = self.ensure_pinned_list()
        with self._managed_connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM lead_list_members WHERE list_id = ?",
                (list_id,),
            ).fetchone()
        return int(row[0]) if row else 0

    def create_manual_website_lead(
        self,
        scrape: dict[str, Any],
        *,
        manual_key: str = "",
    ) -> dict[str, Any]:
        """Create or update a normal lead from a manual website scrape."""
        self.ensure_ready()
        final_url = str(scrape.get("final_url") or scrape.get("source_url") or "").strip()
        parsed = urlparse(final_url if "://" in final_url else f"https://{final_url}")
        host = (parsed.hostname or "manual-website").lower()
        business_name = (
            str(scrape.get("business_name") or "").strip()
            or str(scrape.get("title") or "").strip()
            or host
        )[:160]
        lead_key = self._manual_lead_key(host, business_name)
        now = datetime.now().isoformat(timespec="seconds")

        phones = scrape.get("phones") if isinstance(scrape.get("phones"), list) else []
        emails = scrape.get("emails") if isinstance(scrape.get("emails"), list) else []
        services = scrape.get("services") if isinstance(scrape.get("services"), list) else []
        tech_hints = scrape.get("tech_hints") if isinstance(scrape.get("tech_hints"), list) else []
        crawled_pages = scrape.get("crawled_pages") if isinstance(scrape.get("crawled_pages"), list) else []

        data = {
            "Business Name": business_name,
            "Website": final_url,
            "Official Website": final_url,
            "Resolved Website URL": final_url,
            "Web Presence Status": "Manual website scrape",
            "Website Bucket": "Manual website scrape",
            "Seed Source": "Manual Website",
            "Manual Scrape Key": manual_key,
            "Scraped Title": str(scrape.get("title") or "")[:400],
            "Meta Description": str(scrape.get("meta_description") or "")[:800],
            "Phone": ", ".join(str(p) for p in phones[:4]),
            "Email": ", ".join(str(e) for e in emails[:4]),
            "Services": ", ".join(str(s) for s in services[:12]),
            "Tech Hints": ", ".join(str(t) for t in tech_hints[:12]),
            "Inner Pages Checked": len(crawled_pages),
            "Discovery Sources": "Manual Website",
            "Lead Score": 0,
            "Opportunity Score": 0,
            "Review Bucket": "Needs review",
            "Opportunity Label": "Manual review",
        }

        with self._managed_connection() as conn:
            conn.execute(
                """
                INSERT INTO lead_history (
                    lead_key, business_name, address, city_area, last_seed_source,
                    first_seen_at, last_seen_at, last_web_presence_status, last_lead_score,
                    last_opportunity_score, data_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(lead_key) DO UPDATE SET
                    business_name=excluded.business_name,
                    last_seed_source=excluded.last_seed_source,
                    last_seen_at=excluded.last_seen_at,
                    last_web_presence_status=excluded.last_web_presence_status,
                    last_lead_score=excluded.last_lead_score,
                    last_opportunity_score=excluded.last_opportunity_score,
                    data_json=excluded.data_json
                """,
                (
                    lead_key,
                    business_name,
                    "",
                    "",
                    "Manual Website",
                    now,
                    now,
                    "Manual website scrape",
                    0,
                    0,
                    json.dumps(data),
                ),
            )
            conn.execute(
                """
                INSERT INTO lead_tracker_state (
                    lead_key, pipeline_status, work_bucket, tags, next_action, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(lead_key) DO UPDATE SET
                    pipeline_status=excluded.pipeline_status,
                    work_bucket=excluded.work_bucket,
                    tags=excluded.tags,
                    next_action=excluded.next_action,
                    updated_at=excluded.updated_at
                """,
                (
                    lead_key,
                    "Needs review",
                    "Manual Website",
                    "manual-website",
                    "Review manual scrape",
                    now,
                ),
            )
        return {"lead_key": lead_key, "business_name": business_name}

    def _manual_lead_key(self, host: str, business_name: str) -> str:
        base = re.sub(
            r"[^a-z0-9]+",
            "_",
            f"manual_{host}_{business_name}".lower(),
        ).strip("_")
        return (base or "manual_website")[:120]

    def list_leads(
        self,
        search_text: str = "",
        view_filter: str = "All leads",
        run_id: int | None = None,
        work_bucket: str | None = None,
        lead_list_id: int | None = None,
    ) -> list[dict[str, Any]]:
        self.ensure_ready()
        query = """
            SELECT
                lh.lead_key,
                lh.business_name,
                lh.address,
                lh.city_area,
                lh.last_seed_source,
                lh.first_seen_at,
                lh.last_seen_at,
                lh.last_web_presence_status,
                lh.last_lead_score,
                lh.last_opportunity_score,
                lh.data_json,
                COALESCE(ts.pipeline_status, 'Needs review') AS pipeline_status,
                COALESCE(ts.ready_to_contact, 0) AS ready_to_contact,
                COALESCE(ts.do_not_contact, 0) AS do_not_contact,
                COALESCE(ts.lead_owner, '') AS lead_owner,
                COALESCE(ts.next_action, '') AS next_action,
                COALESCE(ts.lead_signal, '') AS lead_signal,
                COALESCE(ts.work_bucket, '') AS work_bucket,
                COALESCE(ts.tags, '') AS tags
            FROM lead_history lh
            LEFT JOIN lead_tracker_state ts ON ts.lead_key = lh.lead_key
        """
        params: list[Any] = []
        if run_id is not None:
            query += " INNER JOIN run_leads rl ON rl.lead_key = lh.lead_key AND rl.run_id = ?"
            params.append(run_id)
        if lead_list_id is not None:
            query += " INNER JOIN lead_list_members llm ON llm.lead_key = lh.lead_key AND llm.list_id = ?"
            params.append(lead_list_id)
        query += """
            ORDER BY COALESCE(lh.last_opportunity_score, 0) DESC, COALESCE(lh.last_lead_score, 0) DESC, lh.last_seen_at DESC, lh.business_name COLLATE NOCASE
        """
        with self._managed_connection() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
            latest_audits = self._latest_audits_for_keys(conn, [str(row[0] or "").strip() for row in rows])
            trigger_intel = self._trigger_intelligence_for_keys(conn, [str(row[0] or "").strip() for row in rows])

        search = search_text.strip().lower()
        leads: list[dict[str, Any]] = []
        for row in rows:
            lead_key = str(row[0] or "").strip()
            payload = json.loads(row[10] or "{}")
            if not isinstance(payload, dict):
                payload = {}
            lead = {
                "lead_key": lead_key,
                "business_name": row[1],
                "address": row[2] or "",
                "city_area": row[3] or "",
                "last_seed_source": row[4] or "",
                "first_seen_at": row[5] or "",
                "last_seen_at": row[6] or "",
                "last_web_presence_status": row[7] or "",
                "last_lead_score": row[8] or 0,
                "last_opportunity_score": row[9] or 0,
                "data": payload,
                "pipeline_status": row[11],
                "ready_to_contact": bool(row[12]),
                "do_not_contact": bool(row[13]),
                "lead_owner": row[14] or "",
                "next_action": row[15] or "",
                "lead_signal": row[16] or "",
                "work_bucket": row[17] or "",
                "tags": row[18] or "",
                "_latest_audit": latest_audits.get(lead_key, {}),
                "_trigger_intel": trigger_intel.get(lead_key, {}),
            }
            web_intel = self._resolved_web_intel(lead)
            trigger_summary = self._resolved_trigger_intel(lead)
            confidence_freshness = self._resolved_confidence_freshness(lead)
            lead["phone"] = str(payload.get("Phone", ""))
            lead["email"] = str(payload.get("Email", ""))
            lead["review_bucket"] = str(payload.get("Review Bucket", ""))
            lead["web_presence_status"] = str(web_intel.get("web_presence_status", ""))
            lead["pitch_family"] = str(web_intel.get("pitch_family", ""))
            lead["actionable"] = bool(payload.get("Actionable"))
            lead["actionability_notes"] = str(payload.get("Actionability Notes", ""))
            lead.update(trigger_summary)
            lead.update(confidence_freshness)

            # ── Backend grading truth at top level ──
            lead["website_quality_score"] = int(payload.get("Website Quality Score") or 0)
            lead["website_grade"] = str(payload.get("Website Grade", ""))
            lead["opportunity_score"] = int(payload.get("Opportunity Score") or 0)
            lead["opportunity_label"] = str(payload.get("Opportunity Label", ""))
            lead["opportunity_breakdown"] = str(payload.get("Opportunity Breakdown", ""))
            lead["source_confidence_score"] = int(payload.get("Source Confidence Score") or 0)
            lead["source_confidence_tier"] = str(payload.get("Source Confidence Tier", ""))
            lead["source_confidence_matrix"] = str(payload.get("Source Confidence Matrix", ""))
            lead["sources_checked"] = str(payload.get("Sources Checked", ""))
            lead["website_assertion_status"] = str(payload.get("Website Assertion Status", ""))
            lead["source_confidence_warnings"] = str(payload.get("Source Confidence Warnings", ""))
            lead["why_surfaced"] = str(payload.get("Why Surfaced", ""))
            lead["why_suppressed"] = str(payload.get("Why Suppressed", ""))
            lead["evidence_freshness"] = str(payload.get("Evidence Freshness", ""))
            lead["next_best_action"] = str(payload.get("Next Best Action", ""))
            _opp_label = lead["opportunity_label"]
            _opp_breakdown = lead["opportunity_breakdown"]
            lead["suppressed"] = "strong site" in _opp_label.lower() or "suppressor" in _opp_breakdown.lower()
            lead["disqualified"] = "DISQUALIFIED" in _opp_breakdown

            if search and not self._lead_matches_search(lead, search):
                continue
            bucket_value = str(lead.get("work_bucket", "")).strip()
            if work_bucket is not None and bucket_value != work_bucket.strip():
                continue
            if not self._lead_matches_view(lead, view_filter):
                continue
            leads.append(lead)

        return leads

    def list_queue_summaries(
        self,
        search_text: str = "",
        view_filter: str = "All leads",
        run_id: int | None = None,
        work_bucket: str | None = None,
        lead_list_id: int | None = None,
    ) -> list[dict[str, Any]]:
        self.ensure_ready()
        if self._queue_summary_json_supported is False:
            return self.list_leads(
                search_text=search_text,
                view_filter=view_filter,
                run_id=run_id,
                work_bucket=work_bucket,
                lead_list_id=lead_list_id,
            )

        query = """
            WITH queue_rows AS (
                SELECT
                    lh.lead_key AS lead_key,
                    lh.business_name AS business_name,
                    lh.address AS address,
                    lh.city_area AS city_area,
                    lh.last_seed_source AS last_seed_source,
                    lh.first_seen_at AS first_seen_at,
                    lh.last_seen_at AS last_seen_at,
                    lh.last_web_presence_status AS last_web_presence_status,
                    lh.last_lead_score AS last_lead_score,
                    COALESCE(lh.last_opportunity_score, 0) AS last_opportunity_score,
                    COALESCE(ts.pipeline_status, 'Needs review') AS pipeline_status,
                    COALESCE(ts.ready_to_contact, 0) AS ready_to_contact,
                    COALESCE(ts.do_not_contact, 0) AS do_not_contact,
                    COALESCE(ts.lead_owner, '') AS lead_owner,
                    COALESCE(ts.next_action, '') AS next_action,
                    COALESCE(ts.lead_signal, '') AS lead_signal,
                    COALESCE(ts.work_bucket, '') AS work_bucket,
                    COALESCE(ts.tags, '') AS tags,
                    COALESCE(json_extract(lh.data_json, '$."Phone"'), '') AS phone,
                    COALESCE(json_extract(lh.data_json, '$."Email"'), '') AS email,
                    COALESCE(json_extract(lh.data_json, '$."Review Bucket"'), '') AS review_bucket,
                    COALESCE(CAST(json_extract(lh.data_json, '$."Actionable"') AS INTEGER), 0) AS actionable,
                    COALESCE(json_extract(lh.data_json, '$."Actionability Notes"'), '') AS actionability_notes,
                    COALESCE(CAST(json_extract(lh.data_json, '$."Trigger Count"') AS INTEGER), 0) AS trigger_count,
                    COALESCE(json_extract(lh.data_json, '$."Trigger Summary"'), '') AS trigger_summary,
                    COALESCE(json_extract(lh.data_json, '$."Trigger Types"'), '') AS trigger_types,
                    COALESCE(json_extract(lh.data_json, '$."Web Presence Status"'), '') AS payload_web_presence_status,
                    COALESCE(json_extract(lh.data_json, '$."Website Bucket"'), '') AS payload_website_bucket,
                    COALESCE(json_extract(lh.data_json, '$."Website Failure Type"'), '') AS payload_website_failure_type,
                    COALESCE(json_extract(lh.data_json, '$."Web Presence Confidence"'), '') AS payload_web_presence_confidence,
                    COALESCE(json_extract(lh.data_json, '$."Business Reality"'), '') AS business_reality,
                    COALESCE(json_extract(lh.data_json, '$."Reality Confidence"'), '') AS reality_confidence,
                    COALESCE(json_extract(lh.data_json, '$."Colorado Match Confidence"'), '') AS colorado_match_confidence,
                    COALESCE(json_extract(lh.data_json, '$."License Confidence"'), '') AS license_confidence,
                    COALESCE(json_extract(lh.data_json, '$."Contact Cross-Reference"'), '') AS contact_cross_reference,
                    COALESCE(json_extract(lh.data_json, '$."Last Verified At"'), '') AS payload_last_verified_at,
                    COALESCE(json_extract(lh.data_json, '$."Data Freshness"'), '') AS payload_data_freshness,
                    COALESCE(json_extract(lh.data_json, '$."Pitch Family"'), '') AS payload_pitch_family,
                    COALESCE(json_extract(lh.data_json, '$."Opportunity Thesis"'), '') AS payload_opportunity_thesis,
                    COALESCE(json_extract(lh.data_json, '$."Opportunity Score"'), 0) AS payload_opportunity_score,
                    COALESCE(json_extract(lh.data_json, '$."Opportunity Label"'), '') AS payload_opportunity_label,
                    COALESCE(json_extract(lh.data_json, '$."Website Quality Score"'), 0) AS payload_website_quality_score,
                    COALESCE(json_extract(lh.data_json, '$."Website Grade"'), '') AS payload_website_grade,
                    COALESCE(json_extract(lh.data_json, '$."Opportunity Breakdown"'), '') AS payload_opportunity_breakdown,
                    COALESCE(json_extract(lh.data_json, '$."Source Confidence Score"'), 0) AS payload_source_confidence_score,
                    COALESCE(json_extract(lh.data_json, '$."Source Confidence Tier"'), '') AS payload_source_confidence_tier,
                    COALESCE(json_extract(lh.data_json, '$."Source Confidence Matrix"'), '') AS payload_source_confidence_matrix,
                    COALESCE(json_extract(lh.data_json, '$."Sources Checked"'), '') AS payload_sources_checked,
                    COALESCE(json_extract(lh.data_json, '$."Website Assertion Status"'), '') AS payload_website_assertion_status,
                    COALESCE(json_extract(lh.data_json, '$."Source Confidence Warnings"'), '') AS payload_source_confidence_warnings,
                    COALESCE(json_extract(lh.data_json, '$."Why Surfaced"'), '') AS payload_why_surfaced,
                    COALESCE(json_extract(lh.data_json, '$."Why Suppressed"'), '') AS payload_why_suppressed,
                    COALESCE(json_extract(lh.data_json, '$."Evidence Freshness"'), '') AS payload_evidence_freshness,
                    COALESCE(json_extract(lh.data_json, '$."Next Best Action"'), '') AS payload_next_best_action,
                    COALESCE(json_extract(lh.data_json, '$."Tech Stack Signal"'), '') AS payload_tech_stack_signal,
                    COALESCE(json_extract(lh.data_json, '$."Tech Stack Score"'), 0) AS payload_tech_stack_score,
                    COALESCE(json_extract(lh.data_json, '$."Tech Stack Summary"'), '') AS payload_tech_stack_summary
                FROM lead_history lh
                LEFT JOIN lead_tracker_state ts ON ts.lead_key = lh.lead_key
        """
        params: list[Any] = []
        if run_id is not None:
            query += " INNER JOIN run_leads rl ON rl.lead_key = lh.lead_key AND rl.run_id = ?"
            params.append(run_id)
        if lead_list_id is not None:
            query += " INNER JOIN lead_list_members llm ON llm.lead_key = lh.lead_key AND llm.list_id = ?"
            params.append(lead_list_id)
        query += """
            )
            SELECT *
            FROM queue_rows
        """
        query = self._apply_queue_summary_sql_filters(
            query,
            params,
            search_text=search_text,
            view_filter=view_filter,
            work_bucket=work_bucket,
        )
        query += """
            ORDER BY COALESCE(last_opportunity_score, 0) DESC, COALESCE(last_lead_score, 0) DESC, last_seen_at DESC, business_name COLLATE NOCASE
        """

        try:
            with self._managed_connection() as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(query, tuple(params)).fetchall()
                latest_audits = self._latest_audits_for_keys(conn, [str(row["lead_key"] or "").strip() for row in rows])
                trigger_intel = self._trigger_intelligence_for_keys(conn, [str(row["lead_key"] or "").strip() for row in rows])
            self._queue_summary_json_supported = True
        except sqlite3.OperationalError:
            self._queue_summary_json_supported = False
            return self.list_leads(
                search_text=search_text,
                view_filter=view_filter,
                run_id=run_id,
                work_bucket=work_bucket,
                lead_list_id=lead_list_id,
            )

        leads: list[dict[str, Any]] = []
        for row in rows:
            lead_key = str(row["lead_key"] or "").strip()
            lead = {
                "lead_key": lead_key,
                "business_name": row["business_name"] or "",
                "address": row["address"] or "",
                "city_area": row["city_area"] or "",
                "last_seed_source": row["last_seed_source"] or "",
                "first_seen_at": row["first_seen_at"] or "",
                "last_seen_at": row["last_seen_at"] or "",
                "last_web_presence_status": row["last_web_presence_status"] or "",
                "last_lead_score": row["last_lead_score"] or 0,
                "last_opportunity_score": row["last_opportunity_score"] or 0,
                "data": {},
                "pipeline_status": row["pipeline_status"] or "Needs review",
                "ready_to_contact": bool(row["ready_to_contact"]),
                "do_not_contact": bool(row["do_not_contact"]),
                "lead_owner": row["lead_owner"] or "",
                "next_action": row["next_action"] or "",
                "lead_signal": row["lead_signal"] or "",
                "work_bucket": row["work_bucket"] or "",
                "tags": row["tags"] or "",
                "phone": str(row["phone"] or ""),
                "email": str(row["email"] or ""),
                "review_bucket": str(row["review_bucket"] or ""),
                "actionable": bool(row["actionable"]),
                "actionability_notes": str(row["actionability_notes"] or ""),
                "trigger_count": int(row["trigger_count"] or 0),
                "trigger_summary": str(row["trigger_summary"] or ""),
                "trigger_types": str(row["trigger_types"] or ""),
                "Phone": str(row["phone"] or ""),
                "Email": str(row["email"] or ""),
                "Review Bucket": str(row["review_bucket"] or ""),
                "Actionable": bool(row["actionable"]),
                "Actionability Notes": str(row["actionability_notes"] or ""),
                "Trigger Count": int(row["trigger_count"] or 0),
                "Trigger Summary": str(row["trigger_summary"] or ""),
                "Trigger Types": str(row["trigger_types"] or ""),
                "Web Presence Status": str(row["payload_web_presence_status"] or ""),
                "Website Bucket": str(row["payload_website_bucket"] or ""),
                "Website Failure Type": str(row["payload_website_failure_type"] or ""),
                "Web Presence Confidence": str(row["payload_web_presence_confidence"] or ""),
                "Business Reality": str(row["business_reality"] or ""),
                "Reality Confidence": str(row["reality_confidence"] or ""),
                "Colorado Match Confidence": str(row["colorado_match_confidence"] or ""),
                "License Confidence": str(row["license_confidence"] or ""),
                "Contact Cross-Reference": str(row["contact_cross_reference"] or ""),
                "Last Verified At": str(row["payload_last_verified_at"] or ""),
                "Data Freshness": str(row["payload_data_freshness"] or ""),
                "Pitch Family": str(row["payload_pitch_family"] or ""),
                "Opportunity Thesis": str(row["payload_opportunity_thesis"] or ""),
                "Opportunity Score": int(row["payload_opportunity_score"] or 0),
                "Opportunity Label": str(row["payload_opportunity_label"] or ""),
                "Source Confidence Score": int(row["payload_source_confidence_score"] or 0),
                "Source Confidence Tier": str(row["payload_source_confidence_tier"] or ""),
                "Source Confidence Matrix": str(row["payload_source_confidence_matrix"] or ""),
                "Sources Checked": str(row["payload_sources_checked"] or ""),
                "Website Assertion Status": str(row["payload_website_assertion_status"] or ""),
                "Source Confidence Warnings": str(row["payload_source_confidence_warnings"] or ""),
                "Why Surfaced": str(row["payload_why_surfaced"] or ""),
                "Why Suppressed": str(row["payload_why_suppressed"] or ""),
                "Evidence Freshness": str(row["payload_evidence_freshness"] or ""),
                "Next Best Action": str(row["payload_next_best_action"] or ""),
                "Tech Stack Signal": str(row["payload_tech_stack_signal"] or ""),
                "Tech Stack Score": int(row["payload_tech_stack_score"] or 0),
                "Tech Stack Summary": str(row["payload_tech_stack_summary"] or ""),
                "_latest_audit": latest_audits.get(lead_key, {}),
                "_trigger_intel": trigger_intel.get(lead_key, {}),
            }
            web_intel = self._resolved_web_intel(lead)
            trigger_summary = self._resolved_trigger_intel(lead)
            confidence_freshness = self._resolved_confidence_freshness(lead)
            lead["web_presence_status"] = str(web_intel.get("web_presence_status", ""))
            lead["pitch_family"] = str(web_intel.get("pitch_family", ""))
            lead.update(trigger_summary)
            lead.update(confidence_freshness)

            # ── Backend grading truth at top level ──
            _q_opp_label = str(row["payload_opportunity_label"] or "")
            _q_opp_breakdown = str(row["payload_opportunity_breakdown"] or "")
            lead["website_quality_score"] = int(row["payload_website_quality_score"] or 0)
            lead["website_grade"] = str(row["payload_website_grade"] or "")
            lead["opportunity_score"] = int(row["payload_opportunity_score"] or 0)
            lead["opportunity_label"] = _q_opp_label
            lead["opportunity_breakdown"] = _q_opp_breakdown
            lead["source_confidence_score"] = int(row["payload_source_confidence_score"] or 0)
            lead["source_confidence_tier"] = str(row["payload_source_confidence_tier"] or "")
            lead["source_confidence_matrix"] = str(row["payload_source_confidence_matrix"] or "")
            lead["sources_checked"] = str(row["payload_sources_checked"] or "")
            lead["website_assertion_status"] = str(row["payload_website_assertion_status"] or "")
            lead["source_confidence_warnings"] = str(row["payload_source_confidence_warnings"] or "")
            lead["why_surfaced"] = str(row["payload_why_surfaced"] or "")
            lead["why_suppressed"] = str(row["payload_why_suppressed"] or "")
            lead["evidence_freshness"] = str(row["payload_evidence_freshness"] or "")
            lead["next_best_action"] = str(row["payload_next_best_action"] or "")
            lead["tech_stack_signal"] = str(row["payload_tech_stack_signal"] or "")
            lead["tech_stack_score"] = int(row["payload_tech_stack_score"] or 0)
            lead["tech_stack_summary"] = str(row["payload_tech_stack_summary"] or "")
            lead["suppressed"] = "strong site" in _q_opp_label.lower() or "suppressor" in _q_opp_breakdown.lower()
            lead["disqualified"] = "DISQUALIFIED" in _q_opp_breakdown
            leads.append(lead)

        return leads

    def _apply_queue_summary_sql_filters(
        self,
        query: str,
        params: list[Any],
        *,
        search_text: str,
        view_filter: str,
        work_bucket: str | None,
    ) -> str:
        filters: list[str] = []
        search = search_text.strip().lower()
        if search:
            filters.append(
                """
                LOWER(
                    COALESCE(business_name, '') || ' ' ||
                    COALESCE(city_area, '') || ' ' ||
                    COALESCE(address, '') || ' ' ||
                    COALESCE(phone, '') || ' ' ||
                    COALESCE(email, '') || ' ' ||
                    COALESCE(work_bucket, '') || ' ' ||
                    COALESCE(tags, '') || ' ' ||
                    COALESCE(lead_signal, '') || ' ' ||
                    COALESCE(next_action, '') || ' ' ||
                    COALESCE(trigger_summary, '') || ' ' ||
                    COALESCE(trigger_types, '') || ' ' ||
                    COALESCE(payload_source_confidence_tier, '') || ' ' ||
                    COALESCE(payload_sources_checked, '') || ' ' ||
                    COALESCE(payload_website_assertion_status, '') || ' ' ||
                    COALESCE(payload_source_confidence_warnings, '') || ' ' ||
                    COALESCE(payload_why_surfaced, '') || ' ' ||
                    COALESCE(payload_why_suppressed, '') || ' ' ||
                    COALESCE(payload_next_best_action, '')
                ) LIKE ?
                """
            )
            params.append(f"%{search}%")

        if work_bucket is not None:
            filters.append("TRIM(COALESCE(work_bucket, '')) = ?")
            params.append(work_bucket.strip())

        if view_filter == "Actionable only":
            filters.append("COALESCE(actionable, 0) != 0")
        elif view_filter == "Ready to contact":
            filters.append("COALESCE(ready_to_contact, 0) != 0")
        elif view_filter == "No contact":
            filters.append("COALESCE(actionable, 0) = 0")
        elif view_filter in {"High confidence", "Promising", "Needs review", "Low priority"}:
            filters.append("COALESCE(review_bucket, '') = ?")
            params.append(view_filter)
        elif view_filter in PIPELINE_STATUSES:
            filters.append("COALESCE(pipeline_status, 'Needs review') = ?")
            params.append(view_filter)

        if not filters:
            return query
        return query + "\n WHERE " + " AND ".join(filters)

    def bulk_update_pipeline_status(self, lead_keys: list[str], pipeline_status: str) -> None:
        self.ensure_ready()
        cleaned_keys = [lead_key for lead_key in lead_keys if lead_key]
        if not cleaned_keys:
            return
        now = datetime.now().isoformat(timespec="seconds")
        with self._managed_connection() as conn:
            for lead_key in cleaned_keys:
                conn.execute(
                    """
                    INSERT INTO lead_tracker_state (lead_key, pipeline_status, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(lead_key) DO UPDATE SET
                        pipeline_status=excluded.pipeline_status,
                        updated_at=excluded.updated_at
                    """,
                    (lead_key, pipeline_status or "Needs review", now),
                )

    def bulk_update_ready_to_contact(self, lead_keys: list[str], ready_to_contact: bool) -> None:
        self.ensure_ready()
        cleaned_keys = [lead_key for lead_key in lead_keys if lead_key]
        if not cleaned_keys:
            return
        now = datetime.now().isoformat(timespec="seconds")
        ready_value = 1 if ready_to_contact else 0
        with self._managed_connection() as conn:
            for lead_key in cleaned_keys:
                conn.execute(
                    """
                    INSERT INTO lead_tracker_state (lead_key, ready_to_contact, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(lead_key) DO UPDATE SET
                        ready_to_contact=excluded.ready_to_contact,
                        updated_at=excluded.updated_at
                    """,
                    (lead_key, ready_value, now),
                )

    def bulk_update_lead_signal(self, lead_keys: list[str], lead_signal: str) -> None:
        self.ensure_ready()
        cleaned_keys = [lead_key for lead_key in lead_keys if lead_key]
        if not cleaned_keys:
            return
        now = datetime.now().isoformat(timespec="seconds")
        cleaned_signal = lead_signal.strip()
        with self._managed_connection() as conn:
            for lead_key in cleaned_keys:
                conn.execute(
                    """
                    INSERT INTO lead_tracker_state (lead_key, lead_signal, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(lead_key) DO UPDATE SET
                        lead_signal=excluded.lead_signal,
                        updated_at=excluded.updated_at
                    """,
                    (lead_key, cleaned_signal, now),
                )

    def bulk_set_work_bucket(self, lead_keys: list[str], work_bucket: str) -> None:
        self.ensure_ready()
        cleaned_keys = [lead_key for lead_key in lead_keys if lead_key]
        if not cleaned_keys:
            return
        now = datetime.now().isoformat(timespec="seconds")
        cleaned_bucket = work_bucket.strip()
        with self._managed_connection() as conn:
            for lead_key in cleaned_keys:
                conn.execute(
                    """
                    INSERT INTO lead_tracker_state (lead_key, work_bucket, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(lead_key) DO UPDATE SET
                        work_bucket=excluded.work_bucket,
                        updated_at=excluded.updated_at
                    """,
                    (lead_key, cleaned_bucket, now),
                )

    def bulk_add_tag(self, lead_keys: list[str], tag: str) -> None:
        self.ensure_ready()
        cleaned_tag = tag.strip()
        cleaned_keys = [lead_key for lead_key in lead_keys if lead_key]
        if not cleaned_tag or not cleaned_keys:
            return
        now = datetime.now().isoformat(timespec="seconds")
        with self._managed_connection() as conn:
            for lead_key in cleaned_keys:
                existing = conn.execute(
                    "SELECT COALESCE(tags, '') FROM lead_tracker_state WHERE lead_key = ?",
                    (lead_key,),
                ).fetchone()
                current_tags = [item.strip() for item in str(existing[0] if existing else "").split(",") if item.strip()]
                if cleaned_tag.lower() not in {item.lower() for item in current_tags}:
                    current_tags.append(cleaned_tag)
                merged_tags = ", ".join(current_tags)
                conn.execute(
                    """
                    INSERT INTO lead_tracker_state (lead_key, tags, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(lead_key) DO UPDATE SET
                        tags=excluded.tags,
                        updated_at=excluded.updated_at
                    """,
                    (lead_key, merged_tags, now),
                )

    def delete_selected_leads(self, lead_keys: list[str], run_id: int | None = None) -> None:
        self.ensure_ready()
        cleaned_keys = [lead_key for lead_key in lead_keys if lead_key]
        if not cleaned_keys:
            return
        placeholders = ", ".join("?" for _ in cleaned_keys)
        with self._managed_connection() as conn:
            if run_id is None:
                conn.execute(f"DELETE FROM run_leads WHERE lead_key IN ({placeholders})", tuple(cleaned_keys))
                conn.execute(f"DELETE FROM lead_activity_log WHERE lead_key IN ({placeholders})", tuple(cleaned_keys))
                conn.execute(f"DELETE FROM lead_tracker_state WHERE lead_key IN ({placeholders})", tuple(cleaned_keys))
                conn.execute(f"DELETE FROM opportunity_audits WHERE lead_key IN ({placeholders})", tuple(cleaned_keys))
                conn.execute(f"DELETE FROM trigger_events WHERE lead_key IN ({placeholders})", tuple(cleaned_keys))
                conn.execute(f"DELETE FROM lead_list_members WHERE lead_key IN ({placeholders})", tuple(cleaned_keys))
                conn.execute(f"DELETE FROM lead_history WHERE lead_key IN ({placeholders})", tuple(cleaned_keys))
            else:
                conn.execute(
                    f"DELETE FROM run_leads WHERE run_id = ? AND lead_key IN ({placeholders})",
                    (run_id, *cleaned_keys),
                )
                conn.execute(
                    f"DELETE FROM opportunity_audits WHERE run_id = ? AND lead_key IN ({placeholders})",
                    (run_id, *cleaned_keys),
                )
                conn.execute(
                    f"DELETE FROM trigger_events WHERE run_id = ? AND lead_key IN ({placeholders})",
                    (run_id, *cleaned_keys),
                )
                self._cleanup_orphaned_leads(conn)

    def delete_run(self, run_id: int) -> None:
        self.ensure_ready()
        with self._managed_connection() as conn:
            conn.execute("DELETE FROM run_leads WHERE run_id = ?", (run_id,))
            conn.execute("DELETE FROM opportunity_audits WHERE run_id = ?", (run_id,))
            conn.execute("DELETE FROM trigger_events WHERE run_id = ?", (run_id,))
            conn.execute("DELETE FROM runs WHERE id = ?", (run_id,))
            self._cleanup_orphaned_leads(conn)

    def _cleanup_orphaned_leads(self, conn: sqlite3.Connection) -> None:
        orphan_rows = conn.execute(
            """
            SELECT lh.lead_key
            FROM lead_history lh
            LEFT JOIN run_leads rl ON rl.lead_key = lh.lead_key
            WHERE rl.lead_key IS NULL
            """
        ).fetchall()
        orphan_keys = [str(row[0]) for row in orphan_rows if row and row[0]]
        if not orphan_keys:
            return
        placeholders = ", ".join("?" for _ in orphan_keys)
        conn.execute(f"DELETE FROM lead_activity_log WHERE lead_key IN ({placeholders})", tuple(orphan_keys))
        conn.execute(f"DELETE FROM lead_tracker_state WHERE lead_key IN ({placeholders})", tuple(orphan_keys))
        conn.execute(f"DELETE FROM opportunity_audits WHERE lead_key IN ({placeholders})", tuple(orphan_keys))
        conn.execute(f"DELETE FROM trigger_events WHERE lead_key IN ({placeholders})", tuple(orphan_keys))
        conn.execute(f"DELETE FROM lead_list_members WHERE lead_key IN ({placeholders})", tuple(orphan_keys))
        conn.execute(f"DELETE FROM lead_history WHERE lead_key IN ({placeholders})", tuple(orphan_keys))

    def _lead_matches_search(self, lead: dict[str, Any], search: str) -> bool:
        haystack = " ".join(
            [
                str(lead.get("business_name", "")),
                str(lead.get("city_area", "")),
                str(lead.get("address", "")),
                str(lead.get("phone", "")),
                str(lead.get("email", "")),
                str(lead.get("work_bucket", "")),
                str(lead.get("tags", "")),
                str(lead.get("lead_signal", "")),
                str(lead.get("next_action", "")),
                str(lead.get("trigger_summary", "")),
                str(lead.get("trigger_types", "")),
                str(lead.get("source_confidence_tier", "")),
                str(lead.get("sources_checked", "")),
                str(lead.get("website_assertion_status", "")),
                str(lead.get("source_confidence_warnings", "")),
                str(lead.get("why_surfaced", "")),
                str(lead.get("why_suppressed", "")),
                str(lead.get("next_best_action", "")),
            ]
        ).lower()
        return search in haystack

    def _lead_matches_view(self, lead: dict[str, Any], view_filter: str) -> bool:
        if view_filter == "All leads":
            return True
        if view_filter == "Actionable only":
            return bool(lead.get("actionable"))
        if view_filter == "Ready to contact":
            return bool(lead.get("ready_to_contact"))
        if view_filter == "No contact":
            return not bool(lead.get("actionable"))
        if view_filter in {"High confidence", "Promising", "Needs review", "Low priority"}:
            return str(lead.get("review_bucket", "")) == view_filter
        if view_filter in PIPELINE_STATUSES:
            return str(lead.get("pipeline_status", "")) == view_filter
        return True

    def _lead_value(self, lead: dict[str, Any], key: str, default: str = "") -> str:
        value = lead.get(key)
        if value not in (None, ""):
            return str(value).strip()
        payload = lead.get("data", {})
        if isinstance(payload, dict):
            payload_value = payload.get(key)
            if payload_value not in (None, ""):
                return str(payload_value).strip()
        return default

    def _parse_json_list(self, value: str) -> list[str]:
        try:
            payload = json.loads(value or "[]")
        except Exception:
            return []
        if isinstance(payload, list):
            return [str(item) for item in payload if str(item).strip()]
        return []

    def _hydrate_trigger_event(
        self,
        *,
        trigger_type: Any,
        trigger_label: Any,
        trigger_strength: Any,
        observed_at: Any,
        summary: Any,
        details_json: Any,
    ) -> dict[str, Any]:
        raw_details = str(details_json or "")
        try:
            details = json.loads(raw_details) if raw_details else {}
        except Exception:
            details = {}
        if not isinstance(details, dict):
            details = {}
        evidence = details.get("evidence", [])
        if not isinstance(evidence, list):
            evidence = []
        return {
            "type": trigger_type or "",
            "label": trigger_label or "",
            "strength": trigger_strength or "",
            "observed_at": observed_at or "",
            "summary": summary or "",
            "why_now": str(details.get("why_now", "")),
            "evidence": [str(item) for item in evidence if str(item).strip()],
            "version": str(details.get("version", "")),
        }

    def _hydrate_latest_audit_row(self, row: tuple[Any, ...]) -> dict[str, Any]:
        issues = self._parse_json_list(str(row[36] or ""))
        business_impact = self._parse_json_list(str(row[37] or ""))
        return {
            "Last Audited At": row[1] or "",
            "Audit Version": row[2] or "",
            "Website Bucket": row[3] or "",
            "Website Failure Type": row[4] or "",
            "Mobile Readiness": row[5] or "",
            "SSL Status": row[6] or "",
            "Page Speed Signal": row[7] or "",
            "Contact Form Status": row[8] or "",
            "Booking Flow Status": row[9] or "",
            "CTA Strength": row[10] or "",
            "SEO Basics": row[11] or "",
            "Social Dependence": row[12] or "",
            "Directory Dependence": row[13] or "",
            "Image Quality Signal": row[14] or "",
            "Navigation Quality": row[15] or "",
            "Primary Business Impact": row[16] or "",
            "Best Pitch Angle": row[17] or "",
            "Last Verified At": row[18] or "",
            "Data Freshness": row[19] or "",
            "Resolved Website URL": row[20] or "",
            "HTTP Status": row[21] or "",
            "Fetch Time Ms": int(row[22] or 0),
            "Page Title": row[23] or "",
            "Meta Description": row[24] or "",
            "Word Count": int(row[25] or 0),
            "Form Count": int(row[26] or 0),
            "Internal Link Count": int(row[27] or 0),
            "Image Count": int(row[28] or 0),
            "On-Page Phones": row[29] or "",
            "On-Page Emails": row[30] or "",
            "CTA Terms": row[31] or "",
            "Booking Terms": row[32] or "",
            "Viewport Meta": row[33] or "",
            "Website Evidence Summary": row[34] or "",
            "Website Evidence Snippet": row[35] or "",
            "Audit Issues": "; ".join(issues),
            "Audit Issues List": issues,
            "Business Impact Summary": "; ".join(business_impact),
            "Business Impact List": business_impact,
            "Audit Confidence": row[38] or "",
            # Agent review fields (safe for older DBs — COALESCE defaults to '')
            "agent_review_json": row[39] if len(row) > 39 else "",
            "agent_review_status": row[40] if len(row) > 40 else "",
            "agent_review_model": row[41] if len(row) > 41 else "",
            "agent_review_updated_at": row[42] if len(row) > 42 else "",
            "agent_review_input_hash": row[43] if len(row) > 43 else "",
        }

    def _latest_audits_for_keys(
        self,
        conn: sqlite3.Connection,
        lead_keys: list[str],
    ) -> dict[str, dict[str, Any]]:
        unique_keys: list[str] = []
        seen: set[str] = set()
        for lead_key in lead_keys:
            cleaned = str(lead_key or "").strip()
            if cleaned and cleaned not in seen:
                unique_keys.append(cleaned)
                seen.add(cleaned)
        if not unique_keys:
            return {}

        placeholders = ", ".join("?" for _ in unique_keys)
        rows = conn.execute(
            f"""
            SELECT
                oa.lead_key,
                oa.audited_at,
                oa.audit_version,
                oa.website_bucket,
                oa.failure_type,
                oa.mobile_readiness,
                oa.ssl_status,
                oa.page_speed_signal,
                oa.contact_form_status,
                oa.booking_flow_status,
                oa.cta_strength,
                oa.seo_basics,
                oa.social_dependence,
                oa.directory_dependence,
                oa.image_quality_signal,
                oa.navigation_quality,
                oa.primary_business_impact,
                oa.best_pitch_angle,
                oa.last_verified_at,
                oa.data_freshness,
                oa.resolved_url,
                oa.http_status,
                oa.fetch_time_ms,
                oa.page_title,
                oa.meta_description,
                oa.word_count,
                oa.form_count,
                oa.internal_link_count,
                oa.image_count,
                oa.on_page_phones,
                oa.on_page_emails,
                oa.cta_terms,
                oa.booking_terms,
                oa.viewport_meta,
                oa.evidence_summary,
                oa.evidence_snippet,
                oa.issues_json,
                oa.business_impact_json,
                oa.audit_confidence,
                COALESCE(oa.agent_review_json, '') AS agent_review_json,
                COALESCE(oa.agent_review_status, '') AS agent_review_status,
                COALESCE(oa.agent_review_model, '') AS agent_review_model,
                COALESCE(oa.agent_review_updated_at, '') AS agent_review_updated_at,
                COALESCE(oa.agent_review_input_hash, '') AS agent_review_input_hash
            FROM opportunity_audits oa
            LEFT JOIN runs r ON r.id = oa.run_id
            WHERE oa.lead_key IN ({placeholders})
              AND (oa.run_id IS NULL OR r.id IS NOT NULL)
            ORDER BY oa.lead_key, oa.audited_at DESC, oa.id DESC
            """,
            tuple(unique_keys),
        ).fetchall()

        latest_by_key: dict[str, dict[str, Any]] = {}
        for row in rows:
            lead_key = str(row[0] or "").strip()
            if not lead_key or lead_key in latest_by_key:
                continue
            latest_by_key[lead_key] = self._hydrate_latest_audit_row(row)
        return latest_by_key

    def _trigger_intelligence_for_keys(
        self,
        conn: sqlite3.Connection,
        lead_keys: list[str],
    ) -> dict[str, dict[str, Any]]:
        unique_keys: list[str] = []
        seen: set[str] = set()
        for lead_key in lead_keys:
            cleaned = str(lead_key or "").strip()
            if cleaned and cleaned not in seen:
                unique_keys.append(cleaned)
                seen.add(cleaned)
        if not unique_keys:
            return {}

        placeholders = ",".join("?" for _ in unique_keys)
        rows = conn.execute(
            f"""
            SELECT lead_key, trigger_type, trigger_label, trigger_strength, observed_at, summary, details_json
            FROM trigger_events
            WHERE lead_key IN ({placeholders})
            ORDER BY lead_key, observed_at DESC, id DESC
            """,
            tuple(unique_keys),
        ).fetchall()

        events_by_key: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            lead_key = str(row[0] or "").strip()
            if not lead_key:
                continue
            events_by_key.setdefault(lead_key, []).append(
                self._hydrate_trigger_event(
                    trigger_type=row[1],
                    trigger_label=row[2],
                    trigger_strength=row[3],
                    observed_at=row[4],
                    summary=row[5],
                    details_json=row[6],
                )
            )

        return {
            lead_key: build_trigger_intelligence(events_by_key.get(lead_key, []))
            for lead_key in unique_keys
        }

    def _lead_audit(self, lead: dict[str, Any]) -> dict[str, Any]:
        audit = lead.get("latest_audit")
        if not isinstance(audit, dict) or not audit:
            audit = lead.get("_latest_audit", {})
        return audit if isinstance(audit, dict) else {}

    def _audit_value(self, lead: dict[str, Any], key: str, fallback: Any = "") -> Any:
        audit = self._lead_audit(lead)
        value = audit.get(key)
        if value not in (None, ""):
            return value
        return fallback

    def _audit_int_value(self, lead: dict[str, Any], key: str, fallback: Any = 0) -> int:
        value = self._audit_value(lead, key, fallback)
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return int(fallback or 0)

    def _resolved_web_intel(self, lead: dict[str, Any]) -> dict[str, Any]:
        legacy_web_status = self._lead_value(
            lead,
            "Web Presence Status",
            self._lead_value(
                lead,
                "Website Status",
                self._lead_value(lead, "last_web_presence_status"),
            ),
        )
        audit_confidence = str(
            self._audit_value(
                lead,
                "Audit Confidence",
                self._lead_value(lead, "Audit Confidence"),
            )
        ).strip()
        web_intel = {
            "website_bucket": str(
                self._audit_value(
                    lead,
                    "Website Bucket",
                    self._lead_value(lead, "Website Bucket", legacy_web_status),
                )
            ).strip(),
            "web_presence_status": str(
                self._audit_value(
                    lead,
                    "Website Bucket",
                    self._lead_value(lead, "Website Bucket", legacy_web_status),
                )
            ).strip()
            or legacy_web_status,
            "website_failure_type": str(
                self._audit_value(
                    lead,
                    "Website Failure Type",
                    self._lead_value(lead, "Website Failure Type"),
                )
            ).strip(),
            "resolved_url": str(
                self._audit_value(
                    lead,
                    "Resolved Website URL",
                    self._lead_value(lead, "Resolved Website URL", self._lead_value(lead, "Official Website")),
                )
            ).strip(),
            "page_title": str(self._audit_value(lead, "Page Title", self._lead_value(lead, "Page Title"))).strip(),
            "meta_description": str(
                self._audit_value(lead, "Meta Description", self._lead_value(lead, "Meta Description"))
            ).strip(),
            "evidence_summary": str(
                self._audit_value(
                    lead,
                    "Website Evidence Summary",
                    self._lead_value(lead, "Website Evidence Summary"),
                )
            ).strip(),
            "evidence_snippet": str(
                self._audit_value(
                    lead,
                    "Website Evidence Snippet",
                    self._lead_value(lead, "Website Evidence Snippet"),
                )
            ).strip(),
            "primary_business_impact": str(
                self._audit_value(
                    lead,
                    "Primary Business Impact",
                    self._lead_value(lead, "Primary Business Impact"),
                )
            ).strip(),
            "best_pitch_angle": str(
                self._audit_value(
                    lead,
                    "Best Pitch Angle",
                    self._lead_value(lead, "Best Pitch Angle"),
                )
            ).strip(),
            "web_confidence": audit_confidence or self._lead_value(lead, "Web Presence Confidence"),
            "audit_confidence": audit_confidence,
            "last_audited_at": str(
                self._audit_value(
                    lead,
                    "Last Audited At",
                    self._lead_value(lead, "Last Audited At"),
                )
            ).strip(),
            "last_verified_at": str(
                self._audit_value(
                    lead,
                    "Last Verified At",
                    self._lead_value(lead, "Last Verified At"),
                )
            ).strip(),
            "data_freshness": str(
                self._audit_value(
                    lead,
                    "Data Freshness",
                    self._lead_value(lead, "Data Freshness"),
                )
            ).strip(),
            "http_status": str(
                self._audit_value(
                    lead,
                    "HTTP Status",
                    self._lead_value(lead, "HTTP Status"),
                )
            ).strip(),
            "fetch_time_ms": self._audit_int_value(lead, "Fetch Time Ms", 0),
            "word_count": self._audit_int_value(lead, "Word Count", 0),
            "form_count": self._audit_int_value(lead, "Form Count", 0),
            "internal_link_count": self._audit_int_value(lead, "Internal Link Count", 0),
            "image_count": self._audit_int_value(lead, "Image Count", 0),
            "on_page_phones": str(
                self._audit_value(
                    lead,
                    "On-Page Phones",
                    self._lead_value(lead, "On-Page Phones"),
                )
            ).strip(),
            "on_page_emails": str(
                self._audit_value(
                    lead,
                    "On-Page Emails",
                    self._lead_value(lead, "On-Page Emails"),
                )
            ).strip(),
            "cta_terms": str(self._audit_value(lead, "CTA Terms", self._lead_value(lead, "CTA Terms"))).strip(),
            "booking_terms": str(
                self._audit_value(
                    lead,
                    "Booking Terms",
                    self._lead_value(lead, "Booking Terms"),
                )
            ).strip(),
            "viewport_meta": str(
                self._audit_value(
                    lead,
                    "Viewport Meta",
                    self._lead_value(lead, "Viewport Meta"),
                )
            ).strip(),
            "audit_issues": str(
                self._audit_value(
                    lead,
                    "Audit Issues",
                    self._lead_value(lead, "Audit Issues"),
                )
            ).strip(),
            "business_impact_summary": str(
                self._audit_value(
                    lead,
                    "Business Impact Summary",
                    self._lead_value(lead, "Business Impact Summary"),
                )
            ).strip(),
            "mobile_readiness": str(
                self._audit_value(
                    lead,
                    "Mobile Readiness",
                    self._lead_value(lead, "Mobile Readiness"),
                )
            ).strip(),
            "ssl_status": str(
                self._audit_value(
                    lead,
                    "SSL Status",
                    self._lead_value(lead, "SSL Status"),
                )
            ).strip(),
            "page_speed_signal": str(
                self._audit_value(
                    lead,
                    "Page Speed Signal",
                    self._lead_value(lead, "Page Speed Signal"),
                )
            ).strip(),
            "contact_form_status": str(
                self._audit_value(
                    lead,
                    "Contact Form Status",
                    self._lead_value(lead, "Contact Form Status"),
                )
            ).strip(),
            "booking_flow_status": str(
                self._audit_value(
                    lead,
                    "Booking Flow Status",
                    self._lead_value(lead, "Booking Flow Status"),
                )
            ).strip(),
            "cta_strength": str(
                self._audit_value(
                    lead,
                    "CTA Strength",
                    self._lead_value(lead, "CTA Strength"),
                )
            ).strip(),
            "seo_basics": str(
                self._audit_value(
                    lead,
                    "SEO Basics",
                    self._lead_value(lead, "SEO Basics"),
                )
            ).strip(),
            "social_dependence": str(
                self._audit_value(
                    lead,
                    "Social Dependence",
                    self._lead_value(lead, "Social Dependence"),
                )
            ).strip(),
            "directory_dependence": str(
                self._audit_value(
                    lead,
                    "Directory Dependence",
                    self._lead_value(lead, "Directory Dependence"),
                )
            ).strip(),
            "image_quality_signal": str(
                self._audit_value(
                    lead,
                    "Image Quality Signal",
                    self._lead_value(lead, "Image Quality Signal"),
                )
            ).strip(),
            "navigation_quality": str(
                self._audit_value(
                    lead,
                    "Navigation Quality",
                    self._lead_value(lead, "Navigation Quality"),
                )
            ).strip(),
            "opportunity_brief": self._lead_value(lead, "Opportunity Brief"),
            "why_kept": self._lead_value(lead, "Why Kept"),
            "lead_rationale": self._lead_value(lead, "Lead Rationale"),
            "web_presence_details": self._lead_value(lead, "Web Presence Details"),
            "website_signals": self._lead_value(lead, "Website Signals"),
            "score_breakdown": self._lead_value(lead, "Score Breakdown"),
        }
        pitch_family = self._lead_value(lead, "Pitch Family") or derive_pitch_family(web_intel)
        opportunity_thesis = self._lead_value(lead, "Opportunity Thesis") or build_opportunity_thesis(
            {
                **web_intel,
                "Pitch Family": pitch_family,
            }
        )
        web_intel["pitch_family"] = str(pitch_family).strip()
        web_intel["opportunity_thesis"] = str(opportunity_thesis).strip()
        return web_intel

    def _resolved_trigger_intel(self, lead: dict[str, Any]) -> dict[str, Any]:
        fallback_summary = self._lead_value(lead, "Trigger Summary", str(lead.get("trigger_summary", "")))
        fallback_types = self._lead_value(lead, "Trigger Types", str(lead.get("trigger_types", "")))
        fallback_count = self._lead_value(lead, "Trigger Count", lead.get("trigger_count", 0))
        trigger_events = lead.get("trigger_events", []) or []
        if trigger_events:
            intel = build_trigger_intelligence(
                list(trigger_events),
                fallback_summary=fallback_summary,
                fallback_types=fallback_types,
                fallback_count=fallback_count,
            )
        else:
            cached = lead.get("_trigger_intel", {})
            if isinstance(cached, dict) and cached:
                intel = build_trigger_intelligence(
                    [],
                    fallback_summary=cached.get("trigger_summary") or fallback_summary,
                    fallback_types=cached.get("trigger_types") or fallback_types,
                    fallback_count=cached.get("trigger_count") or fallback_count,
                )
                for key in (
                    "top_trigger_type",
                    "top_trigger_label",
                    "top_trigger_strength",
                    "top_trigger_summary",
                    "why_now_summary",
                    "trigger_priority",
                    "trigger_operational_class",
                ):
                    if cached.get(key):
                        intel[key] = cached.get(key)
            else:
                intel = build_trigger_intelligence(
                    [],
                    fallback_summary=fallback_summary,
                    fallback_types=fallback_types,
                    fallback_count=fallback_count,
                )

        normalized = {
            "trigger_count": 0,
            "trigger_summary": "",
            "trigger_types": "",
            "top_trigger_type": "",
            "top_trigger_label": "",
            "top_trigger_strength": "",
            "top_trigger_summary": "",
            "why_now_summary": "",
            "trigger_priority": "",
            "trigger_operational_class": "",
        }
        for key in (
            "trigger_summary",
            "trigger_types",
            "top_trigger_type",
            "top_trigger_label",
            "top_trigger_strength",
            "top_trigger_summary",
            "why_now_summary",
            "trigger_priority",
            "trigger_operational_class",
        ):
            normalized[key] = str(intel.get(key, "") or "").strip()
        try:
            normalized["trigger_count"] = int(intel.get("trigger_count") or 0)
        except (TypeError, ValueError):
            normalized["trigger_count"] = 0
        return normalized

    def _parse_datetime(self, value: Any) -> datetime | None:
        cleaned = str(value or "").strip()
        if not cleaned:
            return None
        try:
            parsed = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed = datetime.fromisoformat(cleaned[:19])
            except ValueError:
                return None
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone().replace(tzinfo=None)
        return parsed

    def _display_timestamp(self, value: Any) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            return ""
        return cleaned.replace("T", " ")[:16]

    def _normalized_freshness_state(self, value: Any) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            return ""
        normalized = self._normalize_text(cleaned)
        if "verified this run" in normalized:
            return "Verified this run"
        if "recently verified" in normalized:
            return "Recently verified"
        if "getting stale" in normalized:
            return "Getting stale"
        if "very stale" in normalized:
            return "Very stale"
        if "changed since previous scan" in normalized:
            return "Changed since previous scan"
        if "newly found" in normalized or "new lead" in normalized:
            return "Newly found"
        if "stale" in normalized or "historic" in normalized or "outdated" in normalized:
            return "Stale"
        return cleaned

    def _derived_freshness_state(self, lead: dict[str, Any], web_intel: dict[str, Any]) -> str:
        explicit = self._normalized_freshness_state(web_intel.get("data_freshness"))
        if explicit:
            return explicit

        first_seen = self._parse_datetime(lead.get("first_seen_at"))
        last_seen = self._parse_datetime(lead.get("last_seen_at"))
        last_verified = self._parse_datetime(web_intel.get("last_verified_at"))
        last_audited = self._parse_datetime(web_intel.get("last_audited_at"))
        verification_dt = last_verified or last_audited

        if first_seen and last_seen and first_seen == last_seen and not verification_dt:
            return "Newly found"
        if verification_dt and last_seen and verification_dt >= last_seen:
            return "Verified this run"
        if verification_dt:
            age_days = max(0, (datetime.now() - verification_dt).days)
            if age_days <= 14:
                return "Recently verified"
            if age_days <= 30:
                return "Getting stale"
            if age_days <= 60:
                return "Stale"
            return "Very stale"
        if first_seen and last_seen and first_seen == last_seen:
            return "Newly found"
        return ""

    def _resolved_confidence_freshness(self, lead: dict[str, Any]) -> dict[str, str]:
        web_intel = self._resolved_web_intel(lead)
        website_confidence = str(web_intel.get("web_confidence", "")).strip()
        audit_confidence = str(web_intel.get("audit_confidence", "")).strip()
        business_legitimacy = self._lead_value(lead, "Business Reality")
        business_confidence = self._lead_value(
            lead,
            "Reality Confidence",
            self._lead_value(
                lead,
                "Colorado Match Confidence",
                self._lead_value(lead, "License Confidence"),
            ),
        )
        contact_confidence = self._lead_value(lead, "Contact Cross-Reference")
        source_confidence = self._lead_value(lead, "Source Confidence Tier")
        freshness_status = self._derived_freshness_state(lead, web_intel)
        verified_stamp = self._display_timestamp(web_intel.get("last_verified_at") or web_intel.get("last_audited_at"))

        confidence_parts: list[str] = []
        if source_confidence:
            confidence_parts.append(f"Source: {source_confidence}")
        if website_confidence:
            confidence_parts.append(f"Web: {website_confidence}")
        if business_confidence:
            confidence_parts.append(f"Business: {business_confidence}")
        if contact_confidence:
            confidence_parts.append(f"Contact: {contact_confidence}")

        verification_status = freshness_status
        if verified_stamp:
            verification_status = (
                f"{freshness_status} ({verified_stamp})" if freshness_status else f"Last verified {verified_stamp}"
            )

        return {
            "website_confidence": website_confidence,
            "business_legitimacy": business_legitimacy,
            "business_confidence": business_confidence,
            "contact_confidence": contact_confidence,
            "source_confidence": source_confidence,
            "audit_confidence": audit_confidence,
            "freshness_status": freshness_status,
            "verification_status": verification_status,
            "confidence_summary": " | ".join(confidence_parts),
        }

    def _normalize_text(self, value: str) -> str:
        return " ".join(re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).split())

    def _tokenize(self, value: str) -> set[str]:
        tokens = {
            token
            for token in self._normalize_text(value).split()
            if len(token) >= 3 and token not in GENERIC_SIMILARITY_TOKENS and not token.isdigit()
        }
        return tokens

    def _lead_type_tokens(self, lead: dict[str, Any]) -> set[str]:
        tokens = set()
        tokens.update(self._tokenize(self._lead_value(lead, "Business Type")))
        tokens.update(self._tokenize(self._lead_value(lead, "business_name")))
        return tokens

    def _lead_city_key(self, lead: dict[str, Any]) -> str:
        raw_city = self._lead_value(lead, "city_area")
        if "," in raw_city:
            raw_city = raw_city.split(",", 1)[0]
        return self._normalize_text(raw_city)

    def _lead_contact_profile(self, lead: dict[str, Any]) -> str:
        has_phone = bool(self._lead_value(lead, "phone") or self._lead_value(lead, "Phone"))
        has_email = bool(self._lead_value(lead, "email") or self._lead_value(lead, "Email"))
        if has_phone and has_email:
            return "Phone + Email"
        if has_email:
            return "Email"
        if has_phone:
            return "Phone"
        return "None"

    def _lead_trigger_labels(self, lead: dict[str, Any]) -> set[str]:
        raw_value = self._lead_value(lead, "Trigger Types")
        if raw_value:
            parts = re.split(r"[|;,]+", raw_value)
            return {self._normalize_text(part) for part in parts if self._normalize_text(part)}
        labels: set[str] = set()
        for event in lead.get("trigger_events", []) or []:
            label = self._normalize_text(str(event.get("label", "")))
            if label:
                labels.add(label)
        return labels

    def _lead_web_bucket(self, lead: dict[str, Any]) -> str:
        return str(self._resolved_web_intel(lead).get("website_bucket", "")).strip()

    def _lead_web_failure(self, lead: dict[str, Any]) -> str:
        return str(self._resolved_web_intel(lead).get("website_failure_type", "")).strip()

    def _lead_review_bucket(self, lead: dict[str, Any]) -> str:
        return self._lead_value(lead, "Review Bucket", str(lead.get("review_bucket", "")).strip())

    def _lead_business_reality(self, lead: dict[str, Any]) -> str:
        return self._lead_value(lead, "Business Reality")

    def _lead_score(self, lead: dict[str, Any]) -> int:
        raw_value = lead.get("last_lead_score")
        if raw_value in (None, ""):
            raw_value = self._lead_value(lead, "Lead Score", "0")
        try:
            return int(raw_value or 0)
        except (TypeError, ValueError):
            return 0

    def _score_similarity(self, base_lead: dict[str, Any], candidate: dict[str, Any]) -> tuple[int, list[str]]:
        score = 0
        reasons: list[str] = []
        has_vertical_match = False

        base_city = self._lead_city_key(base_lead)
        candidate_city = self._lead_city_key(candidate)
        if base_city and candidate_city and base_city == candidate_city:
            score += 10
            reasons.append("same city")

        base_type = self._normalize_text(self._lead_value(base_lead, "Business Type"))
        candidate_type = self._normalize_text(self._lead_value(candidate, "Business Type"))
        base_tokens = self._lead_type_tokens(base_lead)
        candidate_tokens = self._lead_type_tokens(candidate)
        shared_type_tokens = sorted(base_tokens & candidate_tokens)
        if base_type and candidate_type and base_type == candidate_type:
            score += 28
            has_vertical_match = True
            reasons.append("same business type")
        elif len(shared_type_tokens) >= 2:
            score += 20
            has_vertical_match = True
            reasons.append(f"shared niche keywords: {', '.join(shared_type_tokens[:3])}")
        elif len(shared_type_tokens) == 1:
            score += 10
            has_vertical_match = True
            reasons.append(f"shared business keyword: {shared_type_tokens[0]}")

        base_web_bucket = self._normalize_text(self._lead_web_bucket(base_lead))
        candidate_web_bucket = self._normalize_text(self._lead_web_bucket(candidate))
        if base_web_bucket and candidate_web_bucket and base_web_bucket == candidate_web_bucket:
            score += 12
            reasons.append("same website bucket")

        base_failure = self._normalize_text(self._lead_web_failure(base_lead))
        candidate_failure = self._normalize_text(self._lead_web_failure(candidate))
        if base_failure and candidate_failure and base_failure == candidate_failure:
            score += 8
            reasons.append("same website failure pattern")

        base_review = self._normalize_text(self._lead_review_bucket(base_lead))
        candidate_review = self._normalize_text(self._lead_review_bucket(candidate))
        if base_review and candidate_review and base_review == candidate_review:
            score += 6
            reasons.append("same review bucket")

        base_reality = self._normalize_text(self._lead_business_reality(base_lead))
        candidate_reality = self._normalize_text(self._lead_business_reality(candidate))
        if base_reality and candidate_reality and base_reality == candidate_reality:
            score += 6
            reasons.append("same business reality")

        base_contact = self._lead_contact_profile(base_lead)
        candidate_contact = self._lead_contact_profile(candidate)
        if base_contact != "None" and candidate_contact == base_contact:
            score += 4
            reasons.append("same contact setup")

        shared_triggers = sorted(self._lead_trigger_labels(base_lead) & self._lead_trigger_labels(candidate))
        if shared_triggers:
            trigger_points = min(12, 4 * len(shared_triggers))
            score += trigger_points
            reasons.append(f"shared trigger signals: {', '.join(shared_triggers[:2])}")

        score_gap = abs(self._lead_score(base_lead) - self._lead_score(candidate))
        if score_gap <= 5:
            score += 6
            reasons.append("very close lead score")
        elif score_gap <= 10:
            score += 4
            reasons.append("close lead score")
        elif score_gap <= 20:
            score += 2
            reasons.append("similar lead score band")

        if not has_vertical_match:
            score = min(score, 24)

        deduped_reasons = list(dict.fromkeys(reason for reason in reasons if reason))
        return score, deduped_reasons

    def list_similar_leads(
        self,
        lead_key: str,
        *,
        limit: int = 8,
        run_id: int | None = None,
    ) -> list[dict[str, Any]]:
        self.ensure_ready()
        base_lead = self.get_lead(lead_key)
        candidates = self.list_leads(run_id=run_id)
        similar: list[dict[str, Any]] = []
        for candidate in candidates:
            candidate_key = str(candidate.get("lead_key", ""))
            if not candidate_key or candidate_key == lead_key:
                continue
            score, reasons = self._score_similarity(base_lead, candidate)
            if score < 26 or not reasons:
                continue
            if score >= 58:
                level = "Very close"
            elif score >= 42:
                level = "Strong"
            else:
                level = "Good"
            similar.append(
                {
                    "lead_key": candidate_key,
                    "business_name": str(candidate.get("business_name", "")),
                    "city_area": str(candidate.get("city_area", "")),
                    "business_type": self._lead_value(candidate, "Business Type"),
                    "website_bucket": self._lead_web_bucket(candidate),
                    "website_failure": self._lead_web_failure(candidate),
                    "review_bucket": self._lead_review_bucket(candidate),
                    "last_lead_score": self._lead_score(candidate),
                    "contact_profile": self._lead_contact_profile(candidate),
                    "pipeline_status": str(candidate.get("pipeline_status", "")),
                    "ready_to_contact": bool(candidate.get("ready_to_contact")),
                    "lead_signal": str(candidate.get("lead_signal", "")),
                    "actionable": bool(candidate.get("actionable")),
                    "opportunity_brief": self._lead_value(candidate, "Opportunity Brief"),
                    "trigger_count": int(candidate.get("trigger_count", 0) or 0),
                    "top_trigger_label": str(candidate.get("top_trigger_label", "")),
                    "top_trigger_strength": str(candidate.get("top_trigger_strength", "")),
                    "why_now_summary": str(candidate.get("why_now_summary", "")),
                    "trigger_priority": str(candidate.get("trigger_priority", "")),
                    "similarity_score": score,
                    "similarity_level": level,
                    "similarity_reasons": reasons,
                    "similarity_summary": "; ".join(reasons[:4]),
                }
            )

        similar.sort(
            key=lambda item: (
                -int(item.get("similarity_score", 0)),
                -int(item.get("last_lead_score", 0)),
                str(item.get("business_name", "")).lower(),
            )
        )
        return similar[: max(1, int(limit))]

    def get_latest_audit(self, lead_key: str) -> dict[str, Any]:
        self.ensure_ready()
        with self._managed_connection() as conn:
            latest = self._latest_audits_for_keys(conn, [lead_key])
        return latest.get(str(lead_key or "").strip(), {})

    def list_trigger_events(self, lead_key: str, limit: int = 8) -> list[dict[str, Any]]:
        self.ensure_ready()
        with self._managed_connection() as conn:
            rows = conn.execute(
                """
                SELECT trigger_type, trigger_label, trigger_strength, observed_at, summary, details_json
                FROM trigger_events
                WHERE lead_key = ?
                ORDER BY observed_at DESC, id DESC
                LIMIT ?
                """,
                (lead_key, max(1, int(limit))),
            ).fetchall()

        events: list[dict[str, Any]] = []
        for row in rows:
            events.append(
                self._hydrate_trigger_event(
                    trigger_type=row[0],
                    trigger_label=row[1],
                    trigger_strength=row[2],
                    observed_at=row[3],
                    summary=row[4],
                    details_json=row[5],
                )
            )
        return events

    def get_lead(self, lead_key: str) -> dict[str, Any]:
        self.ensure_ready()
        with self._managed_connection() as conn:
            row = conn.execute(
                """
                SELECT
                    lh.lead_key,
                    lh.business_name,
                    lh.address,
                    lh.city_area,
                    lh.last_seed_source,
                    lh.first_seen_at,
                    lh.last_seen_at,
                    lh.last_web_presence_status,
                    lh.last_lead_score,
                    lh.data_json,
                    COALESCE(ts.pipeline_status, 'Needs review') AS pipeline_status,
                    COALESCE(ts.ready_to_contact, 0) AS ready_to_contact,
                    COALESCE(ts.do_not_contact, 0) AS do_not_contact,
                    COALESCE(ts.lead_owner, '') AS lead_owner,
                    COALESCE(ts.next_action, '') AS next_action,
                    COALESCE(ts.lead_signal, '') AS lead_signal,
                    COALESCE(ts.work_bucket, '') AS work_bucket,
                    COALESCE(ts.tags, '') AS tags,
                    COALESCE(ts.opportunity_summary, '') AS opportunity_summary,
                    COALESCE(ts.personalization_notes, '') AS personalization_notes,
                    COALESCE(ts.outreach_angle, '') AS outreach_angle,
                    COALESCE(ts.draft_message, '') AS draft_message,
                    COALESCE(ts.updated_at, '') AS updated_at,
                    (SELECT COUNT(*) FROM run_leads rl WHERE rl.lead_key = lh.lead_key) AS run_count
                FROM lead_history lh
                LEFT JOIN lead_tracker_state ts ON ts.lead_key = lh.lead_key
                WHERE lh.lead_key = ?
                """,
                (lead_key,),
            ).fetchone()

        if not row:
            raise LeadVaultError("Lead not found.")

        payload = json.loads(row[9] or "{}")
        latest_audit = self.get_latest_audit(lead_key)
        trigger_events = self.list_trigger_events(lead_key)
        lead = {
            "lead_key": row[0],
            "business_name": row[1] or "",
            "address": row[2] or "",
            "city_area": row[3] or "",
            "last_seed_source": row[4] or "",
            "first_seen_at": row[5] or "",
            "last_seen_at": row[6] or "",
            "last_web_presence_status": row[7] or "",
            "last_lead_score": row[8] or 0,
            "data": payload,
            "pipeline_status": row[10],
            "ready_to_contact": bool(row[11]),
            "do_not_contact": bool(row[12]),
            "lead_owner": row[13] or "",
            "next_action": row[14] or "",
            "lead_signal": row[15] or "",
            "work_bucket": row[16] or "",
            "tags": row[17] or "",
            "opportunity_summary": row[18] or "",
            "personalization_notes": row[19] or "",
            "outreach_angle": row[20] or "",
            "draft_message": row[21] or "",
            "updated_at": row[22] or "",
            "run_count": row[23] or 0,
            "latest_audit": latest_audit,
            "trigger_events": trigger_events,
        }
        lead.update(self._resolved_trigger_intel(lead))
        lead.update(self._resolved_confidence_freshness(lead))
        web_intel = self._resolved_web_intel(lead)
        lead["pitch_family"] = str(web_intel.get("pitch_family", ""))

        # ── Expose backend grading fields at top level ──
        lead["website_quality_score"] = int(payload.get("Website Quality Score") or 0)
        lead["website_grade"] = str(payload.get("Website Grade", ""))
        lead["quality_score"] = int(payload.get("Quality Score") or 0)
        lead["audit_confidence_score"] = int(payload.get("Audit Confidence Score") or 0)
        lead["inner_pages_checked"] = int(payload.get("Inner Pages Checked") or 0)
        lead["discovery_sources"] = str(payload.get("Discovery Sources", ""))
        lead["opportunity_score"] = int(payload.get("Opportunity Score") or 0)
        lead["opportunity_label"] = str(payload.get("Opportunity Label", ""))
        lead["review_bucket"] = str(payload.get("Review Bucket", ""))
        lead["opportunity_breakdown"] = str(payload.get("Opportunity Breakdown", ""))
        opp_label = lead["opportunity_label"]
        opp_breakdown = lead["opportunity_breakdown"]
        lead["suppressed"] = "strong site" in opp_label.lower() or "suppressor" in opp_breakdown.lower()
        lead["disqualified"] = "DISQUALIFIED" in opp_breakdown

        # ── Agent review (from latest audit row) ──
        agent_review_json = latest_audit.get("agent_review_json", "")
        agent_review_status = latest_audit.get("agent_review_status", "")
        agent_review = {}
        if agent_review_json:
            try:
                agent_review = json.loads(agent_review_json)
            except (json.JSONDecodeError, TypeError):
                pass
        lead["agent_review"] = agent_review
        lead["agent_review_status"] = agent_review_status
        lead["agent_review_model"] = latest_audit.get("agent_review_model", "")
        lead["agent_review_updated_at"] = latest_audit.get("agent_review_updated_at", "")
        lead["agent_review_input_hash"] = latest_audit.get("agent_review_input_hash", "")

        # If agent suppresses, mark it
        if agent_review.get("suppress_opportunity"):
            lead["agent_suppressed"] = True
        else:
            lead["agent_suppressed"] = False

        return lead

    def save_tracker_state(self, lead_key: str, values: dict[str, Any]) -> None:
        self.ensure_ready()
        now = datetime.now().isoformat(timespec="seconds")
        with self._managed_connection() as conn:
            # Read existing row so callers that send a partial field set
            # (e.g. saveWorkflow in the UI) don't blank out columns they
            # didn't include in the request.
            cur = conn.cursor()
            cur.row_factory = sqlite3.Row
            row = cur.execute(
                "SELECT * FROM lead_tracker_state WHERE lead_key = ?",
                (lead_key,),
            ).fetchone()
            if row:
                existing = dict(row)
            else:
                existing = {}

            def _val(key: str, default: str = ""):
                """Return the request value if explicitly provided, else the existing DB value."""
                if key in values:
                    return values[key]
                return existing.get(key, default)

            conn.execute(
                """
                INSERT INTO lead_tracker_state (
                    lead_key,
                    pipeline_status,
                    ready_to_contact,
                    do_not_contact,
                    lead_owner,
                    next_action,
                    lead_signal,
                    work_bucket,
                    tags,
                    opportunity_summary,
                    personalization_notes,
                    outreach_angle,
                    draft_message,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(lead_key) DO UPDATE SET
                    pipeline_status=excluded.pipeline_status,
                    ready_to_contact=excluded.ready_to_contact,
                    do_not_contact=excluded.do_not_contact,
                    lead_owner=excluded.lead_owner,
                    next_action=excluded.next_action,
                    lead_signal=excluded.lead_signal,
                    work_bucket=excluded.work_bucket,
                    tags=excluded.tags,
                    opportunity_summary=excluded.opportunity_summary,
                    personalization_notes=excluded.personalization_notes,
                    outreach_angle=excluded.outreach_angle,
                    draft_message=excluded.draft_message,
                    updated_at=excluded.updated_at
                """,
                (
                    lead_key,
                    _val("pipeline_status") or "Needs review",
                    1 if _val("ready_to_contact") else 0,
                    1 if _val("do_not_contact") else 0,
                    _val("lead_owner"),
                    _val("next_action"),
                    _val("lead_signal"),
                    _val("work_bucket"),
                    _val("tags"),
                    _val("opportunity_summary"),
                    _val("personalization_notes"),
                    _val("outreach_angle"),
                    _val("draft_message"),
                    now,
                ),
            )

    def list_activity(self, lead_key: str) -> list[dict[str, Any]]:
        self.ensure_ready()
        with self._managed_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, created_at, activity_type, summary, details
                FROM lead_activity_log
                WHERE lead_key = ?
                ORDER BY created_at DESC, id DESC
                """,
                (lead_key,),
            ).fetchall()
        return [
            {
                "id": row[0],
                "created_at": row[1],
                "activity_type": row[2],
                "summary": row[3],
                "details": row[4],
            }
            for row in rows
        ]

    def add_activity(self, lead_key: str, activity_type: str, summary: str, details: str) -> None:
        self.ensure_ready()
        cleaned_summary = summary.strip()
        if not cleaned_summary:
            raise LeadVaultError("Add a short activity summary before saving.")
        with self._managed_connection() as conn:
            conn.execute(
                """
                INSERT INTO lead_activity_log (lead_key, created_at, activity_type, summary, details)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    lead_key,
                    datetime.now().isoformat(timespec="seconds"),
                    activity_type or "General",
                    cleaned_summary,
                    details.strip(),
                ),
            )

    # ── Agent Review persistence ──────────────────────────────────

    def save_agent_review(
        self,
        lead_key: str,
        review_json: str,
        status: str,
        model: str,
        input_hash: str,
    ) -> None:
        """Persist an agent review result onto the latest opportunity_audit row."""
        self.ensure_ready()
        now = datetime.now().isoformat(timespec="seconds")
        with self._managed_connection() as conn:
            conn.execute(
                """
                UPDATE opportunity_audits
                SET agent_review_json = ?,
                    agent_review_status = ?,
                    agent_review_model = ?,
                    agent_review_updated_at = ?,
                    agent_review_input_hash = ?
                WHERE id = (
                    SELECT id FROM opportunity_audits
                    WHERE lead_key = ?
                    ORDER BY audited_at DESC, id DESC
                    LIMIT 1
                )
                """,
                (review_json, status, model, now, input_hash, lead_key),
            )

    def get_agent_review(self, lead_key: str) -> dict[str, Any]:
        """Load the agent review from the latest audit row. Returns empty dict if none."""
        audit = self.get_latest_audit(lead_key)
        review_json = audit.get("agent_review_json", "")
        if not review_json:
            return {}
        try:
            return json.loads(review_json)
        except (json.JSONDecodeError, TypeError):
            return {}

    # ── Outreach Draft persistence ───────────────────────────────

    def save_outreach_draft(self, draft_dict: dict[str, Any]) -> int:
        """Save an outreach draft and return its ID."""
        self.ensure_ready()
        with self._managed_connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO outreach_drafts (
                    lead_key, business_name, recipient_email,
                    subject, body_plain, body_html,
                    preview_url, preview_file_path,
                    export_channel, export_status, export_error,
                    generated_at, exported_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    draft_dict.get("lead_key", ""),
                    draft_dict.get("business_name", ""),
                    draft_dict.get("recipient_email", ""),
                    draft_dict.get("subject", ""),
                    draft_dict.get("body_plain", ""),
                    draft_dict.get("body_html", ""),
                    draft_dict.get("preview_url", ""),
                    draft_dict.get("preview_file_path", ""),
                    draft_dict.get("export_channel", ""),
                    draft_dict.get("export_status", "pending"),
                    draft_dict.get("export_error", ""),
                    draft_dict.get("generated_at", ""),
                    draft_dict.get("exported_at", ""),
                ),
            )
            return cur.lastrowid

    def update_outreach_draft_status(
        self, draft_id: int, status: str, channel: str = "", error: str = ""
    ) -> None:
        """Update export status on an outreach draft."""
        self.ensure_ready()
        now = datetime.now().isoformat(timespec="seconds")
        with self._managed_connection() as conn:
            conn.execute(
                """
                UPDATE outreach_drafts
                SET export_status = ?, export_channel = ?, export_error = ?, exported_at = ?
                WHERE id = ?
                """,
                (status, channel, error, now, draft_id),
            )

    def list_outreach_drafts(self, lead_key: str) -> list[dict[str, Any]]:
        """List outreach drafts for a lead, newest first."""
        self.ensure_ready()
        with self._managed_connection() as conn:
            cur = conn.cursor()
            cur.row_factory = sqlite3.Row
            rows = cur.execute(
                """
                SELECT * FROM outreach_drafts
                WHERE lead_key = ?
                ORDER BY generated_at DESC, id DESC
                """,
                (lead_key,),
            ).fetchall()
        return [dict(row) for row in rows]
