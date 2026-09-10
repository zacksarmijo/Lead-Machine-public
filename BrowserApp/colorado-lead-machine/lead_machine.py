from __future__ import annotations

from contextlib import contextmanager
import json
import math
import random
import re
import sqlite3
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import requests

import contact_enrichment as contact_enrichment_module
import colorado_records as colorado_records_module
import discovery_providers as discovery_providers_module
import enrichment as enrichment_module
import matching as matching_module
import network as network_module
import pagespeed as pagespeed_module
import presence as presence_module
import reporting as reporting_module
import scoring as scoring_module
import storage as storage_module
import tech_stack as tech_stack_module
from lead_machine_match_config import (
    BAD_FIT_CATEGORY_KEYWORDS,
    BAD_FIT_GOOGLE_TYPES,
    BAD_FIT_NAME_KEYWORDS,
    CHAIN_EXACT_ONLY,
    EXCLUDE_CHAINS,
    EXCLUDE_ORG_KEYWORDS,
)
from lead_machine_presence_config import (
    DIRECTORY_DOMAINS,
    DIRECTORY_LABELS,
    LINK_HUB_DOMAINS,
    MARKETPLACE_DOMAINS,
    PARKED_SITE_MARKERS,
    PARKED_TEXT_ONLY_MARKERS,
    SOCIAL_DOMAINS,
    TEMPLATE_BUILDER_MARKERS,
)
from lead_machine_search_config import (
    AUTOMATION_INTENSITY_PRESETS,
    OPPORTUNITY_FOCUS_PRESETS,
    OVERTURE_CATEGORY_KEYWORDS,
    PLACE_TYPES,
    SEARCH_LOCATIONS,
    SEARCH_LOCATION_PRESETS,
    SCAN_PROFILE_PRESETS,
    TARGETING_CATEGORY_PRESETS,
    US_STATE_NAMES,
)
from shared_schema import ensure_column as ensure_schema_column, ensure_shared_schema
from trigger_detection import (
    TRIGGER_VERSION,
    detect_trigger_events,
    format_trigger_events,
    summarize_trigger_events,
    summarize_trigger_types,
)
from website_audit import AUDIT_VERSION, build_website_opportunity_scorecard, derive_pitch_family

import socket

try:
    import dns.resolver as _dns_resolver
except ImportError:
    _dns_resolver = None

_mx_domain_cache: dict[str, bool] = {}


def _has_mx_record(domain: str) -> bool:
    """Check if an email domain can receive mail. Uses dnspython if available, else stdlib."""
    if domain in _mx_domain_cache:
        return _mx_domain_cache[domain]
    result = False
    if _dns_resolver is not None:
        for record_type in ("MX", "A", "AAAA"):
            try:
                answers = _dns_resolver.resolve(domain, record_type)
                result = len(answers) > 0
                if result:
                    break
            except Exception:
                continue
    else:
        try:
            answers = socket.getaddrinfo(domain, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
            result = len(answers) > 0
        except socket.gaierror:
            result = False
    _mx_domain_cache[domain] = result
    return result


try:
    import duckdb
except ImportError:
    duckdb = None

try:
    from bs4 import BeautifulSoup

    BS4 = True
except ImportError:
    BeautifulSoup = None
    BS4 = False

try:
    import lxml  # noqa: F401

    LXML_AVAILABLE = True
except ImportError:
    LXML_AVAILABLE = False

WEBSITE_AUDIT_VERSION = AUDIT_VERSION
TRIGGER_DETECTION_VERSION = TRIGGER_VERSION

_MONITOR_BUCKET_RANK = {
    "": 0,
    "Established website": 0,
    "Unknown web presence": 0,
    "Basic site": 1,
    "Weak live site": 1,
    "Weak site": 1,
    "Directory-only presence": 2,
    "Directory only": 2,
    "Social-only presence": 2,
    "Social only": 2,
    "Broken site": 3,
    "No website": 4,
}

EMAIL_RE = contact_enrichment_module.EMAIL_RE
PHONE_RE = re.compile(r"(?:\+?1[\s.\-]?)?(?:\(?\d{3}\)?[\s.\-]?)\d{3}[\s.\-]?\d{4}")

WEBSITE_EVIDENCE_DEFAULTS = {
    "Resolved Website URL": "",
    "HTTP Status": "",
    "Fetch Time Ms": 0,
    "Page Title": "",
    "Meta Description": "",
    "Word Count": 0,
    "Form Count": 0,
    "Internal Link Count": 0,
    "Image Count": 0,
    "On-Page Phones": "",
    "On-Page Emails": "",
    "CTA Terms": "",
    "Booking Terms": "",
    "Viewport Meta": "",
    "Website Evidence Summary": "",
    "Website Evidence Snippet": "",
    "Inner Pages Checked": 0,
    "Inner Page URLs": "",
    "Total Word Count": 0,
    "Contact Page Found": "",
    "Contact Page Has Form": "",
    "Services Described": "",
    "About Page Found": "",
    # Rich audit fields — keep here so each audit run resets stale values
    # (e.g. a lead previously classified "No website" had these stamped
    # with "No owned site to evaluate"; without resetting, those values
    # persist forever even after the lead is re-classified "Weak site").
    "Google Analytics": "",
    "Facebook Pixel": "",
    "Schema Markup": "",
    "Open Graph Tags": "",
    "Canonical Tag": "",
    "Robots Meta": "",
    "Booking Platforms": "",
    "Social Links": "",
    "Review Widget": "",
    "Chat Widget": "",
    "Accessibility Indicators": "",
    "Images With Alt Text": 0,
    "Broken Link Count": 0,
    "Broken Links Checked": 0,
    "Broken Link Ratio": 0.0,
    "Broken Links": "",
    "Outdated Design Markers": "",
    "Discovery Sources Attempted": "",
    "Search Queries": "",
    "Search Providers": "",
    "Raw Result Count": 0,
    "URLs Attempted": "",
    "HTTP Statuses": "",
    "Failure Reasons": "",
    "Retry Recommended": "",
    "Retry Reason": "",
    "Retry Count": 0,
    "Next Retry At": "",
    "Verification Sources": "",
    "No Website Evidence": "",
    "Source Confidence Score": 0,
    "Source Confidence Tier": "",
    "Source Confidence Matrix": "",
    "Sources Checked": "",
    "Website Assertion Status": "",
    "Website Evidence Strength": 0,
    "Identity Evidence Strength": 0,
    "Source Conflict Count": 0,
    "Source Confidence Warnings": "",
    "Why Surfaced": "",
    "Why Suppressed": "",
    "Evidence Freshness": "",
    "Next Best Action": "",
    "Browser Fallback Used": "",
    "Browser Fallback Reason": "",
    "Browser Fallback Status": "",
    "PageSpeed Status": "",
    "PageSpeed Strategy": "",
    "PageSpeed Final URL": "",
    "PageSpeed Analysis Timestamp": "",
    "PageSpeed Lighthouse Version": "",
    "PageSpeed Performance Score": 0,
    "PageSpeed Accessibility Score": 0,
    "PageSpeed Best Practices Score": 0,
    "PageSpeed SEO Score": 0,
    "PageSpeed FCP": "",
    "PageSpeed LCP": "",
    "PageSpeed Speed Index": "",
    "PageSpeed TBT": "",
    "PageSpeed CLS": "",
    "PageSpeed Interactive": "",
    "PageSpeed CrUX Overall": "",
    "PageSpeed Origin CrUX Overall": "",
    "PageSpeed CrUX FCP": "",
    "PageSpeed CrUX FCP Category": "",
    "PageSpeed CrUX LCP": "",
    "PageSpeed CrUX LCP Category": "",
    "PageSpeed CrUX INP": "",
    "PageSpeed CrUX INP Category": "",
    "PageSpeed CrUX CLS": "",
    "PageSpeed CrUX CLS Category": "",
    "PageSpeed CrUX TTFB": "",
    "PageSpeed CrUX TTFB Category": "",
    "PageSpeed Field Summary": "",
    "PageSpeed Summary": "",
    "PageSpeed Opportunities": "",
    "PageSpeed Error": "",
    "BuiltWith Status": "",
    "BuiltWith Domain": "",
    "BuiltWith First Indexed": "",
    "BuiltWith Last Indexed": "",
    "BuiltWith Groups": "",
    "BuiltWith Category Summary": "",
    "Tech Stack Signal": "",
    "Tech Stack Score": 0,
    "Tech Stack Weak Signals": "",
    "Tech Stack Strong Signals": "",
    "Tech Stack Summary": "",
    "Tech Stack Last Checked": "",
    "Tech Stack Error": "",
    "Provider Evidence Summary": "",
    "DataForSEO Status": "",
    "DataForSEO Queries": "",
    "DataForSEO Owned Domains": "",
    "DataForSEO Result Count": 0,
    "DataForSEO Failure Reason": "",
    "Yelp Match Status": "",
    "Yelp Match Confidence": 0,
    "Yelp Business ID": "",
    "Yelp URL": "",
    "Yelp Rating": "",
    "Yelp Review Count": "",
    "Yelp Price": "",
    "Yelp Categories": "",
    "Yelp Phone": "",
    "Yelp Address": "",
    "Yelp Hours": "",
    "Yelp Photo Count": 0,
    "Yelp Photos": "",
    "Yelp Review Snippets": "",
    "Yelp Failure Reason": "",
    "Normalized Phone": "",
    "Normalized Address": "",
    "Business Identity Confidence": 0,
    "Domain Checked": "",
    "Domain A Record": "",
    "Domain AAAA Record": "",
    "Domain DNS Error": "",
    "Domain MX/Address Record": "",
    "Domain SSL Present": "",
    "Domain SSL Expires": "",
    "Robots.txt Status": "",
    "Sitemap Status": "",
    "Domain RDAP Age Days": "",
    "Domain RDAP Error": "",
    "Domain Verification Summary": "",
    "Social Bio Sources Checked": "",
}

# Common inner page path patterns to look for in nav links
_INNER_PAGE_PATTERNS = {
    "contact": ["contact", "contact-us", "contact_us", "get-in-touch", "reach-us"],
    "about": ["about", "about-us", "about_us", "our-story", "who-we-are", "our-team", "team"],
    "services": ["services", "our-services", "what-we-do", "solutions", "products", "offerings", "menu"],
}

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


@dataclass
class LeadMachineConfig:
    google_maps_api_key: str
    save_path: Path
    search_areas: list[str] = field(default_factory=list)
    seed_mode: str = "Hybrid"
    min_rating: float = 4.0
    min_reviews: int = 10
    min_business_age_days: int = 90
    email_delay_min: float = 2.0
    email_delay_max: float = 4.5
    skip_email_lookup: bool = False
    hunter_api_key: str = ""
    dataforseo_login: str = ""
    dataforseo_password: str = ""
    yelp_api_key: str = ""
    california_sos_api_key: str = ""
    enable_browser_fallback: bool = True
    enable_domain_checks: bool = True
    enable_rdap_checks: bool = False
    enable_pagespeed_checks: bool = False
    pagespeed_api_key: str = ""
    pagespeed_strategy: str = "mobile"
    pagespeed_run_cap: int = 10
    builtwith_api_key: str = ""
    enable_builtwith_checks: bool = False
    builtwith_run_cap: int = 10
    search_radius: int = 8000
    tile_grid_size: int = 3
    fast_test_mode: bool = False
    fast_test_lead_limit: int = 75
    fast_test_total_run_cap: int | None = None
    record_lookup_workers: int = 6
    max_details_per_run: int = 4000
    max_details_per_month: int = 4800
    target_lead_keys: list[str] = field(default_factory=list)
    target_pool_name: str = ""
    client_name: str = ""
    scan_profile_name: str = "Custom"
    target_profile_name: str = "All supported"
    target_place_types: list[str] = field(default_factory=list)
    target_category_keywords: list[str] = field(default_factory=list)
    opportunity_focus: str = "any"
    automation_intensity: str = "normal"

    @property
    def usage_log_path(self) -> Path:
        return self.save_path / "api_usage_log.txt"

    @property
    def processed_ids_path(self) -> Path:
        return self.save_path / "processed_ids.json"

    @property
    def database_path(self) -> Path:
        return self.save_path / "lead_machine.db"

    @property
    def overture_cache_dir(self) -> Path:
        return self.save_path / "overture_cache"

    @property
    def run_reports_dir(self) -> Path:
        return self.save_path / "run_reports"


class LeadMachineError(Exception):
    pass


def default_output_folder() -> Path:
    return Path.home() / "Documents" / "Colorado Lead Machine"


def default_search_areas() -> list[str]:
    return [location["name"] for location in SEARCH_LOCATION_PRESETS["Colorado"]]


def clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(value, maximum))


