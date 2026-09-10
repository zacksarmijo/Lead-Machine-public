"""Prompt-safe section grammar loader for enhanced website generation."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_SECTION_GRAMMAR_DIR = (
    Path(__file__).resolve().parent / "inspiration" / "section_grammar"
)

_KEY_RE = re.compile(r"[^a-z0-9_-]+")
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)


@dataclass
class SectionMove:
    key: str
    section_type: str
    best_for: list[str] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)
    works_with_assets: list[str] = field(default_factory=list)
    content_slots: list[str] = field(default_factory=list)
    layout_notes: list[str] = field(default_factory=list)
    conversion_notes: list[str] = field(default_factory=list)
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


def _category_terms(*values: str) -> set[str]:
    terms: set[str] = set()
    for value in values:
        lowered = str(value or "").lower()
        if lowered:
            terms.add(lowered)
        for token in re.split(r"[^a-z0-9]+", lowered):
            if len(token) >= 3:
                terms.add(token)
    return terms


class SectionGrammarLibrary:
    def __init__(
        self,
        base_dir: Path | str = DEFAULT_SECTION_GRAMMAR_DIR,
    ) -> None:
        self.base_dir = Path(base_dir)
        self._cache: dict[str, list[SectionMove]] = {}

    def list_section_types(self) -> list[str]:
        if not self.base_dir.exists():
            return []
        return sorted(
            path.stem
            for path in self.base_dir.glob("*.json")
            if path.is_file() and _safe_key(path.stem) == path.stem
        )

    def load_section_type(self, section_type: str) -> list[SectionMove]:
        safe_type = _safe_key(section_type)
        if not safe_type:
            return []
        if safe_type in self._cache:
            return list(self._cache[safe_type])

        path = self.base_dir / f"{safe_type}.json"
        if not path.exists():
            self._cache[safe_type] = []
            return []
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._cache[safe_type] = []
            return []
        moves: list[SectionMove] = []
        for item in raw.get("moves") or []:
            if not isinstance(item, dict):
                continue
            key = _safe_key(str(item.get("key") or ""))
            if not key:
                continue
            moves.append(
                SectionMove(
                    key=key,
                    section_type=safe_type,
                    best_for=_safe_list(item.get("best_for"), limit=20, max_chars=80),
                    requires=_safe_list(item.get("requires"), limit=12, max_chars=80),
                    works_with_assets=_safe_list(
                        item.get("works_with_assets"),
                        limit=12,
                        max_chars=80,
                    ),
                    content_slots=_safe_list(
                        item.get("content_slots"),
                        limit=16,
                        max_chars=80,
                    ),
                    layout_notes=_safe_list(item.get("layout_notes"), limit=6),
                    conversion_notes=_safe_list(
                        item.get("conversion_notes"),
                        limit=6,
                    ),
                    avoid=_safe_list(item.get("avoid"), limit=8),
                )
            )
        self._cache[safe_type] = moves
        return list(moves)

    def select_moves(
        self,
        *,
        category: str,
        available_assets: list[str],
        conversion_goal: str,
        preferred_sections: list[str] | None = None,
        blocked_sections: list[str] | None = None,
        limit_per_type: int = 3,
    ) -> list[SectionMove]:
        blocked = {_safe_key(item) for item in (blocked_sections or []) if item}
        available = {_safe_key(item) for item in (available_assets or []) if item}
        if "photo" not in available:
            available.add("no_photo")
        terms = _category_terms(category, conversion_goal)
        all_types = self.list_section_types()

        if preferred_sections:
            requested = [_safe_key(item) for item in preferred_sections if item]
            section_types = [item for item in requested if item in all_types]
        else:
            section_types = all_types

        selected: list[SectionMove] = []
        per_type_limit = max(1, int(limit_per_type or 1))
        for section_type in section_types:
            if section_type in blocked:
                continue
            candidates: list[tuple[int, SectionMove]] = []
            for move in self.load_section_type(section_type):
                if move.section_type in blocked:
                    continue
                required = {_safe_key(item) for item in move.requires if item}
                if required and not required.issubset(available):
                    continue
                works_with = {
                    _safe_key(item) for item in move.works_with_assets if item
                }
                if works_with and available and not works_with.intersection(available):
                    continue
                best_for_terms = _category_terms(*move.best_for)
                score = 0
                if not best_for_terms:
                    score += 1
                if "generic" in best_for_terms:
                    score += 1
                score += 8 * len(best_for_terms.intersection(terms))
                if required:
                    score += 2
                if works_with.intersection(available):
                    score += 2
                if conversion_goal:
                    joined = " ".join(move.conversion_notes).lower()
                    for term in terms:
                        if term in joined:
                            score += 1
                candidates.append((score, move))
            candidates.sort(key=lambda item: (-item[0], item[1].key))
            selected.extend(move for _score, move in candidates[:per_type_limit])
        return selected

    def to_prompt_payload(self, moves: list[SectionMove]) -> list[dict[str, Any]]:
        payload: list[dict[str, Any]] = []
        for move in moves:
            item = {
                "key": _safe_key(move.key),
                "section_type": _safe_key(move.section_type),
                "content_slots": _safe_list(move.content_slots, limit=12, max_chars=80),
                "layout_notes": _safe_list(move.layout_notes, limit=4),
                "conversion_notes": _safe_list(move.conversion_notes, limit=4),
                "avoid": _safe_list(move.avoid, limit=5),
            }
            encoded = json.dumps(item, ensure_ascii=False)
            if _URL_RE.search(encoded):
                encoded = _URL_RE.sub("[source-url-stripped]", encoded)
                item = json.loads(encoded)
            payload.append(item)
        return payload
