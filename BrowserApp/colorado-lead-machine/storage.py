from __future__ import annotations

"""Storage and run-report helpers for the Colorado lead machine."""

from contextlib import contextmanager
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from shared_schema import ensure_column as ensure_schema_column, ensure_shared_schema
from trigger_detection import TRIGGER_VERSION
from website_audit import AUDIT_VERSION

if TYPE_CHECKING:
    from lead_machine import LeadMachine


def ensure_storage_ready(machine: "LeadMachine") -> None:
    machine.config.save_path.mkdir(parents=True, exist_ok=True)
    machine.config.run_reports_dir.mkdir(parents=True, exist_ok=True)
    machine.initialize_database()


@contextmanager
def connect_db(machine: "LeadMachine"):
    conn = sqlite3.connect(machine.config.database_path, timeout=30)
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def initialize_database(machine: "LeadMachine") -> None:
    if machine._db_initialized:
        return
    with machine._connect_db() as conn:
        ensure_shared_schema(conn)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS saved_scans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                config_json TEXT NOT NULL,
                seed_mode TEXT NOT NULL DEFAULT '',
                search_areas_json TEXT NOT NULL DEFAULT '[]',
                schedule_json TEXT NOT NULL DEFAULT '',
                is_active INTEGER NOT NULL DEFAULT 1,
                last_run_at TEXT NOT NULL DEFAULT '',
                last_result_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        machine.ensure_column(conn, "saved_scans", "last_run_id", "INTEGER NOT NULL DEFAULT 0")
        machine.ensure_column(conn, "saved_scans", "last_new_count", "INTEGER NOT NULL DEFAULT 0")
        machine.ensure_column(conn, "saved_scans", "last_removed_count", "INTEGER NOT NULL DEFAULT 0")
        machine.ensure_column(conn, "saved_scans", "last_changed_count", "INTEGER NOT NULL DEFAULT 0")
        machine.ensure_column(conn, "saved_scans", "last_monitor_json", "TEXT NOT NULL DEFAULT ''")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_saved_scans_name ON saved_scans(name COLLATE NOCASE)"
        )
    machine._db_initialized = True


def ensure_column(machine: "LeadMachine", conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    ensure_schema_column(conn, table, column, definition)


def hydrate_saved_scan_summary_row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": int(row[0] or 0),
        "name": str(row[1] or ""),
        "seed_mode": str(row[2] or ""),
        "is_active": bool(row[3]),
        "last_run_at": str(row[4] or ""),
        "last_result_count": int(row[5] or 0),
        "created_at": str(row[6] or ""),
        "updated_at": str(row[7] or ""),
        "last_run_id": int(row[8] or 0),
        "last_new_count": int(row[9] or 0),
        "last_removed_count": int(row[10] or 0),
        "last_changed_count": int(row[11] or 0),
    }


def hydrate_saved_scan_detail_row(row: tuple[Any, ...]) -> dict[str, Any]:
    try:
        config = json.loads(row[2] or "{}")
    except Exception:
        config = {}
    try:
        search_areas = json.loads(row[4] or "[]")
    except Exception:
        search_areas = []
    try:
        last_monitor = json.loads(row[15] or "{}")
    except Exception:
        last_monitor = {}
    return {
        "id": int(row[0] or 0),
        "name": str(row[1] or ""),
        "config": config if isinstance(config, dict) else {},
        "seed_mode": str(row[3] or ""),
        "search_areas": list(search_areas) if isinstance(search_areas, list) else [],
        "schedule_json": str(row[5] or ""),
        "is_active": bool(row[6]),
        "last_run_at": str(row[7] or ""),
        "last_result_count": int(row[8] or 0),
        "created_at": str(row[9] or ""),
        "updated_at": str(row[10] or ""),
        "last_run_id": int(row[11] or 0),
        "last_new_count": int(row[12] or 0),
        "last_removed_count": int(row[13] or 0),
        "last_changed_count": int(row[14] or 0),
        "last_monitor": last_monitor if isinstance(last_monitor, dict) else {},
    }


def list_saved_scan_summaries(machine: "LeadMachine") -> list[dict[str, Any]]:
    machine.ensure_storage_ready()
    with machine._connect_db() as conn:
        rows = conn.execute(
            """
            SELECT id, name, seed_mode, is_active, last_run_at, last_result_count,
                   created_at, updated_at, last_run_id, last_new_count,
                   last_removed_count, last_changed_count
            FROM saved_scans
            ORDER BY updated_at DESC, id DESC
            """
        ).fetchall()
    return [machine._hydrate_saved_scan_summary_row(row) for row in rows]


