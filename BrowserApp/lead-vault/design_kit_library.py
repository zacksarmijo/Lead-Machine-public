"""Design kit selection for enhanced website generation."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from inspiration_library import InspirationProfile
from section_grammar_library import SectionGrammarLibrary


DEFAULT_DESIGN_KIT_DIR = Path(__file__).resolve().parent / "inspiration" / "design_kits"

_KEY_RE = re.compile(r"[^a-z0-9_-]+")
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)


@dataclass
class DesignKit:
    key: str
    label: str
    best_for: list[str] = field(default_factory=list)
    visual_principles: list[str] = field(default_factory=list)
    typography: dict[str, Any] = field(default_factory=dict)
    spacing: dict[str, Any] = field(default_factory=dict)
    imagery: dict[str, Any] = field(default_factory=dict)
    cta_rules: list[str] = field(default_factory=list)
    section_rhythm: list[str] = field(default_factory=list)
    avoid: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _safe_key(value: str) -> str:
    return _KEY_RE.sub("-", str(value or "").strip().lower()).strip("-_")


def _safe_text(value: Any, max_chars: int = 220) -> str:
    text = _URL_RE.sub("[source-url-stripped]", str(value or "").strip())
    text = re.sub(r"\s+", " ", text)
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."


def _safe_list(value: Any, *, limit: int = 12, max_chars: int = 220) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _safe_text(item, max_chars=max_chars)
        if not text:
            continue
        norm = text.lower()
        if norm in seen:
            continue
        seen.add(norm)
        out.append(text)
        if len(out) >= limit:
            break
    return out


def _safe_dict(value: Any, *, max_items: int = 8, max_chars: int = 180) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, Any] = {}
    for key, item in list(value.items())[:max_items]:
        safe_key = _safe_key(str(key or ""))
        if not safe_key:
            continue
        if isinstance(item, list):
            out[safe_key] = _safe_list(item, limit=8, max_chars=max_chars)
        elif isinstance(item, dict):
            out[safe_key] = _safe_dict(item, max_items=6, max_chars=max_chars)
        else:
            out[safe_key] = _safe_text(item, max_chars=max_chars)
    return out


def _terms(*values: str) -> set[str]:
    terms: set[str] = set()
    for value in values:
        lowered = str(value or "").lower()
        if lowered:
            terms.add(lowered)
        for token in re.split(r"[^a-z0-9]+", lowered):
            if len(token) >= 3:
                terms.add(token)
    return terms


class DesignKitLibrary:
    def __init__(
        self,
        base_dir: Path | str = DEFAULT_DESIGN_KIT_DIR,
        section_grammar: SectionGrammarLibrary | None = None,
    ) -> None:
        self.base_dir = Path(base_dir)
        self.section_grammar = section_grammar or SectionGrammarLibrary()
        self._cache: dict[str, DesignKit] = {}

    def list_kits(self) -> list[str]:
        if not self.base_dir.exists():
            return []
        return sorted(
            path.stem
            for path in self.base_dir.glob("*.json")
            if path.is_file() and _safe_key(path.stem) == path.stem
        )

    def load(self, key: str) -> DesignKit:
        safe_key = _safe_key(key)
        if safe_key in self._cache:
            return self._cache[safe_key]
        path = self.base_dir / f"{safe_key}.json"
        if not safe_key or not path.exists():
            return DesignKit(key=safe_key or "unknown", label=safe_key or "Unknown")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return DesignKit(key=safe_key, label=safe_key.replace("-", " ").title())
        kit = DesignKit(
            key=_safe_key(str(raw.get("key") or safe_key)),
            label=_safe_text(raw.get("label") or safe_key.replace("-", " ").title(), 80),
            best_for=_safe_list(raw.get("best_for"), limit=24, max_chars=80),
            visual_principles=_safe_list(raw.get("visual_principles"), limit=8),
            typography=_safe_dict(raw.get("typography")),
            spacing=_safe_dict(raw.get("spacing")),
            imagery=_safe_dict(raw.get("imagery")),
            cta_rules=_safe_list(raw.get("cta_rules"), limit=8),
            section_rhythm=_safe_list(raw.get("section_rhythm"), limit=12, max_chars=80),
            avoid=_safe_list(raw.get("avoid"), limit=10),
        )
        self._cache[safe_key] = kit
        return kit

    def select_for(
        self,
        *,
        category: str,
        business_type: str = "",
        experience_archetype: str = "",
        requested_key: str = "auto",
        inspiration: InspirationProfile | None = None,
    ) -> DesignKit:
        requested = _safe_key(requested_key)
        available = self.list_kits()
        if requested and requested != "auto" and requested in available:
            return self.load(requested)

        if inspiration is not None:
            category = category or inspiration.category
            business_type = business_type or inspiration.matched_from

        query_terms = _terms(category, business_type, experience_archetype)
        if {"restaurant", "bakery", "cafe", "hospitality"}.intersection(query_terms):
            preferred_order = ["restaurant-hospitality"]
        elif {"dentist", "chiropractor", "medspa", "healthcare"}.intersection(query_terms):
            preferred_order = ["healthcare-trust"]
        elif {"law", "lawyer", "firm", "realtor", "real", "estate", "consultant", "accountant"}.intersection(query_terms):
            preferred_order = ["professional-services", "premium-local"]
        elif {"landscaper", "salon", "barber", "fitness", "yoga", "gallery"}.intersection(query_terms):
            preferred_order = ["gallery-led"]
        elif {"plumber", "roofer", "hvac", "electrician", "contractor", "repair"}.intersection(query_terms):
            preferred_order = ["local-service"]
        else:
            preferred_order = ["premium-local", "local-service"]

        scored: list[tuple[int, str]] = []
        for key in available:
            kit = self.load(key)
            kit_terms = _terms(*kit.best_for)
            score = 0
            if key in preferred_order:
                score += 50 - preferred_order.index(key)
            score += 10 * len(kit_terms.intersection(query_terms))
            if "generic" in kit_terms:
                score += 1
            scored.append((score, key))
        if scored:
            scored.sort(key=lambda item: (-item[0], item[1]))
            return self.load(scored[0][1])
        return DesignKit(key="local-service", label="Local Service")

    def to_prompt_payload(
        self,
        kit: DesignKit,
        selected_moves: list[dict[str, Any]],
    ) -> dict[str, Any]:
        payload = {
            "kit_key": _safe_key(kit.key),
            "label": _safe_text(kit.label, 80),
            "best_for": _safe_list(kit.best_for, limit=12, max_chars=80),
            "visual_principles": _safe_list(kit.visual_principles, limit=6),
            "typography": _safe_dict(kit.typography),
            "spacing": _safe_dict(kit.spacing),
            "imagery": _safe_dict(kit.imagery),
            "cta_rules": _safe_list(kit.cta_rules, limit=6),
            "section_rhythm": _safe_list(kit.section_rhythm, limit=10, max_chars=80),
            "avoid": _safe_list(kit.avoid, limit=8),
            "selected_section_grammar": selected_moves[:24],
        }
        encoded = json.dumps(payload, ensure_ascii=False)
        if _URL_RE.search(encoded):
            encoded = _URL_RE.sub("[source-url-stripped]", encoded)
            payload = json.loads(encoded)
        return payload
