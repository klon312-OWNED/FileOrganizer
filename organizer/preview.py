"""Извлечение содержимого для предпросмотра: текст, Word, Excel, код."""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

TEXT_EXTS = {
    ".txt", ".md", ".csv", ".log", ".json", ".xml", ".yml", ".yaml", ".ini",
    ".cfg", ".py", ".js", ".ts", ".html", ".htm", ".css", ".java", ".c",
    ".cpp", ".cs", ".go", ".rs", ".php", ".rb", ".sql", ".sh", ".ps1", ".bat",
    ".rtf",
}

CODE_EXTS = {
    ".py", ".js", ".ts", ".html", ".htm", ".css", ".java", ".c", ".cpp", ".cs",
    ".go", ".rs", ".php", ".rb", ".sql", ".sh", ".ps1", ".json", ".xml", ".yml",
    ".yaml",
}

MAX_CHARS = 30000
MAX_TABLE_ROWS = 40
MAX_TABLE_COLS = 12

_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_X_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

try:
    import fitz  # PyMuPDF
    _HAS_PDF = True
except Exception:
    _HAS_PDF = False


@dataclass
class TextSpan:
    text: str
    bold: bool = False
    italic: bool = False


@dataclass
class RichPreview:
    """Структурированный предпросмотр для виджета Tkinter."""

    kind: str  # plain | rich | table | unavailable
    plain: str = ""
    spans: list[TextSpan] = field(default_factory=list)
    table: list[list[str]] = field(default_factory=list)
    note: str = ""


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


def _unescape_xml(text: str) -> str:
    return (
        text.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&apos;", "'")
    )


def _docx_runs_from_paragraph(p_elem) -> list[TextSpan]:
    spans: list[TextSpan] = []
    for run in p_elem.findall(f".{_W_NS}r"):
        bold = run.find(f"{_W_NS}rPr/{_W_NS}b") is not None
        italic = run.find(f"{_W_NS}rPr/{_W_NS}i") is not None
        parts = []
        for t_elem in run.findall(f"{_W_NS}t"):
            if t_elem.text:
                parts.append(t_elem.text)
        text = _unescape_xml("".join(parts))
        if text:
            spans.append(TextSpan(text=text, bold=bold, italic=italic))
    return spans


def _docx_cell_text(tc_elem) -> str:
    parts: list[str] = []
    for p in tc_elem.findall(f".{_W_NS}p"):
        for span in _docx_runs_from_paragraph(p):
            parts.append(span.text)
    return _unescape_xml("".join(parts)).strip()


def _docx_table_rows(tbl_elem) -> list[list[str]]:
    rows: list[list[str]] = []
    for tr in tbl_elem.findall(f"{_W_NS}tr"):
        cells = [_docx_cell_text(tc) for tc in tr.findall(f"{_W_NS}tc")]
        if any(cells):
            rows.append(cells)
    return rows


def _trim_table(table: list[list[str]]) -> list[list[str]]:
    if not table:
        return table
    max_cols = min(max(len(r) for r in table), MAX_TABLE_COLS)
    trimmed: list[list[str]] = []
    for row in table[:MAX_TABLE_ROWS]:
        cells = list(row[:max_cols])
        while len(cells) < max_cols:
            cells.append("")
        trimmed.append(cells)
    return trimmed


def parse_docx_rich(path: Path) -> RichPreview:
    """Разбор .docx: абзацы, таблицы, жирный/курсив из XML."""
    try:
        with zipfile.ZipFile(path) as zf:
            with zf.open("word/document.xml") as f:
                root = ET.fromstring(f.read())
    except (zipfile.BadZipFile, KeyError, OSError, ET.ParseError):
        return RichPreview(kind="unavailable", note="Не удалось прочитать документ Word (.docx).")

    spans: list[TextSpan] = []
    tables: list[list[list[str]]] = []
    body = root.find(f".{_W_NS}body")
    if body is None:
        return RichPreview(kind="unavailable", note="Пустой документ Word.")

    first_para = True
    for child in body:
        tag = child.tag
        if tag == f"{_W_NS}p":
            if not first_para:
                spans.append(TextSpan(text="\n"))
            first_para = False
            spans.extend(_docx_runs_from_paragraph(child))
        elif tag == f"{_W_NS}tbl":
            if not first_para:
                spans.append(TextSpan(text="\n"))
            first_para = False
            table = _trim_table(_docx_table_rows(child))
            if table:
                tables.append(table)

    plain = "".join(s.text for s in spans)
    if tables:
        best = max(tables, key=lambda t: sum(len(r) for r in t))
        note = ""
        if plain.strip():
            note = plain[:500] + ("…" if len(plain) > 500 else "")
        return RichPreview(kind="table", table=best, plain=plain[:MAX_CHARS], note=note)

    if not plain.strip():
        return RichPreview(kind="unavailable", note="Документ Word пуст.")
    return RichPreview(kind="rich", plain=plain[:MAX_CHARS], spans=spans[:500])


