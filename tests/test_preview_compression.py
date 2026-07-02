"""Тесты предпросмотра и сжатия."""

from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class TestCompression(unittest.TestCase):
    def test_zip_item_file(self):
        from organizer.compression import zip_item, remove_source

        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "note.txt"
            src.write_text("hello zip", encoding="utf-8")
            zpath = zip_item(src, level="fast")
            self.assertTrue(zpath.exists())
            self.assertEqual(zpath.suffix, ".zip")
            with zipfile.ZipFile(zpath) as zf:
                self.assertIn("note.txt", zf.namelist())
            remove_source(src)
            self.assertFalse(src.exists())

    def test_zip_group(self):
        from organizer.compression import zip_group, remove_source

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = root / "a.txt"
            b = root / "b.txt"
            a.write_text("a", encoding="utf-8")
            b.write_text("b", encoding="utf-8")
            zpath = zip_group([a, b], root / "bundle.zip", level="store")
            self.assertTrue(zpath.exists())
            with zipfile.ZipFile(zpath) as zf:
                names = zf.namelist()
                self.assertIn("a.txt", names)
                self.assertIn("b.txt", names)
            remove_source(a)
            remove_source(b)

    def test_sort_with_zip_per_item(self):
        from organizer.config import Settings
        from organizer.database import FileIndex
        from organizer.sorter import Sorter

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inbox = root / "inbox"
            inbox.mkdir()
            f = inbox / "data.txt"
            f.write_text("compress me", encoding="utf-8")

            settings = Settings()
            settings.data["watched_folders"] = [str(inbox)]
            settings.data["archive_location"] = str(root)
            settings.data["archive_name"] = "Arch"
            settings.data["sort_mode"] = "type_only"
            settings.data["min_age_seconds"] = 0
            settings.data["compression_enabled"] = True
            settings.data["compression_mode"] = "zip_per_item"
            settings.data["compression_level"] = "fast"

            index = FileIndex(root / "test.db")
            sorter = Sorter(settings, index)
            result = sorter.sort_paths([str(f)])
            self.assertEqual(result.moved, 1)
            zips = list((root / "Arch" / "Документы").glob("*.zip"))
            self.assertEqual(len(zips), 1)
            self.assertFalse(f.exists())
            index.close()


class TestPreview(unittest.TestCase):
    def _make_docx(self, path: Path, paragraphs: list[tuple[str, bool, bool]]) -> None:
        body_parts = []
        for text, bold, italic in paragraphs:
            rpr = ""
            if bold:
                rpr += "<w:b/>"
            if italic:
                rpr += "<w:i/>"
            rpr_xml = f"<w:rPr>{rpr}</w:rPr>" if rpr else ""
            body_parts.append(
                f'<w:p><w:r>{rpr_xml}<w:t>{text}</w:t></w:r></w:p>'
            )
        document = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:body>{''.join(body_parts)}</w:body></w:document>"
        )
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("word/document.xml", document)

    def test_docx_rich_paragraphs(self):
        from organizer.preview import parse_docx_rich

        with tempfile.TemporaryDirectory() as tmp:
            docx = Path(tmp) / "sample.docx"
            self._make_docx(docx, [
                ("Hello", False, False),
                (" bold", True, False),
                (" world", False, True),
            ])
            rich = parse_docx_rich(docx)
            self.assertEqual(rich.kind, "rich")
            self.assertIn("Hello", rich.plain)
            self.assertTrue(any(s.bold for s in rich.spans))
            self.assertTrue(any(s.italic for s in rich.spans))

    def test_doc_legacy_note(self):
        from organizer.preview import get_rich_preview

        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "old.doc"
            doc.write_bytes(b"legacy")
            rich = get_rich_preview(doc)
            self.assertIsNotNone(rich)
            self.assertEqual(rich.kind, "unavailable")
            self.assertIn(".doc", rich.note)

    def test_code_highlight_ranges(self):
        from organizer.preview import code_highlight_spans

        text = "def foo():\n    return 1  # comment\n"
        ranges = code_highlight_spans(".py", text)
        tags = {tag for _, _, tag in ranges}
        self.assertIn("kw", tags)
        self.assertIn("comment", tags)

    def test_plain_text_preview(self):
        from organizer.preview import get_rich_preview

        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "readme.md"
            p.write_text("# Title\n\nBody", encoding="utf-8")
            rich = get_rich_preview(p)
            self.assertIsNotNone(rich)
            self.assertEqual(rich.kind, "plain")
            self.assertIn("Title", rich.plain)


if __name__ == "__main__":
    unittest.main()
