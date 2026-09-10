from __future__ import annotations

import asyncio
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncGenerator

APP_DIR = Path(__file__).resolve().parent
WEB_ROOT = APP_DIR.parent
REPO_ROOT = WEB_ROOT.parent
COLORADO_MODULE_DIR = REPO_ROOT / "colorado-lead-machine"
if str(COLORADO_MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(COLORADO_MODULE_DIR))


def _string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").replace(",", "\n")
    return [part.strip() for part in text.splitlines() if part.strip()]


def _apply_scan_profile(config_dict: dict) -> dict:
    from lead_machine_search_config import SCAN_PROFILE_PRESETS

    merged = dict(config_dict or {})
    profile_name = str(merged.get("scan_profile_name", "Custom") or "Custom")
    profile = SCAN_PROFILE_PRESETS.get(profile_name)
    if isinstance(profile, dict) and profile_name != "Custom":
        for key, value in profile.items():
            if key == "description":
                continue
            merged[key] = value
    merged["scan_profile_name"] = profile_name
    return merged


@dataclass
class RunManager:
    _thread: threading.Thread | None = field(default=None, init=False)
    _machine: object | None = field(default=None, init=False)
    _log_lines: list[str] = field(default_factory=list, init=False)
    _log_lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    _status: str = field(default="idle", init=False)
    _error: str | None = field(default=None, init=False)
    _run_id: int | None = field(default=None, init=False)
    _started_at: float = field(default=0.0, init=False)

    def start_run(self, config_dict: dict, save_path: str, saved_scan_id: int | None = None, run_reason: str = "manual") -> bool:
        if self._status == "running":
            return False

        from lead_machine import LeadMachine, LeadMachineConfig

        config_dict = _apply_scan_profile(config_dict)
        output_folder = Path(save_path) if save_path else Path.home() / "Documents" / "Colorado Lead Machine"
        output_folder.mkdir(parents=True, exist_ok=True)
        automation_intensity = str(config_dict.get("automation_intensity", "normal") or "normal")
        heavy_week = automation_intensity == "heavy_week"
        tile_grid_size = int(config_dict.get("tile_grid_size", 3))
        if heavy_week:
            tile_grid_size = max(tile_grid_size, 4)

        lm_config = LeadMachineConfig(
            google_maps_api_key=config_dict.get("google_maps_api_key", ""),
            save_path=output_folder,
            search_areas=config_dict.get("search_areas", []),
            seed_mode=config_dict.get("seed_mode", "Hybrid"),
            min_rating=float(config_dict.get("min_rating", 4.0)),
            min_reviews=int(config_dict.get("min_reviews", 10)),
            min_business_age_days=int(config_dict.get("min_business_age_days", 90)),
            skip_email_lookup=False if heavy_week else bool(config_dict.get("skip_email_lookup", False)),
            hunter_api_key=config_dict.get("hunter_api_key", ""),
            dataforseo_login=config_dict.get("dataforseo_login", ""),
            dataforseo_password=config_dict.get("dataforseo_password", ""),
            yelp_api_key=config_dict.get("yelp_api_key", ""),
            california_sos_api_key=config_dict.get("california_sos_api_key", ""),
            enable_browser_fallback=bool(config_dict.get("enable_browser_fallback", True)),
            enable_domain_checks=bool(config_dict.get("enable_domain_checks", True)),
            enable_rdap_checks=bool(config_dict.get("enable_rdap_checks", False)),
            enable_pagespeed_checks=bool(config_dict.get("enable_pagespeed_checks", False)),
            pagespeed_api_key=config_dict.get("pagespeed_api_key", ""),
            pagespeed_strategy=str(config_dict.get("pagespeed_strategy", "mobile") or "mobile"),
            pagespeed_run_cap=int(config_dict.get("pagespeed_run_cap", 10) or 10),
            builtwith_api_key=config_dict.get("builtwith_api_key", ""),
            enable_builtwith_checks=bool(config_dict.get("enable_builtwith_checks", False)),
            builtwith_run_cap=int(config_dict.get("builtwith_run_cap", 10) or 10),
            tile_grid_size=tile_grid_size,
            fast_test_mode=False if heavy_week else bool(config_dict.get("fast_test_mode", False)),
            fast_test_lead_limit=int(config_dict.get("fast_test_lead_limit", 75)),
            target_lead_keys=config_dict.get("target_lead_keys", []),
            target_pool_name=config_dict.get("target_pool_name", ""),
            client_name=str(config_dict.get("client_name", "") or ""),
            scan_profile_name=str(config_dict.get("scan_profile_name", "Custom") or "Custom"),
            target_profile_name=str(config_dict.get("target_profile_name", "All supported") or "All supported"),
            target_place_types=_string_list(config_dict.get("target_place_types", [])),
            target_category_keywords=_string_list(config_dict.get("target_category_keywords", [])),
            opportunity_focus=str(config_dict.get("opportunity_focus", "any") or "any"),
            automation_intensity=automation_intensity,
        )
        cap = config_dict.get("fast_test_total_run_cap", "")
        if cap and str(cap).strip():
            try:
                lm_config.fast_test_total_run_cap = int(cap)
            except (ValueError, TypeError):
                pass

        machine = LeadMachine(lm_config, logger=self._append_log)
        self._machine = machine
        with self._log_lock:
            self._log_lines = []
        self._status = "running"
        self._error = None
        self._run_id = None
        self._started_at = time.time()

        self._thread = threading.Thread(
            target=self._run_worker,
            args=(machine, saved_scan_id, run_reason),
            daemon=True,
        )
        self._thread.start()
        return True

    def stop_run(self) -> None:
        if self._machine and self._status == "running":
            self._status = "stopping"
            self._machine.stop()

    def get_status(self) -> dict:
        elapsed = round(time.time() - self._started_at, 1) if self._started_at and self._status in ("running", "stopping") else 0
        with self._log_lock:
            log_count = len(self._log_lines)
        return {
            "status": self._status,
            "run_id": self._run_id,
            "error": self._error,
            "elapsed_seconds": elapsed,
            "log_count": log_count,
        }

    async def stream_logs(self, from_index: int = 0) -> AsyncGenerator[str, None]:
        """Stream log lines as SSE events, starting from `from_index`.

        Multiple consumers can connect and reconnect at any time. Each
        consumer tracks its own read position in the shared log buffer,
        so navigating away and coming back replays any missed lines.
        """
        cursor = from_index
        while True:
            with self._log_lock:
                total = len(self._log_lines)
                new_lines = self._log_lines[cursor:total] if cursor < total else []
            if new_lines:
                for line in new_lines:
                    yield f"data: {line}\n\n"
                cursor = total
            else:
                # No new lines — check if run is done
                if self._status not in ("running", "stopping"):
                    status_msg = "completed" if self._status == "completed" else f"failed: {self._error or 'unknown'}"
                    yield f"event: done\ndata: Run {status_msg}\n\n"
                    return
                await asyncio.sleep(0.3)

    def _append_log(self, message: str) -> None:
        with self._log_lock:
            self._log_lines.append(message)

    def _run_worker(self, machine: object, saved_scan_id: int | None, run_reason: str) -> None:
        try:
            machine.run(saved_scan_id=saved_scan_id, run_reason=run_reason)
            self._status = "completed"
            self._append_log("Run completed successfully.")
        except Exception as exc:
            self._status = "failed"
            self._error = str(exc)
            self._append_log(f"Run failed: {exc}")


run_manager = RunManager()
