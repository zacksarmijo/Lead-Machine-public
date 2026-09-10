from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime
import shutil
from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from app.dependencies import get_store

router = APIRouter(prefix="/api/leads", tags=["leads"])


_SAFE_KEY_RE = re.compile(r"[^A-Za-z0-9_\-]+")


def _safe_key(value: str) -> str:
    return _SAFE_KEY_RE.sub("_", value or "unknown")[:120]


def _csv_cell(value: object) -> str:
    """Keep untrusted scraped text literal when opened in a spreadsheet."""
    text = str(value)
    if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
        return "'" + text
    return text


@router.get("/scans")
async def list_scans():
    store = get_store()
    return store.list_scans()


@router.delete("/scans/{run_id}")
async def delete_scan(run_id: int):
    store = get_store()
    store.delete_run(run_id)
    return {"ok": True}


@router.get("/buckets")
async def list_buckets(run_id: int | None = None):
    store = get_store()
    return store.list_buckets(run_id)


@router.get("/lists")
async def list_lead_lists():
    store = get_store()
    return store.list_lead_lists()


@router.post("/lists")
async def create_lead_list(request: Request):
    body = await request.json()
    store = get_store()
    list_id = store.ensure_lead_list(body["name"])
    return {"id": list_id}


@router.post("/lists/{name}/add")
async def add_to_list(name: str, request: Request):
    body = await request.json()
    store = get_store()
    added, skipped = store.add_leads_to_list(body["lead_keys"], name)
    return {"added": added, "skipped": skipped}


@router.post("/lists/{name}/remove")
async def remove_from_list(name: str, request: Request):
    body = await request.json()
    store = get_store()
    removed = store.remove_leads_from_list(body["lead_keys"], name)
    return {"removed": removed}


@router.post("/shortlists/today")
async def create_today_shortlist(request: Request):
    body = await request.json()
    store = get_store()
    limit = max(1, min(int(body.get("limit") or 25), 100))
    run_id_raw = body.get("run_id")
    try:
        run_id = int(run_id_raw) if run_id_raw not in (None, "") else None
    except (TypeError, ValueError):
        run_id = None
    explicit_keys = [str(key).strip() for key in (body.get("lead_keys") or []) if str(key).strip()]
    if explicit_keys:
        lead_keys = explicit_keys[:limit]
    else:
        view_filter = str(body.get("view_filter") or "High confidence")
        leads = store.list_queue_summaries(view_filter=view_filter, run_id=run_id)
        lead_keys = []
        for lead in leads:
            if len(lead_keys) >= limit:
                break
            if lead.get("do_not_contact") or lead.get("disqualified"):
                continue
            source_tier = str(lead.get("source_confidence_tier") or lead.get("Source Confidence Tier") or "")
            if source_tier == "Low":
                continue
            opp_score = int(lead.get("opportunity_score") or lead.get("Opportunity Score") or lead.get("last_opportunity_score") or 0)
            if opp_score < 20:
                continue
            key = str(lead.get("lead_key", "")).strip()
            if key:
                lead_keys.append(key)

    list_name = str(body.get("name") or f"Today's Shortlist {datetime.now().strftime('%Y-%m-%d')}")
    if not lead_keys:
        return {"ok": False, "error": "No qualified leads found for today's shortlist.", "list_name": list_name, "added": 0}
    list_id, added = store.add_leads_to_list(lead_keys, list_name)
    return {"ok": True, "list_id": list_id, "list_name": list_name, "added": added, "lead_keys": lead_keys}


@router.get("/pinned-keys")
async def pinned_keys():
    store = get_store()
    keys = store.get_pinned_keys()
    return {"pinned_keys": sorted(keys), "count": len(keys)}


@router.post("/pin")
async def pin_leads(request: Request):
    body = await request.json()
    store = get_store()
    list_id, added = store.add_leads_to_list(body["lead_keys"], store._PINNED_LIST_NAME)
    total = store.pinned_count()
    return {"pinned": added, "total_pinned": total}


