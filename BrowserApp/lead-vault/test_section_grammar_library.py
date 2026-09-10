from __future__ import annotations

import json
import re
import unittest

from section_grammar_library import SectionGrammarLibrary


class SectionGrammarLibraryTests(unittest.TestCase):
    def test_loads_all_section_types(self) -> None:
        lib = SectionGrammarLibrary()
        section_types = lib.list_section_types()
        self.assertIn("hero", section_types)
        self.assertIn("conversion", section_types)
        for section_type in section_types:
            with self.subTest(section_type=section_type):
                self.assertGreater(len(lib.load_section_type(section_type)), 0)

    def test_selects_local_service_moves(self) -> None:
        lib = SectionGrammarLibrary()
        moves = lib.select_moves(
            category="plumber",
            available_assets=["phone", "services", "no_photo"],
            conversion_goal="call for emergency plumbing help",
            preferred_sections=["hero", "services", "conversion"],
        )
        keys = {move.key for move in moves}
        self.assertIn("local_service_call_first", keys)
        self.assertIn("prioritized_service_list", keys)
        self.assertIn("call_or_quote_final_cta", keys)

    def test_respects_blocked_sections_and_limit(self) -> None:
        lib = SectionGrammarLibrary()
        moves = lib.select_moves(
            category="dentist",
            available_assets=["phone", "services", "photo"],
            conversion_goal="appointment",
            blocked_sections=["trust"],
            limit_per_type=1,
        )
        self.assertNotIn("trust", {move.section_type for move in moves})
        counts = {}
        for move in moves:
            counts[move.section_type] = counts.get(move.section_type, 0) + 1
        self.assertTrue(all(count <= 1 for count in counts.values()))

    def test_prompt_payload_is_compact_and_url_free(self) -> None:
        lib = SectionGrammarLibrary()
        moves = lib.select_moves(
            category="restaurant",
            available_assets=["photo", "services", "phone"],
            conversion_goal="view menu and visit",
            limit_per_type=2,
        )
        payload = lib.to_prompt_payload(moves)
        encoded = json.dumps(payload, ensure_ascii=False)
        self.assertLess(len(encoded), 20000)
        self.assertNotRegex(encoded, re.compile(r"https?://", re.IGNORECASE))
        self.assertTrue(all("section_type" in item for item in payload))


if __name__ == "__main__":
    unittest.main()
