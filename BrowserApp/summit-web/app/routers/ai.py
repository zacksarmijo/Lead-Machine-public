from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import re
import shutil
import socket
import threading
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import quote, urlparse
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from app.config import load_settings
from app.dependencies import get_store
from app.security import PREVIEW_CSP

router = APIRouter(prefix="/api/ai", tags=["ai"])
logger = logging.getLogger(__name__)

_SAFE_KEY_RE = re.compile(r"[^A-Za-z0-9_\-]+")
_SECTION_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_MOCKUP_VERSION_FILE_RE = re.compile(r"^mockup_v\d{3,}\.html$")
_ALLOWED_GENERATED_FILE_SUFFIXES = {
    ".html",
    ".css",
    ".js",
    ".svg",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".ico",
}


def _safe_generated_html_target(asset_path: str) -> list[str] | None:
    asset_path = str(asset_path or "").strip().lstrip("/\\")
    if not asset_path:
        return ["mockup.html"]
    raw_parts = [part for part in re.split(r"[\\/]+", asset_path) if part]
    if not raw_parts or any(part in (".", "..") for part in raw_parts):
        return None
    if Path(raw_parts[-1]).suffix.lower() != ".html":
        return None
    if raw_parts == ["mockup.html"]:
        return raw_parts
    if len(raw_parts) == 2 and raw_parts[0] == "multi_page_export":
        return raw_parts
    return None


