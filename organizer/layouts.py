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
    else:  # type_date — по умолчанию
        dest = root / category / str(year) / MONTHS_RU[month]

    dest.mkdir(parents=True, exist_ok=True)
    return dest, year, month


def sort_mode_label(mode: str) -> str:
    return SORT_MODES.get(mode, mode)


def storage_mode_label(mode: str) -> str:
    return STORAGE_MODES.get(mode, mode)
