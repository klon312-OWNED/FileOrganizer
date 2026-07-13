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
        year = RulesAssistant().parse_user_query("файлы за год")
        self.assertEqual(year.newer_than_days, 365)
        inst = RulesAssistant().parse_user_query("покажи установщики")
        self.assertTrue(inst.installers_only)
        dups = RulesAssistant().parse_user_query("найди дубликаты")
        self.assertTrue(dups.duplicates_only)
        empty = RulesAssistant().parse_user_query("пустые файлы")
        self.assertTrue(empty.empty_only)
        self.assertEqual(empty.max_size, 0)

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

    def test_empty_files_suggestion_and_search(self):
        from organizer.ai_assistant import RulesAssistant, SearchIntent
        from organizer.config import Settings

        index = mock.MagicMock()
        index.query.return_value = []
        index.count.return_value = 0
        index.total_size.return_value = 0
        index.stats_by_category.return_value = []
        entries = [
            {
                "path": "/dl/empty.txt",
                "name": "empty.txt",
                "sortable": True,
                "excluded": False,
                "folder": "/Downloads",
                "size": 0,
                "mtime": 1,
                "category": "Документы",
            },
            {
                "path": "/dl/full.txt",
                "name": "full.txt",
                "sortable": True,
                "excluded": False,
                "folder": "/Downloads",
                "size": 100,
                "mtime": 1,
                "category": "Документы",
            },
        ]
        suggestions = RulesAssistant().generate_suggestions(Settings(), index, entries)
        self.assertIn("empty_files", {s.id for s in suggestions})
        intent = SearchIntent(empty_only=True, max_size=0)
        results = RulesAssistant().search(intent, index=index, watched_entries=entries)
        self.assertEqual([r.name for r in results], ["empty.txt"])


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



class TestStatsTempTop(unittest.TestCase):
    def test_temp_top_and_stats(self):
        from organizer.ai_assistant import RulesAssistant, is_temp_name

        self.assertTrue(is_temp_name("video.mp4.crdownload"))
        self.assertTrue(is_temp_name("x.tmp"))
        self.assertFalse(is_temp_name("photo.jpg"))

        temp = RulesAssistant().parse_user_query("временные файлы")
        self.assertTrue(temp.temp_only)
        self.assertEqual(temp.action, "search")

        top = RulesAssistant().parse_user_query("топ 10 самых больших")
        self.assertEqual(top.limit, 10)
        self.assertEqual(top.sort_by, "size")

        newest = RulesAssistant().parse_user_query("самые новые файлы")
        self.assertEqual(newest.sort_by, "date")

        stats = RulesAssistant().parse_user_query("сколько места?")
        self.assertEqual(stats.action, "stats")

        folder = RulesAssistant().parse_user_query("pdf в загрузках")
        self.assertEqual(folder.folder_contains, "download")

    def test_temp_search_and_suggestion(self):
        from organizer.ai_assistant import RulesAssistant, SearchIntent
        from organizer.config import Settings

        index = mock.MagicMock()
        index.query.return_value = []
        index.count.return_value = 0
        index.total_size.return_value = 0
        index.stats_by_category.return_value = []
        entries = [
            {
                "path": "/dl/a.crdownload",
                "name": "a.crdownload",
                "sortable": True,
                "excluded": False,
                "folder": "/Downloads",
                "size": 5000,
                "mtime": 1,
                "category": "Другое",
            },
            {
                "path": "/dl/b.pdf",
                "name": "b.pdf",
                "sortable": True,
                "excluded": False,
                "folder": "/Downloads",
                "size": 100,
                "mtime": 2,
                "category": "Документы",
            },
        ]
        intent = SearchIntent(temp_only=True)
        results = RulesAssistant().search(intent, index=index, watched_entries=entries)
        self.assertEqual([r.name for r in results], ["a.crdownload"])

        sug = RulesAssistant().generate_suggestions(Settings(), index, entries)
        self.assertIn("temp_files", {s.id for s in sug})

    def test_storage_stats_format(self):
        from organizer.ai_assistant import compute_storage_stats, format_storage_stats

        index = mock.MagicMock()
        index.count.return_value = 3
        index.total_size.return_value = 3000
        index.stats_by_category.return_value = [
            {"category": "Видео", "cnt": 2, "total_size": 2000},
        ]
        entries = [
            {
                "path": "/a",
                "name": "a",
                "sortable": True,
                "category": "Документы",
                "size": 100,
            },
        ]
        text = format_storage_stats(compute_storage_stats(index, entries))
        self.assertIn("Архив", text)
        self.assertIn("Видео", text)


