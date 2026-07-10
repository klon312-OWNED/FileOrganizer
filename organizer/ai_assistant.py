"""ИИ-помощник: локальные эвристики и опциональный LLM для поиска и подсказок."""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from .classify import classify
from .config import OTHER_CATEGORY, Settings
from .database import FileIndex
from .layouts import MONTHS_RU

Provider = Literal["rules", "openai", "ollama"]

# Ключевые слова категорий (рус/англ)
_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "Картинки": ["картин", "фото", "изображен", "image", "photo", "jpg", "png", "jpeg"],
    "Видео": ["видео", "video", "movie", "фильм", "mp4", "mkv"],
    "Музыка": ["музык", "music", "audio", "песн", "mp3", "flac"],
    "Документы": ["документ", "document", "pdf", "word", "excel", "текст", "doc"],
    "Архивы": ["архив", "archive", "zip", "rar", "7z"],
    "Программы": ["программ", "установщик", "installer", "exe", "msi", "app"],
    "Код": ["код", "code", "script", "python", "js"],
    "Папки": ["папк", "folder", "директор"],
}

_MONTH_NAMES: dict[str, int] = {}
for num, label in MONTHS_RU.items():
    _MONTH_NAMES[label.split("-", 1)[1].lower()] = num
    _MONTH_NAMES[label.lower()] = num
for i, name in enumerate(
    ("январ", "феврал", "март", "апрел", "май", "мая", "июн", "июл",
     "август", "сентябр", "октябр", "ноябр", "декабр"),
    start=1,
):
    _MONTH_NAMES[name] = i

_SIZE_PATTERNS = [
    (re.compile(r"(\d+(?:[.,]\d+)?)\s*(гб|gb)", re.I), 1024 ** 3),
    (re.compile(r"(\d+(?:[.,]\d+)?)\s*(мб|mb)", re.I), 1024 ** 2),
    (re.compile(r"(\d+(?:[.,]\d+)?)\s*(кб|kb)", re.I), 1024),
]

_LARGE_WORDS = ("больш", "крупн", "тяжёл", "тяжел", "large", "big", "huge")
_SMALL_WORDS = ("маленьк", "мелк", "small", "tiny")
_STALE_DAYS = 180


_TEMP_EXTS = {".tmp", ".temp", ".crdownload", ".part", ".partial", ".download", ".!ut", ".bc!"}
_TEMP_NAME_RE = re.compile(
    r"\.(tmp|temp|crdownload|part|partial|download)$|~\$|\.!ut$|\.bc!$",
    re.I,
)


@dataclass
class SearchIntent:
    """Разобранный запрос пользователя."""

    action: str = "search"
    categories: list[str] = field(default_factory=list)
    extensions: list[str] = field(default_factory=list)
    month: int | None = None
    year: int | None = None
    min_size: int | None = None
    max_size: int | None = None
    name_contains: str = ""
    source: str = "all"
    raw_query: str = ""
    delete_candidates: bool = False
    newer_than_days: int | None = None
    older_than_days: int | None = None
    duplicates_only: bool = False
    installers_only: bool = False
    empty_only: bool = False
    temp_only: bool = False
    limit: int | None = None
    sort_by: str = "size"  # size | date | name
    folder_contains: str = ""


@dataclass
class StorageStats:
    """Сводка по занятому месту (только метаданные)."""

    archive_files: int = 0
    archive_size: int = 0
    desktop_sortable: int = 0
    desktop_size: int = 0
    archive_by_category: list[tuple[str, int, int]] = field(default_factory=list)
    desktop_by_category: dict[str, int] = field(default_factory=dict)


@dataclass
class SearchResult:
    path: str
    name: str
    category: str = ""
    size: int = 0
    source: str = ""
    reason: str = ""
    mtime: float = 0.0


@dataclass
class Suggestion:
    id: str
    title: str
    description: str
    action: str
    payload: dict[str, Any] = field(default_factory=dict)
    priority: int = 0


_INSTALLER_EXTS = {".exe", ".msi", ".msix", ".apk", ".dmg", ".appx"}
_DUP_NAME_RE = re.compile(r"\(\d+\)|\bкопия\b|\bcopy\b|_copy", re.I)

QUICK_QUERIES = (
    "найди все pdf за май",
    "покажи большие видео",
    "файлы за неделю",
    "установщики",
    "дубликаты",
    "пустые файлы",
    "временные файлы",
    "топ 10 самых больших",
    "сколько места?",
    "что сортировать сейчас?",
    "какие файлы можно удалить?",
)


def human_size(num: int) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if num < 1024:
            return f"{num:.0f} {unit}" if unit == "Б" else f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} ПБ"


def format_intent_summary(intent: SearchIntent) -> str:
    """Краткое описание разобранного запроса для чата."""
    parts: list[str] = []
    if intent.delete_candidates:
        parts.append("кандидаты на уборку")
    if intent.duplicates_only:
        parts.append("похожие дубликаты")
    if intent.installers_only:
        parts.append("установщики")
    if intent.empty_only:
        parts.append("пустые (0 байт)")
    if intent.temp_only:
        parts.append("временные/недокачанные")
    if intent.categories:
        parts.append(", ".join(intent.categories))
    if intent.extensions:
        parts.append(" ".join(intent.extensions))
    if intent.month:
        parts.append(f"месяц {intent.month}")
    if intent.year:
        parts.append(f"год {intent.year}")
    if intent.newer_than_days:
        parts.append(f"за {intent.newer_than_days} дн.")
    if intent.older_than_days:
        parts.append(f"старше {intent.older_than_days} дн.")
    if intent.min_size:
        parts.append(f"от {human_size(intent.min_size)}")
    if intent.max_size:
        parts.append(f"до {human_size(intent.max_size)}")
    if intent.name_contains:
        parts.append(f"«{intent.name_contains}»")
    if intent.limit:
        parts.append(f"топ {intent.limit}")
    if intent.sort_by and intent.sort_by != "size":
        parts.append(f"сорт. по {intent.sort_by}")
    if intent.source != "all":
        parts.append("архив" if intent.source == "archive" else "отслеживаемые")
    if intent.folder_contains:
        parts.append(f"папка: {intent.folder_contains}")
    return ", ".join(parts) if parts else "без фильтров"