def get_saved_scan(machine: "LeadMachine", scan_id: int) -> dict[str, Any] | None:
    machine.ensure_storage_ready()
    with machine._connect_db() as conn:
        row = conn.execute(
            """
            SELECT id, name, config_json, seed_mode, search_areas_json, schedule_json,
                   is_active, last_run_at, last_result_count, created_at, updated_at,
                   last_run_id, last_new_count, last_removed_count, last_changed_count, last_monitor_json
            FROM saved_scans
            WHERE id = ?
            """,
            (int(scan_id),),
        ).fetchone()
    if not row:
        return None
    return machine._hydrate_saved_scan_detail_row(row)


def list_saved_scans(machine: "LeadMachine") -> list[dict]:
    machine.ensure_storage_ready()
    with machine._connect_db() as conn:
        rows = conn.execute(
            """
            SELECT id, name, config_json, seed_mode, search_areas_json, schedule_json,
                   is_active, last_run_at, last_result_count, created_at, updated_at,
                   last_run_id, last_new_count, last_removed_count, last_changed_count, last_monitor_json
            FROM saved_scans
            ORDER BY updated_at DESC, id DESC
            """
        ).fetchall()
    return [machine._hydrate_saved_scan_detail_row(row) for row in rows]


def set_saved_scan_active(machine: "LeadMachine", scan_id: int, is_active: bool) -> None:
    machine.ensure_storage_ready()
    with machine._connect_db() as conn:
        conn.execute(
            """
            UPDATE saved_scans
            SET is_active = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                1 if is_active else 0,
                datetime.now().isoformat(timespec="seconds"),
                int(scan_id),
            ),
        )


def save_saved_scan(machine: "LeadMachine", name: str, payload: dict, scan_id: int | None = None) -> int:
    cleaned_name = str(name).strip()
    if not cleaned_name:
        from lead_machine import LeadMachineError

        raise LeadMachineError("Saved scan name cannot be blank.")
    machine.ensure_storage_ready()
    now = datetime.now().isoformat(timespec="seconds")
    serializable_payload = dict(payload)
    seed_mode = str(serializable_payload.get("seed_mode", "")).strip()
    search_areas = serializable_payload.get("search_areas", [])
    if not isinstance(search_areas, list):
        search_areas = []
    config_json = json.dumps(serializable_payload, sort_keys=True)
    search_areas_json = json.dumps(search_areas)
    with machine._connect_db() as conn:
        if scan_id is None:
            cursor = conn.execute(
                """
                INSERT INTO saved_scans (
                    name, config_json, seed_mode, search_areas_json,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    cleaned_name,
                    config_json,
                    seed_mode,
                    search_areas_json,
                    now,
                    now,
                ),
            )
            return int(cursor.lastrowid)
        conn.execute(
            """
            UPDATE saved_scans
            SET name = ?, config_json = ?, seed_mode = ?, search_areas_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                cleaned_name,
                config_json,
                seed_mode,
                search_areas_json,
                now,
                scan_id,
            ),
        )
    return int(scan_id)


def delete_saved_scan(machine: "LeadMachine", scan_id: int) -> None:
    machine.ensure_storage_ready()
    with machine._connect_db() as conn:
        conn.execute("DELETE FROM saved_scans WHERE id = ?", (scan_id,))


def list_recent_runs(machine: "LeadMachine", limit: int = 12) -> list[dict]:
    machine.ensure_storage_ready()
    with machine._connect_db() as conn:
        rows = conn.execute(
            """
            SELECT r.id, r.started_at, r.finished_at, r.status, r.seed_mode, r.search_areas_json,
                   r.output_file, r.report_json, r.saved_scan_id, r.run_reason, COALESCE(ss.name, '')
            FROM runs r
            LEFT JOIN saved_scans ss ON ss.id = r.saved_scan_id
            ORDER BY r.id DESC
            LIMIT ?
            """,
            (max(1, int(limit)),),
        ).fetchall()
    recent_runs: list[dict] = []
    for row in rows:
        try:
            search_areas = json.loads(row[5] or "[]")
        except Exception:
            search_areas = []
        try:
            report = json.loads(row[7] or "{}")
        except Exception:
            report = {}
        summary = report.get("summary", {}) if isinstance(report, dict) else {}
        monitor = report.get("monitor", {}) if isinstance(report, dict) else {}
        recent_runs.append(
            {
                "id": int(row[0]),
                "started_at": str(row[1] or ""),
                "finished_at": str(row[2] or ""),
                "status": str(row[3] or ""),
                "seed_mode": str(row[4] or ""),
                "search_areas": list(search_areas) if isinstance(search_areas, list) else [],
                "output_file": str(row[6] or ""),
                "report": report if isinstance(report, dict) else {},
                "summary": summary if isinstance(summary, dict) else {},
                "monitor": monitor if isinstance(monitor, dict) else {},
                "saved_scan_id": int(row[8] or 0),
                "run_reason": str(row[9] or ""),
                "saved_scan_name": str(row[10] or ""),
            }
        )
    return recent_runs


def build_saved_scan_payload_from_run(
    machine: "LeadMachine",
    run: dict,
    *,
    output_folder: str = "",
    skip_email_lookup: bool | None = None,
) -> dict:
    report = run.get("report", {}) if isinstance(run, dict) else {}
    if not isinstance(report, dict):
        report = {}
    areas = run.get("search_areas", [])
    if not isinstance(areas, list):
        areas = []
    payload = {
        "seed_mode": str(report.get("seed_mode") or run.get("seed_mode") or "Hybrid"),
        "output_folder": str(output_folder or machine.config.save_path),
        "min_rating": float(report.get("min_rating", machine.config.min_rating) or machine.config.min_rating),
        "min_reviews": int(report.get("min_reviews", machine.config.min_reviews) or machine.config.min_reviews),
        "min_business_age_days": int(
            report.get("min_business_age_days", machine.config.min_business_age_days) or machine.config.min_business_age_days
        ),
        "tile_grid_size": int(report.get("tile_grid_size", machine.config.tile_grid_size) or machine.config.tile_grid_size),
        "fast_test_mode": bool(report.get("fast_test_mode", machine.config.fast_test_mode)),
        "fast_test_lead_limit": int(
            report.get("fast_test_lead_limit", machine.config.fast_test_lead_limit) or machine.config.fast_test_lead_limit
        ),
        "fast_test_total_run_cap": machine._int_or_none(
            report.get("fast_test_total_run_cap", machine.config.fast_test_total_run_cap)
        ),
        "skip_email_lookup": machine.config.skip_email_lookup if skip_email_lookup is None else bool(skip_email_lookup),
        "enable_builtwith_checks": bool(machine.config.enable_builtwith_checks),
        "builtwith_run_cap": int(machine.config.builtwith_run_cap or 0),
        "search_areas": [str(area) for area in areas],
    }
    return payload


def get_run_report(machine: "LeadMachine", run_id: int | None = None) -> dict:
    machine.ensure_storage_ready()
    with machine._connect_db() as conn:
        if run_id is None:
            row = conn.execute(
                """
                SELECT report_json
                FROM runs
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT report_json
                FROM runs
                WHERE id = ?
                """,
                (run_id,),
            ).fetchone()
    if not row or not row[0]:
        return {}
    try:
        payload = json.loads(row[0])
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def load_targeted_leads(machine: "LeadMachine", lead_keys: list[str]) -> list[dict]:
    unique_keys: list[str] = []
    seen: set[str] = set()
    for lead_key in lead_keys:
        cleaned_key = str(lead_key or "").strip()
        if cleaned_key and cleaned_key not in seen:
            unique_keys.append(cleaned_key)
            seen.add(cleaned_key)
    if not unique_keys:
        return []
    placeholders = ", ".join("?" for _ in unique_keys)
    machine.ensure_storage_ready()
    with machine._connect_db() as conn:
        rows = conn.execute(
            f"""
            SELECT lead_key, data_json
            FROM lead_history
            WHERE lead_key IN ({placeholders})
            """,
            tuple(unique_keys),
        ).fetchall()
    payload_by_key: dict[str, dict] = {}
    for row in rows:
        try:
            payload = json.loads(row[1] or "{}")
        except Exception:
            continue
        if isinstance(payload, dict):
            payload_by_key[str(row[0])] = dict(payload)
    leads: list[dict] = []
    for lead_key in unique_keys:
        payload = payload_by_key.get(lead_key)
        if not payload:
            continue
        payload["_stored_lead_key"] = lead_key
        leads.append(payload)
    return leads


def list_run_preview(machine: "LeadMachine", run_id: int | None = None, limit: int = 25) -> list[dict]:
    machine.ensure_storage_ready()
    with machine._connect_db() as conn:
        target_run_id = run_id
        if target_run_id is None:
            row = conn.execute("SELECT id FROM runs ORDER BY id DESC LIMIT 1").fetchone()
            if not row:
                return []
            target_run_id = int(row[0])
        rows = conn.execute(
            """
            SELECT lh.data_json
            FROM run_leads rl
            JOIN lead_history lh ON lh.lead_key = rl.lead_key
            WHERE rl.run_id = ?
            ORDER BY COALESCE(lh.last_opportunity_score, 0) DESC, COALESCE(lh.last_lead_score, 0) DESC, lh.business_name COLLATE NOCASE ASC
            LIMIT ?
            """,
            (target_run_id, max(1, int(limit))),
        ).fetchall()
    preview: list[dict] = []
    for row in rows:
        try:
            lead = json.loads(row[0] or "{}")
        except Exception:
            continue
        if isinstance(lead, dict):
            preview.append(lead)
    return preview


def start_run_record(machine: "LeadMachine", saved_scan_id: int | None = None, run_reason: str = "manual") -> None:
    started_at = datetime.now().isoformat(timespec="seconds")
    machine.current_saved_scan_id = saved_scan_id
    machine.current_run_reason = str(run_reason or "manual")
    machine.run_report = {
        "started_at": started_at,
        "seed_mode": machine.config.seed_mode,
        "search_areas": list(machine.config.search_areas),
        "saved_scan_id": saved_scan_id or 0,
        "run_reason": machine.current_run_reason,
        "tile_grid_size": machine.config.tile_grid_size,
        "fast_test_mode": machine.config.fast_test_mode,
        "fast_test_lead_limit": machine.config.fast_test_lead_limit,
        "fast_test_total_run_cap": machine.fast_test_total_run_cap(),
        "min_rating": machine.config.min_rating,
        "min_reviews": machine.config.min_reviews,
        "min_business_age_days": machine.config.min_business_age_days,
        "enable_builtwith_checks": bool(machine.config.enable_builtwith_checks),
        "builtwith_run_cap": int(machine.config.builtwith_run_cap or 0),
        "target_pool_name": machine.config.target_pool_name,
        "target_lead_count": len(machine.config.target_lead_keys),
        "stages": {},
        "summary": {},
    }
    with machine._connect_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO runs (started_at, status, seed_mode, search_areas_json)
            VALUES (?, ?, ?, ?)
            """,
            (
                started_at,
                "running",
                machine.config.seed_mode,
                json.dumps(machine.config.search_areas),
            ),
        )
        machine.current_run_id = int(cursor.lastrowid)
        conn.execute(
            """
            UPDATE runs
            SET saved_scan_id = ?, run_reason = ?
            WHERE id = ?
            """,
            (
                saved_scan_id,
                machine.current_run_reason,
                machine.current_run_id,
            ),
        )