@router.post("/unpin")
async def unpin_leads(request: Request):
    body = await request.json()
    store = get_store()
    removed = store.remove_leads_from_list(body["lead_keys"], store._PINNED_LIST_NAME)
    total = store.pinned_count()
    return {"unpinned": removed, "total_pinned": total}


@router.post("/pin-similar/{lead_key:path}")
async def pin_similar(lead_key: str):
    store = get_store()
    similar = store.list_similar_leads(lead_key, limit=20)
    keys = [s["lead_key"] for s in similar if s.get("lead_key")]
    if not keys:
        return {"pinned": 0, "total_pinned": store.pinned_count()}
    list_id, added = store.add_leads_to_list(keys, store._PINNED_LIST_NAME)
    total = store.pinned_count()
    return {"pinned": added, "total_pinned": total}


@router.get("")
async def list_leads(
    search: str = "",
    view_filter: str = "All leads",
    run_id: int | None = None,
    work_bucket: str | None = None,
    lead_list_id: int | None = None,
):
    store = get_store()
    try:
        leads = store.list_queue_summaries(
            search_text=search,
            view_filter=view_filter,
            run_id=run_id,
            work_bucket=work_bucket,
            lead_list_id=lead_list_id,
        )
    except Exception:
        leads = store.list_leads(
            search_text=search,
            view_filter=view_filter,
            run_id=run_id,
            work_bucket=work_bucket,
            lead_list_id=lead_list_id,
        )
    return leads


@router.post("/from-manual-scrape")
async def create_from_manual_scrape(request: Request):
    body = await request.json()
    manual_key = str(body.get("manual_key") or "").strip()
    scrape = body.get("scrape") if isinstance(body.get("scrape"), dict) else {}

    try:
        from lead_vault_website_generator import DEFAULT_SCRAPED_DIR
    except ImportError as exc:
        return {"ok": False, "error": f"Manual scrape storage unavailable: {exc}"}

    scrape_path = DEFAULT_SCRAPED_DIR / _safe_key(manual_key) / "scrape.json"
    if manual_key and scrape_path.exists():
        try:
            scrape = json.loads(scrape_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"ok": False, "error": "Saved manual scrape is unreadable."}

    if not scrape:
        return {"ok": False, "error": "Run a manual scrape before creating a lead."}

    store = get_store()
    try:
        created = store.create_manual_website_lead(scrape, manual_key=manual_key)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    lead_key = str(created.get("lead_key") or "")
    if manual_key and lead_key:
        src = DEFAULT_SCRAPED_DIR / _safe_key(manual_key)
        dst = DEFAULT_SCRAPED_DIR / _safe_key(lead_key)
        if src.exists() and src.is_dir():
            try:
                shutil.copytree(src, dst, dirs_exist_ok=True)
            except OSError:
                pass

    return {
        "ok": True,
        "lead_key": lead_key,
        "business_name": created.get("business_name", ""),
        "lead_url": f"/leads/{lead_key}",
    }


