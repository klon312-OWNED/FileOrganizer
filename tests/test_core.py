"""Тесты ядра: настройки, раскладки, правила категорий, индекс."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class TestCategoryRules(unittest.TestCase):
    def test_parse_and_apply_rules(self):
        from organizer.config import Settings

        text = ".torrent → Другое\n.pdf=Документы\n# comment\n"
        rules = Settings.parse_category_rules_text(text)
        self.assertEqual(rules[".torrent"], "Другое")
        self.assertEqual(rules[".pdf"], "Документы")

        s = Settings()
        s.data["category_rules"] = rules
        self.assertEqual(s.category_for_extension(".torrent"), "Другое")
        self.assertEqual(s.category_for_extension(".pdf"), "Документы")

    def test_rule_overrides_default(self):
        from organizer.config import Settings

        s = Settings()
        s.data["category_rules"] = {".jpg": "Документы"}
        self.assertEqual(s.category_for_extension(".jpg"), "Документы")


class TestSettingsMigration(unittest.TestCase):
    def test_merges_new_defaults(self):
        from organizer.config import Settings, SETTINGS_PATH

        with tempfile.TemporaryDirectory() as tmp:
            settings_file = Path(tmp) / "settings.json"
            old = {"sort_mode": "flat", "watched_folders": ["/tmp"]}
            settings_file.write_text(json.dumps(old), encoding="utf-8")

            import organizer.config as cfg
            orig = cfg.SETTINGS_PATH
            cfg.SETTINGS_PATH = settings_file
            try:
                s = Settings()
                self.assertEqual(s.sort_mode, "flat")
                self.assertIn("category_rules", s.data)
                self.assertIn("onboarding_shown", s.data)
                self.assertEqual(s.data["scheduled_sort_minutes"], 0)
            finally:
                cfg.SETTINGS_PATH = orig

    def test_invalid_scheduled_sort_defaults_zero(self):
        from organizer.config import Settings

        s = Settings()
        s._apply_saved({"scheduled_sort_minutes": "bad"})
        self.assertEqual(s.scheduled_sort_minutes, 0)


class TestLayouts(unittest.TestCase):
    def test_dest_directory_modes(self):
        from organizer.layouts import dest_directory

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dest, year, month = dest_directory(
                archive_root=root,
                sort_mode="type_only",
                category="Картинки",
                extension=".jpg",
                ts=1719590400.0,
            )
            self.assertEqual(dest, root / "Картинки")
            self.assertEqual(year, 2024)

            dest2, _, _ = dest_directory(
                archive_root=root,
                sort_mode="flat",
                category="Документы",
                extension=".pdf",
                ts=1719590400.0,
            )
            self.assertEqual(dest2, root)


class TestHealthCheck(unittest.TestCase):
    def test_broken_and_orphan_detection(self):
        from organizer.database import FileIndex

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            arch = root / "Arch"
            arch.mkdir()
            present = arch / "ok.txt"
            present.write_text("x", encoding="utf-8")
            missing = str(arch / "gone.txt")

            db = FileIndex(root / "test.db")
            db.add_file(
                name="ok.txt", path=str(present), source_path="",
                category="Документы", extension=".txt", size=1,
                added_ts=1.0, year=2025, month=6,
            )
            db.add_file(
                name="gone.txt", path=missing, source_path="",
                category="Документы", extension=".txt", size=1,
                added_ts=1.0, year=2025, month=6,
            )
            orphan = arch / "orphan.txt"
            orphan.write_text("y", encoding="utf-8")

            report = db.health_check(arch)
            self.assertIn(missing, report["broken"])
            self.assertIn(str(orphan.resolve()), report["orphans"])
            db.close()


class TestSorterWithRules(unittest.TestCase):
    def test_sort_uses_custom_category(self):
        from organizer.config import Settings
        from organizer.database import FileIndex
        from organizer.sorter import Sorter

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inbox = root / "inbox"
            inbox.mkdir()
            f = inbox / "data.xyz"
            f.write_text("x", encoding="utf-8")

            settings = Settings()
            settings.data["watched_folders"] = [str(inbox)]
            settings.data["archive_location"] = str(root)
            settings.data["archive_name"] = "Arch"
            settings.data["sort_mode"] = "type_only"
            settings.data["min_age_seconds"] = 0
            settings.data["category_rules"] = {".xyz": "Код"}

            index = FileIndex(root / "test.db")
            sorter = Sorter(settings, index)
            result = sorter.sort_paths([str(f)])
            self.assertEqual(result.moved, 1)
            target = root / "Arch" / "Код" / "data.xyz"
            self.assertTrue(target.exists())
            index.close()

    def test_dry_run_keeps_source_file(self):
        from organizer.config import Settings
        from organizer.database import FileIndex
        from organizer.sorter import Sorter

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inbox = root / "inbox"
            inbox.mkdir()
            src = inbox / "note.txt"
            src.write_text("x", encoding="utf-8")

            settings = Settings()
            settings.data["watched_folders"] = [str(inbox)]
            settings.data["archive_location"] = str(root)
            settings.data["archive_name"] = "Arch"
            settings.data["sort_mode"] = "type_only"
            settings.data["min_age_seconds"] = 0
            settings.data["dry_run"] = True

            index = FileIndex(root / "test.db")
            sorter = Sorter(settings, index)
            result = sorter.sort_paths([str(src)])
            self.assertEqual(result.moved, 1)
            self.assertTrue(src.exists())
            target = root / "Arch" / "Документы" / "note.txt"
            self.assertFalse(target.exists())
            self.assertEqual(index.count(), 0)
            index.close()


if __name__ == "__main__":
    unittest.main()
