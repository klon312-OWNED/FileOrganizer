"""Профили пользовательских папок и эвристическое сопоставление файлов.

Режим «Умная раскладка по моим папкам»: программа изучает подпапки выбранной
библиотеки (имя, расширения, образцы имён, фрагменты текста) и предлагает,
куда положить каждый файл.
"""

from __future__ import annotations

import re
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

# Веса скоринга (сумма = 1.0)
_W_NAME = 0.45
_W_EXT = 0.25
_W_KEYWORDS = 0.30

_DEFAULT_THRESHOLD = 0.28
_MAX_SAMPLE_FILES = 40
_MAX_PREVIEW_FILES = 8
_PREVIEW_CHARS = 4000
_MIN_TOKEN_LEN = 2

_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "of", "to", "in", "on", "for", "with",
    "и", "или", "в", "на", "по", "из", "к", "от", "для", "с", "со", "без",
    "это", "как", "что", "не", "да", "нет", "new", "copy", "файл",
    "file", "doc", "docs", "folder", "папка", "untitled",
})

_PREVIEW_EXTS = {
    ".txt", ".md", ".csv", ".log", ".json", ".xml", ".html", ".htm", ".py", ".js",
}
_DOCX_EXT = ".docx"
_PDF_EXT = ".pdf"


@dataclass
class FolderProfile:
    """Профиль одной категории-папки внутри библиотеки пользователя."""

    path: Path
    name: str
    name_tokens: set[str] = field(default_factory=set)
    extensions: Counter = field(default_factory=Counter)
    sample_names: list[str] = field(default_factory=list)
    keywords: set[str] = field(default_factory=set)
    file_count: int = 0


@dataclass
class MatchProposal:
    """Предложение раскладки одного файла (редактируется в диалоге)."""

    source: Path
    action: str  # move | create | catchall | skip
    dest_folder: Path | None
    score: float = 0.0
    profile_name: str = ""
    suggested_folder: str | None = None
    reason: str = ""
    scores: list[tuple[str, float]] = field(default_factory=list)


def tokenize(text: str) -> set[str]:
    """Разбить имя/текст на значимые токены (латиница, кириллица, цифры)."""
    if not text:
        return set()
    raw = text.lower().replace("_", " ").replace("-", " ").replace(".", " ")
    parts = re.findall(r"[a-zа-яё0-9]+", raw, flags=re.IGNORECASE)
    out: set[str] = set()
    for p in parts:
        p = p.strip().lower()
        if len(p) < _MIN_TOKEN_LEN:
            continue
        if p in _STOPWORDS:
            continue
        if p.isdigit() and len(p) < 3:
            continue
        out.add(p)
    return out


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter == 0:
        return 0.0
    return inter / len(a | b)


def _overlap_ratio(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a)


def _read_text_preview(path: Path, limit: int = _PREVIEW_CHARS) -> str:
    ext = path.suffix.lower()
    try:
        if ext in _PREVIEW_EXTS:
            data = path.read_bytes()[: limit * 2]
            for enc in ("utf-8", "cp1251", "latin-1"):
                try:
                    return data.decode(enc)[:limit]
                except UnicodeDecodeError:
                    continue
            return ""
        if ext == _DOCX_EXT:
            return _docx_preview(path, limit)
        if ext == _PDF_EXT:
            return _pdf_preview(path, limit)
    except OSError:
        return ""
    return ""


def _docx_preview(path: Path, limit: int) -> str:
    try:
        with zipfile.ZipFile(path) as zf:
            xml = zf.read("word/document.xml")
    except (OSError, KeyError, zipfile.BadZipFile):
        return ""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return ""
    parts: list[str] = []
    total = 0
    for node in root.iter():
        if node.tag.endswith("}t") and node.text:
            t = node.text.strip()
            if not t:
                continue
            parts.append(t)
            total += len(t) + 1
            if total >= limit:
                break
    return " ".join(parts)[:limit]


