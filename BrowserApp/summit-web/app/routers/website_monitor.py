from __future__ import annotations

"""HTTP API for the standalone Website Monitor.

The monitor deliberately uses its own tables and API namespace so tracked
websites never enter the lead-generation, outreach, or opportunity pipeline.
"""

from datetime import datetime, timezone
from threading import Lock, Thread
from typing import Any

from fastapi import APIRouter, HTTPException, status

from app.config import load_settings, resolve_db_path
from app.website_monitor import WebsiteMonitorStore


router = APIRouter(prefix="/api/website-monitor", tags=["website-monitor"])


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def get_monitor_store() -> WebsiteMonitorStore:
    """Build a short-lived store; SQLite connections are opened per operation."""
    return WebsiteMonitorStore(resolve_db_path())


def _http_error(exc: ValueError) -> HTTPException:
    message = str(exc) or "Website Monitor request was invalid"
    code = status.HTTP_404_NOT_FOUND if "not found" in message.casefold() else status.HTTP_400_BAD_REQUEST
    return HTTPException(status_code=code, detail=message)


def _decorate_run(value: dict[str, Any] | None) -> dict[str, Any]:
    run = dict(value or {})
    if not run:
        return run
    if run.get("health_score") is None:
        run["health_score"] = run.get("overall_score")
    ranking_summary = (run.get("summary") or {}).get("rankings") or {}
    run.setdefault("average_rank", ranking_summary.get("average_rank"))
    run.setdefault("top_10", ranking_summary.get("top_10"))
    run.setdefault("ranked_keywords", ranking_summary.get("ranking"))
    run.setdefault("total_keywords", ranking_summary.get("tracked"))
    if isinstance(run.get("rankings"), list):
        run["rankings"] = [_decorate_ranking(item) for item in run["rankings"]]
    return run


def _decorate_site(value: dict[str, Any]) -> dict[str, Any]:
    site = dict(value)
    summary = site.get("summary")
    if isinstance(summary, dict):
        for key, item in summary.items():
            if key not in site or site[key] is None:
                site[key] = item
    if site.get("health_score") is None:
        site["health_score"] = site.get("overall_score")
    if isinstance(site.get("latest_run"), dict):
        site["latest_run"] = _decorate_run(site["latest_run"])
        for key in ("average_rank", "top_10", "ranked_keywords", "total_keywords"):
            if site.get(key) is None:
                site[key] = site["latest_run"].get(key)
    return site


def _decorate_ranking(value: dict[str, Any]) -> dict[str, Any]:
    row = dict(value)
    row.setdefault("current_rank", row.get("rank_absolute"))
    row.setdefault("previous_rank", row.get("previous_rank_absolute"))
    row.setdefault("change", row.get("rank_change"))
    row.setdefault("competitors", row.get("top_competitors") or [])
    return row


def _detail_payload(value: dict[str, Any]) -> dict[str, Any]:
    raw = dict(value)
    site = _decorate_site(raw)
    latest_run = _decorate_run(raw.get("latest_run"))
    rankings = [_decorate_ranking(item) for item in (raw.get("latest_rankings") or [])]
    history = [_decorate_run(item) for item in (raw.get("history") or [])]
    return {
        "site": site,
        "latest_run": latest_run,
        "rankings": rankings,
        "issues": list(raw.get("open_issues") or []),
        "history": history,
        "latest_page": raw.get("latest_page"),
        "resolved_issues": list(raw.get("resolved_issues") or []),
    }


