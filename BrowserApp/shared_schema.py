from __future__ import annotations

import sqlite3


SHARED_TABLE_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        status TEXT NOT NULL,
        seed_mode TEXT NOT NULL,
        search_areas_json TEXT NOT NULL,
        output_file TEXT,
        report_json TEXT NOT NULL DEFAULT '',
        error_message TEXT NOT NULL DEFAULT '',
        saved_scan_id INTEGER,
        run_reason TEXT NOT NULL DEFAULT 'manual'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS lead_history (
        lead_key TEXT PRIMARY KEY,
        business_name TEXT NOT NULL,
        address TEXT,
        city_area TEXT,
        last_seed_source TEXT,
        first_seen_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL,
        last_web_presence_status TEXT,
        last_lead_score INTEGER,
        data_json TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS run_leads (
        run_id INTEGER NOT NULL,
        lead_key TEXT NOT NULL,
        PRIMARY KEY(run_id, lead_key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS lead_lists (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS lead_list_members (
        list_id INTEGER NOT NULL,
        lead_key TEXT NOT NULL,
        added_at TEXT NOT NULL,
        PRIMARY KEY (list_id, lead_key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS opportunity_audits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lead_key TEXT NOT NULL,
        run_id INTEGER,
        audited_at TEXT NOT NULL,
        audit_version TEXT NOT NULL,
        website_bucket TEXT NOT NULL DEFAULT '',
        failure_type TEXT NOT NULL DEFAULT '',
        mobile_readiness TEXT NOT NULL DEFAULT '',
        ssl_status TEXT NOT NULL DEFAULT '',
        page_speed_signal TEXT NOT NULL DEFAULT '',
        contact_form_status TEXT NOT NULL DEFAULT '',
        booking_flow_status TEXT NOT NULL DEFAULT '',
        cta_strength TEXT NOT NULL DEFAULT '',
        seo_basics TEXT NOT NULL DEFAULT '',
        social_dependence TEXT NOT NULL DEFAULT '',
        directory_dependence TEXT NOT NULL DEFAULT '',
        image_quality_signal TEXT NOT NULL DEFAULT '',
        navigation_quality TEXT NOT NULL DEFAULT '',
        primary_business_impact TEXT NOT NULL DEFAULT '',
        best_pitch_angle TEXT NOT NULL DEFAULT '',
        last_verified_at TEXT NOT NULL DEFAULT '',
        data_freshness TEXT NOT NULL DEFAULT '',
        resolved_url TEXT NOT NULL DEFAULT '',
        http_status TEXT NOT NULL DEFAULT '',
        fetch_time_ms INTEGER NOT NULL DEFAULT 0,
        page_title TEXT NOT NULL DEFAULT '',
        meta_description TEXT NOT NULL DEFAULT '',
        word_count INTEGER NOT NULL DEFAULT 0,
        form_count INTEGER NOT NULL DEFAULT 0,
        internal_link_count INTEGER NOT NULL DEFAULT 0,
        image_count INTEGER NOT NULL DEFAULT 0,
        on_page_phones TEXT NOT NULL DEFAULT '',
        on_page_emails TEXT NOT NULL DEFAULT '',
        cta_terms TEXT NOT NULL DEFAULT '',
        booking_terms TEXT NOT NULL DEFAULT '',
        viewport_meta TEXT NOT NULL DEFAULT '',
        evidence_summary TEXT NOT NULL DEFAULT '',
        evidence_snippet TEXT NOT NULL DEFAULT '',
        issues_json TEXT NOT NULL DEFAULT '',
        business_impact_json TEXT NOT NULL DEFAULT '',
        audit_confidence TEXT NOT NULL DEFAULT ''
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS trigger_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lead_key TEXT NOT NULL,
        run_id INTEGER,
        trigger_type TEXT NOT NULL,
        trigger_label TEXT NOT NULL DEFAULT '',
        trigger_strength TEXT NOT NULL DEFAULT '',
        observed_at TEXT NOT NULL,
        summary TEXT NOT NULL DEFAULT '',
        details_json TEXT NOT NULL DEFAULT ''
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS lead_retry_queue (
        lead_key TEXT PRIMARY KEY,
        run_id INTEGER,
        reason TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'pending',
        attempt_count INTEGER NOT NULL DEFAULT 0,
        last_error TEXT NOT NULL DEFAULT '',
        next_attempt_at TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
)

SHARED_COLUMN_MIGRATIONS = {
    "runs": {
        "report_json": "TEXT NOT NULL DEFAULT ''",
        "error_message": "TEXT NOT NULL DEFAULT ''",
        "saved_scan_id": "INTEGER",
        "run_reason": "TEXT NOT NULL DEFAULT 'manual'",
    },
    "opportunity_audits": {
        # Agent review columns (additive migration)
        "agent_review_json": "TEXT NOT NULL DEFAULT ''",
        "agent_review_status": "TEXT NOT NULL DEFAULT ''",
        "agent_review_model": "TEXT NOT NULL DEFAULT ''",
        "agent_review_updated_at": "TEXT NOT NULL DEFAULT ''",
        "agent_review_input_hash": "TEXT NOT NULL DEFAULT ''",
        "last_verified_at": "TEXT NOT NULL DEFAULT ''",
        "data_freshness": "TEXT NOT NULL DEFAULT ''",
        "resolved_url": "TEXT NOT NULL DEFAULT ''",
        "http_status": "TEXT NOT NULL DEFAULT ''",
        "fetch_time_ms": "INTEGER NOT NULL DEFAULT 0",
        "page_title": "TEXT NOT NULL DEFAULT ''",
        "meta_description": "TEXT NOT NULL DEFAULT ''",
        "word_count": "INTEGER NOT NULL DEFAULT 0",
        "form_count": "INTEGER NOT NULL DEFAULT 0",
        "internal_link_count": "INTEGER NOT NULL DEFAULT 0",
        "image_count": "INTEGER NOT NULL DEFAULT 0",
        "on_page_phones": "TEXT NOT NULL DEFAULT ''",
        "on_page_emails": "TEXT NOT NULL DEFAULT ''",
        "cta_terms": "TEXT NOT NULL DEFAULT ''",
        "booking_terms": "TEXT NOT NULL DEFAULT ''",
        "viewport_meta": "TEXT NOT NULL DEFAULT ''",
        "evidence_summary": "TEXT NOT NULL DEFAULT ''",
        "evidence_snippet": "TEXT NOT NULL DEFAULT ''",
        "broken_link_count": "INTEGER NOT NULL DEFAULT 0",
        "broken_links": "TEXT NOT NULL DEFAULT ''",
        "outdated_design_markers": "TEXT NOT NULL DEFAULT ''",
        "website_quality_score": "INTEGER NOT NULL DEFAULT 0",
        "website_grade": "TEXT NOT NULL DEFAULT ''",
        "thriving_score": "INTEGER NOT NULL DEFAULT 0",
        "thriving_tier": "TEXT NOT NULL DEFAULT ''",
        "revenue_tier": "TEXT NOT NULL DEFAULT ''",
        "review_velocity": "TEXT NOT NULL DEFAULT ''",
    },
    "lead_history": {
        "last_opportunity_score": "INTEGER",
    },
    "trigger_events": {
        "trigger_label": "TEXT NOT NULL DEFAULT ''",
        "trigger_strength": "TEXT NOT NULL DEFAULT ''",
        "summary": "TEXT NOT NULL DEFAULT ''",
    },
    "lead_retry_queue": {
        "run_id": "INTEGER",
        "reason": "TEXT NOT NULL DEFAULT ''",
        "status": "TEXT NOT NULL DEFAULT 'pending'",
        "attempt_count": "INTEGER NOT NULL DEFAULT 0",
        "last_error": "TEXT NOT NULL DEFAULT ''",
        "next_attempt_at": "TEXT NOT NULL DEFAULT ''",
        "created_at": "TEXT NOT NULL DEFAULT ''",
        "updated_at": "TEXT NOT NULL DEFAULT ''",
    },
}

SHARED_INDEX_STATEMENTS = (
    "CREATE INDEX IF NOT EXISTS idx_run_leads_lead_key ON run_leads (lead_key, run_id)",
    "CREATE INDEX IF NOT EXISTS idx_lead_list_members_key ON lead_list_members (lead_key, list_id)",
    "CREATE INDEX IF NOT EXISTS idx_opportunity_audits_lookup ON opportunity_audits (lead_key, audited_at DESC, id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_opportunity_audits_run_lookup ON opportunity_audits (run_id, lead_key, audited_at DESC, id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_trigger_events_lookup ON trigger_events (lead_key, observed_at DESC, id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_trigger_events_run_lookup ON trigger_events (run_id, lead_key, observed_at DESC, id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_lead_retry_queue_pending ON lead_retry_queue (status, next_attempt_at)",
)


def ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    existing = {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def ensure_shared_schema(conn: sqlite3.Connection) -> None:
    for statement in SHARED_TABLE_STATEMENTS:
        conn.execute(statement)

    for table, columns in SHARED_COLUMN_MIGRATIONS.items():
        for column, definition in columns.items():
            ensure_column(conn, table, column, definition)

    for statement in SHARED_INDEX_STATEMENTS:
        conn.execute(statement)
