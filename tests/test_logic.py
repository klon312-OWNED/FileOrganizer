"""Базовые тесты импортов и ключевой логики."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class TestImports(unittest.TestCase):
    def test_version(self):
        from organizer import __version__
        self.assertRegex(__version__, r"^\d+\.\d+\.\d+$")

    def test_import_modules(self):
        import organizer.config  # noqa: F401
        import organizer.database  # noqa: F401
        import organizer.gui  # noqa: F401
        import organizer.icon  # noqa: F401
        import organizer.layouts  # noqa: F401
        import organizer.notify  # noqa: F401
        import organizer.sorter  # noqa: F401
        import organizer.watcher  # noqa: F401


class TestExcludedPaths(unittest.TestCase):
    def test_exclude_blocks_sort(self):
        from organizer.config import Settings
        from organizer.database import FileIndex
        from organizer.sorter import Sorter

        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "keep.txt"
            src.write_text("x", encoding="utf-8")
            settings = Settings()
            settings.data["watched_folders"] = [tmp]
            settings.data["archive_location"] = tmp
            settings.data["archive_name"] = "Arch"
            settings.add_excluded_path(str(src))
            index = FileIndex(Path(tmp) / "test.db")
            sorter = Sorter(settings, index)
            self.assertIsNone(sorter.sort_file(src))
            self.assertTrue(src.exists())
            index.close()


class TestSortResult(unittest.TestCase):
    def test_duplicate_detection(self):
        from organizer.config import Settings
        from organizer.database import FileIndex
        from organizer.sorter import Sorter

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            arch = root / "Arch"
            arch.mkdir()
            docs = arch / "Документы"
            docs.mkdir(parents=True)
            existing = docs / "report.pdf"
            existing.write_bytes(b"x")
            incoming = root / "inbox"
            incoming.mkdir()
            new_file = incoming / "report.pdf"
            new_file.write_bytes(b"y")

            settings = Settings()
            settings.data["watched_folders"] = [str(incoming)]
            settings.data["archive_location"] = str(root)
            settings.data["archive_name"] = "Arch"
            settings.data["sort_mode"] = "type_only"
            index = FileIndex(root / "test.db")
            sorter = Sorter(settings, index)
            dupes = sorter.find_duplicates([str(new_file)])
            self.assertEqual(len(dupes), 1)
            self.assertEqual(dupes[0]["name"], "report.pdf")
            index.close()

    def test_sort_reports_errors(self):
        from organizer.config import Settings
        from organizer.database import FileIndex
        from organizer.sorter import Sorter, SortResult

        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "bad.txt"
            src.write_text("x", encoding="utf-8")
            settings = Settings()
            settings.data["watched_folders"] = [tmp]
            settings.data["archive_location"] = tmp
            settings.data["archive_name"] = "Arch"
            index = FileIndex(Path(tmp) / "test.db")
            sorter = Sorter(settings, index)
            result = sorter.sort_paths([str(src)])
            self.assertIsInstance(result, SortResult)
            self.assertGreaterEqual(result.moved, 0)
            index.close()


class TestDatabaseStats(unittest.TestCase):
    def test_stats_helpers(self):
        from organizer.database import FileIndex
        import time

        with tempfile.TemporaryDirectory() as tmp:
            db = FileIndex(Path(tmp) / "stats.db")
            db.start_batch(batch="b1", sort_mode="type_date", storage_mode="move", ts=time.time())
            db.finish_batch("b1", 1)
            db.add_file(
                name="a.txt", path=str(Path(tmp) / "a.txt"), source_path="",
                category="Документы", extension=".txt", size=100,
                added_ts=time.time(), year=2025, month=6,
            )
            rows = db.stats_by_category()
            self.assertEqual(len(rows), 1)
            self.assertEqual(db.total_size(), 100)
            self.assertIsNotNone(db.last_sort_time())
            db.close()


class TestIcon(unittest.TestCase):
    def test_icon_generates(self):
        from organizer.icon import icon_path, make_icon_image
        img = make_icon_image(32)
        self.assertEqual(img.size, (32, 32))
        ico = icon_path()
        self.assertTrue(ico.exists())


if __name__ == "__main__":
    unittest.main()
