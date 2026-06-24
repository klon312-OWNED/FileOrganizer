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
    # Сколько секунд файл должен быть "спокоен" перед перемещением
    # (чтобы не перемещать файл во время скачивания)
    "min_age_seconds": 5,
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
                self.data.update(saved)
            except (json.JSONDecodeError, OSError):
                pass  # битый файл — используем значения по умолчанию

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

    def category_for_extension(self, ext: str) -> str:
        """Определить категорию по расширению файла."""
        ext = ext.lower()
        for name, exts in self.categories.items():
            if ext in exts:
                return name
        return OTHER_CATEGORY