class TestAIUiRegression(unittest.TestCase):
    def test_ai_ui_uses_tk_canvas_not_ttk(self):
        """ttk.Canvas не существует — падение при старте вкладки ИИ."""
        text = (ROOT / "organizer" / "ai_ui.py").read_text(encoding="utf-8")
        self.assertNotIn("ttk.Canvas", text)
        self.assertIn("Canvas(", text)


class TestSortPlansV114(unittest.TestCase):
    def test_sort_by_type_and_date(self):
        from organizer.ai_assistant import RulesAssistant
        from organizer.config import Settings

        r = RulesAssistant()
        s = Settings()
        by_type = r.parse_assistant_query("сортируй по типу", s)
        self.assertEqual(by_type.action, "sort")
        self.assertEqual(by_type.sort_plan.sort_mode, "type_only")
        by_date = r.parse_assistant_query("сортируй по дате", s)
        self.assertEqual(by_date.sort_plan.sort_mode, "date_only")
        by_ext = r.parse_assistant_query("сортируй по расширению", s)
        self.assertEqual(by_ext.sort_plan.sort_mode, "extension")

    def test_smart_folders_clarifies_without_library(self):
        from organizer.ai_assistant import RulesAssistant
        from organizer.config import Settings

        r = RulesAssistant()
        reply = r.parse_assistant_query("разложи по моим папкам", Settings())
        self.assertEqual(reply.action, "clarify")
        self.assertIn("библиотек", reply.message.lower())

    def test_ambiguous_layout_clarifies(self):
        from organizer.ai_assistant import RulesAssistant
        from organizer.config import Settings

        reply = RulesAssistant().parse_assistant_query("разложи файлы", Settings())
        self.assertEqual(reply.action, "clarify")

    def test_custom_dest_and_compress(self):
        from organizer.ai_assistant import RulesAssistant, parse_sort_plan
        from organizer.config import Settings

        s = Settings()
        plan = parse_sort_plan("положи docx в Документы/Учёба/Python", s)
        self.assertIsNotNone(plan)
        self.assertEqual(plan.plan_type, "custom_folder")
        self.assertIn("Учёба", plan.custom_dest)

        reply = RulesAssistant().parse_assistant_query("сжми установщики в zip", s)
        self.assertEqual(reply.action, "sort")
        self.assertTrue(reply.sort_plan.enable_compression)
        self.assertTrue(reply.search.installers_only)

    def test_filter_then_sort_pdf_2025(self):
        from organizer.ai_assistant import RulesAssistant
        from organizer.config import Settings

        reply = RulesAssistant().parse_assistant_query(
            "все pdf за 2025 год отсортируй", Settings(),
        )
        self.assertEqual(reply.action, "sort")
        self.assertIn(".pdf", reply.search.extensions)
        self.assertEqual(reply.search.year, 2025)
        self.assertEqual(reply.search.source, "desktop")

    def test_sort_by_courses_means_smart_folders(self):
        from organizer.ai_assistant import parse_sort_plan
        from organizer.config import Settings

        plan = parse_sort_plan("сортируй PDF по курсам", Settings())
        self.assertEqual(plan.plan_type, "smart_folders")

    def test_build_sort_preview_archive(self):
        import tempfile
        from pathlib import Path
        from unittest import mock

        from organizer.ai_assistant import SortPlan, build_sort_preview, collect_sort_paths
        from organizer.config import Settings

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            archive = tmp_path / "Архив"
            archive.mkdir()
            src = tmp_path / "Downloads"
            src.mkdir()
            f = src / "report.pdf"
            f.write_bytes(b"%PDF-1.4")
            settings_path = tmp_path / "settings.json"
            settings_path.write_text("{}", encoding="utf-8")
            with mock.patch("organizer.config.SETTINGS_PATH", settings_path):
                settings = Settings()
            settings.data["archive_location"] = str(tmp_path)
            settings.data["archive_name"] = "Архив"
            settings.data["sort_mode"] = "type_only"

            sorter = mock.MagicMock()
            sorter._is_ready.return_value = True
            sorter._is_inside_destination.return_value = False
            sorter._is_protected.return_value = False
            sorter._file_time.return_value = 1_700_000_000
            sorter._unique_target.side_effect = lambda p: p

            entries = [{
                "path": str(f),
                "name": "report.pdf",
                "sortable": True,
                "category": "Документы",
                "size": 8,
                "mtime": 1_700_000_000,
                "folder": str(src),
            }]
            plan = SortPlan(plan_type="archive", sort_mode="type_only", scope_label="all_watched")
            plan.paths = collect_sort_paths(plan, entries)
            self.assertEqual(plan.paths, [str(f)])
            preview = build_sort_preview(
                plan, settings=settings, sorter=sorter, watched_entries=entries,
            )
            self.assertEqual(len(preview.items), 1)
            self.assertIn("Документы", preview.items[0].dest_hint)

    def test_llm_sort_fields_in_prompt(self):
        text = (ROOT / "organizer" / "ai_assistant.py").read_text(encoding="utf-8")
        self.assertIn("sort_mode", text)
        self.assertIn("target_relpath", text)
        self.assertIn("SortPlan", text)


