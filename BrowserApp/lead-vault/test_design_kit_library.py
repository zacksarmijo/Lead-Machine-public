from __future__ import annotations

import json
import re
import unittest

from design_kit_library import DesignKitLibrary
from section_grammar_library import SectionGrammarLibrary


class DesignKitLibraryTests(unittest.TestCase):
    def test_lists_and_loads_kits(self) -> None:
        lib = DesignKitLibrary()
        keys = lib.list_kits()
        self.assertIn("local-service", keys)
        self.assertIn("premium-local", keys)
        kit = lib.load("local-service")
        self.assertEqual(kit.key, "local-service")
        self.assertTrue(kit.visual_principles)

    def test_selects_expected_kits(self) -> None:
        lib = DesignKitLibrary()
        self.assertEqual(
            lib.select_for(category="plumber", business_type="Plumber").key,
            "local-service",
        )
        self.assertEqual(
            lib.select_for(category="landscaper", business_type="Landscape design").key,
            "gallery-led",
        )
        self.assertEqual(
            lib.select_for(category="restaurant", business_type="Cafe bakery").key,
            "restaurant-hospitality",
        )
        self.assertEqual(
            lib.select_for(category="dentist", business_type="Dental clinic").key,
            "healthcare-trust",
        )

    def test_honors_explicit_requested_key_and_falls_back(self) -> None:
        lib = DesignKitLibrary()
        explicit = lib.select_for(
            category="plumber",
            business_type="Plumber",
            requested_key="premium-local",
        )
        self.assertEqual(explicit.key, "premium-local")
        fallback = lib.select_for(
            category="unknown",
            business_type="",
            requested_key="not-a-kit",
        )
        self.assertIn(fallback.key, {"premium-local", "local-service"})

    def test_prompt_payload_is_compact_and_url_free(self) -> None:
        grammar = SectionGrammarLibrary()
        moves = grammar.select_moves(
            category="plumber",
            available_assets=["phone", "services"],
            conversion_goal="call for quote",
            preferred_sections=["hero", "conversion"],
        )
        move_payload = grammar.to_prompt_payload(moves)
        lib = DesignKitLibrary(section_grammar=grammar)
        kit = lib.select_for(category="plumber", business_type="Plumber")
        payload = lib.to_prompt_payload(kit, move_payload)
        encoded = json.dumps(payload, ensure_ascii=False)
        self.assertEqual(payload["kit_key"], "local-service")
        self.assertIn("selected_section_grammar", payload)
        self.assertLess(len(encoded), 20000)
        self.assertNotRegex(encoded, re.compile(r"https?://", re.IGNORECASE))


if __name__ == "__main__":
    unittest.main()