def _pdf_preview(path: Path, limit: int) -> str:
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return ""
    try:
        doc = fitz.open(path)
        try:
            if doc.page_count < 1:
                return ""
            text = doc.load_page(0).get_text("text") or ""
            return text[:limit]
        finally:
            doc.close()
    except Exception:
        return ""


def build_folder_profile(
    folder: Path,
    *,
    read_previews: bool = True,
    max_sample: int = _MAX_SAMPLE_FILES,
) -> FolderProfile:
    """Построить профиль одной подпапки библиотеки."""
    folder = Path(folder)
    name = folder.name
    profile = FolderProfile(
        path=folder.resolve(),
        name=name,
        name_tokens=tokenize(name),
    )
    keywords = set(profile.name_tokens)
    samples: list[str] = []
    preview_budget = _MAX_PREVIEW_FILES if read_previews else 0

    try:
        entries = sorted(folder.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        profile.keywords = keywords
        return profile

    for entry in entries:
        if entry.name.startswith("."):
            continue
        if entry.is_dir():
            keywords |= tokenize(entry.name)
            continue
        if not entry.is_file():
            continue
        profile.file_count += 1
        ext = entry.suffix.lower()
        if ext:
            profile.extensions[ext] += 1
        if len(samples) < max_sample:
            samples.append(entry.name)
        keywords |= tokenize(entry.stem)
        if preview_budget > 0 and ext in (_PREVIEW_EXTS | {_DOCX_EXT, _PDF_EXT}):
            preview = _read_text_preview(entry)
            if preview:
                keywords |= tokenize(preview)
                preview_budget -= 1

    profile.sample_names = samples
    profile.keywords = keywords
    return profile


def scan_library(
    root: str | Path,
    *,
    read_previews: bool = True,
) -> list[FolderProfile]:
    """Сканировать прямые подпапки корня библиотеки."""
    root = Path(root)
    if not root.is_dir():
        return []
    profiles: list[FolderProfile] = []
    try:
        children = sorted(
            [p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")],
            key=lambda p: p.name.lower(),
        )
    except OSError:
        return []
    for child in children:
        try:
            profiles.append(build_folder_profile(child, read_previews=read_previews))
        except OSError:
            continue
    return profiles


def suggest_folder_name(file_path: Path, *, max_words: int = 3) -> str:
    """Предложить имя новой папки по имени файла."""
    tokens = tokenize(file_path.stem)
    ordered = [
        t for t in re.findall(r"[a-zа-яё0-9]+", file_path.stem.lower())
        if t in tokens
    ]
    chosen = ordered[:max_words] if ordered else sorted(tokens, key=len, reverse=True)[:max_words]
    if not chosen:
        return "Новая папка"
    title = " ".join(w.capitalize() for w in chosen)
    title = re.sub(r'[<>:"/\\|?*]', "", title).strip(" .") or "Новая папка"
    return title[:80]


def score_against_profile(
    file_path: Path,
    profile: FolderProfile,
    *,
    file_tokens: set[str] | None = None,
    file_keywords: set[str] | None = None,
) -> float:
    """Оценка 0..1: насколько файл подходит к профилю папки."""
    path = Path(file_path)
    stem_tokens = file_tokens if file_tokens is not None else tokenize(path.stem)
    keywords = file_keywords if file_keywords is not None else set(stem_tokens)

    name_bag = set(profile.name_tokens)
    for sample in profile.sample_names[:20]:
        name_bag |= tokenize(Path(sample).stem)
    name_score = max(
        _overlap_ratio(stem_tokens, profile.name_tokens),
        _jaccard(stem_tokens, name_bag) * 0.9,
        _overlap_ratio(stem_tokens, name_bag) * 0.85,
    )
    low_name = path.stem.lower()
    if profile.name.lower() in low_name or any(
        t in low_name for t in profile.name_tokens if len(t) >= 4
    ):
        name_score = max(name_score, 0.85)

    ext = path.suffix.lower()
    ext_score = 0.0
    if ext and profile.extensions:
        total = sum(profile.extensions.values()) or 1
        if ext in profile.extensions:
            ext_score = 0.55 + 0.45 * (profile.extensions[ext] / total)
        else:
            top_share = profile.extensions.most_common(1)[0][1] / total
            ext_score = 0.05 if top_share > 0.8 else 0.15
    elif not ext:
        ext_score = 0.2

    kw_score = max(
        _jaccard(keywords, profile.keywords),
        _overlap_ratio(keywords, profile.keywords),
    )
    return max(0.0, min(1.0, _W_NAME * name_score + _W_EXT * ext_score + _W_KEYWORDS * kw_score))


def match_file(
    file_path: Path,
    profiles: list[FolderProfile],
    *,
    threshold: float = _DEFAULT_THRESHOLD,
    read_preview: bool = True,
    catchall_name: str = "Другое",
) -> MatchProposal:
    """Сопоставить файл с профилями и выбрать действие."""
    path = Path(file_path)
    stem_tokens = tokenize(path.stem)
    keywords = set(stem_tokens)
    if read_preview and path.is_file():
        preview = _read_text_preview(path)
        if preview:
            keywords |= tokenize(preview)

    scores: list[tuple[str, float]] = []
    best: FolderProfile | None = None
    best_score = 0.0
    for prof in profiles:
        sc = score_against_profile(
            path, prof, file_tokens=stem_tokens, file_keywords=keywords,
        )
        scores.append((prof.name, round(sc, 3)))
        if sc > best_score:
            best_score = sc
            best = prof
    scores.sort(key=lambda x: x[1], reverse=True)

    suggested = suggest_folder_name(path)

    if best is not None and best_score >= threshold:
        return MatchProposal(
            source=path,
            action="move",
            dest_folder=best.path,
            score=best_score,
            profile_name=best.name,
            suggested_folder=suggested,
            reason=f"Лучшее совпадение: «{best.name}» ({best_score:.0%})",
            scores=scores,
        )

    return MatchProposal(
        source=path,
        action="create",
        dest_folder=None,
        score=best_score,
        profile_name=best.name if best else "",
        suggested_folder=suggested,
        reason=(
            f"Нет уверенного совпадения (макс. {best_score:.0%}); "
            f"предложена папка «{suggested}» или «{catchall_name}»"
        ),
        scores=scores,
    )


def build_match_plan(
    paths: list[str | Path],
    library_root: str | Path,
    *,
    threshold: float = _DEFAULT_THRESHOLD,
    catchall_name: str = "Другое",
    read_previews: bool = True,
) -> tuple[list[MatchProposal], list[FolderProfile]]:
    """Сканировать библиотеку и построить план сопоставления."""
    root = Path(library_root)
    profiles = scan_library(root, read_previews=read_previews)
    proposals: list[MatchProposal] = []
    for raw in paths:
        path = Path(raw)
        if not path.is_file():
            continue
        proposals.append(
            match_file(
                path,
                profiles,
                threshold=threshold,
                read_preview=read_previews,
                catchall_name=catchall_name,
            ),
        )
    return proposals, profiles


def apply_catchall(
    prop: MatchProposal,
    library_root: Path,
    catchall_name: str = "Другое",
) -> MatchProposal:
    """Назначить файл в папку-сборник («Другое»)."""
    name = (catchall_name or "Другое").strip() or "Другое"
    prop.action = "catchall"
    prop.dest_folder = Path(library_root) / name
    prop.profile_name = name
    prop.reason = f"В папку «{name}»"
    return prop


def apply_create_folder(
    prop: MatchProposal,
    library_root: Path,
    folder_name: str,
) -> MatchProposal:
    """Назначить создание новой папки и перемещение туда."""
    name = re.sub(r'[<>:"/\\|?*]', "", (folder_name or "").strip(" .")) or "Новая папка"
    prop.action = "create"
    prop.suggested_folder = name
    prop.dest_folder = Path(library_root) / name
    prop.profile_name = name
    prop.reason = f"Создать папку «{name}»"
    return prop


def default_threshold() -> float:
    return _DEFAULT_THRESHOLD
