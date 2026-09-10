from __future__ import annotations

"""Headless heavy-week Lead Machine run.

This uses the saved Summit settings, then applies high-volume overrides:
full run mode, email lookup enabled, and at least a 4x4 tile grid.
"""

import sys
import json
from datetime import datetime
from pathlib import Path
from typing import Any

WEB_ROOT = Path(__file__).resolve().parent
if str(WEB_ROOT) not in sys.path:
    sys.path.insert(0, str(WEB_ROOT))

from app.config import load_settings  # noqa: E402
from app.dependencies import get_store  # noqa: E402
from lead_machine import LeadMachine, LeadMachineConfig  # noqa: E402
from lead_machine_search_config import SCAN_PROFILE_PRESETS  # noqa: E402


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in str(value or "").replace(",", "\n").splitlines() if part.strip()]


def _apply_scan_profile(settings: dict[str, Any]) -> dict[str, Any]:
    merged = dict(settings or {})
    profile_name = str(merged.get("scan_profile_name", "Custom") or "Custom")
    profile = SCAN_PROFILE_PRESETS.get(profile_name)
    if isinstance(profile, dict) and profile_name != "Custom":
        for key, value in profile.items():
            if key != "description":
                merged[key] = value
    merged["scan_profile_name"] = profile_name
    return merged


def build_config(settings: dict[str, Any]) -> LeadMachineConfig:
    settings = _apply_scan_profile(settings)
    output_folder = Path(settings.get("output_folder") or Path.home() / "Documents" / "Colorado Lead Machine")
    output_folder.mkdir(parents=True, exist_ok=True)
    return LeadMachineConfig(
        google_maps_api_key=str(settings.get("google_maps_api_key", "") or ""),
        save_path=output_folder,
        search_areas=_string_list(settings.get("search_areas", [])),
        seed_mode=str(settings.get("seed_mode", "Hybrid") or "Hybrid"),
        min_rating=_float(settings.get("min_rating"), 4.0),
        min_reviews=_int(settings.get("min_reviews"), 10),
        min_business_age_days=_int(settings.get("min_business_age_days"), 90),
        skip_email_lookup=False,
        hunter_api_key=str(settings.get("hunter_api_key", "") or ""),
        dataforseo_login=str(settings.get("dataforseo_login", "") or ""),
        dataforseo_password=str(settings.get("dataforseo_password", "") or ""),
        yelp_api_key=str(settings.get("yelp_api_key", "") or ""),
        california_sos_api_key=str(settings.get("california_sos_api_key", "") or ""),
        enable_browser_fallback=bool(settings.get("enable_browser_fallback", True)),
        enable_domain_checks=bool(settings.get("enable_domain_checks", True)),
        enable_rdap_checks=bool(settings.get("enable_rdap_checks", False)),
        enable_pagespeed_checks=bool(settings.get("enable_pagespeed_checks", False)),
        pagespeed_api_key=str(settings.get("pagespeed_api_key", "") or ""),
        pagespeed_strategy=str(settings.get("pagespeed_strategy", "mobile") or "mobile"),
        pagespeed_run_cap=_int(settings.get("pagespeed_run_cap"), 10),
        builtwith_api_key=str(settings.get("builtwith_api_key", "") or ""),
        enable_builtwith_checks=bool(settings.get("enable_builtwith_checks", False)),
        builtwith_run_cap=_int(settings.get("builtwith_run_cap"), 10),
        tile_grid_size=max(_int(settings.get("tile_grid_size"), 3), 4),
        fast_test_mode=False,
        fast_test_lead_limit=_int(settings.get("fast_test_lead_limit"), 75),
        client_name=str(settings.get("client_name", "") or ""),
        scan_profile_name=str(settings.get("scan_profile_name", "Custom") or "Custom"),
        target_profile_name=str(settings.get("target_profile_name", "All supported") or "All supported"),
        target_place_types=_string_list(settings.get("target_place_types", [])),
        target_category_keywords=_string_list(settings.get("target_category_keywords", [])),
        opportunity_focus=str(settings.get("opportunity_focus", "any") or "any"),
        automation_intensity="heavy_week",
    )


def create_today_shortlist(run_id: int | None, *, limit: int = 25) -> dict[str, Any]:
    store = get_store()
    leads = store.list_queue_summaries(view_filter="High confidence", run_id=run_id)
    lead_keys: list[str] = []
    for lead in leads:
        if len(lead_keys) >= limit:
            break
        if lead.get("do_not_contact") or lead.get("disqualified"):
            continue
        source_tier = str(lead.get("source_confidence_tier") or "")
        if source_tier == "Low":
            continue
        key = str(lead.get("lead_key", "") or "").strip()
        if key:
            lead_keys.append(key)
    if not lead_keys:
        return {"ok": False, "added": 0, "list_name": ""}
    list_name = f"Today's Shortlist {datetime.now().strftime('%Y-%m-%d')}"
    list_id, added = store.add_leads_to_list(lead_keys, list_name)
    return {"ok": True, "list_id": list_id, "added": added, "list_name": list_name, "lead_keys": lead_keys}


def run_batch_agent_review(settings: dict[str, Any], run_id: int | None, *, limit: int = 10) -> dict[str, Any]:
    if limit <= 0:
        return {"ok": True, "requested": 0, "skipped": "disabled"}
    provider = str(settings.get("ai_provider") or "Anthropic")
    if provider in ("Anthropic", "Claude"):
        api_key = str(settings.get("anthropic_api_key") or settings.get("ai_api_key") or "")
    else:
        api_key = str(settings.get("openai_api_key") or settings.get("ai_api_key") or "")
    if not api_key:
        return {"ok": False, "requested": 0, "error": f"No {provider} API key configured"}

    model = str(settings.get("ai_model") or "")
    if provider in ("Anthropic", "Claude") and model.startswith("gpt"):
        model = ""
    elif provider == "OpenAI" and "claude" in model.lower():
        model = ""

    from lead_vault_agent_review import run_agent_review

    store = get_store()
    leads = store.list_queue_summaries(view_filter="High confidence", run_id=run_id)
    lead_keys = [str(lead.get("lead_key", "") or "").strip() for lead in leads[:limit] if lead.get("lead_key")]
    counts = {"completed": 0, "skipped": 0, "cached": 0, "error": 0}
    for lead_key in lead_keys:
        try:
            lead = store.get_lead(lead_key)
            result = run_agent_review(
                lead=lead,
                api_key=api_key,
                model=model,
                provider=provider,
                stored_hash=lead.get("agent_review_input_hash", ""),
                stored_status=lead.get("agent_review_status", ""),
                stored_review=lead.get("agent_review", {}),
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
        except Exception:
            counts["error"] += 1
    return {"ok": counts["error"] == 0, "requested": len(lead_keys), **counts}


def main() -> int:
    settings = load_settings()
    machine = LeadMachine(build_config(settings), logger=print)
    output = machine.run(run_reason="heavy-week-automation")
    print(f"Heavy-week run exported: {output}")
    run_id = machine.current_run_id
    shortlist = create_today_shortlist(run_id)
    if shortlist.get("ok"):
        print(f"Shortlist created: {shortlist['list_name']} ({shortlist['added']} leads)")
    else:
        print("Shortlist created: no qualified high-confidence leads")
    review_limit = _int(settings.get("automation_agent_review_limit"), 10)
    review = run_batch_agent_review(settings, run_id, limit=review_limit)
    print(
        "Agent review batch: "
        f"{review.get('completed', 0)} completed, {review.get('cached', 0)} cached, "
        f"{review.get('skipped', 0)} skipped, {review.get('error', 0)} errors"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