def record_stage_report(machine: "LeadMachine", stage_key: str, label: str, **metrics: object) -> None:
    stages = machine.run_report.setdefault("stages", {})
    stages[stage_key] = {
        "label": label,
        "metrics": metrics,
    }


def finalize_run_summary(
    machine: "LeadMachine",
    leads: list[dict],
    dropped_no_contact: int,
    output_file: Path,
    elapsed_seconds: int,
) -> None:
    bucket_counts: dict[str, int] = {}
    for lead in leads:
        bucket = str(lead.get("Review Bucket", "")).strip() or "Unbucketed"
        bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1

    scores = [int(lead.get("Lead Score") or 0) for lead in leads]
    average_score = round(sum(scores) / len(scores), 1) if scores else 0
    machine.run_report["summary"] = {
        "actionable_leads": len(leads),
        "dropped_no_contact": dropped_no_contact,
        "average_lead_score": average_score,
        "high_confidence": bucket_counts.get("High confidence", 0),
        "promising": bucket_counts.get("Promising", 0),
        "needs_review": bucket_counts.get("Needs review", 0),
        "output_file": str(output_file),
        "elapsed_seconds": elapsed_seconds,
    }


def write_run_report_files(machine: "LeadMachine") -> Optional[Path]:
    if machine.current_run_id is None or not machine.run_report:
        return None
    report_dir = machine.config.run_reports_dir
    latest_path = report_dir / "latest_run_report.json"
    report_path = report_dir / f"run_{machine.current_run_id}.json"
    payload = json.dumps(machine.run_report, indent=2, sort_keys=True)
    latest_path.write_text(payload, encoding="utf-8")
    report_path.write_text(payload, encoding="utf-8")
    return report_path