def is_temp_name(name: str) -> bool:
    """Временный / недокачанный файл по имени или расширению."""
    n = (name or "").strip()
    if not n:
        return False
    if Path(n).suffix.lower() in _TEMP_EXTS:
        return True
    return bool(_TEMP_NAME_RE.search(n))


def compute_storage_stats(
    index: FileIndex,
    watched_entries: list[dict],
) -> StorageStats:
    """Сводка по архиву и отслеживаемым папкам."""
    sortable = [e for e in watched_entries if e.get("sortable")]
    desk_by_cat: dict[str, int] = {}
    desk_size = 0
    for e in sortable:
        cat = str(e.get("category") or "Другое")
        desk_by_cat[cat] = desk_by_cat.get(cat, 0) + 1
        desk_size += int(e.get("size", 0) or 0)
    arch_rows = index.stats_by_category()
    arch_by_cat = [
        (str(r["category"]), int(r["cnt"]), int(r["total_size"] or 0))
        for r in arch_rows
    ]
    return StorageStats(
        archive_files=index.count(),
        archive_size=index.total_size(),
        desktop_sortable=len(sortable),
        desktop_size=desk_size,
        archive_by_category=arch_by_cat,
        desktop_by_category=desk_by_cat,
    )


def format_storage_stats(stats: StorageStats) -> str:
    """Текстовая сводка для чата."""
    lines = [
        f"Архив: {stats.archive_files} файлов, {human_size(stats.archive_size)}.",
        f"Отслеживаемые папки: {stats.desktop_sortable} элементов, "
        f"{human_size(stats.desktop_size)}.",
    ]
    if stats.archive_by_category:
        top = stats.archive_by_category[:5]
        parts = [f"«{c}» {n} ({human_size(sz)})" for c, n, sz in top]
        lines.append("В архиве по категориям: " + "; ".join(parts) + ".")
    if stats.desktop_by_category:
        top_d = sorted(
            stats.desktop_by_category.items(), key=lambda x: x[1], reverse=True,
        )[:5]
        parts = [f"«{c}» {n}" for c, n in top_d]
        lines.append("На рабочих папках: " + "; ".join(parts) + ".")
    return " ".join(lines)


def estimate_savings(paths_or_entries: list[Any], *, ratio: float = 0.35) -> int:
    """Грубая оценка экономии места (байты) при сжатии/уборке."""
    total = 0
    for item in paths_or_entries:
        if isinstance(item, dict):
            total += int(item.get("size", 0) or 0)
        elif isinstance(item, SearchResult):
            total += int(item.size or 0)
        else:
            try:
                total += int(item)
            except (TypeError, ValueError):
                continue
    return max(0, int(total * ratio))


