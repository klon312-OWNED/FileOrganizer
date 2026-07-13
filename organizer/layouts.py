"""Схемы раскладки файлов в архиве — несколько режимов сортировки."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .config import FOLDER_CATEGORY, OTHER_CATEGORY

MONTHS_RU = {
    1: "01-Январь", 2: "02-Февраль", 3: "03-Март", 4: "04-Апрель",
    5: "05-Май", 6: "06-Июнь", 7: "07-Июль", 8: "08-Август",
    9: "09-Сентябрь", 10: "10-Октябрь", 11: "11-Ноябрь", 12: "12-Декабрь",
}

SORT_MODES: dict[str, str] = {
    "type_date": "По типу и дате — Картинки/2026/06-Июнь",
    "type_only": "Только по типу — Картинки/файл",
    "date_only": "Только по дате — 2026/06-Июнь/файл",
    "extension": "По расширению — .pdf, .jpg",
    "flat": "Без подпапок — всё в корень архива",
    "smart_folders": "По моим папкам — в вашу библиотеку категорий",
}

STORAGE_MODES: dict[str, str] = {
    "move": "Перемещать (убирать из исходной папки)",
    "copy": "Копировать (оригинал остаётся)",
}

DATE_SOURCES: dict[str, str] = {
    "download": "Дата появления (мин. создание/изменение)",
    "modified": "Дата изменения",
    "created": "Дата создания",
}


def dest_directory(
    *,
    archive_root: Path,
    sort_mode: str,
    category: str,
    extension: str,
    ts: float,
    is_dir: bool = False,
) -> tuple[Path, int, int]:
    """Вернуть папку назначения и (год, месяц) для индекса."""
    dt = datetime.fromtimestamp(ts)
    year, month = dt.year, dt.month
    root = archive_root

    if sort_mode == "flat":
        dest = root
    elif sort_mode == "type_only":
        dest = root / category
    elif sort_mode == "date_only":
        dest = root / str(year) / MONTHS_RU[month]
    elif sort_mode == "extension":
        if is_dir or category == FOLDER_CATEGORY:
            dest = root / FOLDER_CATEGORY
        else:
            ext = extension.lower() if extension else ".без_расширения"
            if not ext.startswith("."):
                ext = "." + ext
            dest = root / "По расширению" / ext.lstrip(".")
    elif sort_mode == "smart_folders":
        # Назначение задаётся явно через sorter.apply_smart_folder_plan;
        # запасной путь — как type_only внутри корня библиотеки.
        dest = root / (category or OTHER_CATEGORY)
    else:  # type_date — по умолчанию
        dest = root / category / str(year) / MONTHS_RU[month]

    dest.mkdir(parents=True, exist_ok=True)
    return dest, year, month


def sort_mode_label(mode: str) -> str:
    return SORT_MODES.get(mode, mode)


def sort_mode_preview(mode: str) -> str:
    """Пример пути в архиве для выбранного режима."""
    examples = {
        "type_date": "Картинки/2026/06-Июнь/photo.jpg",
        "type_only": "Документы/report.pdf",
        "date_only": "2026/06-Июнь/photo.jpg",
        "extension": "По расширению/pdf/report.pdf",
        "flat": "photo.jpg",
        "smart_folders": "Учёба/Курс Python/homework_01.pdf",
    }
    return examples.get(mode, "")


def _month_from_label(part: str) -> int | None:
    for num, label in MONTHS_RU.items():
        if label == part:
            return num
    return None


def infer_index_fields(
    archive_root: Path,
    entry: Path,
    *,
    sort_mode: str,
    category_for_extension,
    ts: float,
) -> tuple[str, int, int]:
    """Определить категорию и (год, месяц) по пути файла в архиве."""
    dt = datetime.fromtimestamp(ts)
    year, month = dt.year, dt.month
    ext = entry.suffix.lower()

    try:
        parts = entry.relative_to(archive_root).parts
    except ValueError:
        return category_for_extension(ext), year, month

    if not parts:
        return category_for_extension(ext), year, month

    if sort_mode == "flat" or len(parts) == 1:
        if entry.is_dir() or (len(parts) == 1 and parts[0] == FOLDER_CATEGORY):
            return FOLDER_CATEGORY, year, month
        return category_for_extension(ext), year, month

    first = parts[0]

    if sort_mode == "extension" or first == "По расширению":
        if first == "По расширению" and len(parts) >= 2:
            return f".{parts[1]}", year, month
        if first == FOLDER_CATEGORY:
            return FOLDER_CATEGORY, year, month
        return category_for_extension(ext), year, month

    if sort_mode == "date_only" or (first.isdigit() and len(first) == 4):
        y = int(first) if first.isdigit() and len(first) == 4 else year
        m = _month_from_label(parts[1]) if len(parts) >= 2 else month
        return "По дате", y, m

    if sort_mode == "type_only":
        return first, year, month

    # type_date (по умолчанию): категория/год/месяц
    if len(parts) >= 3 and parts[1].isdigit() and len(parts[1]) == 4:
        y = int(parts[1])
        m = _month_from_label(parts[2]) or month
        return first, y, m

    if first == FOLDER_CATEGORY and len(parts) >= 3 and parts[1].isdigit():
        y = int(parts[1])
        m = _month_from_label(parts[2]) or month
        return FOLDER_CATEGORY, y, m

    return first, year, month


def storage_mode_label(mode: str) -> str:
    return STORAGE_MODES.get(mode, mode)
