from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
INSPIRATION_DIR = ROOT / "inspiration"
URL_RE = re.compile(r"https?://", re.IGNORECASE)
RAW_HTML_KEYS = {"html", "markup", "code", "template", "component_html"}


class DesignDataContractTests(unittest.TestCase):
    def _json_files(self, relative: str) -> list[Path]:
        return sorted((INSPIRATION_DIR / relative).glob("*.json"))

    def _load(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def test_all_new_json_files_load(self) -> None:
        files = []
        for folder in (
            "design_sources",
            "design_sources/imported_patterns",
            "design_kits",
            "section_grammar",
            "review_rules",
        ):
            files.extend(self._json_files(folder))
        self.assertGreaterEqual(len(files), 20)
        for path in files:
            with self.subTest(path=path.name):
                self.assertIsInstance(self._load(path), dict)

    def test_design_kits_have_required_keys(self) -> None:
        required = {
            "version",
            "key",
            "label",
            "best_for",
            "visual_principles",
            "section_rhythm",
            "avoid",
        }
        for path in self._json_files("design_kits"):
            data = self._load(path)
            with self.subTest(path=path.name):
                self.assertTrue(required.issubset(data))
                self.assertEqual(path.stem, data["key"])
                self.assertIsInstance(data["best_for"], list)
                self.assertIsInstance(data["section_rhythm"], list)

    def test_section_grammar_has_required_move_keys(self) -> None:
        move_required = {"key", "content_slots", "layout_notes", "conversion_notes"}
        for path in self._json_files("section_grammar"):
            data = self._load(path)
            with self.subTest(path=path.name):
                self.assertEqual(data.get("version"), 1)
                self.assertEqual(data.get("section_type"), path.stem)
                self.assertIsInstance(data.get("moves"), list)
                self.assertGreater(len(data["moves"]), 0)
                for move in data["moves"]:
                    self.assertTrue(move_required.issubset(move))
                    self.assertIsInstance(move["content_slots"], list)
                    self.assertIsInstance(move["layout_notes"], list)
                    self.assertIsInstance(move["conversion_notes"], list)

    def test_imported_patterns_are_abstract_and_url_free(self) -> None:
        for path in self._json_files("design_sources/imported_patterns"):
            data = self._load(path)
            encoded = json.dumps(data, ensure_ascii=False).lower()
            with self.subTest(path=path.name):
                self.assertNotRegex(encoded, URL_RE)
                self.assertFalse(RAW_HTML_KEYS.intersection(encoded.split('"')))
                for pattern in data.get("patterns") or []:
                    self.assertIn("summary", pattern)
                    self.assertIn("abstract_moves", pattern)
                    self.assertNotIn("repo_url", pattern)

    def test_source_metadata_keeps_urls_out_of_prompt_payloads(self) -> None:
        sources = self._load(INSPIRATION_DIR / "design_sources" / "sources.json")
        encoded_sources = json.dumps(sources, ensure_ascii=False)
        self.assertRegex(encoded_sources, URL_RE)
        for source in sources.get("sources") or []:
            self.assertFalse(source.get("prompt_url_allowed"))
            self.assertFalse(source.get("direct_code_import_allowed"))


if __name__ == "__main__":
    unittest.main()