def parse_pdf_text(path: Path) -> RichPreview:
    """Текст первой страницы PDF (если установлен PyMuPDF)."""
    if not _HAS_PDF:
        return RichPreview(
            kind="unavailable",
            note="Для текста PDF установите PyMuPDF (pip install PyMuPDF).\n"
                 "Миниатюра первой страницы может отображаться отдельно.",
        )
    try:
        doc = fitz.open(path)
        try:
            if doc.page_count < 1:
                return RichPreview(kind="unavailable", note="PDF без страниц.")
            text = doc.load_page(0).get_text().strip()
        finally:
            doc.close()
    except Exception:
        return RichPreview(kind="unavailable", note="Не удалось прочитать PDF.")
    if not text:
        return RichPreview(
            kind="unavailable",
            note="На первой странице PDF нет извлекаемого текста.\n"
                 "См. миниатюру выше или откройте файл в просмотрщике.",
        )
    return RichPreview(kind="plain", plain=text[:MAX_CHARS])


def _xlsx_col_row(ref: str) -> tuple[int, int]:
    col = 0
    row = 0
    i = 0
    while i < len(ref) and ref[i].isalpha():
        col = col * 26 + (ord(ref[i].upper()) - ord("A") + 1)
        i += 1
    while i < len(ref) and ref[i].isdigit():
        row = row * 10 + int(ref[i])
        i += 1
    return col, row


def _xlsx_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    with zf.open("xl/sharedStrings.xml") as f:
        root = ET.fromstring(f.read())
    strings: list[str] = []
    for si in root.findall(f".{_X_NS}si"):
        parts = []
        for t in si.findall(f".{_X_NS}t"):
            if t.text:
                parts.append(t.text)
        strings.append(_unescape_xml("".join(parts)))
    return strings


def _xlsx_first_sheet_name(zf: zipfile.ZipFile) -> str | None:
    with zf.open("xl/workbook.xml") as f:
        root = ET.fromstring(f.read())
    sheets = root.findall(".//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}sheet")
    if not sheets:
        return None
    rid = sheets[0].attrib.get(
        "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id",
    )
    if not rid:
        return "sheet1.xml"
    with zf.open("xl/_rels/workbook.xml.rels") as f:
        rels = ET.fromstring(f.read())
    for rel in rels:
        if rel.attrib.get("Id") == rid:
            target = rel.attrib.get("Target", "worksheets/sheet1.xml")
            if not target.startswith("xl/"):
                target = f"xl/{target.lstrip('/')}"
            return target
    return "xl/worksheets/sheet1.xml"


def parse_xlsx_table(path: Path) -> RichPreview:
    """Первый лист .xlsx как простая таблица."""
    try:
        with zipfile.ZipFile(path) as zf:
            shared = _xlsx_shared_strings(zf)
            sheet_path = _xlsx_first_sheet_name(zf)
            if not sheet_path or sheet_path not in zf.namelist():
                return RichPreview(kind="unavailable", note="Лист Excel не найден.")
            with zf.open(sheet_path) as f:
                root = ET.fromstring(f.read())
    except (zipfile.BadZipFile, OSError, ET.ParseError):
        return RichPreview(kind="unavailable", note="Не удалось прочитать таблицу Excel (.xlsx).")

    cells: dict[tuple[int, int], str] = {}
    max_col = max_row = 0
    for row_elem in root.findall(f".{_X_NS}sheetData/{_X_NS}row"):
        for c in row_elem.findall(f"{_X_NS}c"):
            ref = c.attrib.get("r", "")
            if not ref:
                continue
            col, row = _xlsx_col_row(ref)
            value = ""
            t = c.attrib.get("t")
            v = c.find(f"{_X_NS}v")
            is_elem = c.find(f"{_X_NS}is")
            if t == "s" and v is not None and v.text is not None:
                idx = int(v.text)
                value = shared[idx] if 0 <= idx < len(shared) else ""
            elif t == "inlineStr" and is_elem is not None:
                parts = [t_el.text or "" for t_el in is_elem.findall(f".{_X_NS}t")]
                value = "".join(parts)
            elif v is not None and v.text is not None:
                value = v.text
            cells[(col, row)] = _unescape_xml(value)
            max_col = max(max_col, col)
            max_row = max(max_row, row)

    if not cells:
        return RichPreview(kind="unavailable", note="Лист Excel пуст.")

    table: list[list[str]] = []
    for r in range(1, min(max_row, MAX_TABLE_ROWS) + 1):
        row_vals = []
        for c in range(1, min(max_col, MAX_TABLE_COLS) + 1):
            row_vals.append(cells.get((c, r), ""))
        if any(v.strip() for v in row_vals):
            table.append(row_vals)
    if not table:
        return RichPreview(kind="unavailable", note="Лист Excel пуст.")
    return RichPreview(kind="table", table=table)