class RulesAssistant:
    """Локальный помощник без сети — ключевые слова и эвристики."""

    def parse_user_query(
        self,
        text: str,
        history: list[dict[str, str]] | None = None,
    ) -> SearchIntent:
        q = text.strip()
        # Короткие уточнения («только pdf», «за 2024») — подмешиваем прошлый запрос
        if history and len(q.split()) <= 5:
            prev_user = next(
                (m["content"] for m in reversed(history) if m.get("role") == "user"),
                "",
            )
            low_q = q.lower()
            if prev_user and not any(
                w in low_q for w in ("найд", "покаж", "что ", "как ", "удал", "совет", "подсказ")
            ):
                q = f"{prev_user} {q}"
        low = q.lower()
        intent = SearchIntent(raw_query=q)

        if any(w in low for w in ("подсказ", "совет", "рекоменд", "что сортир", "что удал")):
            intent.action = "suggest"

        if any(w in low for w in (
            "статистик", "сколько мест", "сколько файлов", "занимает",
            "размер архив", "место в архив", "сколько в архив",
        )):
            intent.action = "stats"

        if any(w in low for w in ("удал", "мусор", "лишн", "очист", "уборк")):
            intent.delete_candidates = True

        if any(w in low for w in ("дубликат", "копи", "duplicate", "повтор")):
            intent.duplicates_only = True
            intent.action = "search"

        if any(w in low for w in ("установщик", "installer", "setup", "msi")):
            intent.installers_only = True
            intent.action = "search"
            if "Программы" not in intent.categories:
                intent.categories.append("Программы")

        if any(w in low for w in ("пуст", "empty", "нулев", "0 байт", "0 байтов", "zero-byte")):
            intent.empty_only = True
            intent.action = "search"
            intent.max_size = 0

        if any(w in low for w in (
            "временн", "недокач", "crdownload", "temp файл", "tmp файл",
            ".tmp", ".part", "partial",
        )):
            intent.temp_only = True
            intent.action = "search"

        m_top = re.search(r"топ\s*(\d{1,3})", low)
        if m_top:
            intent.limit = max(1, min(100, int(m_top.group(1))))
            intent.action = "search"
        elif any(w in low for w in ("самые больш", "самый больш", "largest")):
            intent.limit = intent.limit or 10
            intent.sort_by = "size"
            intent.action = "search"
        if any(w in low for w in ("самые нов", "самый нов", "недавн", "newest", "по дате")):
            intent.sort_by = "date"
            intent.action = "search"
            intent.limit = intent.limit or 20
        elif any(w in low for w in ("по имени", "алфавит")):
            intent.sort_by = "name"
            intent.action = "search"

        for cat, keys in _CATEGORY_KEYWORDS.items():
            if any(k in low for k in keys):
                if cat not in intent.categories:
                    intent.categories.append(cat)

        ext_match = re.findall(r"\.([a-z0-9]{1,8})\b", low)
        for ext in ext_match:
            e = f".{ext}"
            if e not in intent.extensions:
                intent.extensions.append(e)

        if "pdf" in low and ".pdf" not in intent.extensions:
            intent.extensions.append(".pdf")
            if "Документы" not in intent.categories:
                intent.categories.append("Документы")

        year_m = re.search(r"(20\d{2})", low)
        if year_m:
            intent.year = int(year_m.group(1))

        for key, num in _MONTH_NAMES.items():
            if key in low:
                intent.month = num
                break

        # Относительные даты: «за неделю», «за 3 дня», «старше месяца»
        if any(w in low for w in ("сегодня", "за сегодня", "за сутки")):
            intent.newer_than_days = 1
        elif any(w in low for w in ("вчера",)):
            intent.newer_than_days = 2
        elif any(w in low for w in ("за неделю", "за 7 дн", "за семь")):
            intent.newer_than_days = 7
        elif any(w in low for w in ("за месяц", "за 30 дн")):
            intent.newer_than_days = 30
        elif any(w in low for w in ("за год", "за 365", "за двенадцать мес")):
            intent.newer_than_days = 365
        else:
            m_new = re.search(r"за\s+(\d+)\s*(дн|день|дня|дней)", low)
            if m_new:
                intent.newer_than_days = int(m_new.group(1))
        if any(w in low for w in ("старше года", "давн", "стары")):
            intent.older_than_days = intent.older_than_days or 365
        elif any(w in low for w in ("старше месяца", "старше 30")):
            intent.older_than_days = 30
        else:
            m_old = re.search(r"старше\s+(\d+)\s*(дн|день|дня|дней|мес)", low)
            if m_old:
                days = int(m_old.group(1))
                if "мес" in m_old.group(2):
                    days *= 30
                intent.older_than_days = days

        for pattern, mult in _SIZE_PATTERNS:
            m = pattern.search(low)
            if m:
                val = float(m.group(1).replace(",", "."))
                size = int(val * mult)
                if any(w in low for w in ("меньш", "до ", "макс", "не больш")):
                    intent.max_size = size
                else:
                    intent.min_size = size
                break

        if intent.min_size is None and any(w in low for w in _LARGE_WORDS):
            intent.min_size = 100 * 1024 * 1024
        if intent.max_size is None and any(w in low for w in _SMALL_WORDS):
            intent.max_size = 1024 * 1024

        if "архив" in low and "zip" not in low and not intent.installers_only:
            intent.source = "archive"
        elif any(w in low for w in ("рабоч", "desktop", "загруз", "download", "отслеж")):
            intent.source = "desktop"

        if "telegram" in low:
            intent.folder_contains = "telegram"
        elif any(w in low for w in ("загрузк", "download")):
            intent.folder_contains = "download"
        elif "desktop" in low or ("рабоч" in low and "стол" in low):
            intent.folder_contains = "desktop"

        if intent.action != "stats" and any(
            w in low for w in ("найд", "покаж", "ищ", "search", "find", "где ")
        ):
            intent.action = "search"

        quoted = re.findall(r"[«\"']([^»\"']+)[»\"']", q)
        if quoted:
            intent.name_contains = quoted[0].lower()
        elif intent.action == "search":
            stop = {
                "найди", "найти", "покажи", "показать", "все", "всех", "за", "из",
                "большие", "большой", "маленькие", "файлы", "файл", "в", "на",
                "май", "июнь", "июль", "архиве", "рабочем", "столе", "можно",
                "какие", "который", "которые", "пожалуйста", "мне", "есть",
                "больше", "меньше", "года", "году", "месяц", "месяца",
            }
            # Не брать в name токены, уже распознанные как категории/размеры/годы
            skip_parts = set()
            for keys in _CATEGORY_KEYWORDS.values():
                skip_parts.update(keys)
            skip_parts.update(_LARGE_WORDS)
            skip_parts.update(_SMALL_WORDS)
            tokens = []
            for t in re.split(r"\s+", low):
                if not t or t in stop or len(t) <= 2:
                    continue
                if any(t.startswith(p) or p in t for p in skip_parts if len(p) >= 3):
                    continue
                if re.fullmatch(r"20\d{2}", t):
                    continue
                if re.fullmatch(r"\d+(?:[.,]\d+)?(?:гб|мб|кб|gb|mb|kb)?", t):
                    continue
                tokens.append(t)
            if tokens and not intent.categories and not intent.extensions:
                intent.name_contains = " ".join(tokens[:4])

        return intent

    def search(
        self,
        intent: SearchIntent,
        *,
        index: FileIndex,
        watched_entries: list[dict],
    ) -> list[SearchResult]:
        results: list[SearchResult] = []

        if intent.source in ("all", "archive"):
            for row in index.query():
                if not self._matches_intent_row(intent, row):
                    continue
                mtime = 0.0
                try:
                    y = int(row["year"] or 0)
                    m = int(row["month"] or 1)
                    if y:
                        mtime = datetime(y, max(1, min(12, m or 1)), 15).timestamp()
                except (ValueError, TypeError, OSError):
                    pass
                results.append(SearchResult(
                    path=row["path"],
                    name=row["name"],
                    category=row["category"],
                    size=int(row["size"] or 0),
                    source="archive",
                    mtime=mtime,
                ))

        if intent.source in ("all", "desktop"):
            for entry in watched_entries:
                if not self._matches_intent_entry(intent, entry):
                    continue
                item = {
                    "name": entry.get("name", ""),
                    "folder": entry.get("folder", ""),
                    "ext": Path(entry.get("name", "")).suffix.lower(),
                    "size": entry.get("size", 0),
                    "mtime": entry.get("mtime", 0),
                }
                reason = ""
                if intent.delete_candidates:
                    is_junk, why = classify(item)
                    if not is_junk:
                        continue
                    reason = why
                results.append(SearchResult(
                    path=entry["path"],
                    name=entry["name"],
                    category=entry.get("category", ""),
                    size=int(entry.get("size", 0)),
                    source="desktop",
                    reason=reason,
                    mtime=float(entry.get("mtime", 0) or 0),
                ))

        if intent.delete_candidates and intent.source != "desktop":
            for entry in watched_entries:
                item = {
                    "name": entry.get("name", ""),
                    "folder": entry.get("folder", ""),
                    "ext": Path(entry.get("name", "")).suffix.lower(),
                    "size": entry.get("size", 0),
                    "mtime": entry.get("mtime", 0),
                }
                is_junk, why = classify(item)
                if not is_junk:
                    continue
                if entry["path"] in {r.path for r in results}:
                    continue
                results.append(SearchResult(
                    path=entry["path"],
                    name=entry["name"],
                    category=entry.get("category", ""),
                    size=int(entry.get("size", 0)),
                    source="desktop",
                    reason=why,
                    mtime=float(entry.get("mtime", 0) or 0),
                ))

        if intent.duplicates_only:
            results = self._filter_duplicate_results(results)

        if intent.empty_only:
            results = [r for r in results if int(r.size or 0) == 0]

        if intent.temp_only:
            results = [r for r in results if is_temp_name(r.name)]

        if intent.sort_by == "name":
            results.sort(key=lambda r: (r.name or "").lower())
        elif intent.sort_by == "date":
            results.sort(key=lambda r: float(r.mtime or 0), reverse=True)
        else:
            results.sort(key=lambda r: r.size, reverse=True)

        limit = intent.limit if intent.limit else 200
        return results[: max(1, min(200, limit))]

    @staticmethod
    def _filter_duplicate_results(results: list[SearchResult]) -> list[SearchResult]:
        """Файлы с похожими именами или одинаковым stem+размером."""
        by_stem: dict[str, list[SearchResult]] = {}
        by_size_stem: dict[tuple[str, int], list[SearchResult]] = {}
        for r in results:
            stem = re.sub(r"\(\d+\)", "", Path(r.name).stem.lower()).strip()
            by_stem.setdefault(stem, []).append(r)
            if int(r.size or 0) > 0:
                by_size_stem.setdefault((stem, int(r.size)), []).append(r)
        seen: set[str] = set()
        out: list[SearchResult] = []

        def add_group(group: list[SearchResult]) -> None:
            for r in group:
                if r.path not in seen:
                    seen.add(r.path)
                    out.append(r)

        for group in by_stem.values():
            if len(group) > 1 or any(_DUP_NAME_RE.search(r.name) for r in group):
                add_group(group)
        for group in by_size_stem.values():
            if len(group) > 1:
                add_group(group)
        return out

    def generate_suggestions(
        self,
        settings: Settings,
        index: FileIndex,
        watched_entries: list[dict],
    ) -> list[Suggestion]:
        suggestions: list[Suggestion] = []
        sortable = [e for e in watched_entries if e.get("sortable")]
        excluded = [e for e in watched_entries if e.get("excluded")]

        if sortable:
            total_size = sum(int(e.get("size", 0)) for e in sortable)
            by_cat: dict[str, list[dict]] = {}
            for e in sortable:
                by_cat.setdefault(e.get("category", OTHER_CATEGORY), []).append(e)
            top_cat = max(by_cat, key=lambda c: len(by_cat[c]))
            suggestions.append(Suggestion(
                id="sort_clutter",
                title=f"Сортировать {len(sortable)} элементов",
                description=(
                    f"В отслеживаемых папках {len(sortable)} файлов/папок "
                    f"({human_size(total_size)}). Больше всего: «{top_cat}» "
                    f"({len(by_cat[top_cat])} шт.)."
                ),
                action="sort_paths",
                payload={"paths": [e["path"] for e in sortable[:50]]},
                priority=90,
            ))

        archive_count = index.count()
        if archive_count > 0:
            stats = index.stats_by_category()
            if stats:
                dominant = stats[0]
                dom_cat = dominant["category"]
                dom_cnt = int(dominant["cnt"])
                if dom_cnt > archive_count * 0.6 and settings.sort_mode != "type_only":
                    suggestions.append(Suggestion(
                        id="sort_mode_type",
                        title="Режим «только по типу»",
                        description=(
                            f"В архиве {dom_cnt} из {archive_count} файлов — "
                            f"категория «{dom_cat}». Плоская раскладка по типу упростит навигацию."
                        ),
                        action="set_sort_mode",
                        payload={"sort_mode": "type_only"},
                        priority=50,
                    ))
                elif len(stats) >= 4 and settings.sort_mode == "flat":
                    suggestions.append(Suggestion(
                        id="sort_mode_type_date",
                        title="Режим «по типу и дате»",
                        description=(
                            f"В архиве {len(stats)} категорий. Режим type_date "
                            "разложит файлы по годам и месяцам."
                        ),
                        action="set_sort_mode",
                        payload={"sort_mode": "type_date"},
                        priority=45,
                    ))

        installers = [
            e for e in sortable
            if Path(e["name"]).suffix.lower() in _INSTALLER_EXTS
            and int(e.get("size", 0)) > 50 * 1024 * 1024
        ]
        if installers and not settings.compression_enabled:
            sz = sum(int(e.get("size", 0)) for e in installers)
            save = estimate_savings(installers, ratio=0.25)
            suggestions.append(Suggestion(
                id="enable_compression",
                title="Включить сжатие при сортировке",
                description=(
                    f"Найдено {len(installers)} крупных установщиков "
                    f"({human_size(sz)}). ZIP может сэкономить ~{human_size(save)}."
                ),
                action="enable_compression",
                payload={},
                priority=70,
            ))
        elif installers:
            suggestions.append(Suggestion(
                id="sort_installers",
                title=f"Установщики: {len(installers)}",
                description=(
                    f"Крупные установщики ({human_size(sum(int(e.get('size', 0)) for e in installers))}). "
                    "Отсортируйте в «Программы» или исключите нужные."
                ),
                action="sort_paths",
                payload={"paths": [e["path"] for e in installers[:30]]},
                priority=65,
            ))

        junk: list[dict] = []
        for e in watched_entries:
            item = {
                "name": e.get("name", ""),
                "folder": e.get("folder", ""),
                "ext": Path(e.get("name", "")).suffix.lower(),
                "size": e.get("size", 0),
                "mtime": e.get("mtime", 0),
            }
            is_junk, why = classify(item)
            if is_junk:
                junk.append({**e, "reason": why})

        if junk:
            jsize = sum(int(e.get("size", 0)) for e in junk)
            suggestions.append(Suggestion(
                id="smart_cleanup",
                title=f"Умная уборка: {len(junk)} кандидатов",
                description=(
                    f"Эвристика нашла {len(junk)} вероятно лишних файлов "
                    f"({human_size(jsize)}). Проверьте перед удалением — "
                    f"потенциально освободится до {human_size(jsize)}."
                ),
                action="smart_cleanup",
                payload={"paths": [e["path"] for e in junk[:30]]},
                priority=80,
            ))

        dup_names: dict[str, list[dict]] = {}
        for e in sortable:
            base = re.sub(r"\(\d+\)", "", e["name"].lower()).strip()
            dup_names.setdefault(base, []).append(e)
        dups = [g for g in dup_names.values() if len(g) > 1]
        if dups:
            sample = dups[0][0]["name"]
            stem = Path(sample).stem
            dup_paths = [e["path"] for g in dups[:10] for e in g]
            suggestions.append(Suggestion(
                id="review_duplicates",
                title=f"Похожие дубликаты: {len(dups)} групп",
                description=(
                    f"Есть файлы с похожими именами (напр. «{sample}»). "
                    "Проверьте перед сортировкой или удалением."
                ),
                action="search",
                payload={"query": "дубликаты", "paths": dup_paths[:40]},
                priority=40,
            ))

        if excluded:
            suggestions.append(Suggestion(
                id="review_excluded",
                title=f"Исключено из сортировки: {len(excluded)}",
                description="Проверьте, нужны ли все исключения — возможно, часть уже неактуальна.",
                action="show_desktop",
                payload={},
                priority=20,
            ))

        # Крупные файлы на рабочем столе / в загрузках
        large = [
            e for e in sortable
            if int(e.get("size", 0)) >= 500 * 1024 * 1024
        ]
        if large:
            lsz = sum(int(e.get("size", 0)) for e in large)
            save = estimate_savings(large, ratio=0.2)
            suggestions.append(Suggestion(
                id="large_files",
                title=f"Крупные файлы: {len(large)} (≥500 МБ)",
                description=(
                    f"Суммарно {human_size(lsz)}. Отсортируйте или сожмите — "
                    f"ориентировочно ~{human_size(save)} при ZIP."
                ),
                action="sort_paths",
                payload={"paths": [e["path"] for e in large[:30]]},
                priority=75,
            ))

        # Старые файлы в отслеживаемых
        now = time.time()
        old_files = [
            e for e in sortable
            if e.get("mtime") and (now - float(e["mtime"])) > _STALE_DAYS * 86400
        ]
        if len(old_files) >= 5:
            suggestions.append(Suggestion(
                id="old_files",
                title=f"Старые файлы: {len(old_files)} (> {_STALE_DAYS} дн.)",
                description=(
                    "Давно не менялись. Можно разложить по дате в архиве "
                    "или проверить на удаление."
                ),
                action="sort_paths",
                payload={"paths": [e["path"] for e in old_files[:40]]},
                priority=55,
            ))

        # Свежие загрузки за 7 дней — напомнить разложить
        recent = [
            e for e in sortable
            if e.get("mtime") and (now - float(e["mtime"])) <= 7 * 86400
        ]
        if len(recent) >= 8:
            suggestions.append(Suggestion(
                id="recent_downloads",
                title=f"Новые за 7 дней: {len(recent)}",
                description=(
                    f"Недавно появились {len(recent)} файлов "
                    f"({human_size(sum(int(e.get('size', 0)) for e in recent))}). "
                    "Удобно сразу разложить, пока помните, что это."
                ),
                action="sort_paths",
                payload={"paths": [e["path"] for e in recent[:40]]},
                priority=72,
            ))

        # Telegram / Downloads clutter
        clutter_folders = [
            e for e in sortable
            if any(
                f in (e.get("folder", "") or "").lower()
                for f in ("telegram", "downloads", "загрузки")
            )
        ]
        if len(clutter_folders) >= 12:
            suggestions.append(Suggestion(
                id="folder_clutter",
                title=f"Загрузки/Telegram: {len(clutter_folders)}",
                description=(
                    "В типичных «мусорных» папках много файлов. "
                    "Отсортируйте пачкой или исключите нужное."
                ),
                action="sort_paths",
                payload={"paths": [e["path"] for e in clutter_folders[:40]]},
                priority=68,
            ))

        # Скриншоты / снимки экрана
        screens = [
            e for e in sortable
            if re.search(r"screenshot|снимок\s*экрана|screen\s*shot", e.get("name", ""), re.I)
        ]
        if screens:
            suggestions.append(Suggestion(
                id="screenshots",
                title=f"Скриншоты: {len(screens)}",
                description=(
                    "Найдены снимки экрана. Обычно их удобно сложить в «Картинки» "
                    "или удалить ненужные."
                ),
                action="sort_paths",
                payload={"paths": [e["path"] for e in screens[:40]]},
                priority=60,
            ))

        # Пустые (0 байт) файлы
        empty = [e for e in sortable if int(e.get("size", 0) or 0) == 0]
        if empty:
            suggestions.append(Suggestion(
                id="empty_files",
                title=f"Пустые файлы: {len(empty)}",
                description=(
                    "Файлы размером 0 байт — часто обрывки загрузок. "
                    "Проверьте и удалите через умную уборку или исключение."
                ),
                action="search",
                payload={"query": "пустые файлы", "paths": [e["path"] for e in empty[:40]]},
                priority=58,
            ))

        temps = [e for e in sortable if is_temp_name(e.get("name", ""))]
        if temps:
            suggestions.append(Suggestion(
                id="temp_files",
                title=f"Временные/недокачанные: {len(temps)}",
                description=(
                    f".tmp / .crdownload / .part и похожие "
                    f"({human_size(sum(int(e.get('size', 0) or 0) for e in temps))}). "
                    "Обычно можно удалить после проверки."
                ),
                action="search",
                payload={"query": "временные файлы", "paths": [e["path"] for e in temps[:40]]},
                priority=62,
            ))

        # Много файлов без категории / «Другое»
        other = [e for e in sortable if e.get("category") in (OTHER_CATEGORY, "", None)]
        if len(other) >= 8:
            suggestions.append(Suggestion(
                id="uncategorized",
                title=f"Без категории: {len(other)}",
                description=(
                    "Много файлов попадут в «Другое». Добавьте правила расширений "
                    "в настройках или отсортируйте вручную."
                ),
                action="sort_paths",
                payload={"paths": [e["path"] for e in other[:40]]},
                priority=35,
            ))

        if not suggestions:
            suggestions.append(Suggestion(
                id="all_good",
                title="Всё аккуратно",
                description="Отслеживаемые папки пусты или уже отсортированы. Добавьте файлы или папки для слежения.",
                action="none",
                payload={},
                priority=0,
            ))

        arch_size = index.total_size()
        arch_count = index.count()
        desk_size = sum(int(e.get("size", 0)) for e in sortable)
        if arch_count >= 50 and arch_size > max(desk_size * 2, 500 * 1024 * 1024):
            suggestions.append(Suggestion(
                id="archive_review",
                title=f"Архив: {human_size(arch_size)}",
                description=(
                    f"В архиве {arch_count} файлов — заметно больше, чем на рабочих папках "
                    f"({human_size(desk_size)}). Спросите «сколько места в архиве?» "
                    "или проверьте старые категории."
                ),
                action="search",
                payload={"query": "сколько места в архиве?"},
                priority=42,
            ))

        suggestions.sort(key=lambda s: s.priority, reverse=True)
        return suggestions[:10]

    def _matches_intent_row(self, intent: SearchIntent, row) -> bool:
        if intent.folder_contains:
            hay = f"{row['path']}".lower()
            if intent.folder_contains not in hay:
                return False
        if intent.temp_only and not is_temp_name(row["name"] or ""):
            return False
        if intent.installers_only:
            ext = (row["extension"] or "").lower()
            if ext not in _INSTALLER_EXTS:
                return False
        elif intent.categories and row["category"] not in intent.categories:
            return False
        ext = (row["extension"] or "").lower()
        if intent.extensions and ext not in intent.extensions:
            return False
        if intent.year and int(row["year"]) != intent.year:
            return False
        if intent.month and int(row["month"]) != intent.month:
            return False
        size = int(row["size"] or 0)
        if intent.min_size is not None and size < intent.min_size:
            return False
        if intent.max_size is not None and size > intent.max_size:
            return False
        if intent.name_contains and intent.name_contains not in row["name"].lower():
            return False
        if intent.newer_than_days or intent.older_than_days:
            # В архиве ориентируемся на year/month записи
            try:
                y = int(row["year"] or 0)
                m = int(row["month"] or 1)
                if y:
                    approx = datetime(y, max(1, min(12, m or 1)), 15).timestamp()
                    if not self._matches_age(intent, approx):
                        return False
            except (ValueError, TypeError, OSError):
                pass
        if intent.duplicates_only and not _DUP_NAME_RE.search(row["name"] or ""):
            # Полная фильтрация дублей — после сбора; здесь мягкий пропуск
            pass
        return True

    def _matches_intent_entry(self, intent: SearchIntent, entry: dict) -> bool:
        name = entry.get("name", "")
        if intent.folder_contains:
            hay = f"{entry.get('folder', '')} {entry.get('path', '')}".lower()
            if intent.folder_contains not in hay:
                return False
        if intent.temp_only and not is_temp_name(name):
            return False
        if intent.installers_only:
            if Path(name).suffix.lower() not in _INSTALLER_EXTS:
                return False
        elif intent.categories and entry.get("category") not in intent.categories:
            return False
        ext = Path(name).suffix.lower()
        if intent.extensions and ext not in intent.extensions:
            return False
        mtime = entry.get("mtime", 0) or 0
        if intent.year or intent.month:
            if mtime:
                dt = datetime.fromtimestamp(mtime)
                if intent.year and dt.year != intent.year:
                    return False
                if intent.month and dt.month != intent.month:
                    return False
        size = int(entry.get("size", 0))
        if intent.min_size is not None and size < intent.min_size:
            return False
        if intent.max_size is not None and size > intent.max_size:
            return False
        if intent.name_contains and intent.name_contains not in name.lower():
            return False
        if intent.folder_contains:
            folder = (entry.get("folder") or "").lower()
            needle = intent.folder_contains.lower()
            if needle == "download":
                if "download" not in folder and "загруз" not in folder:
                    return False
            elif needle not in folder:
                return False
        if not self._matches_age(intent, float(mtime) if mtime else None):
            return False
        return True

    @staticmethod
    def _matches_age(intent: SearchIntent, mtime: float | None) -> bool:
        if intent.newer_than_days is None and intent.older_than_days is None:
            return True
        if not mtime:
            return False
        age_days = (time.time() - mtime) / 86400
        if intent.newer_than_days is not None and age_days > intent.newer_than_days:
            return False
        if intent.older_than_days is not None and age_days < intent.older_than_days:
            return False
        return True


