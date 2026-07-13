"""Тесты умной раскладки по пользовательским папкам."""

from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class TestFolderProfiles(unittest.TestCase):
    def test_tokenize_and_scan(self):
        from organizer.folder_profiles import scan_library, tokenize

        self.assertIn("python", tokenize("Курс_Python-2025"))
        self.assertIn("курс", tokenize("Курс_Python-2025"))
        self.assertNotIn("и", tokenize("и код"))

        with tempfile.TemporaryDirectory() as tmp:
            lib = Path(tmp) / "Учёба"
            py = lib / "Курс Python"
            math = lib / "Математика"
            py.mkdir(parents=True)
            math.mkdir(parents=True)
            (py / "lab01.py").write_text("print('hello python')\n", encoding="utf-8")
            (py / "notes.md").write_text("# Python курс\nфункции и циклы\n", encoding="utf-8")
            (math / "hw1.txt").write_text("интеграл и производная\n", encoding="utf-8")

            profiles = scan_library(lib)
            names = {p.name for p in profiles}
            self.assertEqual(names, {"Курс Python", "Математика"})
            py_prof = next(p for p in profiles if p.name == "Курс Python")
            self.assertIn(".py", py_prof.extensions)
            self.assertTrue(py_prof.name_tokens & {"python", "курс"})

    def test_match_prefers_topic_folder(self):
        from organizer.folder_profiles import build_match_plan

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lib = root / "lib"
            src = root / "inbox"
            py = lib / "Курс Python"
            math = lib / "Математика"
            for d in (py, math, src):
                d.mkdir(parents=True)
            (py / "lecture.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
            (math / "calc.txt").write_text("уравнение\n", encoding="utf-8")

            candidate = src / "python_homework_lab2.py"
            candidate.write_text("# homework for python course\n", encoding="utf-8")

            proposals, profiles = build_match_plan(
                [candidate], lib, threshold=0.20, catchall_name="Другое",
            )
            self.assertEqual(len(profiles), 2)
            self.assertEqual(len(proposals), 1)
            prop = proposals[0]
            self.assertEqual(prop.action, "move")
            self.assertIsNotNone(prop.dest_folder)
            self.assertEqual(prop.dest_folder.name, "Курс Python")
            self.assertGreaterEqual(prop.score, 0.20)

    def test_no_match_suggests_create(self):
        from organizer.folder_profiles import build_match_plan, apply_catchall, apply_create_folder

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lib = root / "lib"
            (lib / "Фото").mkdir(parents=True)
            (lib / "Фото" / "a.jpg").write_bytes(b"\xff\xd8\xff")
            src = root / "weird_quantum_thesis_xyz.pdf"
            src.write_bytes(b"%PDF-1.4 fake")

            proposals, _ = build_match_plan(
                [src], lib, threshold=0.85, catchall_name="Другое",
            )
            self.assertEqual(len(proposals), 1)
            prop = proposals[0]
            self.assertEqual(prop.action, "create")
            self.assertTrue(prop.suggested_folder)

            apply_catchall(prop, lib, "Другое")
            self.assertEqual(prop.action, "catchall")
            self.assertEqual(prop.dest_folder, lib / "Другое")

            apply_create_folder(prop, lib, "Квантовая физика")
            self.assertEqual(prop.action, "create")
            self.assertEqual(prop.dest_folder, lib / "Квантовая физика")


class TestSmartFolderSorter(unittest.TestCase):
    def test_apply_plan_moves_with_unique_names(self):
        from organizer.config import Settings
        from organizer.database import FileIndex
        from organizer.folder_profiles import MatchProposal
        from organizer.sorter import Sorter

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lib = root / "Учёба"
            dest_folder = lib / "Курс Python"
            inbox = root / "Downloads"
            dest_folder.mkdir(parents=True)
            inbox.mkdir()
            # уже есть файл с таким именем
            (dest_folder / "report.txt").write_text("old", encoding="utf-8")
            src = inbox / "report.txt"
            src.write_text("new content", encoding="utf-8")
            # файл должен быть «достаточно старым»
            old = time.time() - 60
            import os
            os.utime(src, (old, old))

            db = FileIndex(root / "test.db")
            settings = Settings()
            settings.data["smart_folders_root"] = str(lib)
            settings.data["dry_run"] = False
            settings.data["min_age_seconds"] = 0
            settings.data["watched_folders"] = [str(inbox)]
            settings.data["archive_location"] = str(root)
            settings.data["archive_name"] = "Архив"
            sorter = Sorter(settings, db)

            prop = MatchProposal(
                source=src,
                action="move",
                dest_folder=dest_folder,
                score=0.9,
                profile_name="Курс Python",
                reason="test",
            )
            result = sorter.apply_confirmed_smart_plan([prop])
            self.assertEqual(result.moved, 1)
            self.assertFalse(src.exists())
            self.assertTrue((dest_folder / "report.txt").exists())
            self.assertTrue((dest_folder / "report (1).txt").exists())
            self.assertEqual(
                (dest_folder / "report (1).txt").read_text(encoding="utf-8"),
                "new content",
            )
            try:
                db.close()
            except Exception:
                pass
            del sorter, db


class TestSettingsSmartFolders(unittest.TestCase):
    def test_defaults_and_clamp(self):
        from organizer.config import Settings

        s = Settings()
        self.assertIn("smart_folders_root", s.data)
        s._apply_saved({"smart_folders_threshold": 2.5, "smart_folders_catchall": ""})
        self.assertLessEqual(s.smart_folders_threshold, 0.95)
        self.assertEqual(s.smart_folders_catchall, "Другое")


if __name__ == "__main__":
    unittest.main()
