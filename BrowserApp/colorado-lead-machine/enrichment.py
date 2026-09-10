from __future__ import annotations

"""Google and Overture seed/enrichment helpers for the Colorado lead machine."""

import math
import time
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from lead_machine import LeadMachine


MAPS_BASE = "https://maps.googleapis.com/maps/api/place"


def _get_lead_machine_error():
    from lead_machine import LeadMachineError

    return LeadMachineError


def _get_duckdb():
    from lead_machine import duckdb

    return duckdb


def _get_website_evidence_defaults() -> dict[str, object]:
    from lead_machine import WEBSITE_EVIDENCE_DEFAULTS

    return WEBSITE_EVIDENCE_DEFAULTS


def _lead_key(lead: dict) -> str:
    return str(lead.get("Place ID", "")) or f"{lead.get('Business Name', '')}|{lead.get('Address', '')}"


def _build_seed_candidate(
    *,
    place_id: str,
    seed_source: str,
    search_tile: str,
    business_name: str,
    address: str,
    phone: str,
    rating: object,
    reviews: object,
    seed_confidence: object,
    business_type: str,
    city_area: str,
    business_status: str,
    seed_website: str,
    website_status: str,
    listed_on: str,
    email: str = "",
    email_source: str = "",
) -> dict:
    return {
        "Place ID": place_id,
        "Google Place ID": place_id if seed_source == "Google Places" else "",
        "Seed Source": seed_source,
        "Search Tile": search_tile,
        "Business Name": business_name,
        "Address": address,
        "Phone": phone,
        "Rating": rating,
        "Reviews": reviews,
        "Seed Confidence": seed_confidence,
        "Business Type": business_type,
        "City/Area": city_area,
        "Business Status": business_status,
        "Seed Website": seed_website,
        "Website Status": website_status,
        "Listed On": listed_on,
        "Web Presence Status": "",
        "Web Presence Details": "",
        "Web Presence Confidence": "",
        "Website Signals": "",
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
        "Browser Fallback Used": "",
        "Browser Fallback Reason": "",
        "Browser Fallback Status": "",
        "Google Place URL": "",
        "Google Hours": "",
        "Google Price Level": "",
        "Google Photo Count": 0,
        "Google Photo References": "",
        "Google Review Snippets": "",
        "Google Address Components": "",
        "Google Location": "",
        "Official Website": "",
        "LinkedIn Profile": "",
        "Social Profiles": "",
        "Social Profile URLs": "",
        "Contact Cross-Reference": "",
        "Cross-Reference Details": "",
        "Formation Date": "",
        "Business Age Days": "",
        "Official Record Source": "",
        "Official Record State": "",
        "Official Record Status": "",
        "Official Status Category": "",
        "Official Match Type": "",
        "Official Match Confidence": "",
        "Official Status Note": "",
        "Official Latest Filing": "",
        "Official History Summary": "",
        "Official Entity ID": "",
        "Official Detail URL": "",
        "Colorado Record Status": "",
        "Colorado Status Category": "",
        "Colorado Match Type": "",
        "Colorado Match Confidence": "",
        "Colorado Status Note": "",
        "Colorado Latest Filing": "",
        "Colorado History Summary": "",
        "Colorado Entity ID": "",
        "License Target": "",
        "License Status": "",
        "License Confidence": "",
        "License Details": "",
        "License Verify Link": "",
        "Business Reality": "",
        "Reality Confidence": "",
        "Reality Details": "",
        "Website Bucket": "",
        "Website Failure Type": "",
        "Mobile Readiness": "",
        "SSL Status": "",
        "Page Speed Signal": "",
        "Contact Form Status": "",
        "Booking Flow Status": "",
        "CTA Strength": "",
        "SEO Basics": "",
        "Social Dependence": "",
        "Directory Dependence": "",
        "Image Quality Signal": "",
        "Navigation Quality": "",
        "Primary Business Impact": "",
        "Best Pitch Angle": "",
        "Audit Confidence": "",
        "Last Audited At": "",
        "Last Verified At": "",
        "Data Freshness": "",
        "Audit Issues": "",
        "Business Impact Summary": "",
        **_get_website_evidence_defaults(),
        "Trigger Count": 0,
        "Trigger Types": "",
        "Trigger Summary": "",
        "Trigger Details": "",
        "Trigger Version": "",
        "Last Triggered At": "",
        "Email": email,
        "Email Source": email_source,
        "Lead Score": "",
        "Review Bucket": "",
        "Opportunity Brief": "",
        "Why Kept": "",
        "Lead Rationale": "",
        "Score Breakdown": "",
        "Review Flags": "",
        "Contact Status": "",
        "Notes": "",
    }


def fetch_overture_latest_release(machine: "LeadMachine") -> str:
    LeadMachineError = _get_lead_machine_error()
    response = machine._request("get", "https://stac.overturemaps.org/catalog.json", timeout=15)
    if response.status_code != 200:
        raise LeadMachineError("Could not fetch the latest Overture release metadata.")
    payload = response.json()
    latest = payload.get("latest")
    if not latest:
        raise LeadMachineError("Overture release metadata did not include a latest release.")
    return str(latest)


