from __future__ import annotations

import json
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
WEB_ROOT = APP_DIR.parent
REPO_ROOT = WEB_ROOT.parent

# Make existing modules importable without modification
for _p in [str(REPO_ROOT), str(REPO_ROOT / "colorado-lead-machine"), str(REPO_ROOT / "lead-vault")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from lead_machine_search_config import (
    AUTOMATION_INTENSITY_PRESETS,
    OPPORTUNITY_FOCUS_PRESETS,
    SEARCH_AREA_PRESETS,
    SCAN_PROFILE_PRESETS,
    TARGETING_CATEGORY_PRESETS,
)

LEAD_MACHINE_SETTINGS = REPO_ROOT / "colorado-lead-machine" / "settings.json"
LEAD_VAULT_SETTINGS = REPO_ROOT / "lead-vault" / "lead_vault_settings.json"
SECRET_SETTING_KEYS = {
    "google_maps_api_key",
    "hunter_api_key",
    "dataforseo_password",
    "yelp_api_key",
    "california_sos_api_key",
    "pagespeed_api_key",
    "builtwith_api_key",
    "openai_api_key",
    "anthropic_api_key",
    "ai_api_key",
}
SECRET_PLACEHOLDERS = {"", "********"}

DEFAULT_DB_DIR = Path.home() / "Documents" / "Colorado Lead Machine"
DEFAULT_DB_PATH = DEFAULT_DB_DIR / "lead_machine.db"


def _read_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def load_settings() -> dict:
    lm = _read_json(LEAD_MACHINE_SETTINGS)
    lv = _read_json(LEAD_VAULT_SETTINGS)
    return {
        "google_maps_api_key": lm.get("google_maps_api_key", ""),
        "hunter_api_key": lm.get("hunter_api_key", ""),
        "dataforseo_login": lm.get("dataforseo_login", ""),
        "dataforseo_password": lm.get("dataforseo_password", ""),
        "yelp_api_key": lm.get("yelp_api_key", ""),
        "california_sos_api_key": lm.get("california_sos_api_key", ""),
        "enable_browser_fallback": lm.get("enable_browser_fallback", True),
        "enable_domain_checks": lm.get("enable_domain_checks", True),
        "enable_rdap_checks": lm.get("enable_rdap_checks", False),
        "enable_pagespeed_checks": lm.get("enable_pagespeed_checks", False),
        "pagespeed_api_key": lm.get("pagespeed_api_key", ""),
        "pagespeed_strategy": lm.get("pagespeed_strategy", "mobile"),
        "pagespeed_run_cap": lm.get("pagespeed_run_cap", "10"),
        "builtwith_api_key": lm.get("builtwith_api_key", ""),
        "enable_builtwith_checks": lm.get("enable_builtwith_checks", False),
        "builtwith_run_cap": lm.get("builtwith_run_cap", "10"),
        "seed_mode": lm.get("seed_mode", "Hybrid"),
        "output_folder": lm.get("output_folder", str(DEFAULT_DB_DIR)),
        "min_rating": lm.get("min_rating", "4.0"),
        "min_reviews": lm.get("min_reviews", "10"),
        "min_business_age_days": lm.get("min_business_age_days", "90"),
        "tile_grid_size": lm.get("tile_grid_size", "3"),
        "fast_test_mode": lm.get("fast_test_mode", False),
        "fast_test_lead_limit": lm.get("fast_test_lead_limit", "75"),
        "fast_test_total_run_cap": lm.get("fast_test_total_run_cap", ""),
        "search_areas": lm.get("search_areas", ["Fort Collins, CO", "Denver, CO", "Colorado Springs, CO"]),
        "search_area_presets": SEARCH_AREA_PRESETS,
        "client_name": lm.get("client_name", ""),
        "scan_profile_name": lm.get("scan_profile_name", "Custom"),
        "scan_profile_presets": SCAN_PROFILE_PRESETS,
        "target_profile_name": lm.get("target_profile_name", "All supported"),
        "target_place_types": lm.get("target_place_types", []),
        "target_category_keywords": lm.get("target_category_keywords", []),
        "targeting_category_presets": TARGETING_CATEGORY_PRESETS,
        "opportunity_focus": lm.get("opportunity_focus", "any"),
        "opportunity_focus_presets": OPPORTUNITY_FOCUS_PRESETS,
        "automation_intensity": lm.get("automation_intensity", "normal"),
        "automation_intensity_presets": AUTOMATION_INTENSITY_PRESETS,
        "automation_agent_review_limit": lm.get("automation_agent_review_limit", "10"),
        "skip_email_lookup": lm.get("skip_email_lookup", False),
        "db_path": lv.get("db_path", str(DEFAULT_DB_PATH)),
        "ai_provider": lv.get("ai_provider", "OpenAI"),
        "openai_api_key": lv.get("openai_api_key", ""),
        "anthropic_api_key": lv.get("anthropic_api_key", ""),
        "ai_api_key": lv.get("ai_api_key", ""),
        "ai_model": lv.get("ai_model", ""),
        "agency_name": lv.get("agency_name", ""),
        "offer_positioning": lv.get("offer_positioning", ""),
    }


def save_settings(data: dict) -> None:
    lm_keys = {
        "google_maps_api_key", "hunter_api_key", "seed_mode", "output_folder",
        "dataforseo_login", "dataforseo_password", "yelp_api_key", "california_sos_api_key", "pagespeed_api_key",
        "builtwith_api_key", "enable_browser_fallback", "enable_domain_checks", "enable_rdap_checks",
        "enable_pagespeed_checks", "enable_builtwith_checks", "pagespeed_strategy", "pagespeed_run_cap",
        "builtwith_run_cap",
        "min_rating", "min_reviews", "min_business_age_days", "tile_grid_size",
        "fast_test_mode", "fast_test_lead_limit", "fast_test_total_run_cap",
        "search_areas", "client_name", "scan_profile_name", "target_profile_name", "target_place_types",
        "target_category_keywords", "opportunity_focus", "automation_intensity", "automation_agent_review_limit",
        "skip_email_lookup",
    }
    lv_keys = {
        "db_path", "ai_provider", "openai_api_key", "anthropic_api_key",
        "ai_api_key", "ai_model", "agency_name", "offer_positioning",
    }
    lm_existing = _read_json(LEAD_MACHINE_SETTINGS)
    lv_existing = _read_json(LEAD_VAULT_SETTINGS)
    for key in lm_keys:
        if key in data:
            if key in SECRET_SETTING_KEYS and str(data[key] or "").strip() in SECRET_PLACEHOLDERS:
                continue
            lm_existing[key] = data[key]
    for key in lv_keys:
        if key in data:
            if key in SECRET_SETTING_KEYS and str(data[key] or "").strip() in SECRET_PLACEHOLDERS:
                continue
            lv_existing[key] = data[key]
    _write_json(LEAD_MACHINE_SETTINGS, lm_existing)
    _write_json(LEAD_VAULT_SETTINGS, lv_existing)


def resolve_db_path() -> Path:
    settings = load_settings()
    db_path = settings.get("db_path", "").strip()
    if db_path:
        return Path(db_path)
    output_folder = settings.get("output_folder", "").strip()
    if output_folder:
        return Path(output_folder) / "lead_machine.db"
    return DEFAULT_DB_PATH