class TestConversationalAgentV115(unittest.TestCase):
    def _agent(self):
        from organizer.ai_assistant import ConversationalAgent, create_assistant
        from organizer.config import Settings

        index = mock.MagicMock()
        index.query.return_value = []
        index.count.return_value = 0
        index.total_size.return_value = 0
        index.stats_by_category.return_value = []
        entries = [
            {
                "path": "/dl/setup.exe",
                "name": "setup.exe",
                "sortable": True,
                "excluded": False,
                "folder": "C:/Users/me/Downloads",
                "size": 60 * 1024 * 1024,
                "mtime": 1,
                "category": "Программы",
            },
            {
                "path": "/dl/kursovaya.docx",
                "name": "kursovaya.docx",
                "sortable": True,
                "excluded": False,
                "folder": "C:/Users/me/Downloads",
                "size": 1024,
                "mtime": 2,
                "category": "Документы",
            },
        ]
        return ConversationalAgent(
            Settings(), index, entries, assistant=create_assistant(Settings()),
        )

    def test_route_tools_rules_downloads(self):
        from organizer.ai_assistant import route_tools_rules

        calls = route_tools_rules("разбери загрузки")
        self.assertEqual(calls[0].name, "plan_sort")
        self.assertIn("query", calls[0].arguments)

    def test_route_tools_rules_coursework(self):
        from organizer.ai_assistant import route_tools_rules

        calls = route_tools_rules("найди курсовые")
        self.assertEqual(calls[0].name, "search_files")

    def test_route_tools_rules_compress_installers(self):
        from organizer.ai_assistant import route_tools_rules

        calls = route_tools_rules("сожми установщики")
        self.assertEqual(calls[0].name, "plan_sort")
        self.assertTrue(calls[0].arguments.get("compress"))

    def test_route_tools_rules_cleanup(self):
        from organizer.ai_assistant import route_tools_rules

        calls = route_tools_rules("покажи что можно удалить")
        self.assertEqual(calls[0].name, "suggest_cleanup")

    def test_route_tools_casual_status(self):
        from organizer.ai_assistant import route_tools_rules

        calls = route_tools_rules("как тебе")
        self.assertEqual(calls[0].name, "explain_status")

    def test_chat_search_coursework(self):
        agent = self._agent()
        turn = agent.chat("найди курсовые")
        self.assertEqual(turn.action, "search")
        self.assertTrue(turn.search_results or turn.search)

    def test_chat_plan_sort_downloads(self):
        agent = self._agent()
        turn = agent.chat("разбери загрузки")
        self.assertIn(turn.action, ("sort", "clarify"))

    def test_suggested_prompts_defined(self):
        from organizer.ai_assistant import SUGGESTED_PROMPTS

        self.assertIn("Разбери загрузки", SUGGESTED_PROMPTS)
        self.assertIn("Найди PDF за этот год", SUGGESTED_PROMPTS)

    def test_persist_chat_roundtrip(self):
        import tempfile
        from organizer.ai_assistant import load_persisted_chat, save_persisted_chat

        with tempfile.TemporaryDirectory() as tmp:
            hist_path = Path(tmp) / "chat_history.json"
            with mock.patch("organizer.ai_assistant.CHAT_HISTORY_PATH", hist_path):
                msgs = [{"role": "user", "content": "привет"}, {"role": "assistant", "content": "ок"}]
                save_persisted_chat(msgs, enabled=True)
                loaded = load_persisted_chat()
            self.assertEqual(len(loaded), 2)
            self.assertEqual(loaded[0]["content"], "привет")