def get_area_bounds(machine: "LeadMachine", location: dict) -> tuple[float, float, float, float]:
    if location.get("bbox"):
        south, north, west, east = [float(value) for value in location["bbox"]]
        return west, east, south, north

    geocoded = machine.geocode_search_area(location["name"])
    if geocoded and geocoded.get("bbox"):
        south, north, west, east = [float(value) for value in geocoded["bbox"]]
        return west, east, south, north

    lat = float(location["lat"])
    lng = float(location["lng"])
    half = max(1, min(machine.config.tile_grid_size, 5)) // 2
    lat_extent = ((half * 0.8) + 1.0) * machine.config.search_radius / 111_320
    lng_extent = ((half * 0.8) + 1.0) * machine.config.search_radius / max(abs(math.cos(math.radians(lat))) * 111_320, 1e-6)
    return lng - lng_extent, lng + lng_extent, lat - lat_extent, lat + lat_extent


def ensure_overture_cache(machine: "LeadMachine", location: dict) -> Path:
    LeadMachineError = _get_lead_machine_error()
    duckdb = _get_duckdb()
    if duckdb is None:
        raise LeadMachineError("duckdb is required for Overture seed mode.")

    release = machine.fetch_overture_latest_release()
    cache_file = machine.config.overture_cache_dir / f"{machine.slugify(location['name'])}_{release}.parquet"
    if cache_file.exists():
        return cache_file

    xmin, xmax, ymin, ymax = machine.get_area_bounds(location)
    machine.log(f"Downloading Overture cache for {location['name']} ({release})")

    conn = duckdb.connect()
    try:
        conn.execute("INSTALL httpfs;")
        conn.execute("LOAD httpfs;")
        conn.execute("SET s3_region='us-west-2';")
        remote_path = f"s3://overturemaps-us-west-2/release/{release}/theme=places/*/*"
        conn.execute(
            f"""
            COPY (
                SELECT
                    id,
                    names.primary AS name,
                    categories.primary AS category,
                    confidence,
                    websites[1] AS website,
                    socials[1] AS social,
                    emails[1] AS email,
                    phones[1] AS phone,
                    addresses[1].freeform AS address,
                    addresses[1].locality AS locality,
                    addresses[1].region AS region,
                    addresses[1].country AS country,
                    CAST(sources AS JSON) AS sources
                FROM read_parquet('{remote_path}')
                WHERE
                    bbox.xmin BETWEEN {xmin} AND {xmax} AND
                    bbox.ymin BETWEEN {ymin} AND {ymax} AND
                    addresses[1].country = 'US'
            ) TO '{cache_file.as_posix()}' (FORMAT PARQUET)
            """
        )
    except Exception as exc:
        raise LeadMachineError(f"Could not build Overture cache for {location['name']}: {exc}") from exc
    finally:
        conn.close()

    return cache_file


def overture_category_matches(machine: "LeadMachine", category: str) -> bool:
    lowered = category.lower().strip()
    if not lowered:
        return False
    return any(keyword in lowered for keyword in machine.target_overture_keywords())