class LeadMachine:
    def __init__(self, config: LeadMachineConfig, logger: Optional[Callable[[str], None]] = None):
        self.config = config
        self.log = logger or (lambda _: None)
        self._session_local = threading.local()
        self._stop_event = threading.Event()
        self.co_record_cache: dict[str, dict] = {}
        self.co_record_cache_lock = threading.Lock()
        self.search_area_cache: dict[str, dict] = {}
        self._db_initialized = False
        self.current_run_id: Optional[int] = None
        self.current_saved_scan_id: Optional[int] = None
        self.current_run_reason: str = "manual"
        self.run_report: dict[str, object] = {}
        self._web_result_evidence: dict[tuple[str, str, str, str, str], dict[str, object]] = {}

    def _create_session(self) -> requests.Session:
        return network_module.create_session(BROWSER_HEADERS)

    @property
    def session(self) -> requests.Session:
        return network_module.get_session(self)

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        return network_module.request(self, method, url, **kwargs)

    def _safe_web_request(
        self,
        method: str,
        url: str,
        *,
        timeout: tuple[float, float] | int | float | None = None,
        max_redirects: int = 4,
    ) -> requests.Response:
        return network_module.safe_web_request(self, method, url, timeout=timeout, max_redirects=max_redirects)

    def fetch_page_result(
        self,
        url: str,
        timeout: int | float | tuple[float, float] = 8,
        *,
        provider: str = "",
        query: str = "",
    ) -> dict[str, Any]:
        return network_module.fetch_page_result(self, url, timeout, provider=provider, query=query)

    def browser_fetch_page_result(
        self,
        url: str,
        timeout_ms: int = 12000,
        *,
        provider: str = "browser",
        query: str = "",
    ) -> dict[str, Any]:
        return network_module.browser_fetch_page_result(self, url, timeout_ms, provider=provider, query=query)

    def dataforseo_serp_discovery(self, business_name: str, city: str, limit: int = 12) -> dict[str, object]:
        return discovery_providers_module.dataforseo_serp_discovery(self, business_name, city, limit=limit)

    def yelp_enrich_lead(self, lead: dict) -> dict[str, object]:
        return discovery_providers_module.yelp_enrich_lead(self, lead)

    def verify_domain(self, url: str) -> dict[str, object]:
        return discovery_providers_module.verify_domain(self, url)

    def enrich_with_pagespeed(self, leads: list[dict]) -> list[dict]:
        return pagespeed_module.enrich_leads_with_pagespeed(self, leads)

    def enrich_with_tech_stack(self, leads: list[dict]) -> list[dict]:
        return tech_stack_module.enrich_leads_with_tech_stack(self, leads)

    def normalize_phone_value(self, value: object) -> str:
        return discovery_providers_module.normalize_phone(value)

    def normalize_address_value(self, value: object) -> str:
        return discovery_providers_module.normalize_address(value)

    def identity_match_score(
        self,
        lead: dict,
        candidate_name: str,
        candidate_address: str = "",
        candidate_phone: str = "",
    ) -> int:
        return discovery_providers_module.identity_match_score(self, lead, candidate_name, candidate_address, candidate_phone)

    def enrich_with_provider_sources(self, leads: list[dict]) -> list[dict]:
        return discovery_providers_module.enrich_with_provider_sources(self, leads)

    def _has_mx_record(self, domain: str) -> bool:
        return _has_mx_record(domain)

    def stop(self) -> None:
        self._stop_event.set()

    def ensure_storage_ready(self) -> None:
        return storage_module.ensure_storage_ready(self)

    def ensure_ready(self) -> None:
        self.ensure_storage_ready()
        self.config.overture_cache_dir.mkdir(parents=True, exist_ok=True)

        if not BS4 or not LXML_AVAILABLE:
            raise LeadMachineError(
                "Install beautifulsoup4 and lxml before running Colorado Lead Machine. "
                "Run: pip install -r requirements.txt"
            )
        requires_google = self.config.seed_mode in {"Google", "Hybrid"}
        if requires_google and not self.config.google_maps_api_key.strip():
            raise LeadMachineError("Add a Google Maps API key before running Google or Hybrid seed mode.")
        if self.config.seed_mode in {"Overture", "Hybrid"} and duckdb is None:
            raise LeadMachineError("Install duckdb to use Overture or Hybrid seed mode. Run: pip install duckdb")
        if self.config.fast_test_lead_limit < 1:
            raise LeadMachineError("Fast test lead limit must be at least 1.")
        if self.config.fast_test_total_run_cap is not None and self.config.fast_test_total_run_cap < 1:
            raise LeadMachineError("Fast test total run cap must be blank or at least 1.")

    def is_targeted_recheck(self) -> bool:
        return bool(self.config.target_lead_keys)

    def run(self, *, saved_scan_id: int | None = None, run_reason: str = "manual") -> Path:
        self.ensure_ready()
        start = time.time()
        targeted_recheck = self.is_targeted_recheck()
        self.log("Starting Lead Machine")
        if self.config.client_name:
            self.log(f"Client/campaign: {self.config.client_name}")
        self.log(
            f"Scan profile: {self.config.scan_profile_name or 'Custom'} | "
            f"Targeting: {self.config.target_profile_name or 'All supported'} | "
            f"Focus: {self.opportunity_focus_label()} | "
            f"Intensity: {self.automation_intensity_label()}"
        )
        if self.config.fast_test_mode:
            overall_cap = self.fast_test_total_run_cap()
            overall_text = f" with an overall hard cap of {overall_cap} leads." if overall_cap else "."
            self.log(
                "Fast test mode is ON. "
                f"Will collect up to {self.fast_test_seed_limit()} seed candidates per city and fully process up to "
                f"{self.config.fast_test_lead_limit} filtered leads per city"
                f"{overall_text}"
            )
        if self.config.seed_mode == "Hybrid":
            self.log(
                "Hybrid mode will use Overture for discovery first, then Google will verify every lead "
                "that still looks like a true no-website business after web-presence checks."
            )
        self.start_run_record(saved_scan_id=saved_scan_id, run_reason=run_reason)
        try:
            if targeted_recheck:
                leads = self.load_targeted_leads(self.config.target_lead_keys)
                self.record_stage_report(
                    "targeted_recheck",
                    "Load targeted leads",
                    requested=len(self.config.target_lead_keys),
                    loaded=len(leads),
                    target_pool=self.config.target_pool_name or "Custom lead set",
                )
                if not leads:
                    raise LeadMachineError("No stored leads were available for this targeted recheck.")
                self.log(
                    f"Loaded {len(leads)} targeted leads"
                    + (f" from {self.config.target_pool_name}" if self.config.target_pool_name else "")
                    + "."
                )
            else:
                candidates = self.seed_candidates()
                leads = self.filter_candidate_leads(candidates)
                if not leads:
                    raise LeadMachineError("No candidates survived the filter stage.")
                leads = self.apply_fast_test_shortlist(leads)
            leads = self.verify_web_presence(leads)
            leads = self.enrich_hybrid_shortlist_with_google(leads)
            leads = self.enrich_with_provider_sources(leads)
            leads = self.enrich_with_colorado_records(leads)
            if not leads:
                raise LeadMachineError("No leads survived the web presence and records stages.")
            leads = self.enrich_with_pagespeed(leads)
            leads = self.enrich_with_tech_stack(leads)
            leads = self.enrich_with_emails(leads)
            leads = self.score_leads(leads)
            if not targeted_recheck:
                leads = self.apply_opportunity_focus(leads)
                if not leads:
                    raise LeadMachineError("No leads matched the selected opportunity focus.")
            for lead in leads:
                has_phone = bool(lead.get("Phone"))
                has_email = bool(lead.get("Email"))
                lead["Actionable"] = has_phone or has_email
                if has_phone and has_email:
                    lead["Actionability Notes"] = "Phone and email available"
                elif has_email:
                    lead["Actionability Notes"] = "Email available"
                elif has_phone:
                    lead["Actionability Notes"] = "Phone only"
                else:
                    lead["Actionability Notes"] = "No phone or email found"

            self.persist_lead_history(leads)

            before = len(leads)
            non_actionable = sum(1 for lead in leads if not lead.get("Actionable"))
            if targeted_recheck:
                dropped = 0
                if non_actionable:
                    self.log(
                        f"Targeted recheck kept {non_actionable} lead(s) with no phone and no email so their refreshed data stays visible."
                    )
                self.record_stage_report(
                    "actionable",
                    "Refresh targeted leads and keep all",
                    kept=len(leads),
                    non_actionable=non_actionable,
                    dropped_no_contact=0,
                )
            else:
                leads = [lead for lead in leads if lead.get("Actionable")]
                dropped = before - len(leads)
                if dropped:
                    self.log(f"Filtered {dropped} leads with no phone and no email.")
                self.record_stage_report(
                    "actionable",
                    "Keep only actionable leads",
                    kept=len(leads),
                    dropped_no_contact=dropped,
                )
                if not leads:
                    raise LeadMachineError("No actionable leads remained after filtering.")
            output_file = self.export_excel(leads)
            elapsed = int(time.time() - start)
            self.finalize_run_summary(leads, dropped, output_file, elapsed)
            self.log(f"Completed in {elapsed // 60}m {elapsed % 60}s")
            self.finish_run_record("completed", output_file)
            return output_file
        except Exception as exc:
            self.finish_run_record("failed", error_message=str(exc))
            raise

    def _check_stop(self) -> None:
        if self._stop_event.is_set():
            raise LeadMachineError("Run stopped by user.")

    @contextmanager
    def _connect_db(self):
        with storage_module.connect_db(self) as conn:
            yield conn

    def initialize_database(self) -> None:
        return storage_module.initialize_database(self)

    def ensure_column(self, conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        return storage_module.ensure_column(self, conn, table, column, definition)

    def _hydrate_saved_scan_summary_row(self, row: tuple[Any, ...]) -> dict[str, Any]:
        return storage_module.hydrate_saved_scan_summary_row(row)

    def _hydrate_saved_scan_detail_row(self, row: tuple[Any, ...]) -> dict[str, Any]:
        return storage_module.hydrate_saved_scan_detail_row(row)

    def list_saved_scan_summaries(self) -> list[dict[str, Any]]:
        return storage_module.list_saved_scan_summaries(self)

    def get_saved_scan(self, scan_id: int) -> dict[str, Any] | None:
        return storage_module.get_saved_scan(self, scan_id)

    def list_saved_scans(self) -> list[dict]:
        return storage_module.list_saved_scans(self)

    def set_saved_scan_active(self, scan_id: int, is_active: bool) -> None:
        return storage_module.set_saved_scan_active(self, scan_id, is_active)

    def save_saved_scan(self, name: str, payload: dict, scan_id: int | None = None) -> int:
        return storage_module.save_saved_scan(self, name, payload, scan_id=scan_id)

    def list_lead_pool_members(self, pool_name: str = "Pinned Leads") -> list[dict]:
        cleaned_name = str(pool_name or "").strip()
        if not cleaned_name:
            return []
        self.ensure_storage_ready()
        with self._connect_db() as conn:
            row = conn.execute(
                "SELECT id FROM lead_lists WHERE LOWER(name) = LOWER(?)",
                (cleaned_name,),
            ).fetchone()
            if not row:
                return []
            rows = conn.execute(
                """
                SELECT
                    lh.lead_key,
                    lh.business_name,
                    lh.city_area,
                    llm.added_at
                FROM lead_list_members llm
                JOIN lead_history lh ON lh.lead_key = llm.lead_key
                WHERE llm.list_id = ?
                ORDER BY llm.added_at ASC, lh.business_name COLLATE NOCASE ASC
                """,
                (int(row[0]),),
            ).fetchall()
        return [
            {
                "lead_key": str(member_row[0]),
                "business_name": str(member_row[1] or ""),
                "city_area": str(member_row[2] or ""),
                "added_at": str(member_row[3] or ""),
            }
            for member_row in rows
        ]

    def delete_saved_scan(self, scan_id: int) -> None:
        return storage_module.delete_saved_scan(self, scan_id)

    def list_recent_runs(self, limit: int = 12) -> list[dict]:
        return storage_module.list_recent_runs(self, limit=limit)

    def build_saved_scan_payload_from_run(self, run: dict, *, output_folder: str = "", skip_email_lookup: bool | None = None) -> dict:
        return storage_module.build_saved_scan_payload_from_run(
            self,
            run,
            output_folder=output_folder,
            skip_email_lookup=skip_email_lookup,
        )

    def _int_or_none(self, value: object) -> int | None:
        try:
            if value in {"", None}:
                return None
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    def get_run_report(self, run_id: int | None = None) -> dict:
        return storage_module.get_run_report(self, run_id=run_id)

    def load_targeted_leads(self, lead_keys: list[str]) -> list[dict]:
        return storage_module.load_targeted_leads(self, lead_keys)

    def list_run_preview(self, run_id: int | None = None, limit: int = 25) -> list[dict]:
        return storage_module.list_run_preview(self, run_id=run_id, limit=limit)

    def start_run_record(self, saved_scan_id: int | None = None, run_reason: str = "manual") -> None:
        return storage_module.start_run_record(self, saved_scan_id=saved_scan_id, run_reason=run_reason)

    def record_stage_report(self, stage_key: str, label: str, **metrics: object) -> None:
        return storage_module.record_stage_report(self, stage_key, label, **metrics)

    def finalize_run_summary(
        self,
        leads: list[dict],
        dropped_no_contact: int,
        output_file: Path,
        elapsed_seconds: int,
    ) -> None:
        return storage_module.finalize_run_summary(
            self,
            leads,
            dropped_no_contact,
            output_file,
            elapsed_seconds,
        )

    def write_run_report_files(self) -> Optional[Path]:
        return storage_module.write_run_report_files(self)

    def finish_run_record(
        self,
        status: str,
        output_file: Optional[Path] = None,
        error_message: str = "",
    ) -> None:
        return storage_module.finish_run_record(self, status, output_file=output_file, error_message=error_message)

    def _list_run_lead_keys(self, conn: sqlite3.Connection, run_id: int) -> list[str]:
        return storage_module.list_run_lead_keys(conn, run_id)

    def _load_leads_for_keys(
        self,
        conn: sqlite3.Connection,
        lead_keys: set[str],
        *,
        limit: int | None = 8,
    ) -> list[dict]:
        return storage_module.load_leads_for_keys(conn, lead_keys, limit=limit)

    def _load_run_audits(
        self,
        conn: sqlite3.Connection,
        run_id: int,
        lead_keys: set[str],
    ) -> dict[str, dict[str, Any]]:
        cleaned_keys = [lead_key for lead_key in lead_keys if lead_key]
        if not cleaned_keys:
            return {}
        placeholders = ", ".join("?" for _ in cleaned_keys)
        rows = conn.execute(
            f"""
            SELECT lead_key, website_bucket, failure_type, primary_business_impact, best_pitch_angle,
                   audit_confidence, data_freshness, resolved_url, evidence_summary, evidence_snippet,
                   contact_form_status, booking_flow_status, cta_strength, seo_basics,
                   image_quality_signal, navigation_quality, social_dependence, directory_dependence,
                   ssl_status, last_verified_at
            FROM opportunity_audits
            WHERE run_id = ? AND lead_key IN ({placeholders})
            """,
            (int(run_id), *cleaned_keys),
        ).fetchall()
        audits: dict[str, dict[str, Any]] = {}
        for row in rows:
            lead_key = str(row[0] or "").strip()
            if not lead_key:
                continue
            audits[lead_key] = {
                "lead_key": lead_key,
                "website_bucket": str(row[1] or ""),
                "failure_type": str(row[2] or ""),
                "primary_business_impact": str(row[3] or ""),
                "best_pitch_angle": str(row[4] or ""),
                "audit_confidence": str(row[5] or ""),
                "data_freshness": str(row[6] or ""),
                "resolved_url": str(row[7] or ""),
                "evidence_summary": str(row[8] or ""),
                "evidence_snippet": str(row[9] or ""),
                "contact_form_status": str(row[10] or ""),
                "booking_flow_status": str(row[11] or ""),
                "cta_strength": str(row[12] or ""),
                "seo_basics": str(row[13] or ""),
                "image_quality_signal": str(row[14] or ""),
                "navigation_quality": str(row[15] or ""),
                "social_dependence": str(row[16] or ""),
                "directory_dependence": str(row[17] or ""),
                "ssl_status": str(row[18] or ""),
                "last_verified_at": str(row[19] or ""),
            }
        return audits

    def _load_trigger_events_for_run(
        self,
        conn: sqlite3.Connection,
        run_id: int,
        lead_keys: set[str],
    ) -> dict[str, list[dict[str, Any]]]:
        cleaned_keys = [lead_key for lead_key in lead_keys if lead_key]
        if not cleaned_keys:
            return {}
        placeholders = ", ".join("?" for _ in cleaned_keys)
        rows = conn.execute(
            f"""
            SELECT lead_key, trigger_type, trigger_label, trigger_strength, summary
            FROM trigger_events
            WHERE run_id = ? AND lead_key IN ({placeholders})
            ORDER BY lead_key, id ASC
            """,
            (int(run_id), *cleaned_keys),
        ).fetchall()
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            lead_key = str(row[0] or "").strip()
            if not lead_key:
                continue
            grouped.setdefault(lead_key, []).append(
                {
                    "type": str(row[1] or ""),
                    "label": str(row[2] or ""),
                    "strength": str(row[3] or ""),
                    "summary": str(row[4] or ""),
                }
            )
        return grouped

    def _monitor_bucket_rank(self, bucket: str) -> int:
        normalized = str(bucket or "").strip()
        return _MONITOR_BUCKET_RANK.get(normalized, 0)

    def _monitor_trend_label(self, previous_count: int, latest_count: int) -> str:
        if previous_count <= 0:
            return "Baseline established"
        delta = latest_count - previous_count
        if delta > 0:
            return f"+{delta} vs previous"
        if delta < 0:
            return f"{delta} vs previous"
        return "No count change"

    def _build_monitor_preview_lead(
        self,
        lead: dict[str, Any],
        *,
        change_kind: str,
        latest_audit: dict[str, Any] | None = None,
        previous_audit: dict[str, Any] | None = None,
        trigger_events: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        preview = dict(lead)
        current_key = str(preview.get("_stored_lead_key", "")).strip()
        web_status = (
            str((latest_audit or {}).get("website_bucket") or preview.get("Web Presence Status") or preview.get("Website Status") or "").strip()
        )
        failure_type = str((latest_audit or {}).get("failure_type") or "").strip()
        pitch_family = derive_pitch_family(latest_audit or preview)
        previous_pitch_family = derive_pitch_family(previous_audit or {})
        score = int(preview.get("Lead Score") or 0)
        actionable = bool(preview.get("Actionable")) or bool(str(preview.get("Phone", "")).strip()) or bool(str(preview.get("Email", "")).strip())
        trigger_events = list(trigger_events or [])
        trigger_types = {str(event.get("type", "")).strip() for event in trigger_events if event}
        trigger_summary = str(preview.get("Trigger Summary", "")).strip()
        impact = str((latest_audit or {}).get("primary_business_impact") or "").strip()
        evidence = str((latest_audit or {}).get("evidence_summary") or "").strip()
        why_it_matters = impact or evidence or trigger_summary
        flags: list[str] = []
        worsened = False
        review_first = False

        if change_kind == "new":
            summary = f"New {pitch_family.replace('_', ' ')} lead." if pitch_family else "New lead appeared in this run."
            if actionable:
                flags.append("newly_actionable")
                review_first = True
            if score >= 80 or self._monitor_bucket_rank(web_status) >= 3:
                review_first = True
        elif change_kind == "removed":
            previous_bucket = str((previous_audit or {}).get("website_bucket") or web_status).strip()
            summary = "Lead dropped out of the latest run."
            if previous_bucket:
                summary = f"Lead disappeared after previously showing {previous_bucket.lower()} conditions."
            if score >= 85 and self._monitor_bucket_rank(previous_bucket) >= 3:
                review_first = True
        else:
            previous_bucket = str((previous_audit or {}).get("website_bucket") or "").strip()
            previous_failure = str((previous_audit or {}).get("failure_type") or "").strip()
            summary_bits: list[str] = []
            if previous_bucket and web_status and previous_bucket != web_status:
                summary_bits.append(f"Website moved from {previous_bucket.lower()} to {web_status.lower()}.")
                if self._monitor_bucket_rank(web_status) > self._monitor_bucket_rank(previous_bucket):
                    worsened = True
            if failure_type and failure_type != previous_failure:
                summary_bits.append(f"Failure is now {failure_type.lower()}.")
                if web_status == "Broken site" or "security" in failure_type.lower():
                    worsened = True
            if pitch_family and previous_pitch_family and pitch_family != previous_pitch_family:
                summary_bits.append(f"Pitch family shifted to {pitch_family.replace('_', ' ')}.")
            if "domain_issue" in trigger_types:
                worsened = True
            if "new_contact_channel" in trigger_types and actionable:
                flags.append("newly_actionable")
                review_first = True
            if not summary_bits:
                summary_bits.append(trigger_summary or "The lead changed since the previous run.")
            summary = " ".join(summary_bits[:3]).strip()
            if score >= 80 or worsened:
                review_first = True

        if worsened:
            flags.append("worsened")
        if review_first:
            flags.append("review_first")

        preview["Monitor Change Kind"] = change_kind
        preview["Monitor Change Summary"] = summary
        preview["Monitor Why It Matters"] = why_it_matters
        preview["Monitor Review Priority"] = "Review first" if review_first else "Watch"
        preview["Monitor Flags"] = ", ".join(flags)
        preview["Monitor Worsened"] = worsened
        preview["Monitor Newly Actionable"] = "newly_actionable" in flags
        preview["Monitor Pitch Family"] = pitch_family
        if current_key:
            preview["_stored_lead_key"] = current_key
        return preview

    def _build_monitor_headlines(self, monitor: dict[str, Any]) -> list[str]:
        return storage_module.build_monitor_headlines(monitor)

    def _build_monitor_summary(self, conn: sqlite3.Connection, saved_scan_id: int, latest_run_id: int) -> dict:
        return storage_module.build_monitor_summary(self, conn, saved_scan_id, latest_run_id)

    def get_saved_scan_monitor_report(self, scan_id: int, preview_limit: int = 8) -> dict:
        return storage_module.get_saved_scan_monitor_report(self, scan_id, preview_limit=preview_limit)

    def make_lead_key(self, lead: dict) -> str:
        source = str(lead.get("Seed Source", "unknown")).strip().lower()
        external_id = str(lead.get("Place ID", "")).strip()
        if external_id:
            return f"{source}:{external_id}"
        name = self.normalize_business_name(str(lead.get("Business Name", "")))
        address = str(lead.get("Address", "")).strip().lower()
        return f"{source}:{name}|{address}"

    def apply_website_opportunity_audit(self, lead: dict, *, audited_at: str | None = None) -> dict:
        scorecard = build_website_opportunity_scorecard(lead, audited_at=audited_at)
        lead.update({key: value for key, value in scorecard.items() if not key.endswith(" Json")})
        return scorecard

    def apply_trigger_detection(
        self,
        lead: dict,
        previous_lead: dict | None = None,
        *,
        observed_at: str | None = None,
    ) -> list[dict]:
        trigger_events = detect_trigger_events(lead, previous_lead, observed_at=observed_at)
        lead["Trigger Count"] = len(trigger_events)
        lead["Trigger Types"] = summarize_trigger_types(trigger_events)
        lead["Trigger Summary"] = summarize_trigger_events(trigger_events)
        lead["Trigger Details"] = format_trigger_events(trigger_events)
        lead["Trigger Version"] = TRIGGER_DETECTION_VERSION
        lead["Last Triggered At"] = (observed_at or datetime.now().isoformat(timespec="seconds")) if trigger_events else ""
        return trigger_events

    def persist_lead_history(self, leads: list[dict]) -> None:
        return storage_module.persist_lead_history(self, leads)

    def is_chain(self, name: str) -> bool:
        normalized = self.normalize_filter_text(name)
        if normalized and any(normalized == self.normalize_filter_text(chain) for chain in CHAIN_EXACT_ONLY):
            return True
        if self.keyword_match(name, EXCLUDE_CHAINS):
            return True
        stripped = re.sub(r"\s*#\d+$", "", normalized).strip()
        if stripped != normalized and any(stripped == self.normalize_filter_text(chain) for chain in EXCLUDE_CHAINS):
            return True
        return False

    def is_large_org(self, name: str) -> bool:
        lowered = name.lower()
        return any(keyword in lowered for keyword in EXCLUDE_ORG_KEYWORDS)

    def normalize_filter_text(self, value: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()

    def normalize_state_code(self, value: object) -> str:
        cleaned = re.sub(r"[^A-Za-z ]+", " ", str(value or "")).strip()
        if not cleaned:
            return ""
        upper = cleaned.upper()
        if upper in US_STATE_NAMES:
            return upper
        normalized = self.normalize_filter_text(cleaned)
        for code, state_name in US_STATE_NAMES.items():
            if normalized == self.normalize_filter_text(state_name):
                return code
        return ""

    def state_name_for_code(self, code: object) -> str:
        return US_STATE_NAMES.get(str(code or "").strip().upper(), "")

    def parse_city_state(self, area: object) -> dict[str, str]:
        cleaned = re.sub(r"\s+", " ", str(area or "").strip())
        if not cleaned:
            return {"city": "", "state_code": "", "state_name": "", "area": ""}

        parts = [part.strip() for part in cleaned.split(",") if part.strip()]
        city = parts[0] if parts else cleaned
        state_code = self.normalize_state_code(parts[1]) if len(parts) >= 2 else ""

        if not state_code:
            head, separator, tail = cleaned.rpartition(" ")
            if separator:
                trailing_code = self.normalize_state_code(tail)
                if trailing_code:
                    city = head.rstrip(" ,")
                    state_code = trailing_code

        if not state_code:
            normalized_area = self.normalize_filter_text(cleaned)
            for code, state_name in sorted(US_STATE_NAMES.items(), key=lambda item: len(item[1]), reverse=True):
                normalized_state = self.normalize_filter_text(state_name)
                suffix = f" {normalized_state}"
                if normalized_area.endswith(suffix):
                    state_code = code
                    city = cleaned[: -len(state_name)].rstrip(" ,")
                    break

        return {
            "city": city.strip(),
            "state_code": state_code,
            "state_name": self.state_name_for_code(state_code),
            "area": cleaned,
        }

    def city_from_area(self, area: object) -> str:
        return self.parse_city_state(area)["city"]

    def state_code_from_area(self, area: object) -> str:
        return self.parse_city_state(area)["state_code"]

    def state_name_from_area(self, area: object) -> str:
        return self.parse_city_state(area)["state_name"]

    def search_context_from_area(self, area: object) -> str:
        parsed = self.parse_city_state(area)
        city = parsed["city"]
        state_code = parsed["state_code"]
        if city and state_code:
            return f"{city}, {state_code}"
        return parsed["area"] or city

    def dataforseo_location_name(self, area: object) -> str:
        parsed = self.parse_city_state(area)
        city = parsed["city"]
        state_name = parsed["state_name"]
        if city and state_name:
            return f"{city},{state_name},United States"
        if city:
            return f"{city},United States"
        return "United States"

    def target_profile(self) -> dict[str, object]:
        name = str(self.config.target_profile_name or "All supported").strip() or "All supported"
        return dict(TARGETING_CATEGORY_PRESETS.get(name) or TARGETING_CATEGORY_PRESETS["All supported"])

    def target_google_place_types(self) -> list[str]:
        explicit = [str(item).strip() for item in self.config.target_place_types if str(item).strip()]
        source = explicit or list(self.target_profile().get("google_place_types") or PLACE_TYPES)
        allowed = set(PLACE_TYPES)
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in source:
            value = str(item).strip()
            if value in allowed and value not in seen:
                seen.add(value)
                cleaned.append(value)
        return cleaned or list(PLACE_TYPES)

    def target_overture_keywords(self) -> list[str]:
        explicit = [str(item).strip().lower() for item in self.config.target_category_keywords if str(item).strip()]
        preset_keywords = list(self.target_profile().get("overture_keywords") or OVERTURE_CATEGORY_KEYWORDS)
        source = [*preset_keywords, *explicit]
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in source:
            value = self.normalize_filter_text(str(item))
            if value and value not in seen:
                seen.add(value)
                cleaned.append(value)
        return cleaned or list(OVERTURE_CATEGORY_KEYWORDS)

    def opportunity_focus_label(self) -> str:
        key = str(self.config.opportunity_focus or "any").strip() or "any"
        return OPPORTUNITY_FOCUS_PRESETS.get(key, OPPORTUNITY_FOCUS_PRESETS["any"])

    def automation_intensity_label(self) -> str:
        key = str(self.config.automation_intensity or "normal").strip() or "normal"
        return AUTOMATION_INTENSITY_PRESETS.get(key, AUTOMATION_INTENSITY_PRESETS["normal"])

    def keeps_real_websites_for_opportunity_focus(self) -> bool:
        focus = str(self.config.opportunity_focus or "any").strip() or "any"
        return focus in {"any", "premium_client_fit"}

    def lead_matches_opportunity_focus(self, lead: dict) -> bool:
        focus = str(self.config.opportunity_focus or "any").strip() or "any"
        if focus == "any":
            return True
        web_presence = str(lead.get("Web Presence Status", "")).strip()
        website_failure_type = str(lead.get("Website Failure Type", "")).strip().lower()
        reviews = int(lead.get("Reviews") or 0)
        business_age_days = lead.get("Business Age Days")
        broken_links = int(lead.get("Broken Link Count") or 0)

        if focus == "no_website":
            return web_presence == "No website"
        if focus == "broken_site":
            return web_presence == "Broken site"
        if focus == "weak_site":
            return web_presence in {"Weak site", "Basic site", "Directory only", "Social only"}
        if focus == "high_review_no_website":
            return web_presence == "No website" and reviews >= max(int(self.config.min_reviews or 0), 20)
        if focus == "new_business":
            return isinstance(business_age_days, int) and 0 < business_age_days <= 365
        if focus == "urgent_fix":
            return (
                web_presence == "Broken site"
                or broken_links >= 2
                or any(term in website_failure_type for term in ["ssl", "security", "dead", "parked", "placeholder"])
            )
        if focus == "premium_client_fit":
            revenue_tier = str(lead.get("Revenue Tier", "")).strip()
            thriving_tier = str(lead.get("Thriving Tier", "")).strip()
            business_reality = str(lead.get("Business Reality", "")).strip()
            opportunity_label = str(lead.get("Opportunity Label", "")).strip()
            opportunity_score = int(lead.get("Opportunity Score") or 0)
            website_quality_score = int(lead.get("Website Quality Score") or 0)
            pagespeed_perf = int(lead.get("PageSpeed Performance Score") or 0)
            form_count = int(lead.get("Form Count") or 0)
            has_contact = bool(lead.get("Phone") or lead.get("Email"))
            lead_category_text = self.normalize_filter_text(
                " ".join(
                    str(lead.get(key, "") or "")
                    for key in (
                        "Business Name",
                        "Business Type",
                        "Lead Rationale",
                        "Opportunity Brief",
                        "Thriving Signals",
                        "Revenue Note",
                    )
                )
            )
            high_value_terms = {
                "custom home",
                "home builder",
                "luxury home",
                "design build",
                "general contractor",
                "real estate",
                "developer",
                "property developer",
                "construction",
                "architect",
                "interior designer",
                "remodel",
                "roofing",
            }
            high_value_category = any(
                self.normalize_filter_text(term) in lead_category_text
                for term in high_value_terms
            )
            active_record = str(lead.get("Official Status Category") or lead.get("Colorado Status Category") or "").strip() == "Active"
            licensed = str(lead.get("License Status", "")).strip() == "License verified"
            has_conversion_gap = (
                not str(lead.get("CTA Terms", "")).strip()
                or (not str(lead.get("Booking Terms", "")).strip() and form_count == 0)
                or (
                    not str(lead.get("On-Page Phones", "")).strip()
                    and not str(lead.get("On-Page Emails", "")).strip()
                    and form_count == 0
                )
                or broken_links >= 1
                or bool(str(lead.get("Outdated Design Markers", "")).strip())
                or (0 < pagespeed_perf < 75)
            )
            budget_fit = (
                revenue_tier in {"High revenue", "Medium-high revenue"}
                or (reviews >= max(int(self.config.min_reviews or 0), 50) and thriving_tier in {"Thriving", "Established"})
                or (
                    high_value_category
                    and (
                        reviews >= max(3, int(self.config.min_reviews or 0))
                        or thriving_tier in {"Growing", "Established", "Thriving"}
                        or active_record
                        or licensed
                    )
                )
            )
            obvious_web_gap = web_presence in {"No website", "Broken site", "Weak site", "Basic site", "Directory only", "Social only"}
            live_site_gap = web_presence == "Real website" and website_quality_score < 75 and has_conversion_gap

            if opportunity_label == "Low opportunity despite high quality":
                return False
            return (
                has_contact
                and budget_fit
                and business_reality != "Uncertain / weak match"
                and (obvious_web_gap or live_site_gap)
                and (opportunity_score >= 12 or has_conversion_gap)
            )
        return True

    def apply_opportunity_focus(self, leads: list[dict]) -> list[dict]:
        focus = str(self.config.opportunity_focus or "any").strip() or "any"
        if focus == "any":
            self.record_stage_report(
                "opportunity_focus",
                "Apply opportunity focus",
                focus=self.opportunity_focus_label(),
                kept=len(leads),
                dropped=0,
            )
            return leads

        kept = [lead for lead in leads if self.lead_matches_opportunity_focus(lead)]
        dropped = len(leads) - len(kept)
        self.log(f"Opportunity focus '{self.opportunity_focus_label()}' kept {len(kept)} and dropped {dropped}.")
        self.record_stage_report(
            "opportunity_focus",
            "Apply opportunity focus",
            focus=self.opportunity_focus_label(),
            kept=len(kept),
            dropped=dropped,
        )
        return kept

    def keyword_match(self, value: str, keywords: set[str]) -> str:
        normalized_value = self.normalize_filter_text(value)
        if not normalized_value:
            return ""
        padded_value = f" {normalized_value} "
        for keyword in keywords:
            normalized_keyword = self.normalize_filter_text(keyword)
            if normalized_keyword and f" {normalized_keyword} " in padded_value:
                return keyword
        return ""

    def bad_fit_reason(
        self,
        name: str,
        category: str = "",
        google_types: Optional[list[str]] = None,
    ) -> str:
        name_match = self.keyword_match(name, BAD_FIT_NAME_KEYWORDS)
        if name_match:
            return f"name matched '{name_match}'"

        category_match = self.keyword_match(category, BAD_FIT_CATEGORY_KEYWORDS)
        if category_match:
            return f"category matched '{category_match}'"

        for google_type in google_types or []:
            normalized_type = self.normalize_filter_text(str(google_type))
            if normalized_type in BAD_FIT_GOOGLE_TYPES:
                return f"type matched '{normalized_type}'"

        return ""

    def check_directory(self, url: str) -> str:
        return presence_module.check_directory(self, url)

    def normalize_domain(self, url: str) -> str:
        parsed = urlparse(url if "://" in url else f"https://{url}")
        return parsed.netloc.lower().replace("www.", "")

    def is_social_url(self, url: str) -> bool:
        return presence_module.is_social_url(self, url)

    def is_linkedin_url(self, url: str) -> bool:
        domain = self.normalize_domain(url)
        return domain == "linkedin.com" or domain.endswith(".linkedin.com")

    def clean_profile_url(self, url: str) -> str:
        parsed = urlparse(url.strip())
        if not parsed.scheme:
            parsed = urlparse(f"https://{url.strip()}")
        return f"{parsed.scheme or 'https'}://{parsed.netloc}{parsed.path}".rstrip("/")

    def is_link_hub_url(self, url: str) -> bool:
        return presence_module.is_link_hub_url(self, url)

    def is_marketplace_url(self, url: str) -> bool:
        return presence_module.is_marketplace_url(self, url)

    def extract_links_from_page(self, html: str, base_url: str) -> list[str]:
        return presence_module.extract_links_from_page(self, html, base_url)

    def extract_website_from_social_bio(self, social_url: str) -> str:
        return presence_module.extract_website_from_social_bio(self, social_url)

    def _extract_facebook_website(self, fb_url: str) -> str:
        """Try to extract a website link from a Facebook page."""
        # Try the /about variant first — it often shows the website field
        return presence_module.extract_facebook_website(self, fb_url)

    def _extract_instagram_website(self, ig_url: str) -> str:
        """Try to extract a website link from an Instagram profile.

        Instagram bio links often go through link hubs (Linktree, etc).
        We fetch the profile page and look for external links.
        """
        return presence_module.extract_instagram_website(self, ig_url)

    def _extract_linkedin_website(self, li_url: str) -> str:
        """Try to extract a website link from a LinkedIn profile/company page."""
        return presence_module.extract_linkedin_website(self, li_url)

    def _follow_link_hub(self, hub_url: str) -> str:
        """Follow a link-in-bio page and extract the best website link."""
        return presence_module.follow_link_hub(self, hub_url)

    def _looks_like_business_domain(self, url: str) -> bool:
        """Quick check that a URL looks like it could be a business website."""
        return presence_module.looks_like_business_domain(self, url)

    def social_platform_name(self, url: str) -> str:
        return presence_module.social_platform_name(self, url)

    def social_handle(self, url: str) -> str:
        return presence_module.social_handle(self, url)

    def format_social_profile(self, url: str) -> str:
        return presence_module.format_social_profile(self, url)

    def join_social_profiles(self, profiles: list[str]) -> str:
        return presence_module.join_social_profiles(self, profiles)

    def join_social_profile_urls(self, profiles: list[str]) -> str:
        return presence_module.join_social_profile_urls(self, profiles)

    def build_contact_cross_reference(self, lead: dict) -> tuple[str, str]:
        phone = str(lead.get("Phone", "")).strip()
        email = str(lead.get("Email", "")).strip().lower()
        official_website = str(lead.get("Official Website", "")).strip()
        linkedin_url = str(lead.get("LinkedIn Profile", "")).strip()
        social_profile_urls = [
            item.strip()
            for item in str(lead.get("Social Profile URLs", lead.get("Social Profiles", ""))).split(",")
            if item.strip()
        ]

        details: list[str] = []
        email_matches_website = False

        if email:
            details.append("email present")
        if phone:
            details.append("phone present")

        if email and official_website:
            email_domain = email.split("@", 1)[1]
            website_domain = self.normalize_domain(official_website)
            if email_domain == website_domain or email_domain.endswith(f".{website_domain}") or website_domain.endswith(f".{email_domain}"):
                email_matches_website = True
                details.append("email domain matches website domain")
            else:
                return "Needs review", f"Email domain {email_domain} does not match website domain {website_domain}"

        if linkedin_url:
            details.append("LinkedIn profile found")
        if social_profile_urls:
            details.append(f"{len(social_profile_urls)} social profile(s) found")

        if official_website and email_matches_website and (linkedin_url or social_profile_urls):
            return "Strong", "; ".join(details)
        if official_website and (phone or email):
            return "Good", "; ".join(details or ["contact info aligns with website presence"])
        if linkedin_url or social_profile_urls:
            return "Some", "; ".join(details or ["social or LinkedIn presence found"])
        if phone or email:
            return "Limited", "; ".join(details)
        return "None", "No contact info or supporting public profiles found"

    def looks_parked_or_placeholder(self, html: str) -> bool:
        return presence_module.looks_parked_or_placeholder(self, html)

    def detect_template_builder(self, html: str, resolved_url: str) -> str:
        return presence_module.detect_template_builder(html, resolved_url)

    def classify_placeholder_reason(self, html: str, resolved_url: str) -> tuple[str, str]:
        return presence_module.classify_placeholder_reason(self, html, resolved_url)

    def _visible_text(self, html: str) -> str:
        """Extract visible text from HTML, stripping tags and attributes."""
        return presence_module.visible_text(html)

    def text_word_count(self, html: str) -> int:
        """Count visible words. Strips scripts, styles, noscript, and common
        hidden-from-view elements so builder templates (Wix, Squarespace) do
        not get credit for boilerplate noscript fallbacks or hidden SEO divs."""
        return presence_module.text_word_count(html)

    def _unique_phone_matches(self, text: str) -> list[str]:
        return presence_module.unique_phone_matches(text, PHONE_RE)

    def extract_site_evidence(
        self,
        html: str,
        resolved_url: str,
        *,
        http_status: int | None = None,
        fetch_time_ms: int | None = None,
    ) -> dict[str, object]:
        return presence_module.extract_site_evidence(
            self,
            html,
            resolved_url,
            http_status=http_status,
            fetch_time_ms=fetch_time_ms,
        )

    def _discover_inner_page_urls(self, html: str, resolved_url: str) -> dict[str, str]:
        return presence_module.discover_inner_page_urls(self, html, resolved_url)

    def _fetch_inner_page_evidence(self, resolved_url: str, homepage_html: str) -> dict[str, object]:
        return presence_module.fetch_inner_page_evidence(self, resolved_url, homepage_html)

    def inspect_site_quality(
        self,
        html: str,
        resolved_url: str,
        *,
        http_status: int | None = None,
        fetch_time_ms: int | None = None,
    ) -> tuple[str, str, str, dict[str, object]]:
        return presence_module.inspect_site_quality(
            self,
            html,
            resolved_url,
            http_status=http_status,
            fetch_time_ms=fetch_time_ms,
        )

    def make_web_result(
        self,
        status: str,
        website: str = "",
        details: str = "",
        confidence: str = "Medium",
        signals: str = "",
        site_evidence: Optional[dict[str, object]] = None,
    ) -> tuple[str, str, str, str, str]:
        result = (status, website, details, confidence, signals)
        self._web_result_evidence[result] = dict(WEBSITE_EVIDENCE_DEFAULTS)
        if site_evidence:
            self._web_result_evidence[result].update(
                {key: value for key, value in site_evidence.items() if not str(key).startswith("_")}
            )
        return result

    def classify_seed_url_fast(self, url: str) -> tuple[str, str]:
        return presence_module.classify_seed_url_fast(self, url)

    def domains_look_related(self, original_url: str, resolved_url: str) -> bool:
        original_domain = self.normalize_domain(original_url)
        resolved_domain = self.normalize_domain(resolved_url)
        if not original_domain or not resolved_domain:
            return False
        if original_domain == resolved_domain:
            return True
        if original_domain.endswith(f".{resolved_domain}") or resolved_domain.endswith(f".{original_domain}"):
            return True
        original_root = ".".join(original_domain.split(".")[-2:])
        resolved_root = ".".join(resolved_domain.split(".")[-2:])
        return bool(original_root and resolved_root and original_root == resolved_root)

    # ── Deep website verification helpers ───────────────────────

    _TRANSIENT_EXCEPTIONS = (
        requests.exceptions.TooManyRedirects,
        requests.exceptions.ConnectTimeout,
        requests.exceptions.ReadTimeout,
        requests.exceptions.ConnectionError,
        requests.exceptions.SSLError,
    )

    def _url_variations(self, url: str) -> list[str]:
        return network_module.url_variations(url)

    # Connect-vs-read timeout split: connect dies fast on dead hosts/DNS,
    # read lingers long enough for slow real sites.
    _DEFAULT_FETCH_TIMEOUT: tuple[float, float] = (3.5, 7.0)
    _SHORT_FETCH_TIMEOUT: tuple[float, float] = (2.5, 5.0)

    def _try_fetch(
        self,
        url: str,
        timeout: tuple[float, float] | int | float | None = None,
    ) -> tuple[requests.Response | None, Exception | None]:
        """Attempt a single GET request.

        Returns (response, exception). Exactly one is None. Caller can use
        the exception type to decide whether URL variations are worth trying
        (e.g. SSLError → try http; DNS/ConnectionError → give up)."""
        return network_module.try_fetch(self, url, timeout)

    def _should_try_variations(self, exc: Exception | None) -> bool:
        """Decide if URL variations (www/https/http) are worth retrying after
        a failed primary attempt. DNS/connect failures won't help — bail."""
        return network_module.should_try_variations(exc)

    def _fetch_with_fallbacks(self, url: str) -> tuple[requests.Response | None, str, bool]:
        """Try the URL with shrunk retry budget. Worst-case total time:
        ~3 attempts × ~10s max each ≈ 30 seconds (not 110).

        Returns (response_or_None, tried_url, was_fallback).
        """
        return network_module.fetch_with_fallbacks(self, url)

    def classify_request_exception(self, exc: Exception, url: str) -> tuple[str, str, str, str, str]:
        return presence_module.classify_request_exception(self, exc, url)

    def classify_known_web_presence(self, url: str) -> tuple[str, str, str, str, str]:
        return presence_module.classify_known_web_presence(self, url)

    def choose_web_presence_result(self, *results: tuple[str, str, str, str, str]) -> tuple[str, str, str, str, str]:
        priority = {
            "No website": 1,
            "Unknown web presence": 2,
            "Directory only": 3,
            "Social only": 4,
            "Broken site": 5,
            "Weak site": 6,
            "Basic site": 7,
            "Real website": 8,
        }
        confidence_rank = {"": 0, "Low": 1, "Medium": 2, "High": 3}
        best = self.make_web_result("Unknown web presence", "", "", "Low", "")
        for result in results:
            result_priority = priority.get(result[0], 0)
            best_priority = priority.get(best[0], 0)
            if result_priority > best_priority:
                best = result
            elif result_priority == best_priority and confidence_rank.get(result[3], 0) > confidence_rank.get(best[3], 0):
                best = result
        return best

    def website_failure_type(self, status: str, details: str, signals: str) -> str:
        lowered = f"{details} {signals}".lower()
        if status == "No website":
            return "No official website"
        if status == "Unknown web presence":
            return "Unknown web presence"
        if status == "Directory only":
            return "Directory-only presence"
        if status == "Social only":
            return "Social-only presence"
        if status == "Basic site":
            return "Live but basic website"
        if status == "Weak site":
            return "Live but weak website"
        if status != "Broken site":
            return status
        if "parked" in lowered or "for sale" in lowered:
            return "Parked or for-sale domain"
        if "coming-soon" in lowered or "under-construction" in lowered or "placeholder" in lowered or "holding page" in lowered:
            return "Placeholder or under-construction site"
        if "dead page" in lowered or "page missing" in lowered or "removed" in lowered or "http 404" in lowered or "http 410" in lowered:
            return "Dead domain or missing page"
        if "ssl" in lowered or "tls" in lowered:
            return "SSL or security failure"
        if "redirect" in lowered:
            return "Redirect problem"
        if "server error" in lowered or "http 5" in lowered:
            return "Server error"
        if "timeout" in lowered or "connection failure" in lowered or "dns" in lowered:
            return "Timeout or connection failure"
        return "Broken website"

    def geocode_search_area(self, area: str) -> Optional[dict]:
        cache_key = area.lower().strip()
        if not cache_key:
            return None
        if cache_key in self.search_area_cache:
            return self.search_area_cache[cache_key]

        try:
            response = self._request(
                "get",
                "https://nominatim.openstreetmap.org/search",
                params={
                    "q": area,
                    "format": "jsonv2",
                    "limit": 1,
                    "countrycodes": "us",
                },
                headers={"User-Agent": "SummitLeadMachine/1.0"},
                timeout=15,
            )
            data = response.json() if response.status_code == 200 else []
            if not data:
                self.search_area_cache[cache_key] = None
                return None

            location = {
                "name": area,
                "lat": float(data[0]["lat"]),
                "lng": float(data[0]["lon"]),
                "bbox": data[0].get("boundingbox", []),
            }
            self.search_area_cache[cache_key] = location
            time.sleep(1.1)
            return location
        except Exception:
            self.search_area_cache[cache_key] = None
            return None

    def resolve_search_locations(self) -> list[dict]:
        requested = [area.strip() for area in self.config.search_areas if area.strip()]
        if not requested:
            requested = default_search_areas()

        default_lookup = {location["name"].lower(): dict(location) for location in SEARCH_LOCATIONS}
        resolved: list[dict] = []
        unresolved: list[str] = []
        seen: set[str] = set()

        for area in requested:
            key = area.lower()
            if key in seen:
                continue
            seen.add(key)

            if key in default_lookup:
                resolved.append(default_lookup[key])
                continue

            geocoded = self.geocode_search_area(area)
            if geocoded:
                resolved.append(geocoded)
            else:
                unresolved.append(area)

        if unresolved:
            self.log(f"Could not resolve these search areas: {', '.join(unresolved)}")
        if not resolved:
            raise LeadMachineError("No valid search areas were resolved. Enter at least one city and state.")

        self.log(f"Resolved {len(resolved)} search areas for this run.")
        return resolved

    def build_search_tiles(self, location: dict) -> list[dict]:
        grid_size = clamp(self.config.tile_grid_size, 1, 5)
        if grid_size == 1:
            return [{**location, "tile_label": "center"}]

        half = grid_size // 2
        lat = float(location["lat"])
        lng = float(location["lng"])
        lat_step = (self.config.search_radius * 0.8) / 111_320
        lng_divisor = max(abs(math.cos(math.radians(lat))) * 111_320, 1e-6)
        lng_step = (self.config.search_radius * 0.8) / lng_divisor

        tiles: list[dict] = []
        for row in range(-half, half + 1):
            for col in range(-half, half + 1):
                if grid_size % 2 == 0 and row == half:
                    continue
                if grid_size % 2 == 0 and col == half:
                    continue
                tile_label = f"r{row:+d}c{col:+d}"
                tiles.append(
                    {
                        "name": location["name"],
                        "lat": lat + (row * lat_step),
                        "lng": lng + (col * lng_step),
                        "tile_label": tile_label,
                    }
                )
        return tiles

    def fetch_overture_latest_release(self) -> str:
        return enrichment_module.fetch_overture_latest_release(self)

    def slugify(self, text: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")

    def get_area_bounds(self, location: dict) -> tuple[float, float, float, float]:
        return enrichment_module.get_area_bounds(self, location)

    def ensure_overture_cache(self, location: dict) -> Path:
        return enrichment_module.ensure_overture_cache(self, location)

    def overture_category_matches(self, category: str) -> bool:
        return enrichment_module.overture_category_matches(self, category)

    def seed_overture_candidates(self) -> list[dict]:
        return enrichment_module.seed_overture_candidates(self)

    def seed_candidates(self) -> list[dict]:
        return enrichment_module.seed_candidates(self)

    def maps_nearby(self, lat: float, lng: float, place_type: str, page_token: Optional[str] = None) -> dict:
        return enrichment_module.maps_nearby(self, lat, lng, place_type, page_token=page_token)

    def maps_details(self, place_id: str) -> dict:
        return enrichment_module.maps_details(self, place_id)

    def load_monthly_usage(self) -> int:
        return storage_module.load_monthly_usage(self)

    def log_usage(self, details_used: int) -> None:
        return storage_module.log_usage(self, details_used)

    def load_processed_ids(self) -> set[str]:
        return storage_module.load_processed_ids(self)

    def save_processed_ids(self, ids: set[str]) -> None:
        return storage_module.save_processed_ids(self, ids)

    def normalize_business_name(self, name: str) -> str:
        return matching_module.normalize_business_name(name)

    def fast_test_total_run_cap(self) -> int | None:
        return self._int_or_none(self.config.fast_test_total_run_cap)

    def fast_test_seed_limit(self) -> int:
        return max(self.config.fast_test_lead_limit * 4, self.config.fast_test_lead_limit)

    def fast_test_total_seed_limit(self) -> int | None:
        total_run_cap = self.fast_test_total_run_cap()
        if total_run_cap is None:
            return None
        return max(total_run_cap * 4, total_run_cap)

    def candidate_priority_score(self, lead: dict) -> int:
        return enrichment_module.candidate_priority_score(self, lead)

    def sort_leads_by_priority(self, leads: list[dict]) -> list[dict]:
        return enrichment_module.sort_leads_by_priority(self, leads)

    def apply_fast_test_shortlist(self, leads: list[dict]) -> list[dict]:
        if not self.config.fast_test_mode:
            return leads

        per_city_limit = self.config.fast_test_lead_limit
        total_limit = self.fast_test_total_run_cap()
        city_counts: dict[str, int] = {}
        city_trimmed: list[dict] = []
        skipped_by_city_cap = 0

        for lead in leads:
            city = str(lead.get("City/Area", "")).strip() or "Unknown area"
            current = city_counts.get(city, 0)
            if current >= per_city_limit:
                skipped_by_city_cap += 1
                continue
            city_counts[city] = current + 1
            city_trimmed.append(lead)

        skipped_by_total_cap = 0
        trimmed = city_trimmed
        if total_limit is not None and len(city_trimmed) > total_limit:
            skipped_by_total_cap = len(city_trimmed) - total_limit
            trimmed = city_trimmed[:total_limit]

        skipped = len(leads) - len(trimmed)
        if skipped == 0:
            self.record_stage_report(
                "fast_test",
                "Fast test shortlist",
                enabled=True,
                per_city_limit=per_city_limit,
                overall_limit=total_limit or "",
                cities_kept=len(city_counts),
                processed_leads=len(leads),
                skipped_by_city_cap=0,
                skipped_by_total_cap=0,
                skipped_for_speed=0,
            )
            return leads

        overall_text = f" with an overall hard cap of {total_limit}" if total_limit is not None else ""
        self.log(
            f"Fast test mode: keeping up to {per_city_limit} filtered leads per city{overall_text}, "
            f"processing {len(trimmed)} total and skipping {skipped} for speed."
        )
        self.record_stage_report(
            "fast_test",
            "Fast test shortlist",
            enabled=True,
            per_city_limit=per_city_limit,
            overall_limit=total_limit or "",
            cities_kept=len(city_counts),
            processed_leads=len(trimmed),
            skipped_by_city_cap=skipped_by_city_cap,
            skipped_by_total_cap=skipped_by_total_cap,
            skipped_for_speed=skipped,
        )
        return trimmed

    def escape_soql_literal(self, value: str) -> str:
        return matching_module.escape_soql_literal(value)

    def business_name_tokens(self, name: str) -> list[str]:
        return matching_module.business_name_tokens(self, name)

    def query_business_name_tokens(self, name: str) -> list[str]:
        return matching_module.query_business_name_tokens(self, name)

    def meaningful_business_name_tokens(self, name: str) -> set[str]:
        return matching_module.meaningful_business_name_tokens(self, name)

    def soql_string_literal(self, value: str) -> str:
        return matching_module.soql_string_literal(self, value)

    def _safe_soql_field_name(self, field: str) -> str:
        return matching_module.safe_soql_field_name(field)

    def build_soql_upper_equals_clause(self, field: str, value: str) -> str:
        return matching_module.build_soql_upper_equals_clause(self, field, value)

    def build_soql_like_clauses(self, fields: list[str], tokens: list[str], *, limit: int = 3) -> list[str]:
        return matching_module.build_soql_like_clauses(self, fields, tokens, limit=limit)

    def _business_name_match_score(
        self,
        source_name: str,
        candidate_name: str,
        *,
        exact_score: int,
        prefix_score: int,
        contains_score: int,
    ) -> int:
        return matching_module.business_name_match_score(
            self,
            source_name,
            candidate_name,
            exact_score=exact_score,
            prefix_score=prefix_score,
            contains_score=contains_score,
        )

    parse_formation_date = staticmethod(colorado_records_module.parse_formation_date)
    colorado_match_assessment = colorado_records_module.colorado_match_assessment
    fetch_colorado_entity_candidates = colorado_records_module.fetch_colorado_entity_candidates
    score_colorado_entity_match = colorado_records_module.score_colorado_entity_match
    pick_best_colorado_entity = colorado_records_module.pick_best_colorado_entity
    license_target_for_lead = staticmethod(colorado_records_module.license_target_for_lead)
    fetch_colorado_license_candidates = colorado_records_module.fetch_colorado_license_candidates
    score_colorado_license_match = colorado_records_module.score_colorado_license_match
    pick_best_colorado_license = colorado_records_module.pick_best_colorado_license
    validate_colorado_license = colorado_records_module.validate_colorado_license
    california_contractor_license_target_for_lead = staticmethod(colorado_records_module.california_contractor_license_target_for_lead)
    fetch_california_contractor_license_candidates = colorado_records_module.fetch_california_contractor_license_candidates
    score_california_contractor_license_match = colorado_records_module.score_california_contractor_license_match
    pick_best_california_contractor_license = colorado_records_module.pick_best_california_contractor_license
    validate_california_contractor_license = colorado_records_module.validate_california_contractor_license
    validate_business_license = colorado_records_module.validate_business_license
    fetch_colorado_transaction_history = colorado_records_module.fetch_colorado_transaction_history
    categorize_colorado_status = staticmethod(colorado_records_module.categorize_colorado_status)
    summarize_colorado_history = staticmethod(colorado_records_module.summarize_colorado_history)
    lookup_colorado_business_record = colorado_records_module.lookup_colorado_business_record
    california_match_assessment = colorado_records_module.california_match_assessment
    fetch_california_entity_candidates = colorado_records_module.fetch_california_entity_candidates
    score_california_entity_match = colorado_records_module.score_california_entity_match
    pick_best_california_entity = colorado_records_module.pick_best_california_entity
    categorize_california_status = staticmethod(colorado_records_module.categorize_california_status)
    lookup_california_business_record = colorado_records_module.lookup_california_business_record
    apply_official_record_to_lead = colorado_records_module.apply_official_record_to_lead

    def maps_find_place_from_text(self, text_query: str, location_bias: str = "") -> dict:
        return enrichment_module.maps_find_place_from_text(self, text_query, location_bias=location_bias)

    def google_match_score(self, lead: dict, candidate_name: str, candidate_address: str) -> int:
        return enrichment_module.google_match_score(self, lead, candidate_name, candidate_address)

    def find_google_place_for_lead(self, lead: dict) -> tuple[Optional[str], Optional[dict]]:
        return enrichment_module.find_google_place_for_lead(self, lead)

    def enrich_hybrid_shortlist_with_google(self, leads: list[dict]) -> list[dict]:
        return enrichment_module.enrich_hybrid_shortlist_with_google(self, leads)

    def seed_google_maps_candidates(self) -> list[dict]:
        return enrichment_module.seed_google_maps_candidates(self)

    def filter_candidate_leads(self, candidates: list[dict]) -> list[dict]:
        return matching_module.filter_candidate_leads(self, candidates)

    def extract_search_result_links(self, html: str, limit: int = 8) -> list[str]:
        return presence_module.extract_search_result_links(self, html, limit=limit)

    def search_public_links(self, query: str, limit: int = 8) -> list[str]:
        return presence_module.search_public_links(self, query, limit=limit)

    def discover_public_profiles(self, name: str, city: str) -> tuple[str, list[str], str]:
        # Focused LinkedIn queries — search company pages AND personal profiles
        return presence_module.discover_public_profiles(self, name, city)

    def discover_presence_bundle(self, name: str, city: str) -> dict[str, object]:
        return presence_module.discover_presence_bundle(self, name, city)

    def discover_web_presence(self, name: str, city: str) -> tuple[str, str, str, str, str]:
        return self.discover_presence_bundle(name, city)["web_result"]

    def verify_web_presence(self, leads: list[dict]) -> list[dict]:
        return presence_module.verify_web_presence(self, leads)

    def enrich_with_colorado_records(self, leads: list[dict]) -> list[dict]:
        return colorado_records_module.enrich_with_colorado_records(self, leads)

    def clean_email(self, email: str) -> Optional[str]:
        return contact_enrichment_module.clean_email(self, email)

    def extract_emails(self, text: str) -> list[str]:
        return contact_enrichment_module.extract_emails(self, text)

    def fetch_page(self, url: str, timeout: int = 8) -> tuple[Optional[str], Optional[str]]:
        return network_module.fetch_page(self, url, timeout)

    def scrape_site(self, base_url: str) -> tuple[Optional[str], Optional[str]]:
        return contact_enrichment_module.scrape_site(self, base_url)

    def scrape_known_site_email(self, lead: dict) -> tuple[Optional[str], Optional[str]]:
        return contact_enrichment_module.scrape_known_site_email(self, lead)

    def hunter_search_email(self, lead: dict) -> tuple[Optional[str], Optional[str]]:
        return contact_enrichment_module.hunter_search_email(self, lead)

    def guess_domain_email(self, name: str, address: str) -> tuple[Optional[str], Optional[str]]:
        return contact_enrichment_module.guess_domain_email(self, name, address)

    def find_email(self, lead: dict) -> tuple[Optional[str], str]:
        return contact_enrichment_module.find_email(self, lead)

    def enrich_with_emails(self, leads: list[dict]) -> list[dict]:
        return contact_enrichment_module.enrich_with_emails(self, leads)

    def format_age_summary(self, age_days: object) -> str:
        return scoring_module.format_age_summary(age_days)

    def primary_business_label(self, lead: dict) -> str:
        return scoring_module.primary_business_label(lead)

    def join_readable_list(self, items: list[str]) -> str:
        return scoring_module.join_readable_list(items)

    def evaluate_business_reality(self, lead: dict, *, cross_reference: str = "") -> tuple[str, str, str]:
        return scoring_module.evaluate_business_reality(self, lead, cross_reference=cross_reference)

    def why_it_matters(self, lead: dict) -> str:
        return scoring_module.why_it_matters(lead)

    def why_business_is_worth_contacting(self, lead: dict, business_reality: str, reality_details: str) -> str:
        return scoring_module.why_business_is_worth_contacting(self, lead, business_reality, reality_details)

    def build_why_kept_summary(self, lead: dict, *, business_reality: str, reality_details: str) -> str:
        return scoring_module.build_why_kept_summary(
            self,
            lead,
            business_reality=business_reality,
            reality_details=reality_details,
        )

    def build_opportunity_brief(
        self,
        lead: dict,
        *,
        cross_reference: str = "",
    ) -> str:
        return scoring_module.build_opportunity_brief(self, lead, cross_reference=cross_reference)

    def compute_thriving_signals(self, lead: dict) -> dict:
        return scoring_module.compute_thriving_signals(lead)

    def compute_revenue_tier(self, lead: dict) -> dict:
        return scoring_module.compute_revenue_tier(lead)

    def compute_premium_fit_confidence(self, lead: dict) -> dict:
        return scoring_module.compute_premium_fit_confidence(self, lead)

    def compute_website_quality_score(self, lead: dict) -> dict:
        return scoring_module.compute_website_quality_score(lead)

    def compute_opportunity_score(self, lead: dict, lead_score: int) -> dict:
        return scoring_module.compute_opportunity_score(lead, lead_score)

    def choose_review_bucket(self, lead: dict, score: int, review_flags: list[str]) -> str:
        return scoring_module.choose_review_bucket(lead, score, review_flags)

    def score_leads(self, leads: list[dict]) -> list[dict]:
        return scoring_module.score_leads(self, leads)

    def export_excel(self, leads: list[dict]) -> Path:
        return reporting_module.export_excel(self, leads)
