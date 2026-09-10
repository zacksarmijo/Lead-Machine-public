from __future__ import annotations

from fastapi import APIRouter, Request

from app.config import SECRET_SETTING_KEYS, load_settings, save_settings

router = APIRouter(prefix="/api/settings", tags=["settings"])

def _redact_settings(settings: dict) -> dict:
    redacted = dict(settings)
    for key in SECRET_SETTING_KEYS:
        has_value = bool(str(redacted.get(key) or "").strip())
        redacted[f"{key}_set"] = has_value
        redacted[key] = ""
    return redacted


@router.get("")
async def get_settings():
    return _redact_settings(load_settings())


@router.put("")
async def put_settings(request: Request):
    data = await request.json()
    save_settings(data)
    return {"ok": True}