@router.get("/export")
async def export_leads(
    search: str = "",
    view_filter: str = "All leads",
    run_id: int | None = None,
    format: str = "csv",
):
    store = get_store()
    try:
        leads = store.list_queue_summaries(search_text=search, view_filter=view_filter, run_id=run_id)
    except Exception:
        leads = store.list_leads(search_text=search, view_filter=view_filter, run_id=run_id)

    if format == "csv":
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        if leads:
            cols = ["business_name", "city_area", "address", "last_opportunity_score", "last_lead_score", "pipeline_status", "ready_to_contact"]
            # Add data-level keys
            extra = [
                "Phone",
                "Email",
                "Web Presence Status",
                "Website Bucket",
                "Review Bucket",
                "Opportunity Score",
                "Opportunity Label",
                "Lead Score",
                "Source Confidence Score",
                "Source Confidence Tier",
                "Sources Checked",
                "Website Assertion Status",
                "Why Surfaced",
                "Why Suppressed",
                "Evidence Freshness",
                "Next Best Action",
                "Tech Stack Signal",
                "Tech Stack Score",
                "Tech Stack Summary",
                "Tech Stack Weak Signals",
                "BuiltWith Domain",
                "BuiltWith Status",
            ]
            extra_aliases = {
                "Tech Stack Signal": "tech_stack_signal",
                "Tech Stack Score": "tech_stack_score",
                "Tech Stack Summary": "tech_stack_summary",
                "Tech Stack Weak Signals": "tech_stack_weak_signals",
                "BuiltWith Domain": "builtwith_domain",
                "BuiltWith Status": "builtwith_status",
            }

            def extra_value(lead_obj, data_obj, key):
                for value in (
                    data_obj.get(key),
                    lead_obj.get(key),
                    lead_obj.get(extra_aliases.get(key, "")),
                ):
                    if value not in (None, ""):
                        return value
                return ""

            writer.writerow(cols + extra)
            for lead in leads:
                data = lead.get("data") or {}
                if isinstance(data, str):
                    try:
                        data = json.loads(data)
                    except Exception:
                        data = {}
                row = [str(lead.get(c, "")) for c in cols]
                row += [str(extra_value(lead, data, k)) for k in extra]
                writer.writerow(_csv_cell(value) for value in row)
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=leads_export.csv"},
        )

    return {"error": "Unsupported format"}


@router.get("/{lead_key:path}/similar")
async def similar_leads(lead_key: str, run_id: int | None = None, limit: int = 8):
    store = get_store()
    return store.list_similar_leads(lead_key, limit=limit, run_id=run_id)


@router.get("/{lead_key:path}/activity")
async def lead_activity(lead_key: str):
    store = get_store()
    return store.list_activity(lead_key)


@router.post("/{lead_key:path}/activity")
async def add_lead_activity(lead_key: str, request: Request):
    body = await request.json()
    store = get_store()
    store.add_activity(lead_key, body.get("activity_type", "General"), body.get("summary", ""), body.get("details", ""))
    return {"ok": True}


@router.put("/{lead_key:path}/state")
async def update_tracker_state(lead_key: str, request: Request):
    body = await request.json()
    store = get_store()
    store.save_tracker_state(lead_key, body)
    return {"ok": True}


@router.get("/{lead_key:path}")
async def get_lead(lead_key: str):
    store = get_store()
    return store.get_lead(lead_key)


# Bulk operations
@router.post("/bulk/pipeline-status")
async def bulk_pipeline_status(request: Request):
    body = await request.json()
    store = get_store()
    store.bulk_update_pipeline_status(body["lead_keys"], body["pipeline_status"])
    return {"ok": True}


@router.post("/bulk/ready-to-contact")
async def bulk_ready_to_contact(request: Request):
    body = await request.json()
    store = get_store()
    store.bulk_update_ready_to_contact(body["lead_keys"], body["ready_to_contact"])
    return {"ok": True}


@router.post("/bulk/lead-signal")
async def bulk_lead_signal(request: Request):
    body = await request.json()
    store = get_store()
    store.bulk_update_lead_signal(body["lead_keys"], body["lead_signal"])
    return {"ok": True}


@router.post("/bulk/work-bucket")
async def bulk_work_bucket(request: Request):
    body = await request.json()
    store = get_store()
    store.bulk_set_work_bucket(body["lead_keys"], body["work_bucket"])
    return {"ok": True}


@router.post("/bulk/tag")
async def bulk_tag(request: Request):
    body = await request.json()
    store = get_store()
    store.bulk_add_tag(body["lead_keys"], body["tag"])
    return {"ok": True}


@router.post("/bulk/delete")
async def bulk_delete(request: Request):
    body = await request.json()
    store = get_store()
    store.delete_selected_leads(body["lead_keys"], body.get("run_id"))
    return {"ok": True}
