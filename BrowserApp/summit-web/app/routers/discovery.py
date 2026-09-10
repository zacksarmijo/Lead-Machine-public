from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.config import load_settings
from app.run_manager import run_manager

router = APIRouter(prefix="/api/discovery", tags=["discovery"])


@router.post("/runs")
async def start_run(request: Request):
    body = await request.json()
    settings = load_settings()
    config = {**settings, **body}
    save_path = config.get("output_folder", "")
    ok = run_manager.start_run(config, save_path, run_reason=config.get("run_reason", "manual"))
    if not ok:
        return {"ok": False, "error": "A run is already in progress"}
    return {"ok": True}


@router.post("/recheck-pinned")
async def recheck_pinned():
    from app.dependencies import get_store
    store = get_store()
    pinned_keys = store.get_pinned_keys()
    if not pinned_keys:
        return {"ok": False, "error": "No pinned leads to recheck"}
    # Derive search areas from pinned leads' city_area values
    search_areas = set()
    for key in pinned_keys:
        lead = store.get_lead(key)
        if lead:
            city = lead.get("city_area") or ""
            if city.strip():
                search_areas.add(city.strip())
    settings = load_settings()
    config = {
        **settings,
        "target_lead_keys": sorted(pinned_keys),
        "target_pool_name": "Pinned Leads",
        "search_areas": sorted(search_areas) if search_areas else settings.get("search_areas", []),
        "run_reason": "Recheck pinned leads",
    }
    save_path = config.get("output_folder", "")
    ok = run_manager.start_run(config, save_path, run_reason="Recheck pinned leads")
    if not ok:
        return {"ok": False, "error": "A run is already in progress"}
    return {"ok": True, "lead_count": len(pinned_keys)}


@router.post("/runs/stop")
async def stop_run():
    run_manager.stop_run()
    return {"ok": True}


@router.get("/runs/status")
async def run_status():
    return run_manager.get_status()


@router.get("/runs/logs")
async def run_logs(from_index: int = 0):
    return StreamingResponse(
        run_manager.stream_logs(from_index=from_index),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
