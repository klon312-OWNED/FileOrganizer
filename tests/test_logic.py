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


class TestIcon(unittest.TestCase):
    def test_icon_generates(self):
        from organizer.icon import icon_path, make_icon_image
        img = make_icon_image(32)
        self.assertEqual(img.size, (32, 32))
        ico = icon_path()
        self.assertTrue(ico.exists())


if __name__ == "__main__":
    unittest.main()