class LLMAssistant:
    """Опциональный LLM-клиент (OpenAI-совместимый API или Ollama)."""

    def __init__(self, settings: Settings, rules: RulesAssistant | None = None) -> None:
        self.settings = settings
        self.rules = rules or RulesAssistant()

    @property
    def provider(self) -> Provider:
        p = self.settings.ai_provider
        return p if p in ("rules", "openai", "ollama") else "rules"

    def parse_user_query(
        self,
        text: str,
        history: list[dict[str, str]] | None = None,
    ) -> SearchIntent:
        if self.provider == "rules":
            return self.rules.parse_user_query(text, history=history)
        try:
            parsed = self._llm_parse(text, history=history)
            if parsed:
                return parsed
        except Exception:
            pass
        return self.rules.parse_user_query(text, history=history)

    def generate_suggestions(
        self,
        settings: Settings,
        index: FileIndex,
        watched_entries: list[dict],
    ) -> list[Suggestion]:
        base = self.rules.generate_suggestions(settings, index, watched_entries)
        if self.provider == "rules":
            return base
        try:
            extra = self._llm_suggestions(settings, index, watched_entries)
            if extra:
                seen = {s.id for s in base}
                for s in extra:
                    if s.id not in seen:
                        base.append(s)
                base.sort(key=lambda s: s.priority, reverse=True)
        except Exception:
            pass
        return base

    def _metadata_summary(
        self,
        settings: Settings,
        index: FileIndex,
        watched_entries: list[dict],
    ) -> dict:
        sortable = [e for e in watched_entries if e.get("sortable")]
        stats = index.stats_by_category()
        return {
            "sort_mode": settings.sort_mode,
            "compression_enabled": settings.compression_enabled,
            "watched_folders": settings.watched_folders,
            "archive_files": index.count(),
            "archive_size": index.total_size(),
            "desktop_sortable": len(sortable),
            "desktop_size": sum(int(e.get("size", 0)) for e in sortable),
            "categories_in_archive": [
                {"name": r["category"], "count": int(r["cnt"]), "size": int(r["total_size"])}
                for r in stats[:12]
            ],
            "desktop_by_category": _count_by(watched_entries, "category"),
        }

    def _llm_parse(
        self,
        text: str,
        history: list[dict[str, str]] | None = None,
    ) -> SearchIntent | None:
        system = (
            "Ты парсер запросов файлового менеджера. Верни ТОЛЬКО JSON без markdown: "
            '{"action":"search|suggest|stats","categories":[],"extensions":[],"month":null,'
            '"year":null,"min_size":null,"max_size":null,"name_contains":"","source":"all|archive|desktop",'
            '"delete_candidates":false,"newer_than_days":null,"older_than_days":null,'
            '"duplicates_only":false,"installers_only":false,"empty_only":false,'
            '"folder_contains":""}. '
            "categories — из: Картинки, Видео, Музыка, Документы, Архивы, Программы, Код, Папки. "
            "sizes в байтах. Учитывай краткий контекст предыдущих сообщений, если он есть."
        )
        raw = self._chat(system, text, history=history)
        if not raw:
            return None
        data = _extract_json(raw)
        if not data:
            return None
        return SearchIntent(
            action=str(data.get("action") or "search"),
            categories=[str(c) for c in (data.get("categories") or [])],
            extensions=[str(e) if str(e).startswith(".") else f".{e}" for e in (data.get("extensions") or [])],
            month=data.get("month"),
            year=data.get("year"),
            min_size=data.get("min_size"),
            max_size=data.get("max_size"),
            name_contains=str(data.get("name_contains") or ""),
            source=str(data.get("source") or "all"),
            raw_query=text,
            delete_candidates=bool(data.get("delete_candidates")),
            newer_than_days=data.get("newer_than_days"),
            older_than_days=data.get("older_than_days"),
            duplicates_only=bool(data.get("duplicates_only")),
            installers_only=bool(data.get("installers_only")),
            empty_only=bool(data.get("empty_only")),
            folder_contains=str(data.get("folder_contains") or ""),
        )

    def _llm_suggestions(
        self,
        settings: Settings,
        index: FileIndex,
        watched_entries: list[dict],
    ) -> list[Suggestion]:
        meta = self._metadata_summary(settings, index, watched_entries)
        system = (
            "Ты помощник по организации файлов. По метаданным предложи 1-2 совета. "
            "Верни ТОЛЬКО JSON-массив: "
            '[{"id":"...","title":"...","description":"...","action":"sort_paths|set_sort_mode|'
            'enable_compression|smart_cleanup|search|none","payload":{},"priority":0-100}]. '
            "Не предлагай удалять без подтверждения. Только metadata, без содержимого файлов."
        )
        raw = self._chat(system, json.dumps(meta, ensure_ascii=False))
        if not raw:
            return []
        data = _extract_json(raw)
        if not isinstance(data, list):
            return []
        out: list[Suggestion] = []
        for item in data[:3]:
            if not isinstance(item, dict):
                continue
            out.append(Suggestion(
                id=str(item.get("id") or f"llm_{len(out)}"),
                title=str(item.get("title") or ""),
                description=str(item.get("description") or ""),
                action=str(item.get("action") or "none"),
                payload=dict(item.get("payload") or {}),
                priority=int(item.get("priority") or 30),
            ))
        return [s for s in out if s.title]

    def _chat(
        self,
        system: str,
        user: str,
        history: list[dict[str, str]] | None = None,
    ) -> str | None:
        messages = self._build_messages(system, user, history)
        if self.provider == "ollama":
            return self._ollama_chat(messages)
        return self._openai_chat(messages)

    @staticmethod
    def _build_messages(
        system: str,
        user: str,
        history: list[dict[str, str]] | None = None,
    ) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = [{"role": "system", "content": system}]
        if history:
            # Текущий запрос уже в `user` — не дублируем последнюю user-реплику
            prior = history[:-1] if history and history[-1].get("role") == "user" else history
            for item in prior[-8:]:
                role = item.get("role")
                content = (item.get("content") or "").strip()
                content = re.sub(r"^(Вы|Помощник|Система|Ошибка):\s*", "", content)
                if role in ("user", "assistant") and content:
                    messages.append({"role": role, "content": content[:800]})
        messages.append({"role": "user", "content": user})
        return messages

    def _openai_chat(self, messages: list[dict[str, str]]) -> str | None:
        key = self.settings.ai_api_key.strip()
        if not key:
            return None
        url = self.settings.ai_base_url.rstrip("/") + "/chat/completions"
        body = json.dumps({
            "model": self.settings.ai_model,
            "messages": messages,
            "temperature": 0.2,
        }).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}",
            },
        )
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        choices = data.get("choices") or []
        if not choices:
            return None
        return choices[0].get("message", {}).get("content")

    def _ollama_chat(self, messages: list[dict[str, str]]) -> str | None:
        url = self.settings.ai_ollama_url.rstrip("/") + "/api/chat"
        body = json.dumps({
            "model": self.settings.ai_ollama_model,
            "messages": messages,
            "stream": False,
        }).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        msg = data.get("message") or {}
        return msg.get("content")

    def test_connection(self) -> tuple[bool, str]:
        """Проверить доступность OpenAI/Ollama. Возвращает (ok, сообщение)."""
        if self.provider == "rules":
            return True, "Локальные правила — сеть не нужна."
        try:
            reply = self._chat(
                "Ответь одним словом: ok",
                "ping",
            )
            if reply and reply.strip():
                return True, f"Связь есть ({self.provider}). Ответ модели получен."
            return False, "Пустой ответ от модели. Проверьте URL и имя модели."
        except urllib.error.HTTPError as exc:
            return False, f"HTTP {exc.code}: {exc.reason}"
        except urllib.error.URLError as exc:
            return False, f"Сеть: {exc.reason}"
        except Exception as exc:
            return False, str(exc)


