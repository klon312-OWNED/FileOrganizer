"""Тесты ИИ-помощника v1.12.0."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class TestRulesQueryParsing(unittest.TestCase):
    def test_pdf_may_query(self):
        from organizer.ai_assistant import RulesAssistant

        intent = RulesAssistant().parse_user_query("найди все pdf за май")
        self.assertIn("Документы", intent.categories)
        self.assertIn(".pdf", intent.extensions)
        self.assertEqual(intent.month, 5)

    def test_large_video_query(self):
        from organizer.ai_assistant import RulesAssistant

        intent = RulesAssistant().parse_user_query("покажи большие видео")
        self.assertIn("Видео", intent.categories)
        self.assertIsNotNone(intent.min_size)
        self.assertGreater(intent.min_size, 50 * 1024 * 1024)

    def test_suggest_action(self):
        from organizer.ai_assistant import RulesAssistant

        intent = RulesAssistant().parse_user_query("что сортировать сейчас?")
        self.assertEqual(intent.action, "suggest")

    def test_delete_candidates(self):
        from organizer.ai_assistant import RulesAssistant

        intent = RulesAssistant().parse_user_query("какие файлы можно удалить")
        self.assertTrue(intent.delete_candidates)


class TestSearchAndSuggestions(unittest.TestCase):
    def _fake_index(self):
        index = mock.MagicMock()
        index.query.return_value = [
            {
                "path": "/arch/doc.pdf",
                "name": "doc.pdf",
                "category": "Документы",
                "extension": ".pdf",
                "size": 1024,
                "year": 2026,
                "month": 5,
            },
        ]
        index.count.return_value = 1
        index.total_size.return_value = 1024
        index.stats_by_category.return_value = [
            {"category": "Документы", "cnt": 1, "total_size": 1024},
        ]
        return index

    def test_search_archive_pdf(self):
        from organizer.ai_assistant import RulesAssistant, SearchIntent

        intent = SearchIntent(categories=["Документы"], extensions=[".pdf"])
        results = RulesAssistant().search(
            intent, index=self._fake_index(), watched_entries=[],
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "doc.pdf")

    def test_generate_sort_suggestion(self):
        from organizer.ai_assistant import RulesAssistant
        from organizer.config import Settings

        entries = [
            {
                "path": "/dl/a.exe",
                "name": "setup.exe",
                "sortable": True,
                "excluded": False,
                "folder": "/Downloads",
                "size": 60 * 1024 * 1024,
                "mtime": 0,
                "category": "Программы",
            },
        ]
        settings = Settings()
        suggestions = RulesAssistant().generate_suggestions(
            settings, self._fake_index(), entries,
        )
        ids = {s.id for s in suggestions}
        self.assertIn("sort_clutter", ids)


class TestLLMFallback(unittest.TestCase):
    def test_llm_parse_fallback(self):
        from organizer.ai_assistant import LLMAssistant
        from organizer.config import Settings

        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / "settings.json"
            settings_path.write_text(
                json.dumps({"ai_provider": "openai", "ai_api_key": "test-key"}),
                encoding="utf-8",
            )
            with mock.patch("organizer.config.SETTINGS_PATH", settings_path):
                settings = Settings()
            assistant = LLMAssistant(settings)
            with mock.patch.object(assistant, "_openai_chat", side_effect=OSError("net")):
                intent = assistant.parse_user_query("найди pdf за май")
            self.assertIn(".pdf", intent.extensions)

    def test_llm_openai_parse_success(self):
        from organizer.ai_assistant import LLMAssistant
        from organizer.config import Settings

        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / "settings.json"
            settings_path.write_text(
                json.dumps({"ai_provider": "openai", "ai_api_key": "k"}),
                encoding="utf-8",
            )
            with mock.patch("organizer.config.SETTINGS_PATH", settings_path):
                settings = Settings()
            assistant = LLMAssistant(settings)
            payload = json.dumps({
                "action": "search",
                "categories": ["Видео"],
                "extensions": [".mp4"],
                "month": None,
                "year": 2025,
                "min_size": 1000000,
                "max_size": None,
                "name_contains": "",
                "source": "all",
                "delete_candidates": False,
            })
            with mock.patch.object(assistant, "_openai_chat", return_value=payload):
                intent = assistant.parse_user_query("большие mp4 2025")
            self.assertIn("Видео", intent.categories)
            self.assertEqual(intent.year, 2025)

    def test_create_assistant_rules_default(self):
        from organizer.ai_assistant import RulesAssistant, create_assistant
        from organizer.config import Settings

        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / "settings.json"
            settings_path.write_text("{}", encoding="utf-8")
            with mock.patch("organizer.config.SETTINGS_PATH", settings_path):
                assistant = create_assistant(Settings())
            self.assertIsInstance(assistant, RulesAssistant)

    def test_llm_history_passed_to_chat(self):
        from organizer.ai_assistant import LLMAssistant
        from organizer.config import Settings

        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / "settings.json"
            settings_path.write_text(
                json.dumps({"ai_provider": "openai", "ai_api_key": "k"}),
                encoding="utf-8",
            )
            with mock.patch("organizer.config.SETTINGS_PATH", settings_path):
                settings = Settings()
            assistant = LLMAssistant(settings)
            captured: list = []

            def fake_chat(system, user, history=None):
                captured.append(history)
                return json.dumps({
                    "action": "search",
                    "categories": ["Документы"],
                    "extensions": [".pdf"],
                    "month": 5,
                    "year": None,
                    "min_size": None,
                    "max_size": None,
                    "name_contains": "",
                    "source": "all",
                    "delete_candidates": False,
                })

            hist = [{"role": "user", "content": "ищи документы"}, {"role": "assistant", "content": "ок"}]
            with mock.patch.object(assistant, "_chat", side_effect=fake_chat):
                intent = assistant.parse_user_query("те же за май", history=hist)
            self.assertEqual(captured[0], hist)
            self.assertIn(".pdf", intent.extensions)
            self.assertEqual(intent.month, 5)


class TestAISettings(unittest.TestCase):
    def test_ai_settings_loaded(self):
        from organizer.config import Settings

        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / "settings.json"
            settings_path.write_text(
                json.dumps({
                    "ai_provider": "ollama",
                    "ai_ollama_model": "mistral",
                    "ai_api_key": "secret",
                }),
                encoding="utf-8",
            )
            with mock.patch("organizer.config.SETTINGS_PATH", settings_path):
                s = Settings()
            self.assertEqual(s.ai_provider, "ollama")
            self.assertEqual(s.ai_ollama_model, "mistral")
            self.assertEqual(s.ai_api_key, "secret")


class TestRulesFollowUpAndSuggestions(unittest.TestCase):
    def test_follow_up_merges_previous_query(self):
        from organizer.ai_assistant import RulesAssistant

        hist = [{"role": "user", "content": "найди все pdf"}, {"role": "assistant", "content": "ок"}]
        intent = RulesAssistant().parse_user_query("за май", history=hist)
        self.assertIn(".pdf", intent.extensions)
        self.assertEqual(intent.month, 5)

    def test_relative_week_and_installers(self):
        from organizer.ai_assistant import RulesAssistant

        week = RulesAssistant().parse_user_query("файлы за неделю")
        self.assertEqual(week.newer_than_days, 7)
        inst = RulesAssistant().parse_user_query("покажи установщики")
        self.assertTrue(inst.installers_only)
        dups = RulesAssistant().parse_user_query("найди дубликаты")
        self.assertTrue(dups.duplicates_only)

    def test_format_intent_and_savings(self):
        from organizer.ai_assistant import SearchIntent, estimate_savings, format_intent_summary

        intent = SearchIntent(categories=["Видео"], newer_than_days=7, min_size=10)
        summary = format_intent_summary(intent)
        self.assertIn("Видео", summary)
        self.assertIn("7", summary)
        self.assertGreater(estimate_savings([{"size": 1000}], ratio=0.5), 0)

    def test_large_and_screenshot_suggestions(self):
        from organizer.ai_assistant import RulesAssistant
        from organizer.config import Settings

        index = mock.MagicMock()
        index.count.return_value = 0
        index.total_size.return_value = 0
        index.stats_by_category.return_value = []
        entries = [
            {
                "path": "/dl/big.iso",
                "name": "big.iso",
                "sortable": True,
                "excluded": False,
                "folder": "/Downloads",
                "size": 600 * 1024 * 1024,
                "mtime": 1,
                "category": "Другое",
            },
            {
                "path": "/dl/Screenshot 1.png",
                "name": "Screenshot 1.png",
                "sortable": True,
                "excluded": False,
                "folder": "/Desktop",
                "size": 200_000,
                "mtime": 1,
                "category": "Картинки",
            },
        ]
        suggestions = RulesAssistant().generate_suggestions(Settings(), index, entries)
        ids = {s.id for s in suggestions}
        self.assertIn("large_files", ids)
        self.assertIn("screenshots", ids)

    def test_recent_and_folder_clutter_suggestions(self):
        import time

        from organizer.ai_assistant import RulesAssistant
        from organizer.config import Settings

        index = mock.MagicMock()
        index.count.return_value = 0
        index.total_size.return_value = 0
        index.stats_by_category.return_value = []
        now = time.time()
        entries = [
            {
                "path": f"/Downloads/f{i}.bin",
                "name": f"f{i}.bin",
                "sortable": True,
                "excluded": False,
                "folder": "C:/Users/me/Downloads",
                "size": 1024,
                "mtime": now - 3600,
                "category": "Другое",
            }
            for i in range(12)
        ]
        suggestions = RulesAssistant().generate_suggestions(Settings(), index, entries)
        ids = {s.id for s in suggestions}
        self.assertIn("recent_downloads", ids)
        self.assertIn("folder_clutter", ids)


class TestLLMConnection(unittest.TestCase):
    def test_connection_rules_ok(self):
        from organizer.ai_assistant import LLMAssistant
        from organizer.config import Settings

        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / "settings.json"
            settings_path.write_text(
                json.dumps({"ai_provider": "openai", "ai_api_key": "k"}),
                encoding="utf-8",
            )
            with mock.patch("organizer.config.SETTINGS_PATH", settings_path):
                settings = Settings()
            assistant = LLMAssistant(settings)
            with mock.patch.object(assistant, "_chat", return_value="ok"):
                ok, msg = assistant.test_connection()
            self.assertTrue(ok)
            self.assertIn("Связь", msg)

    def test_connection_failure(self):
        from organizer.ai_assistant import LLMAssistant
        from organizer.config import Settings

        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / "settings.json"
            settings_path.write_text(
                json.dumps({"ai_provider": "ollama"}),
                encoding="utf-8",
            )
            with mock.patch("organizer.config.SETTINGS_PATH", settings_path):
                settings = Settings()
            assistant = LLMAssistant(settings)
            with mock.patch.object(assistant, "_chat", side_effect=OSError("down")):
                ok, msg = assistant.test_connection()
            self.assertFalse(ok)
            self.assertIn("down", msg)


if __name__ == "__main__":
    unittest.main()
