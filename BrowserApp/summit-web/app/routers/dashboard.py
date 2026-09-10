from __future__ import annotations

import sqlite3
from fastapi import APIRouter

from app.config import resolve_db_path

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/stats")
async def dashboard_stats():
    db_path = resolve_db_path()
    if not db_path.exists():
        return {"total_leads": 0, "actionable": 0, "pipeline": {}, "web_buckets": {}, "recent_runs": []}

    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        total = conn.execute("SELECT COUNT(*) FROM lead_history").fetchone()[0]

        actionable = 0
        try:
            rows = conn.execute(
                "SELECT data_json FROM lead_history"
            ).fetchall()
            import json
            for row in rows:
                try:
                    data = json.loads(row[0]) if row[0] else {}
                    if data.get("Phone") or data.get("Email"):
                        actionable += 1
                except (json.JSONDecodeError, TypeError):
                    pass
        except Exception:
            pass

        pipeline = {}
        try:
            for row in conn.execute(
                "SELECT COALESCE(pipeline_status, 'Needs review') as ps, COUNT(*) as cnt "
                "FROM lead_tracker_state GROUP BY ps ORDER BY cnt DESC"
            ).fetchall():
                pipeline[row["ps"]] = row["cnt"]
        except Exception:
            pass

        web_buckets = {}
        try:
            for row in conn.execute(
                "SELECT website_bucket, COUNT(DISTINCT lead_key) as cnt "
                "FROM opportunity_audits WHERE website_bucket != '' "
                "GROUP BY website_bucket ORDER BY cnt DESC"
            ).fetchall():
                web_buckets[row["website_bucket"]] = row["cnt"]
        except Exception:
            pass

        recent_runs = []
        try:
            for row in conn.execute(
                "SELECT id, started_at, finished_at, status, seed_mode, "
                "(SELECT COUNT(*) FROM run_leads WHERE run_id = runs.id) as lead_count "
                "FROM runs ORDER BY id DESC LIMIT 10"
            ).fetchall():
                recent_runs.append(dict(row))
        except Exception:
            pass

        return {
            "total_leads": total,
            "actionable": actionable,
            "pipeline": pipeline,
            "web_buckets": web_buckets,
            "recent_runs": recent_runs,
        }
    finally:
        conn.close()