def _backup_generated_page_version(
    output_dir: Path,
    target_parts: list[str],
    html: str,
    *,
    reason: str,
    section_id: str = "",
    model: str = "",
    edit_type: str = "",
) -> Path:
    page_name = Path(target_parts[-1]).stem or "page"
    safe_page = re.sub(r"[^A-Za-z0-9_-]+", "_", page_name)[:80] or "page"
    versions_dir = output_dir / "versions" / "pages"
    versions_dir.mkdir(parents=True, exist_ok=True)
    existing_numbers: list[int] = []
    pattern = f"{safe_page}_v*.html"
    for path in versions_dir.glob(pattern):
        match = re.search(r"_v(\d+)\.html$", path.name)
        if match:
            existing_numbers.append(int(match.group(1)))
    next_num = (max(existing_numbers) + 1) if existing_numbers else 1
    backup_path = versions_dir / f"{safe_page}_v{next_num:03d}.html"
    backup_path.write_text(html, encoding="utf-8")
    backup_path.with_suffix(".json").write_text(
        json.dumps({
            "version": next_num,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "reason": reason,
            "section_id": section_id,
            "model": model,
            "edit_type": edit_type,
            "target_path": "/".join(target_parts),
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return backup_path


def _provider_from_model(model: str) -> str:
    model_l = str(model or "").lower()
    if model_l.startswith("gpt") or "openai" in model_l:
        return "OpenAI"
    if "claude" in model_l:
        return "Anthropic"
    return ""


def _normalize_provider(provider: str) -> str:
    if provider == "Claude":
        return "Anthropic"
    if provider in ("OpenAI", "Anthropic"):
        return provider
    return ""


def _resolve_provider_model(
    body: dict,
    settings: dict,
    *,
    default_provider: str = "OpenAI",
    openai_default: str = "gpt-5.4",
    anthropic_default: str = "claude-sonnet-4-6",
) -> tuple[str, str]:
    requested_model = str(body.get("ai_model") or "").strip()
    settings_model = str(settings.get("ai_model") or "").strip()
    model = requested_model or settings_model

    requested_provider = _normalize_provider(str(body.get("ai_provider") or "").strip())
    settings_provider = _normalize_provider(str(settings.get("ai_provider") or "").strip())
    provider = (
        requested_provider
        or _provider_from_model(model)
        or settings_provider
        or default_provider
    )
    if provider not in ("OpenAI", "Anthropic"):
        provider = default_provider

    model_provider = _provider_from_model(model)
    if model_provider and model_provider != provider:
        provider = model_provider

    if provider == "Anthropic":
        if "claude" not in model.lower():
            model = anthropic_default
    elif provider == "OpenAI":
        if not model or "claude" in model.lower():
            model = openai_default

    return provider, model


def _safe_lead_key(lead_key: str) -> str:
    """Mirror of lead_vault_website_generator._safe_key for endpoint use.

    Any character outside [A-Za-z0-9_-] collapses to "_", capped at 120
    chars. Empty input returns "unknown". Used to map a lead_key onto a
    directory name without letting dots, slashes, or backslashes escape
    the generated/ tree.
    """
    return _SAFE_KEY_RE.sub("_", lead_key or "unknown")[:120]


def _request_bool(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _request_string_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        text = str(item or "").strip()
        if text:
            out.append(text[:120])
    return out[:24]


def _resolve_inside(base: Path, *parts: str) -> Path | None:
    """Resolve ``base/parts``. Return None if the result escapes ``base``.

    Uses ``Path.resolve(strict=False)`` so a missing final file still
    resolves cleanly; then verifies the resolved path is under the
    resolved base. This is the defense-in-depth check that pairs with
    ``_safe_lead_key`` to prevent path traversal through the lead_key
    URL segment (e.g. ``..%2F..%2Fetc%2Fpasswd``).
    """
    try:
        base_resolved = base.resolve(strict=False)
        target = base.joinpath(*parts).resolve(strict=False)
    except (OSError, ValueError):
        return None
    try:
        target.relative_to(base_resolved)
    except ValueError:
        return None
    return target

# Per-lead locks so two concurrent requests for the same lead_key do not
# race on the generated mockup.html / meta.json / validation.json files.
_lead_locks: dict[str, asyncio.Lock] = {}
_lead_locks_guard = asyncio.Lock()
_generation_cancel_events: dict[str, threading.Event] = {}
_generation_cancel_guard = threading.Lock()


async def _lock_for_lead(lead_key: str) -> asyncio.Lock:
    async with _lead_locks_guard:
        lock = _lead_locks.get(lead_key)
        if lock is None:
            lock = asyncio.Lock()
            _lead_locks[lead_key] = lock
        return lock


def _begin_generation_cancel_event(lead_key: str) -> threading.Event:
    safe_key = _safe_lead_key(lead_key)
    event = threading.Event()
    with _generation_cancel_guard:
        _generation_cancel_events[safe_key] = event
    return event


def _get_generation_cancel_event(lead_key: str) -> threading.Event | None:
    with _generation_cancel_guard:
        return _generation_cancel_events.get(_safe_lead_key(lead_key))


def _finish_generation_cancel_event(
    lead_key: str,
    event: threading.Event,
) -> None:
    safe_key = _safe_lead_key(lead_key)
    with _generation_cancel_guard:
        if _generation_cancel_events.get(safe_key) is event:
            _generation_cancel_events.pop(safe_key, None)


def _generation_cancel_requested(event: threading.Event | None) -> bool:
    return bool(event and event.is_set())


@router.post("/generate")
async def generate_draft(request: Request):
    body = await request.json()
    lead_key = body.get("lead_key", "")
    settings = load_settings()

    provider = body.get("ai_provider") or settings.get("ai_provider", "OpenAI")
    # Pick the right API key for the selected provider
    if provider in ("Anthropic", "Claude"):
        api_key = body.get("ai_api_key") or settings.get("anthropic_api_key", "") or settings.get("ai_api_key", "")
    else:
        api_key = body.get("ai_api_key") or settings.get("openai_api_key", "") or settings.get("ai_api_key", "")
    # Use model from request body first, fall back to settings, auto-correct mismatches
    model = body.get("ai_model") or settings.get("ai_model", "")
    if provider in ("Anthropic", "Claude") and model.startswith("gpt"):
        model = "claude-sonnet-4-6"
    elif provider == "OpenAI" and "claude" in model.lower():
        model = "gpt-5.4-mini"
    agency_name = body.get("agency_name") or settings.get("agency_name", "")
    offer_positioning = body.get("offer_positioning") or settings.get("offer_positioning", "")

    if not api_key:
        return {"ok": False, "error": f"Add a {provider} API key in Settings before generating drafts."}

    store = get_store()
    lead = store.get_lead(lead_key)
    if not lead:
        return {"ok": False, "error": "Lead not found"}

    try:
        from lead_vault_ai import LeadDraftGenerator
        generator = LeadDraftGenerator(api_key=api_key, provider=provider, model=model)
        result = generator.generate_assets(
            lead=lead,
            personalization_notes=body.get("personalization_notes", ""),
            outreach_angle=body.get("outreach_angle", ""),
            existing_draft=body.get("existing_draft", ""),
            existing_summary=body.get("existing_summary", ""),
            agency_name=agency_name,
            offer_positioning=offer_positioning,
        )
        return {
            "ok": True,
            "opportunity_summary": result.opportunity_summary,
            "outreach_strategy": result.outreach_strategy,
            "draft_message": result.draft_message,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@router.post("/agent-review")
async def agent_review(request: Request):
    """Run the Opportunity Review Agent for a single lead."""
    body = await request.json()
    lead_key = body.get("lead_key", "")
    force = body.get("force", False)
    settings = load_settings()

    provider = body.get("ai_provider") or settings.get("ai_provider", "Anthropic")
    if provider in ("Anthropic", "Claude"):
        api_key = body.get("ai_api_key") or settings.get("anthropic_api_key", "") or settings.get("ai_api_key", "")
    else:
        api_key = body.get("ai_api_key") or settings.get("openai_api_key", "") or settings.get("ai_api_key", "")

    if not api_key:
        return {"ok": False, "error": f"Add a {provider} API key in Settings before running agent reviews."}

    model = body.get("ai_model") or settings.get("ai_model", "")
    if provider in ("Anthropic", "Claude") and model.startswith("gpt"):
        model = ""
    elif provider == "OpenAI" and "claude" in model.lower():
        model = ""

    store = get_store()
    try:
        lead = store.get_lead(lead_key)
    except Exception:
        return {"ok": False, "error": "Lead not found"}

    # Load existing review state for cache check
    stored_hash = lead.get("agent_review_input_hash", "") if not force else None
    stored_status = lead.get("agent_review_status", "") if not force else None
    stored_review = lead.get("agent_review", {}) if not force else None

    try:
        from lead_vault_agent_review import run_agent_review
        result = run_agent_review(
            lead=lead,
            api_key=api_key,
            model=model,
            provider=provider,
            stored_hash=stored_hash,
            stored_status=stored_status,
            stored_review=stored_review,
            force=force,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    # Persist completed and skipped reviews. Do NOT persist errors over
    # a previously valid review — that would destroy good cached data.
    if result["status"] in ("completed", "skipped"):
        try:
            store.save_agent_review(
                lead_key=lead_key,
                review_json=json.dumps(result["review"]),
                status=result["status"],
                model=result.get("model", ""),
                input_hash=result.get("input_hash", ""),
            )
        except Exception:
            pass  # Non-fatal — review still returned to UI

    return {
        "ok": result.get("ok", False),
        "review": result.get("review", {}),
        "status": result.get("status", "error"),
        "input_hash": result.get("input_hash", ""),
        "model": result.get("model", ""),
        "skip_reason": result.get("skip_reason", ""),
        "error": result.get("error", ""),
    }


@router.post("/agent-review/batch")
async def agent_review_batch(request: Request):
    """Run agent reviews for selected leads or the current top lead view."""
    body = await request.json()
    settings = load_settings()

    provider = body.get("ai_provider") or settings.get("ai_provider", "Anthropic")
    if provider in ("Anthropic", "Claude"):
        api_key = body.get("ai_api_key") or settings.get("anthropic_api_key", "") or settings.get("ai_api_key", "")
    else:
        api_key = body.get("ai_api_key") or settings.get("openai_api_key", "") or settings.get("ai_api_key", "")
    if not api_key:
        return {"ok": False, "error": f"Add a {provider} API key in Settings before running agent reviews."}

    model = body.get("ai_model") or settings.get("ai_model", "")
    if provider in ("Anthropic", "Claude") and model.startswith("gpt"):
        model = ""
    elif provider == "OpenAI" and "claude" in model.lower():
        model = ""

    store = get_store()
    force = bool(body.get("force", False))
    limit = max(1, min(int(body.get("limit") or 10), 50))
    lead_keys = [str(key).strip() for key in (body.get("lead_keys") or []) if str(key).strip()]
    if not lead_keys:
        view_filter = str(body.get("view_filter") or "High confidence")
        run_id_raw = body.get("run_id")
        try:
            run_id = int(run_id_raw) if run_id_raw not in (None, "") else None
        except (TypeError, ValueError):
            run_id = None
        leads = store.list_queue_summaries(view_filter=view_filter, run_id=run_id)
        lead_keys = [str(lead.get("lead_key", "")).strip() for lead in leads[:limit] if lead.get("lead_key")]
    else:
        lead_keys = lead_keys[:limit]

    try:
        from lead_vault_agent_review import run_agent_review
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    results: list[dict] = []
    counts = {"completed": 0, "skipped": 0, "cached": 0, "error": 0}
    for lead_key in lead_keys:
        try:
            lead = store.get_lead(lead_key)
            stored_hash = lead.get("agent_review_input_hash", "") if not force else None
            stored_status = lead.get("agent_review_status", "") if not force else None
            stored_review = lead.get("agent_review", {}) if not force else None
            result = run_agent_review(
                lead=lead,
                api_key=api_key,
                model=model,
                provider=provider,
                stored_hash=stored_hash,
                stored_status=stored_status,
                stored_review=stored_review,
                force=force,
            )
            status = str(result.get("status", "error"))
            counts[status if status in counts else "error"] += 1
            if status in ("completed", "skipped"):
                store.save_agent_review(
                    lead_key=lead_key,
                    review_json=json.dumps(result.get("review", {})),
                    status=status,
                    model=result.get("model", ""),
                    input_hash=result.get("input_hash", ""),
                )
            results.append({
                "lead_key": lead_key,
                "status": status,
                "ok": bool(result.get("ok", False)),
                "error": result.get("error", ""),
                "skip_reason": result.get("skip_reason", ""),
            })
        except Exception as exc:
            counts["error"] += 1
            results.append({"lead_key": lead_key, "status": "error", "ok": False, "error": str(exc)})

    return {
        "ok": counts["error"] == 0,
        "requested": len(lead_keys),
        **counts,
        "results": results,
    }


@router.post("/cancel-website-generation")
async def cancel_website_generation(request: Request):
    """Request cancellation for an in-progress website generation."""
    try:
        body = await request.json()
    except Exception:
        return {"ok": False, "error": "Request body must be valid JSON."}

    lead_key = str(body.get("lead_key", "") or "").strip()
    if not lead_key:
        return {"ok": False, "error": "Missing lead_key."}

    event = _get_generation_cancel_event(lead_key)
    if event is None:
        return {
            "ok": False,
            "error": "No website generation is running for this lead.",
        }
    event.set()
    return {
        "ok": True,
        "lead_key": lead_key,
        "cancellation_requested": True,
    }


@router.post("/generate-website-package")
async def generate_website_package(request: Request):
    """Generate a website package for a lead using scraped assets."""
    body = await request.json()
    lead_key = str(body.get("lead_key", "") or "").strip()
    if not lead_key:
        return {"ok": False, "error": "Missing lead_key."}

    settings = load_settings()
    provider, model = _resolve_provider_model(
        body,
        settings,
        default_provider="OpenAI",
        openai_default="gpt-5.4",
        anthropic_default="claude-sonnet-4-6",
    )

    if provider == "OpenAI":
        api_key = (
            body.get("ai_api_key")
            or settings.get("openai_api_key", "")
            or settings.get("ai_api_key", "")
        )
    else:
        api_key = (
            body.get("ai_api_key")
            or settings.get("anthropic_api_key", "")
            or settings.get("ai_api_key", "")
        )
    if not api_key:
        return {"ok": False, "error": f"Add a {provider} API key in Settings before generating."}

    store = get_store()
    try:
        lead = store.get_lead(lead_key)
    except Exception:
        return {"ok": False, "error": "Lead not found"}
    if not lead:
        return {"ok": False, "error": "Lead not found"}

    try:
        from lead_vault_website_generator import (
            MAX_MULTI_PAGE_AI_PAGES,
            WebsiteGenerationCancelled,
            WebsiteGenerator,
            WebsiteGeneratorError,
            sanitize_error,
        )
        from lead_vault_website_validator import save_report, validate_html
    except ImportError as exc:
        return {
            "ok": False,
            "error": f"Website generator module unavailable: {exc}",
        }

    lock = await _lock_for_lead(lead_key)
    if lock.locked():
        return {
            "ok": False,
            "error": "A website package is already being generated for this lead. Try again once it finishes.",
        }

    async with lock:
        cancel_event = _begin_generation_cancel_event(lead_key)
        try:
            loop = asyncio.get_running_loop()
            requested_multi_pages = body.get("multi_page_ai_pages")
            if requested_multi_pages is None:
                requested_multi_pages = settings.get(
                    "website_multi_page_ai_pages",
                    MAX_MULTI_PAGE_AI_PAGES,
                )
            try:
                multi_page_ai_pages = int(requested_multi_pages)
            except (TypeError, ValueError):
                multi_page_ai_pages = MAX_MULTI_PAGE_AI_PAGES
            multi_page_ai_pages = max(
                0,
                min(MAX_MULTI_PAGE_AI_PAGES, multi_page_ai_pages),
            )
            design_kit_key = str(
                body.get("design_kit")
                or body.get("design_kit_key")
                or "auto"
            ).strip()[:120] or "auto"
            section_preferences = _request_string_list(
                body.get("section_preferences")
            )
            blocked_sections = _request_string_list(body.get("blocked_sections"))
            supplied_marketing_brief = (
                body.get("marketing_brief")
                if isinstance(body.get("marketing_brief"), dict)
                else None
            )
            has_enhanced_options = bool(
                design_kit_key != "auto"
                or section_preferences
                or blocked_sections
                or supplied_marketing_brief is not None
                or _request_bool(body.get("run_design_review"), False)
            )
            enhanced_design = _request_bool(
                body.get("enhanced_design"),
                has_enhanced_options,
            )
            run_design_review = _request_bool(
                body.get("run_design_review"),
                enhanced_design,
            )
            generate_kwargs = {}
            if (
                enhanced_design
                or run_design_review
                or design_kit_key != "auto"
                or section_preferences
                or blocked_sections
                or supplied_marketing_brief is not None
            ):
                generate_kwargs = {
                    "enhanced_design": enhanced_design,
                    "design_kit_key": design_kit_key,
                    "section_preferences": section_preferences or None,
                    "blocked_sections": blocked_sections or None,
                    "marketing_brief": supplied_marketing_brief,
                    "run_design_review": run_design_review,
                }
            try:
                generator = WebsiteGenerator(
                    api_key=api_key,
                    model=model,
                    provider=provider,
                    multi_page_ai_pages=multi_page_ai_pages,
                    cancellation_event=cancel_event,
                )
            except TypeError:
                generator = WebsiteGenerator(api_key=api_key, model=model)
                try:
                    generator.cancellation_event = cancel_event
                except Exception:
                    pass

            try:
                if generate_kwargs:
                    result = await loop.run_in_executor(
                        None,
                        lambda: generator.generate(lead, **generate_kwargs),
                    )
                else:
                    result = await loop.run_in_executor(None, generator.generate, lead)
                if _generation_cancel_requested(cancel_event):
                    raise WebsiteGenerationCancelled("Website generation cancelled.")
            except WebsiteGenerationCancelled:
                logger.info("website_package.cancelled lead_key=%s", lead_key)
                return {
                    "ok": False,
                    "cancelled": True,
                    "error": "Website generation cancelled.",
                }
            except WebsiteGeneratorError as exc:
                logger.warning("website_package.generate_error lead_key=%s", lead_key)
                return {"ok": False, "error": sanitize_error(str(exc))}
            except Exception as exc:
                logger.exception("website_package.unexpected_error lead_key=%s", lead_key)
                return {
                    "ok": False,
                    "error": f"Generation failed: {sanitize_error(exc)}",
                }

            if _generation_cancel_requested(cancel_event):
                return {
                    "ok": False,
                    "cancelled": True,
                    "error": "Website generation cancelled.",
                }
            report = await loop.run_in_executor(None, validate_html, result.mockup_path)
            if _generation_cancel_requested(cancel_event):
                return {
                    "ok": False,
                    "cancelled": True,
                    "error": "Website generation cancelled.",
                }
            await loop.run_in_executor(None, save_report, report, result.output_dir)

            retried = False
            if not report.passed and not _generation_cancel_requested(cancel_event):
                try:
                    if generate_kwargs:
                        retry_result = await loop.run_in_executor(
                            None,
                            lambda: generator.generate(lead, **generate_kwargs),
                        )
                    else:
                        retry_result = await loop.run_in_executor(
                            None, generator.generate, lead
                        )
                    if _generation_cancel_requested(cancel_event):
                        raise WebsiteGenerationCancelled("Website generation cancelled.")
                    retry_report = await loop.run_in_executor(
                        None, validate_html, retry_result.mockup_path
                    )
                    await loop.run_in_executor(
                        None, save_report, retry_report, retry_result.output_dir
                    )
                    retried = True
                    if (
                        retry_report.passed
                        or retry_report.error_count < report.error_count
                    ):
                        result = retry_result
                        report = retry_report
                except WebsiteGenerationCancelled:
                    logger.info("website_package.retry_cancelled lead_key=%s", lead_key)
                    return {
                        "ok": False,
                        "cancelled": True,
                        "error": "Website generation cancelled.",
                    }
                except Exception:
                    logger.warning(
                        "website_package.retry_failed lead_key=%s", lead_key
                    )

            meta = _read_json_if_exists(result.meta_path) or {}
            return {
                "ok": True,
                "lead_key": result.lead_key,
                "model": result.model,
                "category": result.category,
                "output_dir": str(result.output_dir),
                "mockup_path": str(result.mockup_path),
                "meta_path": str(result.meta_path),
                "site_plan_path": str(result.site_plan_path) if result.site_plan_path else "",
                "site_design_brief_path": (
                    str(result.site_design_brief_path)
                    if result.site_design_brief_path
                    else ""
                ),
                "multi_page_export_dir": (
                    str(result.multi_page_export_dir)
                    if result.multi_page_export_dir else ""
                ),
                "validation": report.to_dict(),
                "retried": retried,
                "enhanced_design": bool(meta.get("enhanced_design")),
                "design_kit": meta.get("design_kit") or "",
                "section_grammar_keys": meta.get("section_grammar_keys") or [],
                "marketing_brief_path": meta.get("marketing_brief_path") or "",
                "design_review_path": meta.get("design_review_path") or "",
                "design_review_summary": meta.get("design_review_summary") or {},
            }
        finally:
            _finish_generation_cancel_event(lead_key, cancel_event)


@router.post("/edit-website-section")
async def edit_website_section(request: Request):
    """Apply an AI edit to one marked section inside a generated HTML page."""
    body = await request.json()
    lead_key = str(body.get("lead_key", "") or "").strip()
    section_id = str(body.get("section_id", "") or "").strip()
    instruction = str(body.get("instruction", "") or "").strip()
    color_mode = str(body.get("color_mode", "") or "preserve_current").strip()
    target_path_raw = str(body.get("target_path", "") or "").strip()
    if not lead_key:
        return {"ok": False, "error": "Missing lead_key."}
    if not section_id:
        return {"ok": False, "error": "Choose a section to edit."}
    if not instruction:
        return {"ok": False, "error": "Enter an edit instruction."}

    settings = load_settings()
    provider, model = _resolve_provider_model(
        body,
        settings,
        default_provider="OpenAI",
        openai_default="gpt-5.4",
        anthropic_default="claude-sonnet-4-6",
    )

    if provider == "OpenAI":
        api_key = (
            body.get("ai_api_key")
            or settings.get("openai_api_key", "")
            or settings.get("ai_api_key", "")
        )
    else:
        api_key = (
            body.get("ai_api_key")
            or settings.get("anthropic_api_key", "")
            or settings.get("ai_api_key", "")
        )
    if not api_key:
        return {"ok": False, "error": f"Add a {provider} API key in Settings before editing."}

    store = get_store()
    try:
        lead = store.get_lead(lead_key)
    except Exception:
        return {"ok": False, "error": "Lead not found"}
    if not lead:
        return {"ok": False, "error": "Lead not found"}

    try:
        from lead_vault_website_generator import (
            DEFAULT_GENERATED_DIR,
            DEFAULT_SCRAPED_DIR,
            WebsiteGeneratorError,
            WebsiteSectionEditor,
            backup_mockup_version,
            find_editable_section_bounds,
            latest_mockup_version_path,
            load_scraped_assets,
            replace_editable_section,
            sanitize_error,
            save_edit_manifest,
        )
        from lead_vault_website_validator import save_report, validate_html
    except ImportError as exc:
        return {
            "ok": False,
            "error": f"Website editor module unavailable: {exc}",
        }

    safe_key = _safe_lead_key(lead_key)
    output_dir = _resolve_inside(DEFAULT_GENERATED_DIR, safe_key)
    target_parts = _safe_generated_html_target(target_path_raw)
    if target_parts is None:
        return {"ok": False, "error": "Invalid generated page target."}
    target_path = _resolve_inside(DEFAULT_GENERATED_DIR, safe_key, *target_parts)
    mockup_path = _resolve_inside(DEFAULT_GENERATED_DIR, safe_key, "mockup.html")
    meta_path = _resolve_inside(DEFAULT_GENERATED_DIR, safe_key, "meta.json")
    if output_dir is None or target_path is None or mockup_path is None:
        return {"ok": False, "error": "Invalid lead key."}
    if not target_path.exists() or not target_path.is_file():
        return {
            "ok": False,
            "error": "Generate the site before editing sections.",
        }
    editing_mockup = target_parts == ["mockup.html"]

    lock = await _lock_for_lead(lead_key)
    if lock.locked():
        return {
            "ok": False,
            "error": "Another operation is in progress for this lead. Try again once it finishes.",
        }

    async with lock:
        try:
            html = target_path.read_text(encoding="utf-8")
        except OSError as exc:
            return {"ok": False, "error": f"Could not read generated page: {sanitize_error(exc)}"}

        bounds = find_editable_section_bounds(html, section_id)
        if bounds is None:
            return {
                "ok": False,
                "error": (
                    "That section was not found on the selected page. "
                    "Regenerate the site so Summit can add editable section markers."
                ),
            }
        start, end, _tag = bounds
        section_html = html[start:end]
        site_meta = _read_json_if_exists(meta_path) if meta_path else {}
        try:
            scraped = load_scraped_assets(lead_key, DEFAULT_SCRAPED_DIR)
        except Exception:
            scraped = {}

        reference_section_html = ""
        if color_mode == "restore_previous":
            if not editing_mockup:
                return {
                    "ok": False,
                    "error": "Color restore is only available for the main preview right now.",
                }
            latest_backup = latest_mockup_version_path(output_dir)
            if latest_backup is None:
                return {
                    "ok": False,
                    "error": "No previous backup is available to restore colors from.",
                }
            try:
                backup_html = latest_backup.read_text(encoding="utf-8")
            except OSError as exc:
                return {
                    "ok": False,
                    "error": f"Could not read backup colors: {sanitize_error(exc)}",
                }
            backup_bounds = find_editable_section_bounds(backup_html, section_id)
            if backup_bounds is None:
                return {
                    "ok": False,
                    "error": "The previous backup does not contain that section.",
                }
            b_start, b_end, _b_tag = backup_bounds
            reference_section_html = backup_html[b_start:b_end]

        loop = asyncio.get_running_loop()
        try:
            editor = WebsiteSectionEditor(api_key=api_key, model=model, provider=provider)
        except TypeError:
            editor = WebsiteSectionEditor(api_key=api_key, model=model)
        try:
            edit_result = await loop.run_in_executor(
                None,
                lambda: editor.edit_section(
                    lead=lead,
                    section_id=section_id,
                    instruction=instruction,
                    section_html=section_html,
                    site_meta=site_meta or {},
                    scraped=scraped,
                    color_mode=color_mode,
                    reference_section_html=reference_section_html,
                ),
            )
            new_html = replace_editable_section(
                html,
                section_id,
                edit_result.replacement_html,
            )
        except WebsiteGeneratorError as exc:
            return {"ok": False, "error": sanitize_error(str(exc))}
        except Exception as exc:
            logger.exception("website_section_edit.unexpected_error lead_key=%s", lead_key)
            return {"ok": False, "error": f"Edit failed: {sanitize_error(exc)}"}

        try:
            if editing_mockup:
                backup_path = backup_mockup_version(
                    output_dir,
                    html,
                    reason=f"Before AI edit ({color_mode}): {instruction[:140]}",
                    section_id=section_id,
                    model=edit_result.model,
                    edit_type="ai_section_edit",
                )
            else:
                backup_path = _backup_generated_page_version(
                    output_dir,
                    target_parts,
                    html,
                    reason=f"Before AI edit ({color_mode}): {instruction[:140]}",
                    section_id=section_id,
                    model=edit_result.model,
                    edit_type="ai_page_section_edit",
                )
            target_path.write_text(new_html, encoding="utf-8")
            manifest = save_edit_manifest(new_html, output_dir) if editing_mockup else {}
        except Exception as exc:
            return {"ok": False, "error": f"Edit generated but save failed: {sanitize_error(exc)}"}

        report = await loop.run_in_executor(None, validate_html, target_path)
        if editing_mockup:
            await loop.run_in_executor(None, save_report, report, output_dir)

        return {
            "ok": True,
            "lead_key": lead_key,
            "section_id": section_id,
            "target_path": "/".join(target_parts),
            "model": edit_result.model,
            "backup_file": backup_path.name,
            "edit_manifest": manifest,
            "validation": report.to_dict(),
        }


@router.post("/save-website-mockup")
async def save_website_mockup(request: Request):
    """Save manually edited HTML from the Advanced HTML editor."""
    body = await request.json()
    lead_key = str(body.get("lead_key", "") or "").strip()
    html = body.get("html")
    target_path_raw = str(body.get("target_path", "") or "").strip()
    if not lead_key:
        return {"ok": False, "error": "Missing lead_key."}
    if not isinstance(html, str) or not html.strip():
        return {"ok": False, "error": "HTML source is required."}
    if len(html) > 2_500_000:
        return {"ok": False, "error": "HTML source is too large to save."}

    store = get_store()
    try:
        lead = store.get_lead(lead_key)
    except Exception:
        return {"ok": False, "error": "Lead not found"}
    if not lead:
        return {"ok": False, "error": "Lead not found"}

    try:
        from lead_vault_website_generator import (
            DEFAULT_GENERATED_DIR,
            backup_mockup_version,
            build_edit_manifest,
            sanitize_error,
            save_edit_manifest,
        )
        from lead_vault_website_validator import save_report, validate_html
    except ImportError as exc:
        return {
            "ok": False,
            "error": f"Website save module unavailable: {exc}",
        }

    safe_key = _safe_lead_key(lead_key)
    output_dir = _resolve_inside(DEFAULT_GENERATED_DIR, safe_key)
    target_parts = _safe_generated_html_target(target_path_raw)
    if target_parts is None:
        return {"ok": False, "error": "Invalid generated page target."}
    target_path = _resolve_inside(DEFAULT_GENERATED_DIR, safe_key, *target_parts)
    mockup_path = _resolve_inside(DEFAULT_GENERATED_DIR, safe_key, "mockup.html")
    if output_dir is None or target_path is None or mockup_path is None:
        return {"ok": False, "error": "Invalid lead key."}
    if not mockup_path.exists() or not mockup_path.is_file():
        return {"ok": False, "error": "Generate a mockup before editing HTML."}
    if not target_path.exists() or not target_path.is_file():
        return {"ok": False, "error": "Generate the selected page before editing HTML."}
    editing_mockup = target_parts == ["mockup.html"]

    lock = await _lock_for_lead(lead_key)
    if lock.locked():
        return {
            "ok": False,
            "error": "Another operation is in progress for this lead. Try again once it finishes.",
        }

    async with lock:
        try:
            current_html = target_path.read_text(encoding="utf-8")
        except OSError as exc:
            return {"ok": False, "error": f"Could not read generated page: {sanitize_error(exc)}"}

        try:
            previous_manifest = build_edit_manifest(current_html)
            next_manifest_preview = build_edit_manifest(html)
            if editing_mockup:
                backup_path = backup_mockup_version(
                    output_dir,
                    current_html,
                    reason="Before manual HTML save",
                    edit_type="manual_save",
                )
            else:
                backup_path = _backup_generated_page_version(
                    output_dir,
                    target_parts,
                    current_html,
                    reason="Before manual HTML save",
                    edit_type="manual_page_save",
                )
            target_path.write_text(html, encoding="utf-8")
            manifest = save_edit_manifest(html, output_dir) if editing_mockup else {}
        except Exception as exc:
            return {"ok": False, "error": f"Save failed: {sanitize_error(exc)}"}

        loop = asyncio.get_running_loop()
        report = await loop.run_in_executor(None, validate_html, target_path)
        if editing_mockup:
            await loop.run_in_executor(None, save_report, report, output_dir)

        previous_sections = previous_manifest.get("sections") or []
        next_sections = next_manifest_preview.get("sections") or []
        marker_warning = ""
        if previous_sections and len(next_sections) < len(previous_sections):
            marker_warning = (
                "Editable section markers were removed. AI section edits may be limited "
                "until markers are restored or the mockup is regenerated."
            )

        return {
            "ok": True,
            "lead_key": lead_key,
            "target_path": "/".join(target_parts),
            "backup_file": backup_path.name,
            "edit_manifest": manifest,
            "validation": report.to_dict(),
            "marker_warning": marker_warning,
        }


@router.post("/restore-website-backup")
async def restore_website_backup(request: Request):
    """Restore mockup.html from the latest saved website backup."""
    body = await request.json()
    lead_key = str(body.get("lead_key", "") or "").strip()
    version_file = str(body.get("version_file", "") or "").strip()
    if not lead_key:
        return {"ok": False, "error": "Missing lead_key."}

    store = get_store()
    try:
        lead = store.get_lead(lead_key)
    except Exception:
        return {"ok": False, "error": "Lead not found"}
    if not lead:
        return {"ok": False, "error": "Lead not found"}

    try:
        from lead_vault_website_generator import (
            DEFAULT_GENERATED_DIR,
            backup_mockup_version,
            latest_mockup_version_path,
            sanitize_error,
            save_edit_manifest,
        )
        from lead_vault_website_validator import save_report, validate_html
    except ImportError as exc:
        return {
            "ok": False,
            "error": f"Website restore module unavailable: {exc}",
        }

    safe_key = _safe_lead_key(lead_key)
    output_dir = _resolve_inside(DEFAULT_GENERATED_DIR, safe_key)
    mockup_path = _resolve_inside(DEFAULT_GENERATED_DIR, safe_key, "mockup.html")
    if output_dir is None or mockup_path is None:
        return {"ok": False, "error": "Invalid lead key."}
    if not mockup_path.exists() or not mockup_path.is_file():
        return {"ok": False, "error": "No current mockup exists to restore."}

    lock = await _lock_for_lead(lead_key)
    if lock.locked():
        return {
            "ok": False,
            "error": "Another operation is in progress for this lead. Try again once it finishes.",
        }

    async with lock:
        restore_path = None
        if version_file:
            if not _MOCKUP_VERSION_FILE_RE.fullmatch(version_file):
                return {"ok": False, "error": "Invalid backup file."}
            restore_path = _resolve_inside(
                output_dir,
                "versions",
                version_file,
            )
            if restore_path is None or not restore_path.exists() or not restore_path.is_file():
                return {"ok": False, "error": "Selected backup was not found."}
        else:
            restore_path = latest_mockup_version_path(output_dir)
        if restore_path is None:
            return {"ok": False, "error": "No saved backup is available."}
        try:
            current_html = mockup_path.read_text(encoding="utf-8")
            restore_html = restore_path.read_text(encoding="utf-8")
        except OSError as exc:
            return {"ok": False, "error": f"Could not read backup: {sanitize_error(exc)}"}

        try:
            current_backup = backup_mockup_version(
                output_dir,
                current_html,
                reason=f"Before restore from {restore_path.name}",
                edit_type="restore_checkpoint",
            )
            mockup_path.write_text(restore_html, encoding="utf-8")
            manifest = save_edit_manifest(restore_html, output_dir)
        except Exception as exc:
            return {"ok": False, "error": f"Restore failed: {sanitize_error(exc)}"}

        loop = asyncio.get_running_loop()
        report = await loop.run_in_executor(None, validate_html, mockup_path)
        await loop.run_in_executor(None, save_report, report, output_dir)

        return {
            "ok": True,
            "lead_key": lead_key,
            "restored_file": restore_path.name,
            "current_backup_file": current_backup.name,
            "edit_manifest": manifest,
            "validation": report.to_dict(),
        }


_ALLOWED_SCRAPE_MODES = {"auto", "static", "browser"}
_ALLOWED_URL_SCHEMES = {"http", "https"}


def _is_blocked_address(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any((
        ip.is_loopback,
        ip.is_private,
        ip.is_link_local,
        ip.is_multicast,
        ip.is_reserved,
        ip.is_unspecified,
    ))


def _scrape_url_security_error(url: str) -> str:
    raw_url = str(url or "").strip()
    raw_scheme = urlparse(raw_url).scheme.lower()
    host_port_without_scheme = re.fullmatch(
        r"[A-Za-z0-9.-]+:\d+(?:[/?#].*)?",
        raw_url,
    )
    if raw_scheme and raw_scheme not in _ALLOWED_URL_SCHEMES and not host_port_without_scheme:
        return "URL must use http or https."

    try:
        parsed = urlparse(raw_url if "://" in raw_url else f"https://{raw_url}")
    except (ValueError, TypeError):
        return "Invalid URL."

    if parsed.scheme and parsed.scheme.lower() not in _ALLOWED_URL_SCHEMES:
        return "URL must use http or https."

    hostname = (parsed.hostname or "").strip().rstrip(".").lower()
    if not hostname:
        return "Invalid URL."
    if hostname == "localhost" or hostname.endswith(".localhost"):
        return "Localhost URLs are blocked for safety."
    if "." not in hostname and not re.fullmatch(r"\d+(?:\.\d+){3}", hostname):
        return "Single-label/private hostnames are blocked for safety."
    if _is_blocked_address(hostname):
        return "Private, local, and reserved network addresses are blocked for safety."

    try:
        resolved = socket.getaddrinfo(hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return ""
    except OSError:
        return ""

    for info in resolved:
        address = (info[4] or ("",))[0]
        if _is_blocked_address(address):
            return "Private, local, and reserved network addresses are blocked for safety."
    return ""


def _manual_scrape_key(url: str) -> str:
    parsed = urlparse(url if "://" in url else f"https://{url}")
    host = re.sub(r"[^A-Za-z0-9_\-]+", "_", parsed.hostname or "website").strip("_")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"manual_{host or 'website'}_{stamp}"[:120]


def _lead_website_url(lead: dict, override: str) -> str:
    """Pick the URL to scrape from the request body or the lead record."""
    data = lead.get("data") or {}
    candidates = [
        override,
        data.get("Resolved Website URL"),
        data.get("Official Website"),
        data.get("Website"),
        lead.get("website_url"),
    ]
    for candidate in candidates:
        value = str(candidate or "").strip()
        if value:
            return value
    return ""


@router.post("/manual-scrape-website")
async def manual_scrape_website(request: Request):
    """Scrape an arbitrary pasted website URL outside the lead-detail flow."""
    try:
        body = await request.json()
    except Exception:
        return {"ok": False, "error": "Request body must be valid JSON."}

    url = str(body.get("url") or "").strip()
    if not url:
        return {"ok": False, "error": "Website URL is required."}
    security_error = _scrape_url_security_error(url)
    if security_error:
        return {"ok": False, "error": security_error}

    mode = str(body.get("mode") or "auto").strip().lower()
    if mode not in _ALLOWED_SCRAPE_MODES:
        return {
            "ok": False,
            "error": "mode must be one of: auto, static, browser",
        }

    manual_key = _manual_scrape_key(url)

    try:
        from lead_vault_scraper import (
            DEFAULT_TIMEOUT,
            save_scraped_assets,
            scrape_site,
        )
        from lead_vault_website_generator import LEAD_VAULT_DIR, sanitize_error
    except ImportError as exc:
        return {
            "ok": False,
            "error": f"Scraper module unavailable: {exc}",
        }

    loop = asyncio.get_running_loop()
    logger.info(
        "manual_scrape_website.start key=%s url_host=%s mode=%s",
        manual_key,
        _safe_host(url),
        mode,
    )
    try:
        scraped = await loop.run_in_executor(
            None, scrape_site, url, DEFAULT_TIMEOUT, mode
        )
    except Exception as exc:
        logger.exception("manual_scrape_website.unexpected_error key=%s", manual_key)
        return {
            "ok": False,
            "error": f"Scrape failed: {sanitize_error(exc)}",
        }

    if not scraped.ok:
        return {
            "ok": False,
            "error": sanitize_error(scraped.error or "Scrape failed"),
            "manual_key": manual_key,
            "source_url": scraped.source_url,
            "final_url": scraped.final_url,
            "status_code": scraped.status_code,
        }

    try:
        output_dir = await loop.run_in_executor(
            None, save_scraped_assets, manual_key, scraped, LEAD_VAULT_DIR
        )
    except Exception as exc:
        logger.exception("manual_scrape_website.save_error key=%s", manual_key)
        return {
            "ok": False,
            "error": f"Scrape succeeded but save failed: {sanitize_error(exc)}",
        }

    summary = _build_scrape_summary(scraped.to_dict())
    return {
        "ok": True,
        "manual_key": manual_key,
        "output_dir": str(output_dir),
        "scrape": summary,
        "counts": summary["counts"],
        "source_url": scraped.source_url,
        "final_url": scraped.final_url,
        "status_code": scraped.status_code,
    }


@router.post("/scrape-website")
async def scrape_website(request: Request):
    """Scrape a lead's website and persist assets for Phase 3 generation.

    Body:
      lead_key (required): lead identifier already in the store.
      url (optional): override lead's resolved website URL.
      mode (optional): "auto" (default), "static", or "browser".
    """
    try:
        body = await request.json()
    except Exception:
        return {"ok": False, "error": "Request body must be valid JSON."}

    lead_key = str(body.get("lead_key", "") or "").strip()
    if not lead_key:
        return {"ok": False, "error": "Missing lead_key."}

    mode = str(body.get("mode") or "auto").strip().lower()
    if mode not in _ALLOWED_SCRAPE_MODES:
        return {
            "ok": False,
            "error": "mode must be one of: auto, static, browser",
        }

    override_url = str(body.get("url") or "").strip()
    if override_url:
        security_error = _scrape_url_security_error(override_url)
        if security_error:
            return {"ok": False, "error": security_error}

    store = get_store()
    try:
        lead = store.get_lead(lead_key)
    except Exception:
        return {"ok": False, "error": "Lead not found"}
    if not lead:
        return {"ok": False, "error": "Lead not found"}

    url = _lead_website_url(lead, override_url)
    if not url:
        return {
            "ok": False,
            "error": (
                "No website URL on this lead. Resolve the lead's URL or "
                "pass {\"url\": \"...\"} in the request body."
            ),
        }
    security_error = _scrape_url_security_error(url)
    if security_error:
        return {"ok": False, "error": security_error}

    try:
        from lead_vault_scraper import (
            DEFAULT_TIMEOUT,
            save_scraped_assets,
            scrape_site,
        )
        from lead_vault_website_generator import LEAD_VAULT_DIR, sanitize_error
    except ImportError as exc:
        return {
            "ok": False,
            "error": f"Scraper module unavailable: {exc}",
        }

    lock = await _lock_for_lead(lead_key)
    if lock.locked():
        return {
            "ok": False,
            "error": (
                "Another operation is in progress for this lead. Try "
                "again once it finishes."
            ),
        }

    async with lock:
        loop = asyncio.get_running_loop()
        logger.info(
            "scrape_website.start lead_key=%s url_host=%s mode=%s",
            lead_key,
            _safe_host(url),
            mode,
        )
        try:
            scraped = await loop.run_in_executor(
                None, scrape_site, url, DEFAULT_TIMEOUT, mode
            )
        except Exception as exc:
            logger.exception("scrape_website.unexpected_error lead_key=%s", lead_key)
            return {
                "ok": False,
                "error": f"Scrape failed: {sanitize_error(exc)}",
            }

        if not scraped.ok:
            logger.warning(
                "scrape_website.scrape_not_ok lead_key=%s status=%s",
                lead_key,
                scraped.status_code,
            )
            return {
                "ok": False,
                "error": sanitize_error(scraped.error or "Scrape failed"),
                "source_url": scraped.source_url,
                "final_url": scraped.final_url,
                "status_code": scraped.status_code,
            }

        try:
            output_dir = await loop.run_in_executor(
                None, save_scraped_assets, lead_key, scraped, LEAD_VAULT_DIR
            )
        except Exception as exc:
            logger.exception("scrape_website.save_error lead_key=%s", lead_key)
            return {
                "ok": False,
                "error": f"Scrape succeeded but save failed: {sanitize_error(exc)}",
            }

        logger.info(
            "scrape_website.success lead_key=%s bytes=%d photos=%d",
            lead_key,
            len(scraped.main_text or ""),
            len(scraped.photos),
        )
        return {
            "ok": True,
            "lead_key": lead_key,
            "source_url": scraped.source_url,
            "final_url": scraped.final_url,
            "status_code": scraped.status_code,
            "output_dir": str(output_dir),
            "counts": {
                "photos": len(scraped.photos),
                "services": len(scraped.services),
                "phones": len(scraped.phones),
                "emails": len(scraped.emails),
                "main_text_chars": len(scraped.main_text or ""),
            },
            "business_name": scraped.business_name,
            "title": scraped.title,
        }


def _safe_host(url: str) -> str:
    """Best-effort hostname for logs; never raises."""
    try:
        from urllib.parse import urlparse
        return urlparse(url).hostname or ""
    except Exception:
        return ""


def _read_json_if_exists(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _capped_string_list(value, *, limit: int = 12, max_chars: int = 400) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if not text:
            continue
        out.append(text[:max_chars])
        if len(out) >= limit:
            break
    return out


def _capped_string_dict(value, *, limit: int = 10, max_chars: int = 1024) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, str] = {}
    for key, item in value.items():
        k = str(key or "").strip()[:80]
        v = str(item or "").strip()[:max_chars]
        if not k or not v:
            continue
        out[k] = v
        if len(out) >= limit:
            break
    return out


def _build_scrape_summary(scrape_json: dict, saved_at: str = "") -> dict:
    photos = _capped_string_list(scrape_json.get("photos"), limit=12, max_chars=2048)
    services = _capped_string_list(scrape_json.get("services"), limit=20)
    phones = _capped_string_list(scrape_json.get("phones"), limit=8)
    emails = _capped_string_list(scrape_json.get("emails"), limit=8)
    headings = _capped_string_list(scrape_json.get("headings"), limit=12)
    tech_hints = _capped_string_list(scrape_json.get("tech_hints"), limit=12)
    colors = _capped_string_list(scrape_json.get("colors"), limit=10, max_chars=80)
    fonts = _capped_string_list(scrape_json.get("fonts"), limit=8, max_chars=120)
    social_links = _capped_string_dict(scrape_json.get("social_links"), limit=10)
    crawled_pages = [
        {
            "url": str((page or {}).get("url") or "")[:2048],
            "status_code": (page or {}).get("status_code"),
            "title": str((page or {}).get("title") or "")[:400],
            "text_chars": (page or {}).get("text_chars"),
        }
        for page in (scrape_json.get("crawled_pages") or [])[:8]
        if isinstance(page, dict)
    ]
    crawl_errors = [
        {
            "url": str((err or {}).get("url") or "")[:2048],
            "status_code": (err or {}).get("status_code"),
            "error": str((err or {}).get("error") or "")[:240],
        }
        for err in (scrape_json.get("crawl_errors") or [])[:8]
        if isinstance(err, dict)
    ]
    site_blueprint = _build_site_blueprint_summary(scrape_json.get("site_blueprint") or {})
    main_text = str(scrape_json.get("main_text") or "")
    missing_fields: list[str] = []
    if not scrape_json.get("business_name"):
        missing_fields.append("business_name")
    if not services:
        missing_fields.append("services")
    if not phones and not emails:
        missing_fields.append("contact")
    if not photos:
        missing_fields.append("photos")
    if len(main_text.strip()) < 400:
        missing_fields.append("main_text")

    return {
        "source_url": str(scrape_json.get("source_url") or "")[:2048],
        "final_url": str(scrape_json.get("final_url") or "")[:2048],
        "status_code": scrape_json.get("status_code"),
        "business_name": str(scrape_json.get("business_name") or "")[:400],
        "title": str(scrape_json.get("title") or "")[:400],
        "meta_description": str(scrape_json.get("meta_description") or "")[:800],
        "logo_url": str(scrape_json.get("logo_url") or "")[:2048],
        "favicon_url": str(scrape_json.get("favicon_url") or "")[:2048],
        "has_https": bool(scrape_json.get("has_https")),
        "robots_allowed": bool(scrape_json.get("robots_allowed", True)),
        "services": services,
        "phones": phones,
        "emails": emails,
        "photos": photos,
        "headings": headings,
        "tech_hints": tech_hints,
        "colors": colors,
        "fonts": fonts,
        "social_links": social_links,
        "crawled_pages": crawled_pages,
        "crawl_errors": crawl_errors,
        "site_blueprint": site_blueprint,
        "main_text_preview": main_text.strip()[:700],
        "missing_fields": missing_fields,
        "counts": {
            "photos": len(scrape_json.get("photos") or []),
            "services": len(scrape_json.get("services") or []),
            "phones": len(scrape_json.get("phones") or []),
            "emails": len(scrape_json.get("emails") or []),
            "main_text_chars": len(main_text),
            "crawled_pages": len(scrape_json.get("crawled_pages") or []),
            "blueprint_pages": site_blueprint.get("page_count_observed", 0),
        },
        "saved_at": saved_at,
    }


def _build_site_blueprint_summary(site_blueprint: dict) -> dict:
    if not isinstance(site_blueprint, dict):
        return {}
    pages = [
        {
            "url": str((page or {}).get("url") or "")[:2048],
            "label": str((page or {}).get("label") or "")[:160],
            "role": str((page or {}).get("role") or "other")[:80],
            "source": str((page or {}).get("source") or "")[:80],
            "crawled": bool((page or {}).get("crawled")),
        }
        for page in (site_blueprint.get("pages") or [])[:24]
        if isinstance(page, dict)
    ]
    skipped_pages = [
        {
            "url": str((page or {}).get("url") or "")[:2048],
            "label": str((page or {}).get("label") or "")[:160],
            "reason": str((page or {}).get("reason") or "")[:160],
        }
        for page in (site_blueprint.get("skipped_pages") or [])[:24]
        if isinstance(page, dict)
    ]
    recommended_pages = [
        {
            "role": str((page or {}).get("role") or "")[:80],
            "title": str((page or {}).get("title") or "")[:160],
            "reason": str((page or {}).get("reason") or "")[:240],
        }
        for page in (site_blueprint.get("recommended_pages") or [])[:12]
        if isinstance(page, dict)
    ]
    forms = site_blueprint.get("forms") if isinstance(site_blueprint.get("forms"), dict) else {}
    return {
        "version": site_blueprint.get("version"),
        "base_url": str(site_blueprint.get("base_url") or "")[:2048],
        "page_count_observed": int(site_blueprint.get("page_count_observed") or 0),
        "content_page_count": int(site_blueprint.get("content_page_count") or 0),
        "observed_roles": _capped_string_list(site_blueprint.get("observed_roles"), limit=16),
        "role_counts": site_blueprint.get("role_counts") or {},
        "pages": pages,
        "skipped_pages": skipped_pages,
        "forms": {
            "forms": int(forms.get("forms") or 0),
            "auth_forms": int(forms.get("auth_forms") or 0),
            "contact_forms": int(forms.get("contact_forms") or 0),
            "form_types": _capped_string_list(forms.get("form_types"), limit=8),
        },
        "recommended_pages": recommended_pages,
        "auth_detected": bool(site_blueprint.get("auth_detected")),
        "multi_page_detected": bool(site_blueprint.get("multi_page_detected")),
        "generator_fit": str(site_blueprint.get("generator_fit") or "")[:120],
        "risk_flags": _capped_string_list(site_blueprint.get("risk_flags"), limit=16),
    }


def _lead_business_type_for_design_brief(lead: dict) -> str:
    data = lead.get("data") if isinstance(lead.get("data"), dict) else {}
    for candidate in (
        data.get("Business Type"),
        data.get("Category"),
        lead.get("business_type"),
    ):
        value = str(candidate or "").strip()
        if value:
            return value[:400]
    return ""


def _lead_business_name_for_design_brief(lead: dict, brief: dict) -> str:
    data = lead.get("data") if isinstance(lead.get("data"), dict) else {}
    for candidate in (
        brief.get("business_name"),
        lead.get("business_name"),
        data.get("Business Name"),
        data.get("Name"),
    ):
        value = str(candidate or "").strip()
        if value:
            return value[:400]
    return "Business"


def _site_design_brief_shape_error(brief: object) -> str:
    if not isinstance(brief, dict):
        return "Design brief must be a JSON object."
    required = (
        "site_dna",
        "experience_dna",
        "layout_strategy",
        "creative_variation",
    )
    missing = [
        key for key in required
        if not isinstance(brief.get(key), dict)
    ]
    if missing:
        return "Design brief is missing: " + ", ".join(missing)
    return ""


def _site_design_brief_summary(
    brief: dict | None,
    *,
    source: str = "",
    path_name: str = "",
) -> dict | None:
    if not isinstance(brief, dict):
        return None
    experience = brief.get("experience_dna")
    site_dna = brief.get("site_dna")
    creative = brief.get("creative_variation")
    review = brief.get("review_status")
    experience = experience if isinstance(experience, dict) else {}
    site_dna = site_dna if isinstance(site_dna, dict) else {}
    creative = creative if isinstance(creative, dict) else {}
    review = review if isinstance(review, dict) else {}
    return {
        "exists": True,
        "source": source,
        "path": path_name,
        "business_name": str(brief.get("business_name") or "")[:400],
        "category": str(site_dna.get("category") or "")[:120],
        "archetype_key": str(experience.get("archetype_key") or "")[:120],
        "archetype_label": str(experience.get("archetype_label") or "")[:160],
        "motion_level": str(experience.get("motion_level") or "")[:80],
        "hero_system": str(creative.get("hero_system") or "")[:160],
        "nav_system": str(creative.get("nav_system") or "")[:160],
        "approved_by_user": bool(review.get("approved_by_user")),
        "saved_in_website_studio": bool(review.get("saved_in_website_studio")),
        "saved_at": str(review.get("saved_at") or "")[:80],
        "generated_at": str(brief.get("generated_at") or "")[:80],
    }


def _inject_preview_highlight(html: str, section_id: str) -> str:
    """Inject a transient editor highlight into sandboxed mockup preview HTML."""
    if not section_id or not _SECTION_ID_RE.fullmatch(section_id):
        return html

    style = """
<style id="summit-preview-highlight-style">
[data-summit-section].summit-edit-highlight {
  position: relative !important;
  outline: 4px solid #f97316 !important;
  outline-offset: -4px !important;
  box-shadow: 0 0 0 9999px rgba(0,0,0,.18), 0 0 0 10px rgba(249,115,22,.24) !important;
  z-index: 2147483000 !important;
}
[data-summit-section].summit-edit-highlight::before {
  content: "Editing: " attr(data-summit-label);
  position: absolute !important;
  top: 10px !important;
  left: 10px !important;
  z-index: 2147483001 !important;
  padding: 6px 10px !important;
  border-radius: 8px !important;
  background: #f97316 !important;
  color: #fff !important;
  font: 700 12px/1.2 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif !important;
  letter-spacing: .02em !important;
  box-shadow: 0 8px 24px rgba(0,0,0,.22) !important;
  pointer-events: none !important;
}
@media (prefers-reduced-motion: reduce) {
  [data-summit-section].summit-edit-highlight { scroll-margin-top: 24px !important; }
}
</style>
""".strip()
    script = f"""
<script id="summit-preview-highlight-script">
(() => {{
  const sectionId = {json.dumps(section_id)};
  const selector = `[data-summit-section="${{sectionId}}"]`;
  const target = document.querySelector(selector);
  if (!target) return;
  target.classList.add('summit-edit-highlight');
  target.scrollIntoView({{ behavior: 'smooth', block: 'center', inline: 'nearest' }});
}})();
</script>
""".strip()

    injected = html
    if re.search(r"</head\s*>", injected, flags=re.IGNORECASE):
        injected = re.sub(
            r"</head\s*>",
            style + "\n</head>",
            injected,
            count=1,
            flags=re.IGNORECASE,
        )
    else:
        injected = style + "\n" + injected

    if re.search(r"</body\s*>", injected, flags=re.IGNORECASE):
        injected = re.sub(
            r"</body\s*>",
            script + "\n</body>",
            injected,
            count=1,
            flags=re.IGNORECASE,
        )
    else:
        injected = injected + "\n" + script
    return injected


@router.get("/website-packages")
async def website_packages():
    """List generated website packages for the Website Studio index."""
    try:
        from lead_vault_website_generator import (
            DEFAULT_GENERATED_DIR,
            MULTI_PAGE_EXPORT_DIR,
            SITE_PLAN_FILE,
        )
    except ImportError as exc:
        return {"ok": False, "error": f"Generator module unavailable: {exc}"}

    generated_root = Path(DEFAULT_GENERATED_DIR)
    if not generated_root.exists():
        return {"ok": True, "packages": []}

    lead_by_safe_key: dict[str, dict] = {}
    try:
        store = get_store()
        for lead in store.list_leads():
            key = str(lead.get("lead_key") or "").strip()
            if key:
                lead_by_safe_key[_safe_lead_key(key)] = lead
    except Exception:
        lead_by_safe_key = {}

    packages: list[dict] = []
    try:
        folders = [path for path in generated_root.iterdir() if path.is_dir()]
    except OSError:
        folders = []

    for folder in folders:
        safe_key = folder.name
        mockup_path = _resolve_inside(generated_root, safe_key, "mockup.html")
        if not mockup_path or not mockup_path.exists():
            continue

        lead = lead_by_safe_key.get(safe_key)
        meta = _read_json_if_exists(folder / "meta.json") or {}
        lead_key = str(
            (lead or {}).get("lead_key")
            or meta.get("lead_key")
            or safe_key
        )
        data = (lead or {}).get("data") or (lead or {}).get("data_json") or {}
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                data = {}
        if not isinstance(data, dict):
            data = {}

        site_plan = _read_json_if_exists(folder / SITE_PLAN_FILE) or {}
        validation = _read_json_if_exists(folder / "validation.json") or {}
        export_dir = folder / MULTI_PAGE_EXPORT_DIR
        export_manifest = _read_json_if_exists(export_dir / "export_manifest.json") or {}
        page_count = 0
        if export_dir.exists():
            try:
                page_count = len([path for path in export_dir.glob("*.html")])
            except OSError:
                page_count = 0

        packages.append({
            "lead_key": lead_key,
            "safe_key": safe_key,
            "lead_exists": bool(lead),
            "orphaned_package": not bool(lead),
            "business_name": (
                (lead or {}).get("business_name")
                or data.get("Business Name")
                or meta.get("business_name")
                or safe_key.replace("_", " ").title()
            ),
            "city_area": (lead or {}).get("city_area") or data.get("City/Area") or "",
            "website_bucket": (lead or {}).get("last_web_presence_status") or data.get("Web Presence Status") or "",
            "pipeline_status": (lead or {}).get("pipeline_status") or ("Generated package only" if not lead else ""),
            "generated_at": _mtime_iso(mockup_path),
            "bytes": mockup_path.stat().st_size,
            "model": meta.get("model") or "",
            "category": meta.get("category") or "",
            "generation_mode": meta.get("generation_mode") or site_plan.get("mode") or "",
            "multi_page_export_enabled": bool(meta.get("multi_page_export_enabled") or page_count),
            "page_count": page_count,
            "export_kind": export_manifest.get("kind") or "",
            "validation_passed": validation.get("passed") if validation else None,
            "error_count": validation.get("error_count", 0) if validation else 0,
            "warning_count": validation.get("warning_count", 0) if validation else 0,
            "studio_url": f"/website-studio/{quote(lead_key, safe='')}",
            "lead_url": f"/leads/{quote(lead_key, safe='')}",
        })

    packages.sort(key=lambda item: item.get("generated_at") or "", reverse=True)
    return {"ok": True, "packages": packages}


@router.delete("/website-package/{lead_key}")
async def delete_website_package(lead_key: str):
    """Delete a generated Website Studio package without deleting the lead."""
    lead_key = str(lead_key or "").strip()
    if not lead_key:
        return JSONResponse(
            {"ok": False, "error": "Missing lead_key."}, status_code=400
        )

    try:
        from lead_vault_website_generator import DEFAULT_GENERATED_DIR, sanitize_error
    except ImportError as exc:
        return JSONResponse(
            {"ok": False, "error": f"Generator module unavailable: {exc}"},
            status_code=500,
        )

    safe_key = _safe_lead_key(lead_key)
    output_dir = _resolve_inside(DEFAULT_GENERATED_DIR, safe_key)
    if output_dir is None:
        return JSONResponse(
            {"ok": False, "error": "Invalid lead key."}, status_code=400
        )
    if not output_dir.exists() or not output_dir.is_dir():
        return JSONResponse(
            {"ok": False, "error": "Generated website package not found."},
            status_code=404,
        )

    lock = await _lock_for_lead(lead_key)
    if lock.locked():
        return {
            "ok": False,
            "error": "Another operation is in progress for this website. Try again once it finishes.",
        }

    async with lock:
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, shutil.rmtree, output_dir)
        except OSError as exc:
            return JSONResponse(
                {"ok": False, "error": f"Delete failed: {sanitize_error(exc)}"},
                status_code=500,
            )

    return {
        "ok": True,
        "lead_key": lead_key,
        "safe_key": safe_key,
        "deleted": True,
    }


@router.get("/website-package/{lead_key}")
async def website_package_status(lead_key: str):
    """Report scrape + generate + validation state for a lead.

    Used by the Phase 6 UI to populate the Website Package tab without
    triggering any external work. Does not mutate anything.
    """
    lead_key = str(lead_key or "").strip()
    if not lead_key:
        return JSONResponse(
            {"ok": False, "error": "Missing lead_key."}, status_code=400
        )

    store = get_store()
    try:
        lead = store.get_lead(lead_key)
    except Exception:
        lead = None

    try:
        from lead_vault_website_generator import (
            DEFAULT_GENERATED_DIR,
            DEFAULT_SCRAPED_DIR,
            EDIT_MANIFEST_FILE,
            MULTI_PAGE_EXPORT_DIR,
            SITE_DESIGN_BRIEF_FILE,
            SITE_PLAN_FILE,
            build_edit_manifest,
            list_mockup_versions,
            sanitize_error,
        )
    except ImportError as exc:
        return {"ok": False, "error": f"Generator module unavailable: {exc}"}

    safe_key = _safe_lead_key(lead_key)
    output_dir = _resolve_inside(DEFAULT_GENERATED_DIR, safe_key)
    scrape_path = _resolve_inside(DEFAULT_SCRAPED_DIR, safe_key, "scrape.json")
    mockup_path = _resolve_inside(DEFAULT_GENERATED_DIR, safe_key, "mockup.html")
    meta_path = _resolve_inside(DEFAULT_GENERATED_DIR, safe_key, "meta.json")
    site_plan_path = _resolve_inside(
        DEFAULT_GENERATED_DIR, safe_key, SITE_PLAN_FILE
    )
    site_design_brief_path = _resolve_inside(
        DEFAULT_GENERATED_DIR, safe_key, SITE_DESIGN_BRIEF_FILE
    )
    multi_page_export_dir = _resolve_inside(
        DEFAULT_GENERATED_DIR, safe_key, MULTI_PAGE_EXPORT_DIR
    )
    manifest_path = _resolve_inside(
        DEFAULT_GENERATED_DIR, safe_key, EDIT_MANIFEST_FILE
    )
    validation_path = _resolve_inside(
        DEFAULT_GENERATED_DIR, safe_key, "validation.json"
    )
    preview_qa_path = _resolve_inside(
        DEFAULT_GENERATED_DIR, safe_key, "preview_qa", "preview_qa.json"
    )
    marketing_brief_path = _resolve_inside(
        DEFAULT_GENERATED_DIR, safe_key, "marketing_brief.json"
    )
    design_review_path = _resolve_inside(
        DEFAULT_GENERATED_DIR, safe_key, "design_review.json"
    )
    generation_error_path = _resolve_inside(
        DEFAULT_GENERATED_DIR, safe_key, "generation_error.json"
    )
    package_exists = bool(
        (mockup_path and mockup_path.exists())
        or (scrape_path and scrape_path.exists())
    )
    if not lead and not package_exists:
        return JSONResponse(
            {"ok": False, "error": "Lead not found"}, status_code=404
        )

    scrape_summary: dict | None = None
    if scrape_path and scrape_path.exists():
        scrape_json = _read_json_if_exists(scrape_path) or {}
        scrape_summary = _build_scrape_summary(scrape_json, _mtime_iso(scrape_path))

    generated_summary: dict | None = None
    edit_manifest: dict | None = None
    versions: list[dict] = []
    if mockup_path and mockup_path.exists():
        meta = _read_json_if_exists(meta_path) if meta_path else None
        site_plan = _read_json_if_exists(site_plan_path) if site_plan_path else None
        export_files: list[dict[str, str]] = []
        export_manifest: dict = {}
        if multi_page_export_dir and multi_page_export_dir.exists():
            manifest_file = multi_page_export_dir / "export_manifest.json"
            export_manifest = _read_json_if_exists(manifest_file) or {}
            for path in sorted(multi_page_export_dir.glob("*.html"))[:20]:
                export_files.append({
                    "filename": path.name,
                    "path": f"{MULTI_PAGE_EXPORT_DIR}/{path.name}",
                })
        generated_summary = {
            "meta": meta or {},
            "generated_at": _mtime_iso(mockup_path),
            "bytes": mockup_path.stat().st_size,
            "site_plan": site_plan or {},
            "multi_page_export": {
                "exists": bool(export_files),
                "files": export_files,
                "manifest": export_manifest,
            },
        }
        if manifest_path and manifest_path.exists():
            edit_manifest = _read_json_if_exists(manifest_path)
        if edit_manifest is None:
            try:
                edit_manifest = build_edit_manifest(
                    mockup_path.read_text(encoding="utf-8")
                )
            except OSError:
                edit_manifest = None
        if output_dir:
            versions = list_mockup_versions(output_dir)

    validation_summary: dict | None = None
    if validation_path and validation_path.exists():
        validation_summary = _read_json_if_exists(validation_path)

    preview_qa_summary: dict | None = None
    if preview_qa_path and preview_qa_path.exists():
        preview_qa_summary = _read_json_if_exists(preview_qa_path)

    marketing_brief_summary: dict | None = None
    if marketing_brief_path and marketing_brief_path.exists():
        marketing_brief_summary = _read_json_if_exists(marketing_brief_path)

    design_review_summary: dict | None = None
    if design_review_path and design_review_path.exists():
        design_review_summary = _read_json_if_exists(design_review_path)

    generation_error = None
    if generation_error_path and generation_error_path.exists():
        generation_error = _read_json_if_exists(generation_error_path)
        if isinstance(generation_error, dict) and generation_error.get("error"):
            generation_error = dict(generation_error)
            generation_error["error"] = sanitize_error(generation_error.get("error"))

    design_brief_summary = None
    if site_design_brief_path and site_design_brief_path.exists():
        design_brief = _read_json_if_exists(site_design_brief_path)
        review = (
            design_brief.get("review_status")
            if isinstance(design_brief, dict)
            else {}
        )
        source = (
            "saved_user_approved"
            if isinstance(review, dict) and review.get("approved_by_user")
            else "saved_generated"
        )
        design_brief_summary = _site_design_brief_summary(
            design_brief,
            source=source,
            path_name=site_design_brief_path.name,
        )

    return {
        "ok": True,
        "lead_key": lead_key,
        "safe_key": safe_key,
        "lead_exists": bool(lead),
        "orphaned_package": not bool(lead),
        "scraped": scrape_summary is not None,
        "generated": generated_summary is not None,
        "scrape": scrape_summary,
        "generated_info": generated_summary,
        "validation": validation_summary,
        "preview_qa": preview_qa_summary,
        "marketing_brief": marketing_brief_summary,
        "design_review": design_review_summary,
        "generation_error": generation_error,
        "design_brief": design_brief_summary,
        "edit_manifest": edit_manifest,
        "versions": versions,
    }


@router.get("/design-kits")
async def design_kits():
    try:
        from design_kit_library import DesignKitLibrary
    except ImportError as exc:
        return JSONResponse(
            {"ok": False, "error": f"Design kit module unavailable: {exc}"},
            status_code=500,
        )
    lib = DesignKitLibrary()
    kits = [lib.load(key).to_dict() for key in lib.list_kits()]
    return {"ok": True, "kits": kits}


@router.get("/section-grammar")
async def section_grammar():
    try:
        from section_grammar_library import SectionGrammarLibrary
    except ImportError as exc:
        return JSONResponse(
            {"ok": False, "error": f"Section grammar module unavailable: {exc}"},
            status_code=500,
        )
    lib = SectionGrammarLibrary()
    sections = []
    for section_type in lib.list_section_types():
        moves = [move.to_dict() for move in lib.load_section_type(section_type)]
        sections.append({"section_type": section_type, "moves": moves})
    return {"ok": True, "sections": sections}


@router.get("/website-package/{lead_key}/marketing-brief")
async def website_package_marketing_brief(lead_key: str):
    lead_key = str(lead_key or "").strip()
    if not lead_key:
        return JSONResponse(
            {"ok": False, "error": "Missing lead_key."}, status_code=400
        )

    store = get_store()
    try:
        lead = store.get_lead(lead_key)
    except Exception:
        lead = None

    try:
        from lead_vault_website_generator import DEFAULT_GENERATED_DIR
        from marketing_skill_bridge import MARKETING_BRIEF_FILE
    except ImportError as exc:
        return JSONResponse(
            {"ok": False, "error": f"Marketing brief module unavailable: {exc}"},
            status_code=500,
        )

    safe_key = _safe_lead_key(lead_key)
    path = _resolve_inside(DEFAULT_GENERATED_DIR, safe_key, MARKETING_BRIEF_FILE)
    if path is None:
        return JSONResponse(
            {"ok": False, "error": "Invalid lead key."}, status_code=400
        )
    if not path.exists():
        return JSONResponse(
            {"ok": False, "error": "Marketing brief not found."},
            status_code=404,
        )
    brief = _read_json_if_exists(path)
    if brief is None:
        return JSONResponse(
            {"ok": False, "error": "Marketing brief could not be read."},
            status_code=500,
        )
    return {
        "ok": True,
        "lead_key": lead_key,
        "safe_key": safe_key,
        "path": MARKETING_BRIEF_FILE,
        "brief": brief,
    }


@router.get("/website-package/{lead_key}/design-review")
async def website_package_design_review(lead_key: str):
    lead_key = str(lead_key or "").strip()
    if not lead_key:
        return JSONResponse(
            {"ok": False, "error": "Missing lead_key."}, status_code=400
        )

    store = get_store()
    try:
        lead = store.get_lead(lead_key)
    except Exception:
        lead = None

    try:
        from design_review_agent import DESIGN_REVIEW_FILE
        from lead_vault_website_generator import DEFAULT_GENERATED_DIR
    except ImportError as exc:
        return JSONResponse(
            {"ok": False, "error": f"Design review module unavailable: {exc}"},
            status_code=500,
        )

    safe_key = _safe_lead_key(lead_key)
    path = _resolve_inside(DEFAULT_GENERATED_DIR, safe_key, DESIGN_REVIEW_FILE)
    if path is None:
        return JSONResponse(
            {"ok": False, "error": "Invalid lead key."}, status_code=400
        )
    if not path.exists():
        return JSONResponse(
            {"ok": False, "error": "Design review not found."},
            status_code=404,
        )
    review = _read_json_if_exists(path)
    if review is None:
        return JSONResponse(
            {"ok": False, "error": "Design review could not be read."},
            status_code=500,
        )
    return {
        "ok": True,
        "lead_key": lead_key,
        "safe_key": safe_key,
        "path": DESIGN_REVIEW_FILE,
        "review": review,
    }


@router.get("/website-package/{lead_key}/design-brief")
async def website_package_design_brief(lead_key: str, refresh: bool = False):
    """Return the saved design brief, or preview one from the current scrape."""
    lead_key = str(lead_key or "").strip()
    if not lead_key:
        return JSONResponse(
            {"ok": False, "error": "Missing lead_key."}, status_code=400
        )

    store = get_store()
    try:
        lead = store.get_lead(lead_key)
    except Exception:
        lead = None

    try:
        from lead_vault_website_generator import (
            DEFAULT_GENERATED_DIR,
            DEFAULT_SCRAPED_DIR,
            SITE_DESIGN_BRIEF_FILE,
            WebsiteGeneratorError,
            build_site_design_brief,
            build_site_generation_plan,
            load_profile,
            load_scraped_assets,
            load_site_design_brief,
            sanitize_error,
        )
    except ImportError as exc:
        return {"ok": False, "error": f"Generator module unavailable: {exc}"}

    safe_key = _safe_lead_key(lead_key)
    output_dir = _resolve_inside(DEFAULT_GENERATED_DIR, safe_key)
    scrape_path = _resolve_inside(DEFAULT_SCRAPED_DIR, safe_key, "scrape.json")
    if output_dir is None or scrape_path is None:
        return JSONResponse(
            {"ok": False, "error": "Invalid lead key."}, status_code=400
        )

    if not refresh:
        saved_brief = load_site_design_brief(output_dir, lead_key=lead_key)
        if saved_brief is not None:
            review = saved_brief.get("review_status")
            source = (
                "saved_user_approved"
                if isinstance(review, dict) and review.get("approved_by_user")
                else "saved_generated"
            )
            return {
                "ok": True,
                "lead_key": lead_key,
                "safe_key": safe_key,
                "source": source,
                "saved": True,
                "path": SITE_DESIGN_BRIEF_FILE,
                "summary": _site_design_brief_summary(
                    saved_brief,
                    source=source,
                    path_name=SITE_DESIGN_BRIEF_FILE,
                ),
                "brief": saved_brief,
            }

    if not scrape_path.exists():
        return JSONResponse(
            {
                "ok": False,
                "error": "Scrape this lead before building a design brief.",
            },
            status_code=404,
        )

    try:
        scraped = load_scraped_assets(lead_key, DEFAULT_SCRAPED_DIR)
        inspiration = load_profile(_lead_business_type_for_design_brief(lead))
        site_plan = build_site_generation_plan(lead, scraped, inspiration)
        brief = build_site_design_brief(lead, scraped, inspiration, site_plan)
    except WebsiteGeneratorError as exc:
        return JSONResponse(
            {"ok": False, "error": sanitize_error(str(exc))},
            status_code=400,
        )
    except Exception as exc:
        logger.exception("website_design_brief.preview_error lead_key=%s", lead_key)
        return JSONResponse(
            {"ok": False, "error": f"Design brief failed: {sanitize_error(exc)}"},
            status_code=500,
        )

    review = dict(brief.get("review_status") or {})
    review.update({
        "editable_in_website_studio": True,
        "approved_by_user": False,
        "saved_in_website_studio": False,
        "notes": "Preview from current scrape. Save it to use this brief for generation.",
    })
    brief["review_status"] = review
    return {
        "ok": True,
        "lead_key": lead_key,
        "safe_key": safe_key,
        "source": "preview_from_scrape",
        "saved": False,
        "path": "",
        "summary": _site_design_brief_summary(
            brief,
            source="preview_from_scrape",
            path_name="",
        ),
        "brief": brief,
    }


@router.post("/website-package/{lead_key}/design-brief")
async def save_website_package_design_brief(lead_key: str, request: Request):
    """Persist a user-reviewed design brief for the next generation."""
    lead_key = str(lead_key or "").strip()
    if not lead_key:
        return JSONResponse(
            {"ok": False, "error": "Missing lead_key."}, status_code=400
        )

    store = get_store()
    try:
        lead = store.get_lead(lead_key)
    except Exception:
        lead = None

    try:
        body = await request.json()
    except json.JSONDecodeError:
        body = {}
    raw_brief = body.get("brief") if isinstance(body, dict) else None
    if raw_brief is None and isinstance(body, dict):
        raw_brief = body
    shape_error = _site_design_brief_shape_error(raw_brief)
    if shape_error:
        return JSONResponse(
            {"ok": False, "error": shape_error},
            status_code=400,
        )
    try:
        brief = json.loads(json.dumps(raw_brief, ensure_ascii=False))
    except (TypeError, ValueError):
        return JSONResponse(
            {"ok": False, "error": "Design brief must be JSON serializable."},
            status_code=400,
        )
    if len(json.dumps(brief, ensure_ascii=False)) > 400_000:
        return JSONResponse(
            {"ok": False, "error": "Design brief is too large to save."},
            status_code=400,
        )

    try:
        from lead_vault_website_generator import (
            DEFAULT_GENERATED_DIR,
            SITE_DESIGN_BRIEF_FILE,
            write_site_design_brief,
        )
    except ImportError as exc:
        return {"ok": False, "error": f"Generator module unavailable: {exc}"}

    safe_key = _safe_lead_key(lead_key)
    output_dir = _resolve_inside(DEFAULT_GENERATED_DIR, safe_key)
    if output_dir is None:
        return JSONResponse(
            {"ok": False, "error": "Invalid lead key."}, status_code=400
        )

    brief["lead_key"] = lead_key
    brief["business_name"] = _lead_business_name_for_design_brief(lead, brief)
    review = dict(brief.get("review_status") or {})
    review.update({
        "editable_in_website_studio": True,
        "approved_by_user": True,
        "saved_in_website_studio": True,
        "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    brief["review_status"] = review

    try:
        brief_path = write_site_design_brief(brief, output_dir)
    except OSError as exc:
        return JSONResponse(
            {"ok": False, "error": f"Could not save design brief: {exc}"},
            status_code=500,
        )

    return {
        "ok": True,
        "lead_key": lead_key,
        "safe_key": safe_key,
        "source": "saved_user_approved",
        "saved": True,
        "path": SITE_DESIGN_BRIEF_FILE,
        "summary": _site_design_brief_summary(
            brief,
            source="saved_user_approved",
            path_name=brief_path.name,
        ),
        "brief": brief,
    }


@router.post("/website-package/{lead_key}/preview-qa")
async def website_package_preview_qa(lead_key: str):
    """Capture desktop/mobile mockup screenshots and layout/runtime checks."""
    lead_key = str(lead_key or "").strip()
    if not lead_key:
        return JSONResponse(
            {"ok": False, "error": "Missing lead_key."}, status_code=400
        )

    store = get_store()
    try:
        lead = store.get_lead(lead_key)
    except Exception:
        lead = None

    try:
        from lead_vault_preview_qa import run_preview_qa
        from lead_vault_website_generator import DEFAULT_GENERATED_DIR
    except ImportError as exc:
        return JSONResponse(
            {"ok": False, "error": f"Preview QA module unavailable: {exc}"},
            status_code=500,
        )

    safe_key = _safe_lead_key(lead_key)
    output_dir = _resolve_inside(DEFAULT_GENERATED_DIR, safe_key)
    mockup_path = _resolve_inside(DEFAULT_GENERATED_DIR, safe_key, "mockup.html")
    if output_dir is None or mockup_path is None:
        return JSONResponse(
            {"ok": False, "error": "Invalid lead key."}, status_code=400
        )
    if not mockup_path.exists() or not mockup_path.is_file():
        return JSONResponse(
            {"ok": False, "error": "Generate a mockup before running preview QA."},
            status_code=404,
        )

    lock = await _lock_for_lead(lead_key)
    if lock.locked():
        return {
            "ok": False,
            "error": "Another operation is in progress for this lead. Try again once it finishes.",
        }

    async with lock:
        loop = asyncio.get_running_loop()
        report = await loop.run_in_executor(
            None,
            run_preview_qa,
            mockup_path,
            output_dir,
        )
    return report


@router.get("/website-package/{lead_key}/mockup")
async def website_package_mockup(lead_key: str, highlight: str = ""):
    """Serve the generated mockup.html for iframe preview.

    The UI renders this inside an iframe with ``sandbox="allow-scripts"``
    (no ``allow-same-origin``) so the mockup executes in a unique origin
    and cannot reach the app's cookies, storage, or API.

    Path traversal defenses:
      1. ``lead_key`` is normalized through ``_safe_lead_key`` which
         strips everything outside [A-Za-z0-9_-].
      2. ``_resolve_inside`` re-validates the resolved path is under the
         generated/ root, catching symlinks or edge cases.
    The response also enforces a CSP sandbox, including when opened directly
    in a tab. Existing generated packages may outlive their database lead.
    """
    lead_key = str(lead_key or "").strip()
    if not lead_key:
        return JSONResponse(
            {"ok": False, "error": "Missing lead_key."}, status_code=400
        )

    store = get_store()
    try:
        lead = store.get_lead(lead_key)
    except Exception:
        lead = None

    try:
        from lead_vault_website_generator import DEFAULT_GENERATED_DIR
    except ImportError as exc:
        return JSONResponse(
            {"ok": False, "error": f"Generator module unavailable: {exc}"},
            status_code=500,
        )

    safe_key = _safe_lead_key(lead_key)
    mockup_path = _resolve_inside(DEFAULT_GENERATED_DIR, safe_key, "mockup.html")
    if mockup_path is None:
        return JSONResponse(
            {"ok": False, "error": "Invalid lead key."}, status_code=400
        )
    if not mockup_path.exists() or not mockup_path.is_file():
        return JSONResponse(
            {"ok": False, "error": "No mockup generated for this lead yet."},
            status_code=404,
        )

    if highlight:
        try:
            html = mockup_path.read_text(encoding="utf-8")
        except OSError:
            return JSONResponse(
                {"ok": False, "error": "Could not read mockup."},
                status_code=500,
            )
        return HTMLResponse(
            _inject_preview_highlight(html, highlight),
            headers={
                "Content-Security-Policy": PREVIEW_CSP,
                "Cache-Control": "no-store, max-age=0",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
            },
        )

    return FileResponse(
        mockup_path,
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Security-Policy": PREVIEW_CSP,
            "Cache-Control": "no-store, max-age=0",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        },
    )


@router.get("/website-package/{lead_key}/files/{asset_path:path}")
async def website_package_generated_file(lead_key: str, asset_path: str):
    """Serve safe generated website assets for multi-page previews.

    Only static front-end asset suffixes are allowed. This keeps the
    preview flexible enough for secondary HTML pages, CSS, JS, and image
    assets without turning the generated/ folder into a general-purpose
    file server for reports or metadata.
    """
    lead_key = str(lead_key or "").strip()
    if not lead_key:
        return JSONResponse(
            {"ok": False, "error": "Missing lead_key."}, status_code=400
        )

    asset_path = str(asset_path or "").strip().lstrip("/\\")
    if not asset_path:
        return JSONResponse(
            {"ok": False, "error": "Missing asset path."}, status_code=400
        )

    raw_parts = [part for part in re.split(r"[\\/]+", asset_path) if part]
    if not raw_parts or any(part in (".", "..") for part in raw_parts):
        return JSONResponse(
            {"ok": False, "error": "Invalid asset path."}, status_code=400
        )

    suffix = Path(raw_parts[-1]).suffix.lower()
    if suffix not in _ALLOWED_GENERATED_FILE_SUFFIXES:
        return JSONResponse(
            {"ok": False, "error": "Unsupported asset type."}, status_code=404
        )

    store = get_store()
    try:
        lead = store.get_lead(lead_key)
    except Exception:
        lead = None

    try:
        from lead_vault_website_generator import DEFAULT_GENERATED_DIR
    except ImportError as exc:
        return JSONResponse(
            {"ok": False, "error": f"Generator module unavailable: {exc}"},
            status_code=500,
        )

    safe_key = _safe_lead_key(lead_key)
    asset_file = _resolve_inside(DEFAULT_GENERATED_DIR, safe_key, *raw_parts)
    if asset_file is None:
        return JSONResponse(
            {"ok": False, "error": "Invalid asset path."}, status_code=400
        )
    if not asset_file.exists() or not asset_file.is_file():
        return JSONResponse(
            {"ok": False, "error": "Generated asset not found."},
            status_code=404,
        )

    return FileResponse(
        asset_file,
        headers={
            "Content-Security-Policy": PREVIEW_CSP,
            "Cache-Control": "no-store, max-age=0",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        },
    )


def _mtime_iso(path: Path) -> str:
    try:
        from datetime import datetime, timezone
        ts = path.stat().st_mtime
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(
            timespec="seconds"
        )
    except Exception:
        return ""


# ── Phase 5: Report + Email package ────────────────────────────────────


@router.post("/generate-report-package")
async def generate_report_package(request: Request):
    """Produce report.pdf, email.md, and comparison screenshots for a lead.

    Assumes `/generate-website-package` has already produced mockup.html
    for this lead. Captures screenshots of the current site + the
    generated mockup, assembles a side-by-side PDF, and drafts a short
    outreach email via the selected AI provider (falls back to a template if the API
    key is missing so the PDF is still useful on its own).
    """
    body = await request.json()
    lead_key = str(body.get("lead_key", "") or "").strip()
    if not lead_key:
        return {"ok": False, "error": "Missing lead_key."}

    settings = load_settings()
    provider, email_model = _resolve_provider_model(
        body,
        settings,
        default_provider="OpenAI",
        openai_default="gpt-5.4-mini",
        anthropic_default="claude-sonnet-4-6",
    )
    if provider == "OpenAI":
        api_key = (
            body.get("ai_api_key")
            or settings.get("openai_api_key", "")
            or settings.get("ai_api_key", "")
            or ""
        )
    else:
        api_key = (
            body.get("ai_api_key")
            or settings.get("anthropic_api_key", "")
            or settings.get("ai_api_key", "")
            or ""
        )

    store = get_store()
    try:
        lead = store.get_lead(lead_key)
    except Exception:
        return {"ok": False, "error": "Lead not found"}
    if not lead:
        return {"ok": False, "error": "Lead not found"}

    try:
        from lead_vault_report_generator import (
            ReportGenerator,
            ReportGeneratorError,
        )
        from lead_vault_website_generator import sanitize_error
    except ImportError as exc:
        return {
            "ok": False,
            "error": f"Report generator module unavailable: {exc}",
        }

    lock = await _lock_for_lead(f"report:{lead_key}")
    if lock.locked():
        return {
            "ok": False,
            "error": "A report is already being generated for this lead.",
        }

    async with lock:
        loop = asyncio.get_running_loop()
        generator = ReportGenerator(
            api_key=api_key,
            email_model=email_model,
            email_provider=provider,
        )
        try:
            package = await loop.run_in_executor(None, generator.generate, lead)
        except ReportGeneratorError as exc:
            logger.warning("report_package.generate_error lead_key=%s", lead_key)
            return {"ok": False, "error": sanitize_error(str(exc))}
        except Exception as exc:
            logger.exception("report_package.unexpected_error lead_key=%s", lead_key)
            return {
                "ok": False,
                "error": f"Report generation failed: {sanitize_error(exc)}",
            }

        return {
            "ok": True,
            "lead_key": package.lead_key,
            "output_dir": str(package.output_dir),
            "report_pdf": str(package.report_pdf),
            "email_md": str(package.email_md),
            "meta": package.meta,
        }


@router.get("/report-package/{lead_key}")
async def report_package_status(lead_key: str):
    """Read-only status of the report + email artifacts for a lead."""
    lead_key = str(lead_key or "").strip()
    if not lead_key:
        return JSONResponse(
            {"ok": False, "error": "Missing lead_key."}, status_code=400
        )

    store = get_store()
    try:
        lead = store.get_lead(lead_key)
    except Exception:
        lead = None
    if not lead:
        return JSONResponse(
            {"ok": False, "error": "Lead not found"}, status_code=404
        )

    try:
        from lead_vault_website_generator import DEFAULT_GENERATED_DIR
    except ImportError as exc:
        return {"ok": False, "error": f"Generator module unavailable: {exc}"}

    safe_key = _safe_lead_key(lead_key)
    pdf_path = _resolve_inside(DEFAULT_GENERATED_DIR, safe_key, "report.pdf")
    email_path = _resolve_inside(DEFAULT_GENERATED_DIR, safe_key, "email.md")
    meta_path = _resolve_inside(DEFAULT_GENERATED_DIR, safe_key, "report_meta.json")

    pdf_exists = bool(pdf_path and pdf_path.exists())
    email_text: str | None = None
    if email_path and email_path.exists():
        try:
            email_text = email_path.read_text(encoding="utf-8")[:20000]
        except OSError:
            email_text = None

    meta = _read_json_if_exists(meta_path) if meta_path else None

    return {
        "ok": True,
        "lead_key": lead_key,
        "pdf_exists": pdf_exists,
        "pdf_generated_at": _mtime_iso(pdf_path) if pdf_exists else "",
        "email_markdown": email_text,
        "meta": meta or {},
    }


@router.get("/report-package/{lead_key}/pdf")
async def report_package_pdf(lead_key: str):
    """Serve the generated report.pdf as a download."""
    lead_key = str(lead_key or "").strip()
    if not lead_key:
        return JSONResponse(
            {"ok": False, "error": "Missing lead_key."}, status_code=400
        )
    store = get_store()
    try:
        lead = store.get_lead(lead_key)
    except Exception:
        lead = None
    if not lead:
        return JSONResponse(
            {"ok": False, "error": "Lead not found"}, status_code=404
        )

    try:
        from lead_vault_website_generator import DEFAULT_GENERATED_DIR
    except ImportError as exc:
        return JSONResponse(
            {"ok": False, "error": f"Generator module unavailable: {exc}"},
            status_code=500,
        )

    safe_key = _safe_lead_key(lead_key)
    pdf_path = _resolve_inside(DEFAULT_GENERATED_DIR, safe_key, "report.pdf")
    if pdf_path is None:
        return JSONResponse(
            {"ok": False, "error": "Invalid lead key."}, status_code=400
        )
    if not pdf_path.exists() or not pdf_path.is_file():
        return JSONResponse(
            {"ok": False, "error": "No report PDF yet. Generate it first."},
            status_code=404,
        )

    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename=f"{safe_key}-proposal.pdf",
        headers={
            "Cache-Control": "no-store, max-age=0",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        },
    )
