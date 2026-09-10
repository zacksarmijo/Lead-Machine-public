from __future__ import annotations

"""Business-name matching and candidate filtering helpers."""

import re
from typing import TYPE_CHECKING

from lead_machine_match_config import WEAK_MATCH_NAME_TOKENS

if TYPE_CHECKING:
    from lead_machine import LeadMachine


def normalize_business_name(name: str) -> str:
    lowered = re.sub(r"[^a-z0-9 ]", " ", name.lower())
    lowered = re.sub(r"\b(llc|inc|corp|co|ltd|pllc|pc)\b", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def escape_soql_literal(value: str) -> str:
    return value.replace("'", "''")


def business_name_tokens(machine: "LeadMachine", name: str) -> list[str]:
    normalized = machine.normalize_business_name(name)
    tokens = [token for token in normalized.split() if len(token) >= 3]
    stop_words = {"the", "and", "for", "llc", "inc", "corp", "co", "ltd", "pllc", "pc"}
    return [token for token in tokens if token not in stop_words]


def query_business_name_tokens(machine: "LeadMachine", name: str) -> list[str]:
    tokens = machine.business_name_tokens(name)
    strong = [token for token in tokens if token not in WEAK_MATCH_NAME_TOKENS]
    weak = [token for token in tokens if token in WEAK_MATCH_NAME_TOKENS]
    return strong + weak


def meaningful_business_name_tokens(machine: "LeadMachine", name: str) -> set[str]:
    tokens = set(machine.business_name_tokens(name))
    return {token for token in tokens if token not in WEAK_MATCH_NAME_TOKENS}


def soql_string_literal(machine: "LeadMachine", value: str) -> str:
    return f"'{machine.escape_soql_literal(str(value).strip())}'"


def safe_soql_field_name(field: str) -> str:
    cleaned = str(field).strip().lower()
    if not re.fullmatch(r"[a-z][a-z0-9_]*", cleaned):
        raise ValueError(f"Unsafe SOQL field name: {field}")
    return cleaned


def build_soql_upper_equals_clause(machine: "LeadMachine", field: str, value: str) -> str:
    normalized = machine.normalize_filter_text(value)
    if not normalized:
        return ""
    safe_field = machine._safe_soql_field_name(field)
    return f"upper({safe_field}) = {machine.soql_string_literal(normalized.upper())}"


def build_soql_like_clauses(machine: "LeadMachine", fields: list[str], tokens: list[str], *, limit: int = 3) -> list[str]:
    safe_fields = [machine._safe_soql_field_name(field) for field in fields]
    clauses: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        normalized = re.sub(r"[^a-z0-9]+", "", token.lower())
        if len(normalized) < 3 or normalized in seen:
            continue
        seen.add(normalized)
        escaped = machine.escape_soql_literal(normalized.upper())
        if len(safe_fields) == 1:
            clauses.append(f"upper({safe_fields[0]}) like '%{escaped}%'")
        else:
            field_clauses = [f"upper({field}) like '%{escaped}%'" for field in safe_fields]
            clauses.append(f"({' OR '.join(field_clauses)})")
        if len(clauses) >= limit:
            break
    return clauses


def business_name_match_score(
    machine: "LeadMachine",
    source_name: str,
    candidate_name: str,
    *,
    exact_score: int,
    prefix_score: int,
    contains_score: int,
) -> int:
    target_name = machine.normalize_business_name(source_name)
    normalized_candidate = machine.normalize_business_name(candidate_name)
    target_tokens = set(machine.business_name_tokens(source_name))
    candidate_tokens = set(machine.business_name_tokens(candidate_name))
    target_meaningful = machine.meaningful_business_name_tokens(source_name)
    candidate_meaningful = machine.meaningful_business_name_tokens(candidate_name)

    score = 0
    has_exactish_match = False
    if target_name and normalized_candidate == target_name:
        score += exact_score
        has_exactish_match = True
    elif target_name and (normalized_candidate.startswith(target_name) or target_name.startswith(normalized_candidate)):
        score += prefix_score
        has_exactish_match = True
    elif target_name and target_name in normalized_candidate:
        score += contains_score

    overlap = target_tokens & candidate_tokens
    meaningful_overlap = target_meaningful & candidate_meaningful
    score += len(meaningful_overlap) * 18
    score += max(0, len(overlap) - len(meaningful_overlap)) * 4

    if target_tokens:
        score += int((len(overlap) / max(len(target_tokens), 1)) * 12)
    if target_meaningful:
        score += int((len(meaningful_overlap) / max(len(target_meaningful), 1)) * 28)

    if target_meaningful and not meaningful_overlap:
        score -= 25
    elif not has_exactish_match:
        missing_meaningful = target_meaningful - candidate_meaningful
        score -= len(missing_meaningful) * 26

    return max(score, 0)


def filter_candidate_leads(machine: "LeadMachine", candidates: list[dict]) -> list[dict]:
    machine.log("Stage 2/5: Deduplicate and filter candidates")
    filtered: list[dict] = []
    seen_businesses: set[str] = set()
    chains_skipped = 0
    bad_fit_skipped = 0
    low_rating_skipped = 0
    closed_skipped = 0
    duplicates_skipped = 0

    for candidate in candidates:
        machine._check_stop()
        name = candidate.get("Business Name", "")
        address = candidate.get("Address", "")
        business_status = candidate.get("Business Status", "")
        rating = candidate.get("Rating") or 0
        reviews = candidate.get("Reviews") or 0
        seed_source = str(candidate.get("Seed Source", ""))

        if machine.is_chain(name) or machine.is_large_org(name):
            chains_skipped += 1
            continue
        bad_fit_reason = machine.bad_fit_reason(name, str(candidate.get("Business Type", "")))
        if bad_fit_reason:
            bad_fit_skipped += 1
            continue
        if business_status == "CLOSED_PERMANENTLY":
            closed_skipped += 1
            continue
        has_google_quality = isinstance(rating, (int, float)) and isinstance(reviews, (int, float)) and (rating or reviews)
        if has_google_quality and (rating < machine.config.min_rating or reviews < machine.config.min_reviews):
            low_rating_skipped += 1
            continue
        if not has_google_quality and seed_source == "Google Places":
            low_rating_skipped += 1
            continue

        dedupe_key = f"{machine.normalize_business_name(name)}|{address.lower().strip()}"
        if dedupe_key in seen_businesses:
            duplicates_skipped += 1
            continue
        seen_businesses.add(dedupe_key)
        filtered.append(candidate)

    address_phone_deduped: list[dict] = []
    address_phone_map: dict[str, dict] = {}
    address_phone_dupes = 0
    for lead in filtered:
        addr = lead.get("Address", "").lower().strip()
        phone = str(lead.get("Phone", "")).strip()
        if addr and phone:
            key = f"{addr}|{phone}"
            if key in address_phone_map:
                address_phone_dupes += 1
                existing = address_phone_map[key]
                if machine.candidate_priority_score(lead) > machine.candidate_priority_score(existing):
                    address_phone_deduped.remove(existing)
                    address_phone_map[key] = lead
                else:
                    continue
            else:
                address_phone_map[key] = lead
        address_phone_deduped.append(lead)
    duplicates_skipped += address_phone_dupes
    filtered = machine.sort_leads_by_priority(address_phone_deduped)

    machine.log(
        f"Filter stage complete. Kept: {len(filtered)} | Chains skipped: {chains_skipped} | "
        f"Bad-fit skipped: {bad_fit_skipped} | Low-rated skipped: {low_rating_skipped} | "
        f"Closed skipped: {closed_skipped} | Duplicates skipped: {duplicates_skipped}"
        + (f" (including {address_phone_dupes} address+phone dupes)" if address_phone_dupes else "")
    )
    machine.record_stage_report(
        "filter",
        "Deduplicate and filter candidates",
        kept=len(filtered),
        chains_skipped=chains_skipped,
        bad_fit_skipped=bad_fit_skipped,
        low_rating_skipped=low_rating_skipped,
        closed_skipped=closed_skipped,
        duplicates_skipped=duplicates_skipped,
        address_phone_dupes=address_phone_dupes,
    )
    return filtered