def seed_overture_candidates(machine: "LeadMachine") -> list[dict]:
    LeadMachineError = _get_lead_machine_error()
    duckdb = _get_duckdb()
    if duckdb is None:
        raise LeadMachineError("duckdb is required for Overture seed mode.")

    machine.log("Stage 1/5: Seed search from Overture")
    search_locations = machine.resolve_search_locations()
    candidates: list[dict] = []
    seen_keys: set[str] = set()
    chain_skipped = 0
    bad_fit_skipped = 0
    seed_limit = machine.fast_test_seed_limit() if machine.config.fast_test_mode else 0
    total_seed_limit = machine.fast_test_total_seed_limit() if machine.config.fast_test_mode else None
    seed_limit_hit = False
    per_city_seed_caps_hit = 0
    total_seed_cap_hit = False

    for location in search_locations:
        machine._check_stop()
        if total_seed_limit is not None and len(candidates) >= total_seed_limit:
            total_seed_cap_hit = True
            seed_limit_hit = True
            machine.log(
                f"Fast test mode reached the total Overture seed cap ({total_seed_limit}); stopping seed collection early."
            )
            break
        if total_seed_cap_hit:
            break
        cache_file = machine.ensure_overture_cache(location)
        machine.log(f"Scanning Overture cache for {location['name']}")
        location_seed_count = 0

        conn = duckdb.connect()
        try:
            rows = conn.execute(
                f"""
                SELECT id, name, category, confidence, website, social, email, phone, address, locality, region, country, sources
                FROM read_parquet('{cache_file.as_posix()}')
                """
            ).fetchall()
        finally:
            conn.close()

        for row in rows:
            if seed_limit and location_seed_count >= seed_limit:
                seed_limit_hit = True
                per_city_seed_caps_hit += 1
                machine.log(
                    f"Fast test mode reached the Overture seed cap for {location['name']} ({seed_limit}); moving to the next city."
                )
                break
            (
                place_id,
                name,
                category,
                confidence,
                website,
                social,
                email,
                phone,
                address,
                locality,
                region,
                country,
                sources,
            ) = row

            if not name or not machine.overture_category_matches(str(category or "")):
                continue
            if confidence is not None and float(confidence) < 0.45:
                continue
            if machine.is_chain(str(name or "")) or machine.is_large_org(str(name or "")):
                chain_skipped += 1
                continue
            if machine.bad_fit_reason(str(name or ""), str(category or "")):
                bad_fit_skipped += 1
                continue

            dedupe_key = f"overture:{place_id}"
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)

            primary_url = website or social or ""
            seed_status, seed_detail = machine.classify_seed_url_fast(str(primary_url or ""))

            candidates.append(
                _build_seed_candidate(
                    place_id=str(place_id),
                    seed_source="Overture",
                    search_tile="dataset",
                    business_name=str(name),
                    address=str(address or ""),
                    phone=str(phone or ""),
                    rating="",
                    reviews="",
                    seed_confidence=float(confidence) if confidence is not None else "",
                    business_type=str(category or ""),
                    city_area=location["name"],
                    business_status="ACTIVE",
                    seed_website=str(primary_url or ""),
                    website_status=seed_status,
                    listed_on=seed_detail if seed_status in {"Directory only", "Social only"} else "",
                    email=str(email or ""),
                    email_source="Overture" if email else "",
                )
            )
            location_seed_count += 1

            if total_seed_limit is not None and len(candidates) >= total_seed_limit:
                seed_limit_hit = True
                total_seed_cap_hit = True
                machine.log(
                    f"Fast test mode reached the total Overture seed cap ({total_seed_limit}); stopping seed collection early."
                )
                break

        machine.log(f"Overture candidates for {location['name']}: {len(candidates)} total so far")

    machine.log(
        f"Overture seed complete. Candidates: {len(candidates)} | Chains skipped: {chain_skipped} | "
        f"Bad-fit skipped: {bad_fit_skipped}"
    )
    machine.record_stage_report(
        "seed_overture",
        "Seed from Overture",
        candidates=len(candidates),
        chains_skipped=chain_skipped,
        bad_fit_skipped=bad_fit_skipped,
        fast_test_seed_cap=seed_limit if seed_limit else "",
        fast_test_total_seed_cap=total_seed_limit if total_seed_limit else "",
        fast_test_seed_cap_hit=seed_limit_hit,
        fast_test_total_seed_cap_hit=total_seed_cap_hit,
        fast_test_seed_cap_cities_hit=per_city_seed_caps_hit,
    )
    return candidates


def seed_candidates(machine: "LeadMachine") -> list[dict]:
    mode = machine.config.seed_mode
    if mode == "Google":
        return machine.seed_google_maps_candidates()
    if mode == "Overture":
        return machine.seed_overture_candidates()
    if mode == "Hybrid":
        overture_candidates = machine.seed_overture_candidates()
        machine.log(
            "Hybrid seed complete. "
            f"Overture candidates: {len(overture_candidates)} | "
            "Google verification will run later on every lead still classified as No website."
        )
        machine.record_stage_report(
            "seed_combined",
            "Hybrid seed results",
            overture_candidates=len(overture_candidates),
            total_candidates=len(overture_candidates),
            google_verifies_no_website_leads=True,
        )
        return overture_candidates
    LeadMachineError = _get_lead_machine_error()
    raise LeadMachineError(f"Unknown seed mode: {mode}")


def maps_nearby(
    machine: "LeadMachine",
    lat: float,
    lng: float,
    place_type: str,
    page_token: Optional[str] = None,
) -> dict:
    params = {
        "location": f"{lat},{lng}",
        "radius": machine.config.search_radius,
        "type": place_type,
        "key": machine.config.google_maps_api_key,
    }
    if page_token:
        params = {"pagetoken": page_token, "key": machine.config.google_maps_api_key}
    response = machine._request("get", f"{MAPS_BASE}/nearbysearch/json", params=params, timeout=20)
    return response.json()


def maps_details(machine: "LeadMachine", place_id: str) -> dict:
    params = {
        "place_id": place_id,
        "fields": (
            "name,formatted_address,formatted_phone_number,website,"
            "business_status,types,rating,user_ratings_total,url,opening_hours,"
            "current_opening_hours,price_level,photos,reviews,address_components,"
            "geometry,plus_code"
        ),
        "key": machine.config.google_maps_api_key,
    }
    response = machine._request("get", f"{MAPS_BASE}/details/json", params=params, timeout=20)
    payload = response.json()
    return payload.get("result", {}) if payload.get("status") == "OK" else {}


