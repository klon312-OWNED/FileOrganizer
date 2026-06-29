"""Настройки приложения: категории, отслеживаемые папки, папка назначения.

Настройки хранятся в JSON-файле в папке данных приложения, чтобы их можно
было менять из интерфейса и сохранять между запусками.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def app_install_root() -> Path:
    """Корневая папка установки (исходники или собранный PyInstaller)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent

# Папка для данных приложения (настройки + база индекса)
APP_DIR = Path(os.path.expanduser("~")) / ".file_organizer"
APP_DIR.mkdir(parents=True, exist_ok=True)

SETTINGS_PATH = APP_DIR / "settings.json"
DB_PATH = APP_DIR / "index.db"

HOME = Path(os.path.expanduser("~"))

# Категории: имя -> список расширений (в нижнем регистре, с точкой).
# Если расширение файла не найдено ни в одной категории, файл попадает в "Другое".
DEFAULT_CATEGORIES: dict[str, list[str]] = {
    "Картинки": [
        ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif",
        ".svg", ".heic", ".ico", ".raw", ".cr2", ".nef",
    ],
    "Видео": [
        ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v",
        ".mpg", ".mpeg", ".3gp",
    ],
    "Музыка": [
        ".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma", ".opus",
        ".aiff",
    ],
    "Документы": [
        ".pdf", ".doc", ".docx", ".txt", ".rtf", ".odt", ".xls", ".xlsx",
        ".csv", ".ppt", ".pptx", ".odp", ".ods", ".md", ".epub", ".djvu",
    ],
    "Архивы": [
        ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".iso", ".cab",
    ],
    "Программы": [
        ".exe", ".msi", ".bat", ".cmd", ".apk", ".dmg", ".appx", ".jar",
    ],
    "Код": [
        ".py", ".js", ".ts", ".html", ".css", ".java", ".c", ".cpp", ".cs",
        ".go", ".rs", ".php", ".rb", ".json", ".xml", ".yml", ".yaml", ".sql",
        ".sh", ".ps1",
    ],
}

# Имя категории по умолчанию для неизвестных типов файлов
OTHER_CATEGORY = "Другое"

# Категория для папок (директорий)
FOLDER_CATEGORY = "Папки"

# Расширения файлов, которые ещё качаются — их трогать нельзя.
SKIP_EXTENSIONS = [".crdownload", ".part", ".tmp", ".partial", ".download", ".!ut"]

_VALID_SORT_MODES = frozenset({"type_date", "type_only", "date_only", "extension", "flat"})
_VALID_STORAGE_MODES = frozenset({"move", "copy"})
_VALID_DATE_SOURCES = frozenset({"download", "modified", "created"})

DEFAULT_SETTINGS: dict = {
    # Папки, за которыми следим и которые сортируем
    "watched_folders": [
        str(HOME / "Downloads"),
        str(HOME / "Desktop"),
    ],
    # Место, где будет создана папка-архив (его выбирает пользователь)
    "archive_location": str(HOME),
    # Имя папки-архива
    "archive_name": "Архив",
    # Сортировать ли папки (целиком переносить в категорию "Папки")
    "sort_folders": True,
    # Режим раскладки: type_date | type_only | date_only | extension | flat
    "sort_mode": "type_date",
    # move — перемещать; copy — копировать, оригинал оставлять
    "storage_mode": "move",
    # Источник даты для папок назначения
    "date_source": "download",
    # Сколько секунд файл должен быть "спокоен" перед перемещением
    "min_age_seconds": 5,
    # Пути, которые никогда не сортировать (файлы и папки)
    "excluded_paths": [],
    # Toast при фоновой сортировке (Windows)
    "notify_on_sort": True,
    # Тёмная тема оформления
    "dark_mode": False,
    # Сворачивать в трей при закрытии окна (иначе — выход)
    "close_to_tray": True,
    # Индекс последней открытой вкладки (0 = Архив)
    "last_tab": 0,
    # Категории по типам
    "categories": DEFAULT_CATEGORIES,
}


