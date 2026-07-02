"""Тесты v1.8.0: кэш миниатюр, PDF, таблицы Word, оценка ZIP, распаковка."""

from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class TestV180(unittest.TestCase):
    def test_estimate_zip_size(self):
        from organizer.compression import estimate_zip_size

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = root / "a.bin"
            a.write_bytes(b"x" * 1000)
            est = estimate_zip_size([a], level="fast")
            self.assertGreater(est, 0)
            self.assertLess(est, 1000)
            store = estimate_zip_size([a], level="store")
            self.assertEqual(store, 1000)

    def test_unzip_item(self):
        from organizer.compression import unzip_item

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            zpath = root / "pack.zip"
            with zipfile.ZipFile(zpath, "w") as zf:
                zf.writestr("inside.txt", "hello")
            dest = unzip_item(zpath)
            self.assertTrue((dest / "inside.txt").is_file())
            self.assertEqual((dest / "inside.txt").read_text(encoding="utf-8"), "hello")

    def test_unzip_blocks_path_traversal(self):
        from organizer.compression import unzip_item

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            zpath = root / "bad.zip"
            with zipfile.ZipFile(zpath, "w") as zf:
                zf.writestr("../escape.txt", "nope")
            with self.assertRaises(OSError):
                unzip_item(zpath, root / "out")

    def test_thumb_cache(self):
        from organizer import thumbs

        with tempfile.TemporaryDirectory() as tmp:
            img_path = Path(tmp) / "pix.png"
            try:
                from PIL import Image
                Image.new("RGB", (40, 30), color=(255, 0, 0)).save(img_path)
            except ImportError:
                self.skipTest("Pillow not installed")

            old_cache = thumbs.THUMB_CACHE_DIR
            cache_dir = Path(tmp) / "thumbs"
            thumbs.THUMB_CACHE_DIR = cache_dir
            cache_dir.mkdir(parents=True, exist_ok=True)
            try:
                t1 = thumbs.get_thumbnail(img_path, (48, 48))
                self.assertIsNotNone(t1)
                files_after_first = list(cache_dir.glob("*.jpg"))
                self.assertEqual(len(files_after_first), 1)
                t2 = thumbs.get_thumbnail(img_path, (48, 48))
                self.assertIsNotNone(t2)
                self.assertEqual(len(list(cache_dir.glob("*.jpg"))), 1)
            finally:
                thumbs.THUMB_CACHE_DIR = old_cache

    def test_docx_table_preview(self):
        from organizer.preview import parse_docx_rich

        document = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body>"
            "<w:tbl>"
            "<w:tr><w:tc><w:p><w:r><w:t>A1</w:t></w:r></w:p></w:tc>"
            "<w:tc><w:p><w:r><w:t>B1</w:t></w:r></w:p></w:tc></w:tr>"
            "<w:tr><w:tc><w:p><w:r><w:t>A2</w:t></w:r></w:p></w:tc>"
            "<w:tc><w:p><w:r><w:t>B2</w:t></w:r></w:p></w:tc></w:tr>"
            "</w:tbl>"
            "</w:body></w:document>"
        )
        with tempfile.TemporaryDirectory() as tmp:
            docx = Path(tmp) / "table.docx"
            with zipfile.ZipFile(docx, "w") as zf:
                zf.writestr("word/document.xml", document)
            rich = parse_docx_rich(docx)
            self.assertEqual(rich.kind, "table")
            self.assertEqual(rich.table[0][0], "A1")
            self.assertEqual(rich.table[1][1], "B2")

    def test_pdf_preview_optional(self):
        from organizer.preview import parse_pdf_text
        from organizer.thumbs import _HAS_PDF, get_thumbnail

        if not _HAS_PDF:
            rich = parse_pdf_text(Path("missing.pdf"))
            self.assertEqual(rich.kind, "unavailable")
            self.skipTest("PyMuPDF not installed")
        try:
            import fitz
        except ImportError:
            self.skipTest("PyMuPDF not installed")

        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "sample.pdf"
            doc = fitz.open()
            page = doc.new_page()
            page.insert_text((72, 72), "PDF preview test")
            doc.save(pdf_path)
            doc.close()
            rich = parse_pdf_text(pdf_path)
            self.assertIn("PDF preview", rich.plain)
            thumb = get_thumbnail(pdf_path, (120, 120))
            self.assertIsNotNone(thumb)


if __name__ == "__main__":
    unittest.main()
