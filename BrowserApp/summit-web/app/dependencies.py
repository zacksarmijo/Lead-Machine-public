from __future__ import annotations

from app.config import resolve_db_path

# Lazy import so sys.path is set up by config.py first
_store_class = None


def _get_store_class():
    global _store_class
    if _store_class is None:
        from lead_vault_store import LeadVaultStore
        _store_class = LeadVaultStore
    return _store_class


def get_store():
    cls = _get_store_class()
    db_path = resolve_db_path()
    store = cls(db_path)
    store.ensure_ready()
    return store