def finish_run_record(
    machine: "LeadMachine",
    status: str,
    output_file: Optional[Path] = None,
    error_message: str = "",
) -> None:
    if machine.current_run_id is None:
        return
    finished_at = datetime.now().isoformat(timespec="seconds")
    machine.run_report["finished_at"] = finished_at
    machine.run_report["status"] = status
    if output_file:
        machine.run_report.setdefault("summary", {})
        machine.run_report["summary"]["output_file"] = str(output_file)
    if error_message:
        machine.run_report["error_message"] = error_message
    report_path = machine.write_run_report_files()
    with machine._connect_db() as conn:
        conn.execute(
            """
            UPDATE runs
            SET finished_at = ?, status = ?, output_file = ?, report_json = ?, error_message = ?
            WHERE id = ?
            """,
            (
                finished_at,
                status,
                str(output_file) if output_file else "",
                json.dumps(machine.run_report, sort_keys=True),
                error_message,
                machine.current_run_id,
            ),
        )
        if machine.current_saved_scan_id is not None and status == "completed":
            monitor_summary = machine._build_monitor_summary(
                conn,
                int(machine.current_saved_scan_id),
                int(machine.current_run_id),
            )
            machine.run_report["monitor"] = monitor_summary
            conn.execute(
                """
                UPDATE runs
                SET report_json = ?
                WHERE id = ?
                """,
                (
                    json.dumps(machine.run_report, sort_keys=True),
                    machine.current_run_id,
                ),
            )
            conn.execute(
                """
                UPDATE saved_scans
                SET last_run_at = ?,
                    last_result_count = ?,
                    last_run_id = ?,
                    last_new_count = ?,
                    last_removed_count = ?,
                    last_changed_count = ?,
                    last_monitor_json = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    finished_at,
                    int(monitor_summary.get("latest_result_count", 0)),
                    machine.current_run_id,
                    int(monitor_summary.get("new_count", 0)),
                    int(monitor_summary.get("removed_count", 0)),
                    int(monitor_summary.get("changed_count", 0)),
                    json.dumps(monitor_summary, sort_keys=True),
                    finished_at,
                    machine.current_saved_scan_id,
                ),
            )
            report_path = machine.write_run_report_files()
    if report_path:
        machine.log(f"Run report saved: {report_path}")


def list_run_lead_keys(conn: sqlite3.Connection, run_id: int) -> list[str]:
    rows = conn.execute(
        """
        SELECT lead_key
        FROM run_leads
        WHERE run_id = ?
        """,
        (int(run_id),),
    ).fetchall()
    return [str(row[0]) for row in rows if row and row[0]]


def load_leads_for_keys(
    conn: sqlite3.Connection,
    lead_keys: set[str],
    *,
    limit: int | None = 8,
) -> list[dict]:
    cleaned_keys = [lead_key for lead_key in lead_keys if lead_key]
    if not cleaned_keys:
        return []
    placeholders = ", ".join("?" for _ in cleaned_keys)
    limit_clause = "LIMIT ?" if limit is not None else ""
    params: list[Any] = [*cleaned_keys]
    if limit is not None:
        params.append(max(1, int(limit)))
    rows = conn.execute(
        f"""
        SELECT lead_key, data_json
        FROM lead_history
        WHERE lead_key IN ({placeholders})
        ORDER BY COALESCE(last_opportunity_score, 0) DESC, COALESCE(last_lead_score, 0) DESC, business_name COLLATE NOCASE ASC
        {limit_clause}
        """,
        tuple(params),
    ).fetchall()
    leads: list[dict] = []
    for row in rows:
        try:
            payload = json.loads(row[1] or "{}")
        except Exception:
            continue
        if isinstance(payload, dict):
            payload["_stored_lead_key"] = str(row[0] or "")
            leads.append(payload)
    return leads


def build_monitor_headlines(monitor: dict[str, Any]) -> list[str]:
    previous_run_id = int(monitor.get("previous_run_id") or 0)
    if previous_run_id <= 0:
        return ["First completed monitoring baseline established for this saved scan."]

    headlines: list[str] = []
    result_delta = int(monitor.get("result_count_delta") or 0)
    if result_delta > 0:
        headlines.append(f"Result count is up by {result_delta} lead(s) vs the previous run.")
    elif result_delta < 0:
        headlines.append(f"Result count is down by {abs(result_delta)} lead(s) vs the previous run.")
    else:
        headlines.append("Result count is flat vs the previous run.")

    newly_actionable = int(monitor.get("newly_actionable_count") or 0)
    worsened = int(monitor.get("worsened_count") or 0)
    review_first = int(monitor.get("review_first_count") or 0)
    if newly_actionable:
        headlines.append(f"{newly_actionable} lead(s) became newly actionable.")
    if worsened:
        headlines.append(f"{worsened} lead(s) show worse website conditions than before.")
    if review_first:
        headlines.append(f"{review_first} lead(s) deserve review first.")
    if not newly_actionable and not worsened and not review_first:
        headlines.append("Nothing urgent changed; keep monitoring the baseline.")
    return headlines[:4]


def build_monitor_summary(machine: "LeadMachine", conn: sqlite3.Connection, saved_scan_id: int, latest_run_id: int) -> dict:
    latest_run = conn.execute(
        """
        SELECT id, started_at, finished_at, status, seed_mode
        FROM runs
        WHERE id = ?
        """,
        (int(latest_run_id),),
    ).fetchone()
    previous_run = conn.execute(
        """
        SELECT id, started_at, finished_at, status, seed_mode
        FROM runs
        WHERE saved_scan_id = ? AND status = 'completed' AND id < ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (int(saved_scan_id), int(latest_run_id)),
    ).fetchone()

    latest_keys = set(machine._list_run_lead_keys(conn, int(latest_run_id)))
    previous_keys = set(machine._list_run_lead_keys(conn, int(previous_run[0]))) if previous_run else set()
    new_keys = latest_keys - previous_keys
    removed_keys = previous_keys - latest_keys

    changed_rows = conn.execute(
        """
        SELECT DISTINCT lead_key
        FROM trigger_events
        WHERE run_id = ?
        ORDER BY lead_key
        """,
        (int(latest_run_id),),
    ).fetchall()
    changed_keys = {str(row[0]) for row in changed_rows if row and row[0]}
    changed_keys = {lead_key for lead_key in changed_keys if lead_key in latest_keys and lead_key not in new_keys}

    previous_run_id = int(previous_run[0]) if previous_run else 0
    latest_preview = machine._load_leads_for_keys(conn, latest_keys, limit=8)
    new_leads_all = machine._load_leads_for_keys(conn, new_keys, limit=None)
    removed_leads_all = machine._load_leads_for_keys(conn, removed_keys, limit=None)
    changed_leads_all = machine._load_leads_for_keys(conn, changed_keys, limit=None)
    latest_audits = machine._load_run_audits(conn, int(latest_run_id), latest_keys)
    previous_audits = machine._load_run_audits(conn, previous_run_id, previous_keys) if previous_run_id else {}
    trigger_events = machine._load_trigger_events_for_run(conn, int(latest_run_id), changed_keys)

    new_leads = [
        machine._build_monitor_preview_lead(
            lead,
            change_kind="new",
            latest_audit=latest_audits.get(str(lead.get("_stored_lead_key", "")).strip()),
        )
        for lead in new_leads_all
    ]
    removed_leads = [
        machine._build_monitor_preview_lead(
            lead,
            change_kind="removed",
            previous_audit=previous_audits.get(str(lead.get("_stored_lead_key", "")).strip()),
        )
        for lead in removed_leads_all
    ]
    changed_leads = [
        machine._build_monitor_preview_lead(
            lead,
            change_kind="changed",
            latest_audit=latest_audits.get(str(lead.get("_stored_lead_key", "")).strip()),
            previous_audit=previous_audits.get(str(lead.get("_stored_lead_key", "")).strip()),
            trigger_events=trigger_events.get(str(lead.get("_stored_lead_key", "")).strip(), []),
        )
        for lead in changed_leads_all
    ]

    review_first_leads = [
        lead
        for lead in [*changed_leads, *new_leads, *removed_leads]
        if str(lead.get("Monitor Review Priority", "")).strip() == "Review first"
    ]
    newly_actionable_count = sum(1 for lead in [*new_leads, *changed_leads] if lead.get("Monitor Newly Actionable"))
    worsened_count = sum(1 for lead in changed_leads if lead.get("Monitor Worsened"))
    review_first_count = len(review_first_leads)
    previous_result_count = len(previous_keys)
    latest_result_count = len(latest_keys)
    result_delta = latest_result_count - previous_result_count
    if previous_result_count <= 0:
        monitor_state = "Baseline"
        usefulness = "First completed run establishes the monitoring baseline."
        relationship = "No previous completed run for this saved scan yet."
    elif review_first_count or worsened_count:
        monitor_state = "Review first"
        usefulness = "Meaningful monitoring changes deserve review before the next outreach pass."
        relationship = f"Compared to run #{previous_run_id}."
    elif len(new_keys) or len(removed_keys) or len(changed_keys):
        monitor_state = "Watching"
        usefulness = "The scan changed, but nothing stands out as urgent yet."
        relationship = f"Compared to run #{previous_run_id}."
    else:
        monitor_state = "Stable"
        usefulness = "The latest run looks steady against the previous completed run."
        relationship = f"Compared to run #{previous_run_id}."

    trend_summary = machine._monitor_trend_label(previous_result_count, latest_result_count)

    monitor = {
        "saved_scan_id": int(saved_scan_id),
        "latest_run_id": int(latest_run_id),
        "previous_run_id": previous_run_id,
        "latest_started_at": str(latest_run[1] or "") if latest_run else "",
        "latest_finished_at": str(latest_run[2] or "") if latest_run else "",
        "latest_status": str(latest_run[3] or "") if latest_run else "",
        "latest_seed_mode": str(latest_run[4] or "") if latest_run else "",
        "previous_started_at": str(previous_run[1] or "") if previous_run else "",
        "previous_finished_at": str(previous_run[2] or "") if previous_run else "",
        "previous_status": str(previous_run[3] or "") if previous_run else "",
        "previous_seed_mode": str(previous_run[4] or "") if previous_run else "",
        "latest_result_count": latest_result_count,
        "previous_result_count": previous_result_count,
        "result_count_delta": result_delta,
        "result_trend": "baseline" if previous_result_count <= 0 else ("up" if result_delta > 0 else "down" if result_delta < 0 else "flat"),
        "trend_summary": trend_summary,
        "latest_run_relationship": relationship,
        "new_count": len(new_keys),
        "removed_count": len(removed_keys),
        "changed_count": len(changed_keys),
        "newly_actionable_count": newly_actionable_count,
        "worsened_count": worsened_count,
        "review_first_count": review_first_count,
        "monitor_state": monitor_state,
        "monitor_usefulness": usefulness,
        "change_headlines": [],
        "latest_preview": latest_preview,
        "new_leads": new_leads[:8],
        "removed_leads": removed_leads[:8],
        "changed_leads": changed_leads[:8],
        "review_first_leads": review_first_leads[:8],
    }
    monitor["change_headlines"] = machine._build_monitor_headlines(monitor)
    return monitor