class Settings:
    """Загрузка, доступ и сохранение пользовательских настроек."""

    def __init__(self) -> None:
        self.data: dict = json.loads(json.dumps(DEFAULT_SETTINGS))  # глубокая копия
        self.load()

    def load(self) -> None:
        if SETTINGS_PATH.exists():
            try:
                saved = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
                self._apply_saved(saved)
            except (json.JSONDecodeError, OSError):
                pass  # битый файл — используем значения по умолчанию

    def _apply_saved(self, saved: dict) -> None:
        """Слить сохранённые настройки с defaults и проверить значения."""
        merged = json.loads(json.dumps(DEFAULT_SETTINGS))
        merged.update(saved)
        if merged.get("sort_mode") not in _VALID_SORT_MODES:
            merged["sort_mode"] = DEFAULT_SETTINGS["sort_mode"]
        if merged.get("storage_mode") not in _VALID_STORAGE_MODES:
            merged["storage_mode"] = DEFAULT_SETTINGS["storage_mode"]
        if merged.get("date_source") not in _VALID_DATE_SOURCES:
            merged["date_source"] = DEFAULT_SETTINGS["date_source"]
        try:
            merged["min_age_seconds"] = max(0, int(merged.get("min_age_seconds", 5)))
        except (TypeError, ValueError):
            merged["min_age_seconds"] = DEFAULT_SETTINGS["min_age_seconds"]
        if not merged.get("archive_name"):
            merged["archive_name"] = DEFAULT_SETTINGS["archive_name"]
        self.data = merged

    def save(self) -> None:
        SETTINGS_PATH.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # Удобные геттеры
    @property
    def watched_folders(self) -> list[str]:
        return self.data.get("watched_folders", [])

    @property
    def archive_location(self) -> str:
        return self.data.get("archive_location", str(HOME))

    @property
    def archive_name(self) -> str:
        return self.data.get("archive_name", "Архив") or "Архив"

    @property
    def destination(self) -> str:
        """Полный путь к папке-архиву: <выбранное место>/Архив."""
        # обратная совместимость: если задан явный destination — используем его
        if self.data.get("destination"):
            return self.data["destination"]
        return str(Path(self.archive_location) / self.archive_name)

    @property
    def sort_folders(self) -> bool:
        return bool(self.data.get("sort_folders", True))

    @property
    def min_age_seconds(self) -> int:
        return int(self.data.get("min_age_seconds", 5))

    @property
    def categories(self) -> dict[str, list[str]]:
        return self.data.get("categories", DEFAULT_CATEGORIES)

    @property
    def sort_mode(self) -> str:
        return self.data.get("sort_mode", "type_date")

    @property
    def storage_mode(self) -> str:
        return self.data.get("storage_mode", "move")

    @property
    def date_source(self) -> str:
        return self.data.get("date_source", "download")

    @property
    def excluded_paths(self) -> list[str]:
        raw = self.data.get("excluded_paths", [])
        if not isinstance(raw, list):
            return []
        return [str(p) for p in raw if p]

    @property
    def notify_on_sort(self) -> bool:
        return bool(self.data.get("notify_on_sort", True))

    @property
    def dark_mode(self) -> bool:
        return bool(self.data.get("dark_mode", False))

    @property
    def close_to_tray(self) -> bool:
        return bool(self.data.get("close_to_tray", True))

    @property
    def last_tab(self) -> int:
        try:
            return max(0, min(4, int(self.data.get("last_tab", 0))))
        except (TypeError, ValueError):
            return 0

    def add_excluded_path(self, path: str) -> None:
        try:
            key = str(Path(path).resolve())
        except OSError:
            key = path
        current = self.excluded_paths
        if key not in current:
            current.append(key)
            self.data["excluded_paths"] = current

    def remove_excluded_path(self, path: str) -> None:
        try:
            key = str(Path(path).resolve())
        except OSError:
            key = path
        self.data["excluded_paths"] = [p for p in self.excluded_paths if p != key]

    def category_for_extension(self, ext: str) -> str:
        """Определить категорию по расширению файла."""
        ext = ext.lower()
        for name, exts in self.categories.items():
            if ext in exts:
                return name
        return OTHER_CATEGORY