class ScanCoordinator:
    """Run one network/provider scan at a time without blocking the web UI."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._state: dict[str, Any] = {
            "running": False,
            "site_id": None,
            "started_at": None,
            "finished_at": None,
            "error": "",
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._state)

    def is_running(self, site_id: int | None = None) -> bool:
        with self._lock:
            if not self._state["running"]:
                return False
            return site_id is None or int(self._state["site_id"]) == int(site_id)

    def start(self, site_id: int) -> bool:
        with self._lock:
            if self._state["running"]:
                return False
            self._state = {
                "running": True,
                "site_id": int(site_id),
                "started_at": _utcnow(),
                "finished_at": None,
                "error": "",
            }
        worker = Thread(target=self._run, args=(int(site_id),), daemon=True, name=f"website-scan-{site_id}")
        worker.start()
        return True

    def _run(self, site_id: int) -> None:
        error = ""
        try:
            get_monitor_store().scan_site(site_id, load_settings())
        except Exception as exc:  # surfaced through the status endpoint; server remains available
            error = str(exc).strip() or type(exc).__name__
        with self._lock:
            self._state = {
                "running": False,
                "site_id": int(site_id),
                "started_at": self._state.get("started_at"),
                "finished_at": _utcnow(),
                "error": error[:1000],
            }


scan_coordinator = ScanCoordinator()


@router.get("/summary")
def monitor_summary() -> dict[str, Any]:
    payload = get_monitor_store().get_summary()
    payload["sites"] = [_decorate_site(item) for item in payload.get("sites", [])]
    payload["owned_count"] = payload.get("owned_site_count", 0)
    payload["observed_count"] = payload.get("observed_site_count", 0)
    payload["average_health"] = payload.get("average_health_score")
    settings = load_settings()
    payload["providers"] = {
        "dataforseo_configured": bool(
            str(settings.get("dataforseo_login") or "").strip()
            and str(settings.get("dataforseo_password") or "").strip()
        ),
        "pagespeed_configured": bool(str(settings.get("pagespeed_api_key") or "").strip()),
    }
    scan_state = scan_coordinator.snapshot()
    payload["scanning_site_ids"] = [scan_state["site_id"]] if scan_state.get("running") else []
    return payload


@router.get("/sites")
def list_monitored_sites() -> dict[str, Any]:
    return {"sites": [_decorate_site(item) for item in get_monitor_store().list_sites()]}


@router.post("/sites", status_code=status.HTTP_201_CREATED)
def create_monitored_site(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return _detail_payload(get_monitor_store().create_site(payload))
    except ValueError as exc:
        raise _http_error(exc) from exc


@router.get("/sites/{site_id}")
def get_monitored_site(site_id: int) -> dict[str, Any]:
    try:
        return _detail_payload(get_monitor_store().get_site_detail(site_id))
    except ValueError as exc:
        raise _http_error(exc) from exc


@router.put("/sites/{site_id}")
def update_monitored_site(site_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    if scan_coordinator.is_running(site_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Wait for this website scan to finish before editing it")
    try:
        return _detail_payload(get_monitor_store().update_site(site_id, payload))
    except ValueError as exc:
        raise _http_error(exc) from exc


@router.delete("/sites/{site_id}")
def delete_monitored_site(site_id: int) -> dict[str, Any]:
    if scan_coordinator.is_running(site_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Wait for this website scan to finish before deleting it")
    try:
        return get_monitor_store().delete_site(site_id)
    except ValueError as exc:
        raise _http_error(exc) from exc


@router.post("/sites/{site_id}/scan", status_code=status.HTTP_202_ACCEPTED)
def start_site_scan(site_id: int) -> dict[str, Any]:
    if scan_coordinator.is_running():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Another website scan is already running")
    try:
        site = get_monitor_store().get_site_summary(site_id)
    except ValueError as exc:
        raise _http_error(exc) from exc
    if not site.get("active", True):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Enable this website before scanning it")
    if not scan_coordinator.start(site_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Another website scan is already running")
    return {"accepted": True, "status": "running", "site_id": int(site_id)}


@router.get("/scans/status")
def scan_status() -> dict[str, Any]:
    return scan_coordinator.snapshot()


__all__ = ["router", "get_monitor_store", "ScanCoordinator", "scan_coordinator"]