class TestFreeFormNluV116(unittest.TestCase):
    """20+ casual Russian prompts for rules parser (v1.16)."""

    def _parse(self, text: str, history: list | None = None):
        from organizer.ai_assistant import RulesAssistant

        return RulesAssistant().parse_user_query(text, history=history)

    def test_casual_downloads_sort(self):
        from organizer.ai_assistant import route_tools_rules

        calls = route_tools_rules("ну разбери загрузки плз")
        self.assertEqual(calls[0].name, "plan_sort")

    def test_typo_naydi(self):
        intent = self._parse("найдти все pdf")
        self.assertIn(".pdf", intent.extensions)

    def test_word_alias_spring(self):
        intent = self._parse("найди все ворд за весну")
        self.assertTrue(intent.extensions)
        self.assertIn(".doc", intent.extensions[0])
        self.assertEqual(intent.months, [3, 4, 5])

    def test_compound_find_and_move(self):
        from organizer.ai_assistant import split_compound_request

        parts = split_compound_request("найди все ворд за весну и положи в учёбу")
        self.assertIsNotNone(parts)
        self.assertIn("найди", parts[0].lower())
        self.assertIn("положи", parts[1].lower())

    def test_compound_routing(self):
        from organizer.ai_assistant import route_tools_rules

        calls = route_tools_rules("найди pdf за май и положи в учёбу")
        names = [c.name for c in calls]
        self.assertIn("plan_sort", names)

    def test_negation_exe(self):
        intent = self._parse("не трогай exe остальное сортируй")
        self.assertIn(".exe", intent.exclude_extensions)

    def test_negation_except_folder(self):
        intent = self._parse("кроме папки Project всё сортируй")
        self.assertIn("project", intent.exclude_folder.lower())

    def test_relative_yesterday(self):
        intent = self._parse("файлы за вчера")
        self.assertEqual(intent.newer_than_days, 2)

    def test_relative_last_week(self):
        intent = self._parse("на прошлой неделе")
        self.assertEqual(intent.newer_than_days, 14)
        self.assertEqual(intent.older_than_days, 7)

    def test_relative_recently(self):
        intent = self._parse("недавно скачанные pdf")
        self.assertEqual(intent.newer_than_days, 14)

    def test_slang_cleanup(self):
        from organizer.ai_assistant import route_tools_rules

        calls = route_tools_rules("че можно удалить")
        self.assertEqual(calls[0].name, "suggest_cleanup")

    def test_slang_stats(self):
        from organizer.ai_assistant import route_tools_rules

        calls = route_tools_rules("сколько там места вообще")
        self.assertEqual(calls[0].name, "get_stats")

    def test_skiny_verb(self):
        from organizer.ai_assistant import route_tools_rules

        calls = route_tools_rules("скинь pdf в документы")
        self.assertEqual(calls[0].name, "plan_sort")

    def test_zakin_verb(self):
        from organizer.ai_assistant import route_tools_rules

        calls = route_tools_rules("закинь установщики в архив")
        self.assertEqual(calls[0].name, "plan_sort")

    def test_pronoun_context_history(self):
        from organizer.ai_assistant import resolve_context_references

        hist = [{"role": "user", "content": "найди pdf за май"}]
        resolved = resolve_context_references("их в учёбу", hist, None)
        self.assertIn("pdf", resolved.lower())

    def test_like_last_time_session(self):
        import tempfile
        from organizer.ai_assistant import (
            SESSION_CONTEXT_PATH,
            SessionContext,
            resolve_context_references,
            save_session_context,
        )

        with tempfile.TemporaryDirectory() as tmp:
            ctx_path = Path(tmp) / "agent_session.json"
            with mock.patch("organizer.ai_assistant.SESSION_CONTEXT_PATH", ctx_path):
                save_session_context(SessionContext(
                    last_query="разложи pdf по типу",
                    last_sort_mode="type_only",
                    last_target_relpath="Документы/Учёба",
                ))
                resolved = resolve_context_references("как в прошлый раз", [], None)
                self.assertIn("pdf", resolved.lower())

    def test_understood_summary(self):
        from organizer.ai_assistant import SearchIntent, format_understood_summary

        intent = SearchIntent(
            action="search", extensions=[".pdf"], folder_contains="download",
        )
        summary = format_understood_summary(intent)
        self.assertIn(".pdf", summary)
        self.assertIn("Загрузки", summary)

    def test_confidence_low_gibberish(self):
        intent = self._parse("абракадабра xyz")
        self.assertLess(intent.confidence, 0.55)

    def test_confidence_high_search(self):
        intent = self._parse("найди большие видео за май")
        self.assertGreaterEqual(intent.confidence, 0.55)

    def test_normalize_typos(self):
        from organizer.ai_assistant import normalize_query_text

        self.assertIn("найди", normalize_query_text("найдти pdf"))

    def test_session_persist(self):
        import tempfile
        from organizer.ai_assistant import (
            AgentTurn,
            SearchIntent,
            SortPlan,
            load_session_context,
            save_session_context,
            update_session_from_turn,
        )

        with tempfile.TemporaryDirectory() as tmp:
            ctx_path = Path(tmp) / "agent_session.json"
            with mock.patch("organizer.ai_assistant.SESSION_CONTEXT_PATH", ctx_path):
                turn = AgentTurn(
                    message="",
                    action="sort",
                    search=SearchIntent(extensions=[".pdf"]),
                    sort_plan=SortPlan(sort_mode="type_only", target_relpath="Учёба"),
                )
                update_session_from_turn(turn, "pdf в учёбу")
                loaded = load_session_context()
            self.assertEqual(loaded.last_sort_mode, "type_only")
            self.assertEqual(loaded.last_target_relpath, "Учёба")

    def test_agent_casual_chat(self):
        agent = TestConversationalAgentV115()._agent()
        turn = agent.chat("ну разбери загрузки плз")
        self.assertIn(turn.action, ("sort", "clarify"))
        self.assertTrue(turn.understood or turn.message)

    def test_plain_text_llm_fallback(self):
        from organizer.ai_assistant import _extract_intent_from_plain_text

        data = _extract_intent_from_plain_text(
            "Хорошо, поищу pdf файлы для вас.",
            "найди pdf",
        )
        self.assertIsInstance(data, dict)
        self.assertTrue(data.get("tool_calls"))

    def test_route_clarify_on_unknown(self):
        from organizer.ai_assistant import route_tools_rules

        calls = route_tools_rules("абракадабра xyz qwerty")
        self.assertEqual(calls[0].name, "clarify")


if __name__ == "__main__":
    unittest.main()