def candidate_priority_score(machine: "LeadMachine", lead: dict) -> int:
    score = 0
    website_status = str(lead.get("Website Status", "")).strip()
    website_weights = {
        "No website": 60,
        "Directory only": 48,
        "Social only": 44,
        "Broken site": 38,
        "Website listed": 10,
    }
    score += website_weights.get(website_status, 0)

    if str(lead.get("Phone", "")).strip():
        score += 12
    if str(lead.get("Email", "")).strip():
        score += 8
    if str(lead.get("Address", "")).strip():
        score += 4

    seed_confidence = lead.get("Seed Confidence")
    try:
        if seed_confidence not in {"", None}:
            score += int(float(seed_confidence) * 10)
    except (TypeError, ValueError):
        pass

    try:
        rating = float(lead.get("Rating") or 0)
    except (TypeError, ValueError):
        rating = 0.0
    try:
        reviews = int(float(lead.get("Reviews") or 0))
    except (TypeError, ValueError):
        reviews = 0

    if rating:
        score += max(0, min(int(round(rating * 2)), 10))
    if reviews:
        score += min(reviews // 10, 12)

    business_type = str(lead.get("Business Type", "")).lower()
    service_tokens = [
        "plumber",
        "electric",
        "contractor",
        "repair",
        "cleaning",
        "lawyer",
        "dentist",
        "doctor",
        "insurance",
        "real_estate",
        "photograph",
        "spa",
        "salon",
    ]
    if any(token in business_type for token in service_tokens):
        score += 6

    return score


def sort_leads_by_priority(machine: "LeadMachine", leads: list[dict]) -> list[dict]:
    ranked = list(leads)
    for lead in ranked:
        lead["Candidate Priority Score"] = machine.candidate_priority_score(lead)
    ranked.sort(
        key=lambda lead: (
            -(int(lead.get("Candidate Priority Score") or 0)),
            -(float(lead.get("Rating") or 0) if str(lead.get("Rating") or "").strip() else 0.0),
            -(int(float(lead.get("Reviews") or 0)) if str(lead.get("Reviews") or "").strip() else 0),
            machine.normalize_business_name(str(lead.get("Business Name", ""))),
        )
    )
    return ranked


def maps_find_place_from_text(machine: "LeadMachine", text_query: str, location_bias: str = "") -> dict:
    params = {
        "input": text_query,
        "inputtype": "textquery",
        "fields": "place_id,name,formatted_address,business_status",
        "key": machine.config.google_maps_api_key,
    }
    if location_bias:
        params["locationbias"] = location_bias
    response = machine._request("get", f"{MAPS_BASE}/findplacefromtext/json", params=params, timeout=20)
    return response.json()


def google_match_score(machine: "LeadMachine", lead: dict, candidate_name: str, candidate_address: str) -> int:
    score = machine._business_name_match_score(
        str(lead.get("Business Name", "")),
        candidate_name,
        exact_score=100,
        prefix_score=72,
        contains_score=55,
    )

    city_name = machine.city_from_area(lead.get("City/Area", ""))
    if city_name and machine.normalize_filter_text(city_name) in machine.normalize_filter_text(candidate_address):
        score += 10

    lead_address = machine.normalize_filter_text(str(lead.get("Address", "")))
    candidate_address_normalized = machine.normalize_filter_text(candidate_address)
    if lead_address and candidate_address_normalized:
        lead_tokens = [token for token in lead_address.split() if len(token) >= 4 or token.isdigit()]
        address_overlap = sum(1 for token in lead_tokens[:4] if token in candidate_address_normalized)
        score += address_overlap * 4

    return score


def find_google_place_for_lead(machine: "LeadMachine", lead: dict) -> tuple[Optional[str], Optional[dict]]:
    existing_google_place_id = str(lead.get("Google Place ID", "")).strip()
    if existing_google_place_id:
        return existing_google_place_id, {"place_id": existing_google_place_id}
    if str(lead.get("Seed Source", "")).strip() == "Google Places":
        existing_place_id = str(lead.get("Place ID", "")).strip()
        if existing_place_id:
            return existing_place_id, {"place_id": existing_place_id}

    city_area = str(lead.get("City/Area", "")).strip()
    query_parts = [str(lead.get("Business Name", "")).strip()]
    if str(lead.get("Address", "")).strip():
        query_parts.append(str(lead.get("Address", "")).strip())
    elif city_area:
        query_parts.append(city_area)
    text_query = ", ".join(part for part in query_parts if part)
    if not text_query:
        return None, None

    location_bias = ""
    biased_location = machine.geocode_search_area(city_area) if city_area else None
    if biased_location:
        location_bias = f"circle:25000@{biased_location['lat']},{biased_location['lng']}"

    try:
        payload = machine.maps_find_place_from_text(text_query, location_bias)
    except Exception:
        return None, None

    candidates = payload.get("candidates", []) if isinstance(payload, dict) else []
    best_candidate: Optional[dict] = None
    best_score = 0
    for candidate in candidates:
        score = machine.google_match_score(
            lead,
            str(candidate.get("name", "")),
            str(candidate.get("formatted_address", "")),
        )
        if score > best_score:
            best_score = score
            best_candidate = candidate

    if not best_candidate or best_score < 45:
        return None, None

    place_id = str(best_candidate.get("place_id", "")).strip()
    if not place_id:
        return None, None
    return place_id, best_candidate


def enrich_hybrid_shortlist_with_google(machine: "LeadMachine", leads: list[dict]) -> list[dict]:
    if machine.config.seed_mode != "Hybrid":
        return leads

    ranked = machine.sort_leads_by_priority(leads)
    no_website_leads = [
        lead
        for lead in ranked
        if str(lead.get("Web Presence Status", "")).strip() in {"No website", "Unknown web presence"}
    ]
    if not no_website_leads:
        machine.record_stage_report(
            "hybrid_google",
            "Google verification for no-website leads",
            enabled=False,
            attempted=0,
            enriched=0,
            confirmed_no_website=0,
            reclassified=0,
            removed_real_website=0,
            removed_closed=0,
            removed_low_quality=0,
            removed_bad_fit=0,
            unmatched=0,
        )
        return ranked

    machine.log(
        f"Stage 3.5/5: Google verify all {len(no_website_leads)} Hybrid leads with No website or Unknown web presence"
    )

    removed_keys: set[str] = set()
    enriched = 0
    unmatched = 0
    confirmed_no_website = 0
    reclassified = 0
    removed_real_website = 0
    removed_closed = 0
    removed_low_quality = 0
    removed_bad_fit = 0

    for index, lead in enumerate(no_website_leads, start=1):
        machine._check_stop()
        place_id, _candidate = machine.find_google_place_for_lead(lead)
        if not place_id:
            unmatched += 1
            lead["Web Presence Status"] = "Unknown web presence"
            lead["Web Presence Confidence"] = "Low"
            lead["Web Presence Details"] = (
                str(lead.get("Web Presence Details", "")).strip()
                or "Google Places could not confidently match this business for website verification"
            )
            lead["Retry Recommended"] = "Yes"
            lead["Retry Reason"] = "Google Places unmatched"
            lead["Failure Reasons"] = "Google Places unmatched"
            continue

        details = machine.maps_details(place_id)
        if not details:
            unmatched += 1
            lead["Web Presence Status"] = "Unknown web presence"
            lead["Web Presence Confidence"] = "Low"
            lead["Retry Recommended"] = "Yes"
            lead["Retry Reason"] = "Google Place Details returned no data"
            lead["Failure Reasons"] = "Google Place Details returned no data"
            continue

        full_name = details.get("name", lead.get("Business Name", ""))
        detail_types = [str(item) for item in details.get("types", [])]
        rating = details.get("rating") or lead.get("Rating") or 0
        reviews = details.get("user_ratings_total") or lead.get("Reviews") or 0
        business_status = str(details.get("business_status", "")).strip()

        if machine.is_chain(full_name) or machine.is_large_org(full_name) or machine.bad_fit_reason(
            full_name,
            ", ".join(detail_types),
            detail_types,
        ):
            removed_bad_fit += 1
            removed_keys.add(_lead_key(lead))
            continue

        if business_status == "CLOSED_PERMANENTLY":
            removed_closed += 1
            removed_keys.add(_lead_key(lead))
            continue

        has_google_quality = bool(rating or reviews)
        if has_google_quality and (
            float(rating) < machine.config.min_rating or int(reviews) < machine.config.min_reviews
        ):
            removed_low_quality += 1
            removed_keys.add(_lead_key(lead))
            continue

        raw_site = str(details.get("website", "")).strip()
        directory_flag = machine.check_directory(raw_site)
        if details.get("formatted_address"):
            lead["Address"] = details.get("formatted_address", "")
        if details.get("formatted_phone_number"):
            lead["Phone"] = details.get("formatted_phone_number", "")
        if detail_types:
            lead["Business Type"] = ", ".join(detail_types[:3])
        lead["Business Name"] = full_name
        lead["Business Status"] = business_status or lead.get("Business Status", "")
        lead["Rating"] = rating
        lead["Reviews"] = reviews
        lead["Google Place ID"] = place_id
        lead["Google Place URL"] = str(details.get("url", ""))
        lead["Google Price Level"] = str(details.get("price_level", ""))
        hours = details.get("current_opening_hours") or details.get("opening_hours") or {}
        if isinstance(hours, dict):
            lead["Google Hours"] = "; ".join(str(item) for item in hours.get("weekday_text", [])[:7])
        photos = details.get("photos", []) if isinstance(details.get("photos"), list) else []
        if photos:
            lead["Google Photo Count"] = len(photos)
            lead["Google Photo References"] = ", ".join(str(photo.get("photo_reference", "")) for photo in photos[:3] if isinstance(photo, dict))
        reviews_payload = details.get("reviews", []) if isinstance(details.get("reviews"), list) else []
        if reviews_payload:
            lead["Google Review Snippets"] = " || ".join(
                str(review.get("text", "")).strip()[:220]
                for review in reviews_payload[:3]
                if isinstance(review, dict) and str(review.get("text", "")).strip()
            )
        address_components = details.get("address_components", []) if isinstance(details.get("address_components"), list) else []
        if address_components:
            lead["Google Address Components"] = "; ".join(
                str(component.get("long_name", ""))
                for component in address_components[:8]
                if isinstance(component, dict) and component.get("long_name")
            )
        geometry = details.get("geometry", {}) if isinstance(details.get("geometry"), dict) else {}
        location = geometry.get("location", {}) if isinstance(geometry.get("location"), dict) else {}
        if location:
            lead["Google Location"] = f"{location.get('lat', '')},{location.get('lng', '')}".strip(",")
        if raw_site:
            google_result = machine.classify_known_web_presence(raw_site)
            google_status, google_website, google_details, google_confidence, google_signals = google_result
            google_site_evidence = machine._web_result_evidence.get(google_result, {})
            if google_site_evidence:
                lead.update(google_site_evidence)

            lead["Seed Website"] = raw_site
            lead["Website Status"] = "Directory listing only" if directory_flag else "Website listed"
            lead["Listed On"] = directory_flag or ""
            lead["Web Presence Status"] = google_status
            lead["Official Website"] = google_website
            lead["Web Presence Details"] = google_details
            lead["Web Presence Confidence"] = google_confidence
            lead["Website Signals"] = google_signals
            lead["Website Failure Type"] = machine.website_failure_type(google_status, google_details, google_signals)
            machine.apply_website_opportunity_audit(lead)

            if google_status == "Real website":
                removed_real_website += 1
                removed_keys.add(_lead_key(lead))
                machine.log(f"Google removed real website from no-website list: {full_name} | {google_website or raw_site}")
                continue

            reclassified += 1
        else:
            if not str(lead.get("Seed Website", "")).strip():
                lead["Website Status"] = "No website"
            prior_evidence = str(lead.get("No Website Evidence", "")).strip()
            verification_sources = [
                source.strip()
                for source in str(lead.get("Verification Sources", "")).split(";")
                if source.strip()
            ]
            if prior_evidence:
                lead["Web Presence Status"] = "No website"
                lead["Web Presence Confidence"] = "High"
                lead["No Website Evidence"] = "; ".join(
                    dict.fromkeys([prior_evidence, "Google Places matched business and shows no website"])
                )
                lead["Verification Sources"] = "; ".join(dict.fromkeys([*verification_sources, "Google Places"]))
                lead["Web Presence Details"] = (
                    "No official website found in public discovery, and Google Places also shows no website"
                )
                lead["Website Signals"] = "public discovery and Google Places both show no official website"
                confirmed_no_website += 1
            else:
                lead["Web Presence Status"] = "Unknown web presence"
                lead["Web Presence Confidence"] = "Medium"
                lead["No Website Evidence"] = "Google Places matched business and shows no website"
                lead["Verification Sources"] = "Google Places"
                lead["Web Presence Details"] = (
                    "Google Places shows no website, but another independent source has not confirmed absence yet"
                )
                lead["Website Signals"] = "Google Places no website; public-search confirmation still required"
                lead["Retry Recommended"] = "Yes"
                lead["Retry Reason"] = "Needs second no-website confirmation source"
                lead["Failure Reasons"] = "Needs second no-website confirmation source"
            lead["Website Failure Type"] = machine.website_failure_type(
                str(lead.get("Web Presence Status", "")),
                str(lead.get("Web Presence Details", "")),
                str(lead.get("Website Signals", "")),
            )
            machine.apply_website_opportunity_audit(lead)
        lead["Google Enriched"] = True
        enriched += 1

        if index == 1 or index % 25 == 0 or index == len(no_website_leads):
            machine.log(
                f"Hybrid Google progress: {index}/{len(no_website_leads)} | enriched: {enriched} | "
                f"confirmed no website: {confirmed_no_website} | reclassified: {reclassified} | "
                f"removed: {removed_real_website + removed_closed + removed_low_quality + removed_bad_fit} | "
                f"unmatched: {unmatched}"
            )

    other_overture_leads = [
        lead
        for lead in ranked
        if not str(lead.get("Google Place ID", "")).strip()
        and str(lead.get("Web Presence Status", "")).strip() != "No website"
    ]
    verified_via_google = 0
    removed_closed_google = 0
    removed_bad_fit_google = 0
    if other_overture_leads:
        machine.log(
            f"Stage 3.5b/5: Google closed-status check for {len(other_overture_leads)} "
            f"non-no-website Overture leads without Google Place ID"
        )
        for index, lead in enumerate(other_overture_leads, start=1):
            machine._check_stop()
            place_id, _candidate = machine.find_google_place_for_lead(lead)
            if not place_id:
                continue
            details = machine.maps_details(place_id)
            if not details:
                continue
            verified_via_google += 1
            full_name = details.get("name", lead.get("Business Name", ""))
            detail_types = [str(item) for item in details.get("types", [])]
            business_status = str(details.get("business_status", "")).strip()
            rating = details.get("rating") or lead.get("Rating") or 0
            reviews = details.get("user_ratings_total") or lead.get("Reviews") or 0

            if business_status == "CLOSED_PERMANENTLY":
                removed_closed_google += 1
                removed_keys.add(_lead_key(lead))
                machine.log(f"Google removed permanently closed: {full_name}")
                continue

            if machine.is_chain(full_name) or machine.is_large_org(full_name) or machine.bad_fit_reason(
                full_name,
                ", ".join(detail_types),
                detail_types,
            ):
                removed_bad_fit_google += 1
                removed_keys.add(_lead_key(lead))
                continue

            lead["Google Place ID"] = place_id
            lead["Business Status"] = business_status or lead.get("Business Status", "")
            if not lead.get("Rating") and rating:
                lead["Rating"] = rating
            if not lead.get("Reviews") and reviews:
                lead["Reviews"] = reviews
            if details.get("formatted_phone_number") and not lead.get("Phone"):
                lead["Phone"] = details.get("formatted_phone_number", "")
            lead["Google Enriched"] = True

            if index == 1 or index % 50 == 0 or index == len(other_overture_leads):
                machine.log(
                    f"Google status check progress: {index}/{len(other_overture_leads)} | "
                    f"verified: {verified_via_google} | "
                    f"removed closed: {removed_closed_google} | removed bad-fit: {removed_bad_fit_google}"
                )

    kept: list[dict] = []
    for lead in ranked:
        if _lead_key(lead) in removed_keys:
            continue
        kept.append(lead)

    kept = machine.sort_leads_by_priority(kept)
    machine.record_stage_report(
        "hybrid_google",
        "Google verification for no-website leads",
        enabled=True,
        attempted=len(no_website_leads),
        enriched=enriched,
        confirmed_no_website=confirmed_no_website,
        reclassified=reclassified,
        removed_real_website=removed_real_website,
        unmatched=unmatched,
        removed_closed=removed_closed,
        removed_low_quality=removed_low_quality,
        removed_bad_fit=removed_bad_fit,
        verified_via_google=verified_via_google,
        removed_closed_google=removed_closed_google,
        removed_bad_fit_google=removed_bad_fit_google,
        kept_after_google=len(kept),
    )
    machine.log(
        f"Hybrid Google verification complete. Attempted: {len(no_website_leads)} | Enriched: {enriched} | "
        f"Confirmed no website: {confirmed_no_website} | Reclassified: {reclassified} | "
        f"Removed real website: {removed_real_website} | Removed closed: {removed_closed} | "
        f"Removed low-quality: {removed_low_quality} | Removed bad-fit: {removed_bad_fit} | "
        f"Unmatched: {unmatched}"
        + (
            f" | Google status verified: {verified_via_google} | "
            f"Removed closed (Google): {removed_closed_google} | Removed bad-fit (Google): {removed_bad_fit_google}"
            if other_overture_leads
            else ""
        )
    )
    return kept


def seed_google_maps_candidates(machine: "LeadMachine") -> list[dict]:
    candidates: list[dict] = []
    search_locations = machine.resolve_search_locations()
    target_place_types = machine.target_google_place_types()
    seen_ids = machine.load_processed_ids()
    previous_count = len(seen_ids)
    new_ids: set[str] = set()
    total_checked = 0
    quick_skipped = 0
    bad_fit_skipped = 0
    details_this_run = 0
    seed_limit = machine.fast_test_seed_limit() if machine.config.fast_test_mode else 0
    seed_limit_hit = False
    total_seed_limit = machine.fast_test_total_seed_limit() if machine.config.fast_test_mode else None
    per_city_seed_caps_hit = 0
    total_seed_cap_hit = False

    monthly_so_far = machine.load_monthly_usage()
    remaining_free = machine.config.max_details_per_month - monthly_so_far
    cap_this_run = min(machine.config.max_details_per_run, max(0, remaining_free))

    machine.log("Stage 1/5: Seed search from Google Maps")
    machine.log(f"Quota left this month: {remaining_free} Place Details calls")
    machine.log(f"Previously tracked place IDs: {previous_count}")

    if cap_this_run <= 0:
        LeadMachineError = _get_lead_machine_error()
        raise LeadMachineError("Monthly Place Details quota is exhausted.")

    quota_warned = False

    for location in search_locations:
        machine._check_stop()
        location_seed_count = 0
        location_seed_cap_hit = False
        if details_this_run >= cap_this_run or total_seed_cap_hit:
            if total_seed_cap_hit:
                machine.log(f"Fast test mode reached the total Google seed cap ({total_seed_limit}).")
            else:
                machine.log(f"Reached run cap of {cap_this_run} Place Details calls.")
            break
        search_tiles = machine.build_search_tiles(location)
        machine.log(
            f"Scanning {location['name']} across {len(search_tiles)} tiles "
            f"and {len(target_place_types)} target types ({details_this_run}/{cap_this_run})"
        )

        for tile in search_tiles:
            machine._check_stop()
            if details_this_run >= cap_this_run or total_seed_cap_hit or location_seed_cap_hit:
                break

            for place_type in target_place_types:
                machine._check_stop()
                if details_this_run >= cap_this_run or total_seed_cap_hit or location_seed_cap_hit:
                    break

                page_token = None
                pages = 0

                while pages < 3:
                    machine._check_stop()
                    if total_seed_cap_hit or location_seed_cap_hit:
                        break
                    if page_token:
                        time.sleep(2)

                    data = machine.maps_nearby(tile["lat"], tile["lng"], place_type, page_token)
                    status = data.get("status")
                    if status not in {"OK", "ZERO_RESULTS"}:
                        if status:
                            machine.log(
                                f"Google returned {status} for {place_type} in {location['name']} ({tile['tile_label']})"
                            )
                        break

                    for place in data.get("results", []):
                        machine._check_stop()
                        if details_this_run >= cap_this_run or total_seed_cap_hit:
                            break
                        if seed_limit and location_seed_count >= seed_limit:
                            seed_limit_hit = True
                            location_seed_cap_hit = True
                            per_city_seed_caps_hit += 1
                            machine.log(
                                f"Fast test mode reached the Google seed cap for {location['name']} ({seed_limit}); moving to the next city."
                            )
                            break

                        place_id = place.get("place_id")
                        if not place_id or place_id in seen_ids:
                            continue

                        seen_ids.add(place_id)
                        new_ids.add(place_id)

                        name = place.get("name", "")
                        quick_rating = place.get("rating", 0) or 0
                        quick_reviews = place.get("user_ratings_total", 0) or 0
                        quick_types = [str(item) for item in place.get("types", [])]

                        if machine.is_chain(name) or machine.is_large_org(name):
                            quick_skipped += 1
                            continue
                        if machine.bad_fit_reason(name, ", ".join(quick_types), quick_types):
                            quick_skipped += 1
                            bad_fit_skipped += 1
                            continue
                        if quick_rating < max(3.0, machine.config.min_rating - 0.6) or quick_reviews < 3:
                            quick_skipped += 1
                            continue

                        if not quota_warned and details_this_run >= cap_this_run * 0.9:
                            machine.log(f"Approaching the run cap: {details_this_run}/{cap_this_run}")
                            quota_warned = True

                        details = machine.maps_details(place_id)
                        total_checked += 1
                        details_this_run += 1
                        if not details:
                            continue

                        full_name = details.get("name", name)
                        rating = details.get("rating") or quick_rating
                        reviews = details.get("user_ratings_total") or quick_reviews
                        raw_site = details.get("website", "")
                        directory_flag = machine.check_directory(raw_site)
                        detail_types = [str(item) for item in details.get("types", [])]

                        if machine.bad_fit_reason(full_name, ", ".join(detail_types), detail_types):
                            bad_fit_skipped += 1
                            continue

                        candidates.append(
                            _build_seed_candidate(
                                place_id=place_id,
                                seed_source="Google Places",
                                search_tile=tile["tile_label"],
                                business_name=full_name,
                                address=details.get("formatted_address", ""),
                                phone=details.get("formatted_phone_number", ""),
                                rating=rating,
                                reviews=reviews,
                                seed_confidence=1.0,
                                business_type=", ".join(detail_types[:3]),
                                city_area=location["name"],
                                business_status=details.get("business_status", ""),
                                seed_website=raw_site,
                                website_status="Directory listing only" if directory_flag else ("Website listed" if raw_site else "No website"),
                                listed_on=directory_flag or "",
                            )
                        )
                        location_seed_count += 1
                        machine.log(f"Candidate found: {full_name} | {rating} stars | tile {tile['tile_label']}")
                        if total_seed_limit is not None and len(candidates) >= total_seed_limit:
                            seed_limit_hit = True
                            total_seed_cap_hit = True
                            machine.log(
                                f"Fast test mode reached the total Google seed cap ({total_seed_limit}); stopping seed collection early."
                            )
                            break
                        time.sleep(0.05)

                    page_token = data.get("next_page_token")
                    if not page_token:
                        break
                    pages += 1

    machine.log_usage(details_this_run)
    machine.save_processed_ids(seen_ids)
    machine.log(
        f"Seed search complete. Candidates: {len(candidates)} | Details checked: {total_checked} | "
        f"Quick-skipped before details: {quick_skipped} | Bad-fit skipped: {bad_fit_skipped}"
    )
    machine.log(f"New place IDs this run: {len(new_ids)} | Total tracked: {len(seen_ids)}")
    machine.record_stage_report(
        "seed_google",
        "Seed from Google Places",
        candidates=len(candidates),
        details_checked=total_checked,
        quick_skipped=quick_skipped,
        bad_fit_skipped=bad_fit_skipped,
        new_place_ids=len(new_ids),
        total_tracked_place_ids=len(seen_ids),
        target_types=len(target_place_types),
        fast_test_seed_cap=seed_limit if seed_limit else "",
        fast_test_total_seed_cap=total_seed_limit if total_seed_limit else "",
        fast_test_seed_cap_hit=seed_limit_hit,
        fast_test_total_seed_cap_hit=total_seed_cap_hit,
        fast_test_seed_cap_cities_hit=per_city_seed_caps_hit,
    )
    return candidates
