"""Inspiration library loader — Phase 2 of website generator pipeline.

Loads curated design patterns (palettes, layouts, tone, must-include and
avoid lists) and maps a freeform business type string to a canonical
category profile the AI generator can build against.

Design rules:
- Reference URLs are listed in categories.json for human review. They are
  NEVER included in the payload returned to the AI generator, so nothing
  is lifted from third-party sites.
- Missing palette files and missing layout docs degrade gracefully to
  the 'generic' profile or to name-only stubs — the loader never raises
  on legitimate data gaps.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

DEFAULT_INSPIRATION_DIR = Path(__file__).resolve().parent / "inspiration"
FALLBACK_CATEGORY_KEY = "generic"

# Fields stripped from the public AI-facing payload. They exist for human
# curators but must never reach the model.
_HUMAN_ONLY_FIELDS = ("reference_urls",)


@dataclass
class Palette:
    name: str = ""
    primary: str = ""
    accent: str = ""
    bg: str = ""
    surface: str = ""
    text: str = ""
    muted: str = ""
    border: str = ""
    success: str = ""
    warning: str = ""
    font_display: str = ""
    font_body: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LayoutPattern:
    name: str
    body: str = ""
    documented: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "body": self.body, "documented": self.documented}


@dataclass
class InspirationProfile:
    category: str
    matched_from: str = ""
    fallback: bool = False
    palette: Palette = field(default_factory=Palette)
    layouts: list[LayoutPattern] = field(default_factory=list)
    tone: str = ""
    must_include: list[str] = field(default_factory=list)
    avoid: list[str] = field(default_factory=list)
    interaction_kit: list[str] = field(default_factory=list)

    def to_ai_payload(self) -> dict[str, Any]:
        """Payload safe to feed an AI prompt — strips human-only fields."""
        return {
            "category": self.category,
            "matched_from": self.matched_from,
            "fallback": self.fallback,
            "palette": self.palette.to_dict(),
            "layouts": [layout.to_dict() for layout in self.layouts],
            "tone": self.tone,
            "must_include": list(self.must_include),
            "avoid": list(self.avoid),
            "interaction_kit": list(self.interaction_kit),
        }


class InspirationLibrary:
    """Lazy loader for categories.json + palettes + layout markdown."""

    def __init__(self, base_dir: Path | str = DEFAULT_INSPIRATION_DIR) -> None:
        self.base_dir = Path(base_dir)
        self._categories: dict[str, Any] | None = None
        self._palette_cache: dict[str, Palette] = {}
        self._layout_cache: dict[str, LayoutPattern] = {}

    # ── Public API ──────────────────────────────────────────────────

    def list_categories(self) -> list[str]:
        return [
            key for key in self._load_categories()
            if not key.startswith("_")
        ]

    def match_category(self, business_type: str) -> str:
        """Map a freeform business_type string to a canonical category key.

        Matching order:
          1. Exact canonical key hit
          2. Keyword list on each category (longest keyword wins)
          3. FALLBACK_CATEGORY_KEY
        """
        raw = (business_type or "").strip().lower()
        categories = self._load_categories()

        if not raw:
            return FALLBACK_CATEGORY_KEY

        if raw in categories and not raw.startswith("_"):
            return raw

        # Token-based keyword scan. Preserve longest keyword wins to keep
        # 'real estate agent' -> realtor ahead of 'agent' being too generic.
        best_key = ""
        best_score = 0
        for key, profile in categories.items():
            if key.startswith("_"):
                continue
            if not isinstance(profile, dict):
                continue
            keywords = profile.get("keywords") or []
            for kw in keywords:
                kw_lower = str(kw).strip().lower()
                if not kw_lower:
                    continue
                if kw_lower in raw and len(kw_lower) > best_score:
                    best_key = key
                    best_score = len(kw_lower)

        return best_key or FALLBACK_CATEGORY_KEY

    def load(self, category_or_business_type: str) -> InspirationProfile:
        """Resolve + load a full inspiration profile.

        Accepts either a canonical category key or a freeform business
        type string. Always returns a profile — falls back to generic
        if the resolved category has missing data.
        """
        input_str = (category_or_business_type or "").strip()
        resolved = self.match_category(input_str)
        categories = self._load_categories()

        profile_data = categories.get(resolved)
        fallback_used = False
        if not isinstance(profile_data, dict):
            resolved = FALLBACK_CATEGORY_KEY
            profile_data = categories.get(FALLBACK_CATEGORY_KEY, {})
            fallback_used = True

        palette_name = str(profile_data.get("palette") or resolved or FALLBACK_CATEGORY_KEY)
        palette = self._load_palette(palette_name)

        layout_names = list(profile_data.get("recommended_layouts") or [])
        layouts = [self._load_layout(name) for name in layout_names]

        return InspirationProfile(
            category=resolved,
            matched_from=input_str,
            fallback=fallback_used or resolved == FALLBACK_CATEGORY_KEY,
            palette=palette,
            layouts=layouts,
            tone=str(profile_data.get("tone") or ""),
            must_include=[str(x) for x in (profile_data.get("must_include") or [])],
            avoid=[str(x) for x in (profile_data.get("avoid") or [])],
            interaction_kit=[str(x) for x in (profile_data.get("interaction_kit") or [])],
        )

    # ── Internals ───────────────────────────────────────────────────

    def _load_categories(self) -> dict[str, Any]:
        if self._categories is not None:
            return self._categories
        path = self.base_dir / "categories.json"
        if not path.exists():
            self._categories = {FALLBACK_CATEGORY_KEY: {}}
            return self._categories
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            self._categories = {FALLBACK_CATEGORY_KEY: {}}
            return self._categories
        if not isinstance(data, dict):
            self._categories = {FALLBACK_CATEGORY_KEY: {}}
            return self._categories
        self._categories = data
        return data

    def _load_palette(self, name: str) -> Palette:
        safe = _sanitize_filename(name) or FALLBACK_CATEGORY_KEY
        if safe in self._palette_cache:
            return self._palette_cache[safe]

        path = self.base_dir / "palettes" / f"{safe}.json"
        if not path.exists():
            # Fall back to generic palette if specific one missing
            if safe != FALLBACK_CATEGORY_KEY:
                fallback = self._load_palette(FALLBACK_CATEGORY_KEY)
                self._palette_cache[safe] = fallback
                return fallback
            palette = Palette(name=FALLBACK_CATEGORY_KEY)
            self._palette_cache[safe] = palette
            return palette

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            palette = Palette(name=safe)
            self._palette_cache[safe] = palette
            return palette

        palette = Palette(
            name=str(raw.get("name") or safe),
            primary=str(raw.get("primary") or ""),
            accent=str(raw.get("accent") or ""),
            bg=str(raw.get("bg") or ""),
            surface=str(raw.get("surface") or ""),
            text=str(raw.get("text") or ""),
            muted=str(raw.get("muted") or ""),
            border=str(raw.get("border") or ""),
            success=str(raw.get("success") or ""),
            warning=str(raw.get("warning") or ""),
            font_display=str(raw.get("font_display") or ""),
            font_body=str(raw.get("font_body") or ""),
            notes=str(raw.get("notes") or ""),
        )
        self._palette_cache[safe] = palette
        return palette

    def _load_layout(self, name: str) -> LayoutPattern:
        safe = _sanitize_filename(name)
        if not safe:
            return LayoutPattern(name=name or "", body="", documented=False)
        if safe in self._layout_cache:
            return self._layout_cache[safe]

        path = self.base_dir / "layouts" / f"{safe}.md"
        if not path.exists():
            pattern = LayoutPattern(name=safe, body="", documented=False)
            self._layout_cache[safe] = pattern
            return pattern

        try:
            body = path.read_text(encoding="utf-8").strip()
        except OSError:
            body = ""
        pattern = LayoutPattern(name=safe, body=body, documented=bool(body))
        self._layout_cache[safe] = pattern
        return pattern


def _sanitize_filename(name: str) -> str:
    """Return a path-safe filename stem for palettes/layouts lookup."""
    cleaned = re.sub(r"[^A-Za-z0-9_\-]+", "_", (name or "").strip().lower())
    return cleaned.strip("_")


# Module-level convenience singleton (cheap to keep in memory).
_default_library: InspirationLibrary | None = None


def get_default_library() -> InspirationLibrary:
    global _default_library
    if _default_library is None:
        _default_library = InspirationLibrary()
    return _default_library


def load_profile(business_type: str) -> InspirationProfile:
    """Shortcut for callers that don't need a library instance."""
    return get_default_library().load(business_type)


