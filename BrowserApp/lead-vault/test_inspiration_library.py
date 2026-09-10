"""Tests for inspiration_library."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from inspiration_library import (
    FALLBACK_CATEGORY_KEY,
    InspirationLibrary,
    Palette,
    _looks_like_color,
    _sanitize_filename,
    get_default_library,
    load_profile,
    validate_library,
)


class SanitizerTests(unittest.TestCase):
    def test_strips_punctuation_and_lowercases(self) -> None:
        self.assertEqual(_sanitize_filename("Hero Split"), "hero_split")
        self.assertEqual(_sanitize_filename("Real/Estate.Agent"), "real_estate_agent")
        self.assertEqual(_sanitize_filename("  PLUMBER!!  "), "plumber")
        self.assertEqual(_sanitize_filename(""), "")

    def test_blocks_path_traversal(self) -> None:
        # Traversal attempts collapse to safe underscores
        stem = _sanitize_filename("../../etc/passwd")
        self.assertNotIn("..", stem)
        self.assertNotIn("/", stem)
        self.assertNotIn("\\", stem)


class ColorValidationTests(unittest.TestCase):
    def test_valid_hex(self) -> None:
        self.assertTrue(_looks_like_color("#fff"))
        self.assertTrue(_looks_like_color("#FFFFFF"))
        self.assertTrue(_looks_like_color("#1a73e8"))
        self.assertTrue(_looks_like_color("#1a73e8ff"))

    def test_valid_rgb(self) -> None:
        self.assertTrue(_looks_like_color("rgb(255, 0, 0)"))
        self.assertTrue(_looks_like_color("rgba(0,0,0,0.5)"))

    def test_invalid(self) -> None:
        self.assertFalse(_looks_like_color("not a color"))
        self.assertFalse(_looks_like_color("#xyz"))
        self.assertFalse(_looks_like_color(""))


class CategoryMatchTests(unittest.TestCase):
    def test_exact_canonical_key(self) -> None:
        lib = get_default_library()
        self.assertEqual(lib.match_category("realtor"), "realtor")
        self.assertEqual(lib.match_category("PLUMBER"), "plumber")

    def test_keyword_realtor(self) -> None:
        lib = get_default_library()
        self.assertEqual(lib.match_category("Licensed Real Estate Broker"), "realtor")

    def test_keyword_plumber(self) -> None:
        lib = get_default_library()
        self.assertEqual(lib.match_category("24/7 Emergency Drain Cleaning"), "plumber")

    def test_keyword_hvac(self) -> None:
        lib = get_default_library()
        self.assertEqual(lib.match_category("Air Conditioning Repair"), "hvac")

    def test_keyword_dentist(self) -> None:
        lib = get_default_library()
        self.assertEqual(lib.match_category("Family Dental Care"), "dentist")

    def test_unknown_falls_back(self) -> None:
        lib = get_default_library()
        self.assertEqual(lib.match_category("Underwater Basket Weaving"), FALLBACK_CATEGORY_KEY)

    def test_empty_falls_back(self) -> None:
        lib = get_default_library()
        self.assertEqual(lib.match_category(""), FALLBACK_CATEGORY_KEY)
        self.assertEqual(lib.match_category("   "), FALLBACK_CATEGORY_KEY)

    def test_longest_keyword_wins(self) -> None:
        """'real estate' (11 chars) should beat a shorter 2-char accidental hit."""
        lib = get_default_library()
        self.assertEqual(lib.match_category("real estate agent serving Denver"), "realtor")


class ProfileLoadTests(unittest.TestCase):
    def test_loads_realtor_profile(self) -> None:
        profile = load_profile("realtor")
        self.assertEqual(profile.category, "realtor")
        self.assertFalse(profile.fallback)
        self.assertTrue(profile.palette.primary.startswith("#"))
        self.assertGreater(len(profile.layouts), 0)

    def test_fallback_profile_has_palette(self) -> None:
        profile = load_profile("made up business type")
        self.assertEqual(profile.category, FALLBACK_CATEGORY_KEY)
        self.assertTrue(profile.fallback)
        self.assertTrue(profile.palette.primary.startswith("#"))

    def test_ai_payload_strips_reference_urls(self) -> None:
        profile = load_profile("realtor")
        payload = profile.to_ai_payload()
        # reference_urls must NEVER be in the AI-facing payload
        self.assertNotIn("reference_urls", payload)
        # Core fields must still be there
        self.assertIn("palette", payload)
        self.assertIn("layouts", payload)
        self.assertIn("tone", payload)

    def test_layout_body_loaded_for_known_layout(self) -> None:
        profile = load_profile("plumber")
        known = [layout for layout in profile.layouts if layout.name == "hero_split"]
        self.assertTrue(known, "hero_split should be among plumber layouts")
        self.assertTrue(known[0].documented)
        self.assertGreater(len(known[0].body), 0)

    def test_missing_layout_returns_undocumented_stub(self) -> None:
        """Layouts referenced but not on disk should degrade, not crash."""
        profile = load_profile("plumber")
        undoc = [l for l in profile.layouts if not l.documented]
        # Not asserting a specific count (data can change), but if any
        # exist they must have name set and empty body.
        for layout in undoc:
            self.assertTrue(layout.name)
            self.assertEqual(layout.body, "")


class ValidationTests(unittest.TestCase):
    def test_validate_default_library(self) -> None:
        issues = validate_library()
        # Keys must exist
        for key in (
            "missing_palettes", "missing_layouts", "orphan_palettes",
            "orphan_layouts", "empty_keywords", "fallback_broken", "invalid_hex",
        ):
            self.assertIn(key, issues)
        # Fallback must not be broken — that's the safety net
        self.assertEqual(issues["fallback_broken"], [])
        # Generic palette must have valid colors — non-negotiable
        generic_issues = [i for i in issues["invalid_hex"] if i.startswith("generic.")]
        self.assertEqual(generic_issues, [], f"generic palette has invalid colors: {generic_issues}")

    def test_motion_primitives_registry_shape(self) -> None:
        path = Path(__file__).resolve().parent / "inspiration" / "motion_primitives.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["_meta"]["version"], 1)
        primitives = data.get("primitives")
        self.assertIsInstance(primitives, dict)
        for required in (
            "reveal_up",
            "gradient_mesh",
            "parallax_image",
            "sticky_cta",
            "cursor_spotlight",
        ):
            self.assertIn(required, primitives)

        for key, primitive in primitives.items():
            with self.subTest(primitive=key):
                self.assertRegex(key, r"^[a-z][a-z0-9_]*$")
                for field in (
                    "label",
                    "description",
                    "attributes",
                    "allowed_contexts",
                    "avoid_contexts",
                    "accessibility",
                    "performance",
                    "implementation_notes",
                ):
                    self.assertIn(field, primitive)
                self.assertIsInstance(primitive["attributes"], dict)
                self.assertGreater(len(primitive["attributes"]), 0)
                self.assertIsInstance(primitive["allowed_contexts"], list)
                self.assertIsInstance(primitive["avoid_contexts"], list)
                self.assertIsInstance(primitive["implementation_notes"], list)

                accessibility = primitive["accessibility"]
                self.assertIn("requires_reduced_motion_fallback", accessibility)
                self.assertIn("fallback_behavior", accessibility)

                performance = primitive["performance"]
                self.assertIsInstance(performance.get("max_instances"), int)
                self.assertGreaterEqual(performance["max_instances"], 1)
                for bool_field in (
                    "uses_intersection_observer",
                    "uses_canvas",
                    "mobile_enabled",
                ):
                    self.assertIsInstance(performance.get(bool_field), bool)

    def test_experience_archetypes_registry_shape(self) -> None:
        base = Path(__file__).resolve().parent / "inspiration"
        archetypes_path = base / "experience_archetypes.json"
        motion_path = base / "motion_primitives.json"
        categories_path = base / "categories.json"

        data = json.loads(archetypes_path.read_text(encoding="utf-8"))
        motion_data = json.loads(motion_path.read_text(encoding="utf-8"))
        category_data = json.loads(categories_path.read_text(encoding="utf-8"))

        self.assertEqual(data["_meta"]["version"], 1)
        self.assertIn("motion_primitives.json", data["_meta"]["depends_on"])

        primitives = set(motion_data["primitives"].keys())
        category_keys = {key for key in category_data if not key.startswith("_")}
        archetypes = data.get("archetypes")
        self.assertIsInstance(archetypes, dict)
        for required in (
            "premium_editorial",
            "tech_launch",
            "local_service_conversion",
            "gallery_led",
            "luxury_calm",
            "utility_dashboard",
        ):
            self.assertIn(required, archetypes)

        required_fields = (
            "label",
            "description",
            "motion_level",
            "background_system",
            "scroll_system",
            "nav_system",
            "section_rhythm",
            "cta_system",
            "recommended_primitives",
            "avoid_primitives",
            "best_for",
            "avoid_for",
            "performance_budget",
            "prompt_guidance",
        )
        for key, archetype in archetypes.items():
            with self.subTest(archetype=key):
                self.assertRegex(key, r"^[a-z][a-z0-9_]*$")
                for field in required_fields:
                    self.assertIn(field, archetype)

                self.assertIsInstance(archetype["background_system"], dict)
                self.assertIsInstance(archetype["scroll_system"], dict)
                self.assertIsInstance(archetype["nav_system"], dict)
                self.assertIsInstance(archetype["cta_system"], dict)
                self.assertIsInstance(archetype["section_rhythm"], list)
                self.assertGreaterEqual(len(archetype["section_rhythm"]), 4)
                self.assertIsInstance(archetype["prompt_guidance"], list)
                self.assertGreaterEqual(len(archetype["prompt_guidance"]), 2)

                recommended = set(archetype["recommended_primitives"])
                avoided = set(archetype["avoid_primitives"])
                self.assertTrue(recommended.issubset(primitives))
                self.assertTrue(avoided.issubset(primitives))
                self.assertFalse(recommended.intersection(avoided))

                for category_key in archetype["best_for"] + archetype["avoid_for"]:
                    self.assertIn(category_key, category_keys)

                performance = archetype["performance_budget"]
                for int_field in (
                    "max_animated_elements",
                    "max_background_systems",
                    "max_parallax_elements",
                ):
                    self.assertIsInstance(performance.get(int_field), int)
                    self.assertGreaterEqual(performance[int_field], 0)
                for bool_field in (
                    "mobile_parallax_enabled",
                    "allow_pointer_tracking",
                ):
                    self.assertIsInstance(performance.get(bool_field), bool)


class IsolatedLibraryTests(unittest.TestCase):
    def _build_minimal_library(self, td: str) -> Path:
        base = Path(td)
        (base / "palettes").mkdir()
        (base / "layouts").mkdir()
        (base / "categories.json").write_text(
            json.dumps({
                "_meta": {"version": 1},
                "generic": {
                    "palette": "generic",
                    "recommended_layouts": ["hero_split"],
                    "tone": "clean",
                    "keywords": [],
                },
                "widget": {
                    "palette": "generic",
                    "recommended_layouts": ["hero_split"],
                    "tone": "snappy",
                    "keywords": ["widget", "gizmo"],
                },
            }),
            encoding="utf-8",
        )
        (base / "palettes" / "generic.json").write_text(
            json.dumps({
                "name": "generic",
                "primary": "#000000",
                "bg": "#FFFFFF",
                "text": "#111111",
            }),
            encoding="utf-8",
        )
        (base / "layouts" / "hero_split.md").write_text("# Hero Split\n", encoding="utf-8")
        return base

    def test_load_from_custom_dir(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = self._build_minimal_library(td)
            lib = InspirationLibrary(base)
            self.assertEqual(lib.match_category("Widget Maker Co"), "widget")
            profile = lib.load("Gizmo Inc")
            self.assertEqual(profile.category, "widget")
            self.assertEqual(profile.palette.primary, "#000000")

    def test_validation_surfaces_missing_palette(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = self._build_minimal_library(td)
            # Add a category whose palette file doesn't exist
            data = json.loads((base / "categories.json").read_text())
            data["bogus"] = {
                "palette": "no_such_palette",
                "recommended_layouts": ["hero_split"],
                "keywords": ["bogus"],
            }
            (base / "categories.json").write_text(json.dumps(data), encoding="utf-8")
            lib = InspirationLibrary(base)
            issues = validate_library(lib)
            self.assertTrue(
                any("bogus" in i for i in issues["missing_palettes"]),
                f"expected bogus in missing_palettes, got {issues['missing_palettes']}",
            )

    def test_validation_catches_bad_hex(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = self._build_minimal_library(td)
            # Write a bad palette
            (base / "palettes" / "junk.json").write_text(
                json.dumps({"name": "junk", "primary": "not-a-color", "bg": "#fff"}),
                encoding="utf-8",
            )
            lib = InspirationLibrary(base)
            issues = validate_library(lib)
            self.assertTrue(
                any("junk.primary" in i for i in issues["invalid_hex"]),
                f"expected junk.primary in invalid_hex, got {issues['invalid_hex']}",
            )


if __name__ == "__main__":
    unittest.main()
