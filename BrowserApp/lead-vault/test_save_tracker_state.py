"""Tests for CB-1: saveWorkflow must not wipe signal/tags/bucket."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from lead_vault_store import LeadVaultStore


def _make_store(tmp_path: Path) -> LeadVaultStore:
    """Create a minimal store with just lead_tracker_state (skip full ensure_ready)."""
    db = tmp_path / "test.db"
    conn = sqlite3.connect(db)
    # ensure_ready checks for lead_history, so create a stub
    conn.execute("CREATE TABLE lead_history (lead_key TEXT)")
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
            updated_at TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.commit()
    conn.close()
    store = LeadVaultStore(db)
    return store


def _read_row(store: LeadVaultStore, lead_key: str) -> dict:
    conn = sqlite3.connect(store.db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM lead_tracker_state WHERE lead_key = ?", (lead_key,)
    ).fetchone()
    conn.close()
    return dict(row) if row else {}


def test_partial_save_preserves_unmentioned_fields(tmp_path):
    """The core CB-1 bug: saving workflow fields must not blank signal/tags/bucket."""
    store = _make_store(tmp_path)

    # Step 1: seed a row with signal, tags, and work_bucket set
    store.save_tracker_state("acme", {
        "pipeline_status": "Approved",
        "lead_signal": "In contact",
        "work_bucket": "Web redesign",
        "tags": "priority,denver",
        "ready_to_contact": 1,
        "do_not_contact": 0,
    })

    row = _read_row(store, "acme")
    assert row["lead_signal"] == "In contact"
    assert row["work_bucket"] == "Web redesign"
    assert row["tags"] == "priority,denver"
    assert row["ready_to_contact"] == 1

    # Step 2: simulate what saveWorkflow sends — only workflow fields, NO signal/tags/bucket
    store.save_tracker_state("acme", {
        "pipeline_status": "Approved",
        "lead_owner": "Example Owner",
        "next_action": "Send email",
        "opportunity_summary": "Good fit",
        "outreach_angle": "SEO audit",
        "draft_message": "Hi there",
        "personalization_notes": "Likes dogs",
    })

    row = _read_row(store, "acme")
    # These must survive the partial save
    assert row["lead_signal"] == "In contact", "lead_signal was wiped!"
    assert row["work_bucket"] == "Web redesign", "work_bucket was wiped!"
    assert row["tags"] == "priority,denver", "tags was wiped!"
    assert row["ready_to_contact"] == 1, "ready_to_contact was wiped!"
    # And the workflow fields must be updated
    assert row["lead_owner"] == "Example Owner"
    assert row["next_action"] == "Send email"
    assert row["draft_message"] == "Hi there"


def test_full_save_still_works(tmp_path):
    """When all fields are provided, they should all be written."""
    store = _make_store(tmp_path)

    store.save_tracker_state("beta", {
        "pipeline_status": "Contacted",
        "lead_signal": "Won site",
        "work_bucket": "Maintenance",
        "tags": "vip",
        "ready_to_contact": 0,
        "do_not_contact": 1,
        "lead_owner": "Alice",
        "next_action": "Follow up",
        "opportunity_summary": "Big deal",
        "outreach_angle": "Redesign",
        "draft_message": "Hello",
        "personalization_notes": "Golfer",
    })

    row = _read_row(store, "beta")
    assert row["pipeline_status"] == "Contacted"
    assert row["lead_signal"] == "Won site"
    assert row["do_not_contact"] == 1
    assert row["lead_owner"] == "Alice"


def test_first_save_with_partial_fields(tmp_path):
    """First save (INSERT path) with partial fields should use defaults for missing."""
    store = _make_store(tmp_path)

    store.save_tracker_state("gamma", {
        "pipeline_status": "Approved",
        "lead_owner": "Bob",
    })

    row = _read_row(store, "gamma")
    assert row["pipeline_status"] == "Approved"
    assert row["lead_owner"] == "Bob"
    assert row["lead_signal"] == ""
    assert row["tags"] == ""
    assert row["work_bucket"] == ""


def test_explicit_empty_string_overwrites(tmp_path):
    """If caller explicitly sends empty string, it should overwrite existing value."""
    store = _make_store(tmp_path)

    store.save_tracker_state("delta", {
        "lead_signal": "In contact",
        "tags": "hot",
    })
    assert _read_row(store, "delta")["lead_signal"] == "In contact"

    # Explicitly clear lead_signal
    store.save_tracker_state("delta", {
        "lead_signal": "",
    })
    row = _read_row(store, "delta")
    assert row["lead_signal"] == ""
    assert row["tags"] == "hot", "tags should survive"
