"""Тесты функций v1.9.2: быстрый поиск, крупный текст, умная уборка."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class TestQuickSearchFilter(unittest.TestCase):
    def test_filter_by_substring(self):
        from organizer.gui import filter_entries_by_name

        entries = [
            {"name": "report.pdf", "path": "/a/report.pdf"},
            {"name": "photo.jpg", "path": "/a/photo.jpg"},
            {"name": "Report-final.docx", "path": "/a/Report-final.docx"},
        ]
        out = filter_entries_by_name(entries, "report")
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["name"], "report.pdf")
        self.assertEqual(out[1]["name"], "Report-final.docx")

    def test_empty_query_returns_all(self):
        from organizer.gui import filter_entries_by_name

        entries = [{"name": "a.txt"}, {"name": "b.txt"}]
        self.assertEqual(filter_entries_by_name(entries, ""), entries)
        self.assertEqual(filter_entries_by_name(entries, "   "), entries)


class TestLargeTextSetting(unittest.TestCase):
    def test_loads_and_saves_large_text(self):
        from organizer.config import Settings

        with tempfile.TemporaryDirectory() as tmp:
            settings_file = Path(tmp) / "settings.json"
            settings_file.write_text(json.dumps({"large_text": True}), encoding="utf-8")

            import organizer.config as cfg
            orig = cfg.SETTINGS_PATH
            cfg.SETTINGS_PATH = settings_file
            try:
                s = Settings()
                self.assertTrue(s.large_text)
                s.data["large_text"] = False
                s.save()
                reloaded = json.loads(settings_file.read_text(encoding="utf-8"))
                self.assertFalse(reloaded["large_text"])
            finally:
                cfg.SETTINGS_PATH = orig

    def test_theme_apply_accepts_large_text(self):
        from organizer import theme
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        try:
            st = theme.apply(root, dark=False, large_text=True)
            self.assertIsNotNone(st)
            row_h = st.configure("Treeview")["rowheight"]
            self.assertEqual(row_h, 34)
        finally:
            root.destroy()


class TestSmartCleanupPlan(unittest.TestCase):
    def test_installer_in_downloads_is_candidate(self):
        from organizer.config import Settings
        from organizer.database import FileIndex
        from organizer.sorter import Sorter

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            downloads = root / "Downloads"
            downloads.mkdir()
            installer = downloads / "setup.msi"
            installer.write_bytes(b"x" * 100)

            settings = Settings()
            settings.data["watched_folders"] = [str(downloads)]
            settings.data["min_age_seconds"] = 0
            index = FileIndex(root / "test.db")
            try:
                plan = Sorter(settings, index).build_smart_cleanup_plan()
                names = {p["name"] for p in plan}
                self.assertIn("setup.msi", names)
            finally:
                index.close()


if __name__ == "__main__":
    unittest.main()
