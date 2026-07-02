"""Тесты v1.10.0: уборка, сжатие, пагинация, drag-drop."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class TestCleanupSummary(unittest.TestCase):
    def test_summarize_by_reason_with_sizes(self):
        from organizer.cleanup_summary import format_cleanup_dialog, summarize_cleanup_plan

        plan = [
            {"name": "a.exe", "reason": "Установщик", "size": 1000},
            {"name": "b.exe", "reason": "Установщик", "size": 500},
            {"name": "c.tmp", "reason": "Временный", "size": 200},
        ]
        summary = summarize_cleanup_plan(plan)
        self.assertEqual(summary["total"], 3)
        self.assertEqual(summary["total_size"], 1700)
        self.assertEqual(summary["by_reason"]["Установщик"]["count"], 2)
        self.assertEqual(summary["by_reason"]["Установщик"]["size"], 1500)

        text = format_cleanup_dialog(
            summary,
            protected_count=2,
            excluded_paths=[r"C:\safe\work.docx"],
            sample=plan,
        )
        self.assertIn("Установщик: 2 шт.", text)
        self.assertIn("Защищено от уборки: 2", text)
        self.assertIn("work.docx", text)


class TestCompressionSavings(unittest.TestCase):
    def test_zip_space_saved(self):
        from organizer.compression import format_zip_result, source_bytes, zip_item, zip_space_saved

        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "data.txt"
            payload = "x" * 5000
            src.write_text(payload, encoding="utf-8")
            original = source_bytes(src)
            zpath = zip_item(src, level="best")
            saved = zip_space_saved(original, zpath.stat().st_size)
            self.assertGreater(saved, 0)
            report = format_zip_result(
                ok=1, fail=0, total=1,
                original_bytes=original, zip_bytes=zpath.stat().st_size,
            )
            self.assertIn("Сэкономлено", report)

    def test_format_zip_no_savings_for_store(self):
        from organizer.compression import format_zip_result

        report = format_zip_result(
            ok=1, fail=0, total=1, original_bytes=100, zip_bytes=100,
        )
        self.assertIn("100", report)


class TestProtectedCount(unittest.TestCase):
    def test_excluded_paths_counted(self):
        from organizer.config import Settings
        from organizer.database import FileIndex
        from organizer.sorter import Sorter

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inbox = root / "Downloads"
            inbox.mkdir()
            protected = inbox / "keep.txt"
            protected.write_text("x", encoding="utf-8")
            (inbox / "setup.msi").write_bytes(b"y")

            settings = Settings()
            settings.data["watched_folders"] = [str(inbox)]
            settings.data["min_age_seconds"] = 0
            settings.add_excluded_path(str(protected))

            index = FileIndex(root / "test.db")
            try:
                sorter = Sorter(settings, index)
                self.assertGreaterEqual(sorter.count_watched_protected(), 1)
                plan = sorter.build_smart_cleanup_plan()
                names = {p["name"] for p in plan}
                self.assertIn("setup.msi", names)
                self.assertNotIn("keep.txt", names)
            finally:
                index.close()


class TestArchivePagination(unittest.TestCase):
    def test_total_pages(self):
        from organizer.gui import ARCHIVE_PAGE_SIZE

        rows = list(range(ARCHIVE_PAGE_SIZE * 2 + 10))
        pages = (len(rows) + ARCHIVE_PAGE_SIZE - 1) // ARCHIVE_PAGE_SIZE
        self.assertEqual(pages, 3)
        page0 = rows[0:ARCHIVE_PAGE_SIZE]
        page1 = rows[ARCHIVE_PAGE_SIZE:ARCHIVE_PAGE_SIZE * 2]
        self.assertEqual(len(page0), ARCHIVE_PAGE_SIZE)
        self.assertEqual(len(page1), ARCHIVE_PAGE_SIZE)


class TestWinDropPaths(unittest.TestCase):
    def test_bind_returns_false_off_windows(self):
        from organizer.win_drop import bind_file_drop

        if not sys.platform.startswith("win"):
            called = []

            def cb(paths):
                called.append(paths)

            self.assertFalse(bind_file_drop(object(), cb))


class TestDeleteOriginalsSetting(unittest.TestCase):
    def test_setting_roundtrip(self):
        from organizer.config import Settings

        with tempfile.TemporaryDirectory() as tmp:
            settings_file = Path(tmp) / "settings.json"
            settings_file.write_text(
                json.dumps({"delete_originals_after_zip": False}),
                encoding="utf-8",
            )
            import organizer.config as cfg
            orig = cfg.SETTINGS_PATH
            cfg.SETTINGS_PATH = settings_file
            try:
                s = Settings()
                self.assertFalse(s.delete_originals_after_zip)
            finally:
                cfg.SETTINGS_PATH = orig


if __name__ == "__main__":
    unittest.main()