def get_saved_scan_monitor_report(machine: "LeadMachine", scan_id: int, preview_limit: int = 8) -> dict:
    machine.ensure_storage_ready()
    with machine._connect_db() as conn:
        latest_row = conn.execute(
            """
            SELECT id
            FROM runs
            WHERE saved_scan_id = ? AND status = 'completed'
            ORDER BY id DESC
            LIMIT 1
            """,
            (int(scan_id),),
        ).fetchone()
        if not latest_row:
            return {}
        summary = machine._build_monitor_summary(conn, int(scan_id), int(latest_row[0]))
        limit = max(1, int(preview_limit))
        summary["latest_preview"] = list(summary.get("latest_preview", []))[:limit]
        summary["new_leads"] = list(summary.get("new_leads", []))[:limit]
        summary["removed_leads"] = list(summary.get("removed_leads", []))[:limit]
        summary["changed_leads"] = list(summary.get("changed_leads", []))[:limit]
        summary["review_first_leads"] = list(summary.get("review_first_leads", []))[:limit]
        return summary


def persist_lead_history(machine: "LeadMachine", leads: list[dict]) -> None:
    if machine.current_run_id is None:
        return
    now = datetime.now().isoformat(timespec="seconds")
    with machine._connect_db() as conn:
        for lead in leads:
            stored_lead_key = str(lead.get("_stored_lead_key", "")).strip()
            lead_key = stored_lead_key or machine.make_lead_key(lead)
            previous_row = conn.execute(
                "SELECT data_json FROM lead_history WHERE lead_key = ?",
                (lead_key,),
            ).fetchone()
            previous_lead: dict | None = None
            if previous_row and previous_row[0]:
                try:
                    loaded_previous = json.loads(previous_row[0])
                except Exception:
                    loaded_previous = None
                if isinstance(loaded_previous, dict):
                    previous_lead = loaded_previous
            scorecard = machine.apply_website_opportunity_audit(lead, audited_at=now)
            trigger_events = machine.apply_trigger_detection(lead, previous_lead, observed_at=now)
            payload = json.dumps(lead)
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
                    address=excluded.address,
                    city_area=excluded.city_area,
                    last_seed_source=excluded.last_seed_source,
                    last_seen_at=excluded.last_seen_at,
                    last_web_presence_status=excluded.last_web_presence_status,
                    last_lead_score=excluded.last_lead_score,
                    last_opportunity_score=excluded.last_opportunity_score,
                    data_json=excluded.data_json
                """,
                (
                    lead_key,
                    str(lead.get("Business Name", "")),
                    str(lead.get("Address", "")),
                    str(lead.get("City/Area", "")),
                    str(lead.get("Seed Source", "")),
                    now,
                    now,
                    str(lead.get("Web Presence Status", "")),
                    int(lead.get("Lead Score") or 0),
                    int(lead.get("Opportunity Score") or 0),
                    payload,
                ),
            )
            conn.execute(
                "INSERT OR REPLACE INTO run_leads (run_id, lead_key) VALUES (?, ?)",
                (machine.current_run_id, lead_key),
            )
            retry_recommended = str(lead.get("Retry Recommended", "")).strip().lower() == "yes"
            retry_reason = (
                str(lead.get("Retry Reason", "")).strip()
                or str(lead.get("Failure Reasons", "")).strip()
                or str(lead.get("Web Presence Details", "")).strip()
                or "Retry recommended"
            )
            if retry_recommended:
                next_retry = (
                    str(lead.get("Next Retry At", "")).strip()
                    or (datetime.now() + timedelta(days=1)).isoformat(timespec="seconds")
                )
                conn.execute(
                    """
                    INSERT INTO lead_retry_queue (
                        lead_key, run_id, reason, status, attempt_count,
                        last_error, next_attempt_at, created_at, updated_at
                    )
                    VALUES (?, ?, ?, 'pending', ?, ?, ?, ?, ?)
                    ON CONFLICT(lead_key) DO UPDATE SET
                        run_id=excluded.run_id,
                        reason=excluded.reason,
                        status='pending',
                        attempt_count=lead_retry_queue.attempt_count,
                        last_error=excluded.last_error,
                        next_attempt_at=excluded.next_attempt_at,
                        updated_at=excluded.updated_at
                    """,
                    (
                        lead_key,
                        machine.current_run_id,
                        retry_reason[:500],
                        int(lead.get("Retry Count") or 0),
                        retry_reason[:500],
                        next_retry,
                        now,
                        now,
                    ),
                )
            else:
                conn.execute(
                    """
                    UPDATE lead_retry_queue
                    SET status = 'resolved', updated_at = ?
                    WHERE lead_key = ? AND status = 'pending'
                    """,
                    (now, lead_key),
                )
            conn.execute(
                """
                INSERT INTO opportunity_audits (
                    lead_key, run_id, audited_at, audit_version, website_bucket, failure_type,
                    mobile_readiness, ssl_status, page_speed_signal, contact_form_status,
                    booking_flow_status, cta_strength, seo_basics, social_dependence,
                    directory_dependence, image_quality_signal, navigation_quality,
                    primary_business_impact, best_pitch_angle, last_verified_at, data_freshness,
                    resolved_url, http_status, fetch_time_ms, page_title, meta_description,
                    word_count, form_count, internal_link_count, image_count, on_page_phones,
                    on_page_emails, cta_terms, booking_terms, viewport_meta, evidence_summary,
                    evidence_snippet,
                    issues_json, business_impact_json, audit_confidence
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    lead_key,
                    machine.current_run_id,
                    str(scorecard.get("Last Audited At", now)),
                    str(scorecard.get("Audit Version", AUDIT_VERSION)),
                    str(scorecard.get("Website Bucket", "")),
                    str(scorecard.get("Website Failure Type", "")),
                    str(scorecard.get("Mobile Readiness", "")),
                    str(scorecard.get("SSL Status", "")),
                    str(scorecard.get("Page Speed Signal", "")),
                    str(scorecard.get("Contact Form Status", "")),
                    str(scorecard.get("Booking Flow Status", "")),
                    str(scorecard.get("CTA Strength", "")),
                    str(scorecard.get("SEO Basics", "")),
                    str(scorecard.get("Social Dependence", "")),
                    str(scorecard.get("Directory Dependence", "")),
                    str(scorecard.get("Image Quality Signal", "")),
                    str(scorecard.get("Navigation Quality", "")),
                    str(scorecard.get("Primary Business Impact", "")),
                    str(scorecard.get("Best Pitch Angle", "")),
                    str(scorecard.get("Last Verified At", now)),
                    str(scorecard.get("Data Freshness", "")),
                    str(scorecard.get("Resolved Website URL", "")),
                    str(scorecard.get("HTTP Status", "")),
                    int(scorecard.get("Fetch Time Ms") or 0),
                    str(scorecard.get("Page Title", "")),
                    str(scorecard.get("Meta Description", "")),
                    int(scorecard.get("Word Count") or 0),
                    int(scorecard.get("Form Count") or 0),
                    int(scorecard.get("Internal Link Count") or 0),
                    int(scorecard.get("Image Count") or 0),
                    str(scorecard.get("On-Page Phones", "")),
                    str(scorecard.get("On-Page Emails", "")),
                    str(scorecard.get("CTA Terms", "")),
                    str(scorecard.get("Booking Terms", "")),
                    str(scorecard.get("Viewport Meta", "")),
                    str(scorecard.get("Website Evidence Summary", "")),
                    str(scorecard.get("Website Evidence Snippet", "")),
                    json.dumps(scorecard.get("Audit Issues Json", [])),
                    json.dumps(scorecard.get("Business Impact Json", [])),
                    str(scorecard.get("Audit Confidence", "")),
                ),
            )
            conn.execute(
                "DELETE FROM trigger_events WHERE run_id = ? AND lead_key = ?",
                (machine.current_run_id, lead_key),
            )
            for event in trigger_events:
                conn.execute(
                    """
                    INSERT INTO trigger_events (
                        lead_key, run_id, trigger_type, trigger_label, trigger_strength,
                        observed_at, summary, details_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        lead_key,
                        machine.current_run_id,
                        str(event.get("type", "")),
                        str(event.get("label", "")),
                        str(event.get("strength", "")),
                        str(event.get("observed_at", now)),
                        str(event.get("summary", "")),
                        json.dumps(
                            {
                                "why_now": str(event.get("why_now", "")),
                                "evidence": list(event.get("evidence", [])),
                                "version": str(event.get("version", TRIGGER_VERSION)),
                            }
                        ),
                    ),
                )


def load_monthly_usage(machine: "LeadMachine") -> int:
    month = datetime.now().strftime("%Y-%m")
    path = machine.config.usage_log_path
    if not path.exists():
        return 0
    total = 0
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith(month):
                parts = line.split(",")
                if len(parts) >= 2:
                    total += int(parts[1])
    except Exception:
        pass
    return total


def log_usage(machine: "LeadMachine", details_used: int) -> None:
    month = datetime.now().strftime("%Y-%m")
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    with machine.config.usage_log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"{month},{details_used},{stamp}\n")


def load_processed_ids(machine: "LeadMachine") -> set[str]:
    path = machine.config.processed_ids_path
    if not path.exists():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return set(payload) if isinstance(payload, list) else set()
    except Exception:
        return set()


def save_processed_ids(machine: "LeadMachine", ids: set[str]) -> None:
    try:
        machine.config.processed_ids_path.write_text(json.dumps(sorted(ids), indent=2), encoding="utf-8")
    except Exception as exc:
        machine.log(f"Could not save processed IDs: {exc}")