def _simple_rtf_to_text(raw: str) -> str:
    raw = re.sub(r"\\par[d]?", "\n", raw)
    raw = re.sub(r"\\'[0-9a-fA-F]{2}", lambda m: bytes.fromhex(m.group(0)[2:]).decode("cp1251", "replace"), raw)
    raw = re.sub(r"\\[a-z]+\d* ?", "", raw)
    raw = raw.replace("{", "").replace("}", "")
    return raw[:MAX_CHARS]


# Простая подсветка ключевых слов для кода
_CODE_KEYWORDS: dict[str, tuple[str, ...]] = {
    ".py": ("def", "class", "import", "from", "return", "if", "else", "elif", "for", "while", "try", "except", "with", "as", "None", "True", "False"),
    ".js": ("function", "const", "let", "var", "return", "if", "else", "for", "while", "class", "import", "export", "async", "await"),
    ".ts": ("function", "const", "let", "var", "return", "if", "else", "interface", "type", "import", "export", "async", "await"),
    ".java": ("public", "class", "void", "return", "if", "else", "import", "package", "new", "static"),
    ".sql": ("SELECT", "FROM", "WHERE", "INSERT", "UPDATE", "DELETE", "CREATE", "TABLE", "JOIN", "ORDER", "BY"),
}


def code_highlight_spans(ext: str, text: str) -> list[tuple[int, int, str]]:
    """Диапазоны (start, end, tag) для подсветки в Text."""
    ext = ext.lower()
    keywords = _CODE_KEYWORDS.get(ext, ())
    if not keywords:
        return []
    ranges: list[tuple[int, int, str]] = []
    for kw in keywords:
        for m in re.finditer(rf"\b{re.escape(kw)}\b", text):
            ranges.append((m.start(), m.end(), "kw"))
    for m in re.finditer(r"(#.*$|//.*$|/\*.*?\*/)", text, flags=re.MULTILINE | re.DOTALL):
        ranges.append((m.start(), m.end(), "comment"))
    for m in re.finditer(r'(".*?"|\'.*?\')', text, flags=re.DOTALL):
        ranges.append((m.start(), m.end(), "string"))
    ranges.sort(key=lambda x: x[0])
    return ranges


def get_rich_preview(path: str | Path) -> RichPreview | None:
    """Структурированный предпросмотр или None, если тип не поддерживается."""
    p = Path(path)
    if not p.is_file():
        return None
    ext = p.suffix.lower()
    try:
        if ext == ".docx":
            return parse_docx_rich(p)
        if ext == ".doc":
            return RichPreview(
                kind="unavailable",
                note="Формат .doc (Word 97–2003) не поддерживается для предпросмотра.\n"
                     "Откройте файл в Word или сохраните как .docx.",
            )
        if ext == ".xlsx":
            return parse_xlsx_table(p)
        if ext == ".pdf":
            return parse_pdf_text(p)
        if ext == ".rtf":
            text = _simple_rtf_to_text(_read_text_file(p))
            return RichPreview(kind="plain", plain=text) if text else None
        if ext in TEXT_EXTS:
            text = _read_text_file(p)
            if not text:
                return None
            kind = "code" if ext in CODE_EXTS else "plain"
            return RichPreview(kind=kind, plain=text)
    except Exception:
        return RichPreview(kind="unavailable", note="Ошибка чтения файла.")
    return None


def get_text_preview(path: str | Path) -> str | None:
    """Обратная совместимость: плоский текст."""
    rich = get_rich_preview(path)
    if rich is None:
        return None
    if rich.kind == "table" and rich.table:
        return "\n".join("\t".join(row) for row in rich.table)
    if rich.plain:
        return rich.plain
    if rich.note:
        return rich.note
    return None
