"""Извлечение текстового предпросмотра содержимого файлов.

Поддерживает обычные текстовые файлы, .docx (Word) и .xlsx (Excel) без
сторонних библиотек — через распаковку zip и разбор XML.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

TEXT_EXTS = {
    ".txt", ".md", ".csv", ".log", ".json", ".xml", ".yml", ".yaml", ".ini",
    ".cfg", ".py", ".js", ".ts", ".html", ".htm", ".css", ".java", ".c",
    ".cpp", ".cs", ".go", ".rs", ".php", ".rb", ".sql", ".sh", ".ps1", ".bat",
}

MAX_CHARS = 20000


def _read_text_file(path: Path) -> str:
    for enc in ("utf-8", "utf-8-sig", "cp1251", "latin-1"):
        try:
            with open(path, "r", encoding=enc, errors="strict") as f:
                return f.read(MAX_CHARS)
        except (UnicodeDecodeError, OSError):
            continue
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read(MAX_CHARS)
    except OSError:
        return ""


def _read_docx(path: Path) -> str:
    """Извлечь текст из .docx (это zip с word/document.xml)."""
    try:
        with zipfile.ZipFile(path) as z:
            with z.open("word/document.xml") as f:
                xml = f.read().decode("utf-8", errors="replace")
    except (zipfile.BadZipFile, KeyError, OSError):
        return ""
    # абзацы </w:p> -> перевод строки, теги <w:t> содержат текст
    xml = xml.replace("</w:p>", "\n")
    parts = re.findall(r"<w:t[^>]*>(.*?)</w:t>", xml, flags=re.DOTALL)
    text = "".join(parts)
    text = (text.replace("&amp;", "&").replace("&lt;", "<")
                .replace("&gt;", ">").replace("&quot;", '"').replace("&apos;", "'"))
    return text[:MAX_CHARS]


def _read_xlsx(path: Path) -> str:
    """Извлечь строки из .xlsx (общие строки sharedStrings.xml)."""
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            if "xl/sharedStrings.xml" in names:
                with z.open("xl/sharedStrings.xml") as f:
                    xml = f.read().decode("utf-8", errors="replace")
                parts = re.findall(r"<t[^>]*>(.*?)</t>", xml, flags=re.DOTALL)
                return ("\n".join(parts))[:MAX_CHARS]
    except (zipfile.BadZipFile, OSError):
        return ""
    return ""


def get_text_preview(path: str | Path) -> str | None:
    """Вернуть текстовый предпросмотр или None, если он недоступен."""
    p = Path(path)
    if not p.is_file():
        return None
    ext = p.suffix.lower()
    try:
        if ext in TEXT_EXTS:
            return _read_text_file(p)
        if ext == ".docx":
            return _read_docx(p)
        if ext == ".xlsx":
            return _read_xlsx(p)
    except Exception:
        return None
    return None