def _count_by(entries: list[dict], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for e in entries:
        k = str(e.get(key, ""))
        out[k] = out.get(k, 0) + 1
    return out


def _extract_json(text: str) -> Any:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"[\[{][\s\S]*[\]}]", text)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
    return None


def create_assistant(settings: Settings) -> RulesAssistant | LLMAssistant:
    """Фабрика: rules или LLM с fallback."""
    if settings.ai_provider in ("openai", "ollama"):
        return LLMAssistant(settings)
    return RulesAssistant()


def parse_user_query(
    text: str,
    settings: Settings,
    history: list[dict[str, str]] | None = None,
) -> SearchIntent:
    return create_assistant(settings).parse_user_query(text, history=history)


def generate_suggestions(
    settings: Settings,
    index: FileIndex,
    watched_entries: list[dict],
) -> list[Suggestion]:
    return create_assistant(settings).generate_suggestions(settings, index, watched_entries)


def search_files(
    intent: SearchIntent,
    *,
    index: FileIndex,
    watched_entries: list[dict],
) -> list[SearchResult]:
    return RulesAssistant().search(intent, index=index, watched_entries=watched_entries)


def storage_stats_summary(
    index: FileIndex,
    watched_entries: list[dict],
) -> str:
    return format_storage_stats(compute_storage_stats(index, watched_entries))