# ── Validation ───────────────────────────────────────────────────────

def validate_library(library: InspirationLibrary | None = None) -> dict[str, list[str]]:
    """Report integrity issues for self-review and CI.

    Returns a dict with these keys (all lists of human-readable strings):
      - missing_palettes: categories pointing to palette files not on disk
      - missing_layouts:  categories referencing layout files not on disk
      - orphan_palettes:  palette files on disk but unused by any category
      - orphan_layouts:   layout files on disk but unused by any category
      - empty_keywords:   non-generic categories with no keywords (never
                          fuzzy-matched)
      - fallback_broken:  generic category or palette missing/unloadable
      - invalid_hex:      palette color values that are not valid hex/rgb
    """
    lib = library or get_default_library()
    categories = lib._load_categories()

    issues: dict[str, list[str]] = {
        "missing_palettes": [],
        "missing_layouts": [],
        "orphan_palettes": [],
        "orphan_layouts": [],
        "empty_keywords": [],
        "fallback_broken": [],
        "invalid_hex": [],
    }

    used_palettes: set[str] = set()
    used_layouts: set[str] = set()

    for key, raw in categories.items():
        if key.startswith("_") or not isinstance(raw, dict):
            continue
        palette_name = _sanitize_filename(str(raw.get("palette") or key))
        if palette_name:
            used_palettes.add(palette_name)
            palette_path = lib.base_dir / "palettes" / f"{palette_name}.json"
            if not palette_path.exists():
                issues["missing_palettes"].append(f"{key} -> {palette_name}")
        layouts_ref = raw.get("recommended_layouts") or []
        for layout_name in layouts_ref:
            safe = _sanitize_filename(str(layout_name))
            if not safe:
                continue
            used_layouts.add(safe)
            layout_path = lib.base_dir / "layouts" / f"{safe}.md"
            if not layout_path.exists():
                issues["missing_layouts"].append(f"{key} -> {safe}")
        if key != FALLBACK_CATEGORY_KEY and not (raw.get("keywords") or []):
            issues["empty_keywords"].append(key)

    palette_dir = lib.base_dir / "palettes"
    if palette_dir.exists():
        for p in palette_dir.glob("*.json"):
            if p.stem not in used_palettes:
                issues["orphan_palettes"].append(p.stem)
            # Hex validation (accept #abc, #abcdef, rgb(), rgba()).
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if isinstance(raw, dict):
                for field_name in (
                    "primary", "accent", "bg", "surface", "text",
                    "muted", "border", "success", "warning",
                ):
                    value = str(raw.get(field_name) or "").strip()
                    if value and not _looks_like_color(value):
                        issues["invalid_hex"].append(f"{p.stem}.{field_name}={value}")

    layout_dir = lib.base_dir / "layouts"
    if layout_dir.exists():
        for p in layout_dir.glob("*.md"):
            if p.stem not in used_layouts:
                issues["orphan_layouts"].append(p.stem)

    # Fallback sanity
    if FALLBACK_CATEGORY_KEY not in categories:
        issues["fallback_broken"].append(f"missing category '{FALLBACK_CATEGORY_KEY}'")
    else:
        fallback_palette = lib.base_dir / "palettes" / f"{FALLBACK_CATEGORY_KEY}.json"
        if not fallback_palette.exists():
            issues["fallback_broken"].append(
                f"missing fallback palette '{FALLBACK_CATEGORY_KEY}.json'"
            )

    return issues


_HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
_RGB_RE = re.compile(r"^rgba?\s*\(.+\)$", re.IGNORECASE)


def _looks_like_color(value: str) -> bool:
    v = value.strip()
    if not v:
        return False
    return bool(_HEX_RE.match(v) or _RGB_RE.match(v))
