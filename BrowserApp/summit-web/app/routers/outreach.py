from __future__ import annotations

from datetime import datetime, timezone
from fastapi import APIRouter, Request

from app.config import load_settings
from app.dependencies import get_store

router = APIRouter(prefix="/api/outreach", tags=["outreach"])


@router.post("/generate-draft")
async def generate_draft(request: Request):
    """Build an outreach draft from lead data + existing AI content."""
    body = await request.json()
    lead_key = body.get("lead_key", "")
    settings = load_settings()

    store = get_store()
    lead = store.get_lead(lead_key)
    if not lead:
        return {"ok": False, "error": "Lead not found"}

    agency_name = body.get("agency_name") or settings.get("agency_name", "")

    # Allow frontend overrides for preview URL / file path
    preview_url = body.get("preview_url", "")
    preview_file_path = body.get("preview_file_path", "")

    try:
        from outreach_export import build_draft_from_lead

        draft = build_draft_from_lead(lead, agency_name=agency_name)

        # Apply any overrides from the request
        if preview_url:
            draft.preview_url = preview_url
        if preview_file_path:
            draft.preview_file_path = preview_file_path
        if body.get("recipient_email"):
            draft.recipient_email = body["recipient_email"]
        if body.get("subject"):
            draft.subject = body["subject"]
        if body.get("body_plain"):
            draft.body_plain = body["body_plain"]
            from outreach_export import _plain_to_html
            draft.body_html = _plain_to_html(body["body_plain"])

        return {"ok": True, "draft": draft.to_dict()}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@router.post("/export-outlook")
async def export_outlook(request: Request):
    """Export an outreach draft to Outlook via .eml file."""
    body = await request.json()
    draft_data = body.get("draft", {})

    if not draft_data.get("subject") and not draft_data.get("body_plain"):
        return {"ok": False, "error": "No draft content to export"}

    store = get_store()

    try:
        from outreach_export import OutreachDraft, export_to_outlook

        draft = OutreachDraft.from_dict(draft_data)
        result = export_to_outlook(draft)

        # Save to outreach history
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        draft_record = draft.to_dict()
        draft_record["export_status"] = "exported" if result["ok"] else "failed"
        draft_record["export_channel"] = result.get("method", "outlook")
        draft_record["export_error"] = result.get("error", "")
        draft_record["exported_at"] = now if result["ok"] else ""

        draft_id = store.save_outreach_draft(draft_record)

        # Log activity on the lead
        if result["ok"] and draft.lead_key:
            try:
                store.add_activity(
                    draft.lead_key,
                    "Email note",
                    f"Exported outreach draft to Outlook ({result.get('method', '')})",
                    f"Subject: {draft.subject}\nRecipient: {draft.recipient_email or '(none)'}",
                )
            except Exception:
                pass  # Non-fatal

        return {
            "ok": result["ok"],
            "method": result.get("method", ""),
            "eml_path": result.get("eml_path", ""),
            "error": result.get("error", ""),
            "draft_id": draft_id,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@router.get("/history/{lead_key:path}")
async def outreach_history(lead_key: str):
    """Get outreach draft history for a lead."""
    store = get_store()
    return store.list_outreach_drafts(lead_key)
