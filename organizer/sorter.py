"""Движок сортировки: перемещает файлы и папки в Категория/Год/Месяц и индексирует."""

from __future__ import annotations

import shutil
import time
from datetime import datetime
from pathlib import Path

from .config import APP_DIR, FOLDER_CATEGORY, SKIP_EXTENSIONS, Settings, app_install_root
from .database import FileIndex

MONTHS_RU = {
    1: "01-Январь", 2: "02-Февраль", 3: "03-Март", 4: "04-Апрель",
    5: "05-Май", 6: "06-Июнь", 7: "07-Июль", 8: "08-Август",
    9: "09-Сентябрь", 10: "10-Октябрь", 11: "11-Ноябрь", 12: "12-Декабрь",
}

# Папка самого приложения — её и всё внутри трогать нельзя.
APP_ROOT = app_install_root()


class Sorter:
    """Сортирует файлы по типу и дате загрузки, а папки — целиком в 'Папки'."""

    def __init__(self, settings: Settings, index: FileIndex) -> None:
        self.settings = settings
        self.index = index
        # текущая "пачка" перемещений (для группировки при отмене)
        self.current_batch: str | None = None

    def _record_move(self, src: str, dst: str, kind: str, ts: float) -> None:
        batch = self.current_batch or f"single-{time.time():.6f}"
        self.index.log_move(batch=batch, src=src, dst=dst, kind=kind, ts=time.time())

    # ---- вспомогательные ----

    @staticmethod
    def _download_time(path: Path) -> float:
        """Время появления файла/папки (приближение даты загрузки)."""
        st = path.stat()
        return min(st.st_ctime, st.st_mtime)

    @staticmethod
    def _folder_size(path: Path) -> int:
        total = 0
        try:
            for p in path.rglob("*"):
                if p.is_file():
                    try:
                        total += p.stat().st_size
                    except OSError:
                        pass
        except OSError:
            pass
        return total

    def _is_ready(self, path: Path) -> bool:
        """Объект готов к перемещению (не качается/не изменяется прямо сейчас)?"""
        if path.is_file():
            ext = path.suffix.lower()
            if ext in SKIP_EXTENSIONS:
                return False
        try:
            age = time.time() - path.stat().st_mtime
        except OSError:
            return False
        return age >= self.settings.min_age_seconds

    def _is_inside_destination(self, path: Path) -> bool:
        try:
            dest = Path(self.settings.destination).resolve()
            rpath = path.resolve()
            return dest == rpath or dest in rpath.parents
        except OSError:
            return False

    def _is_protected(self, path: Path) -> bool:
        """Запрещённые для перемещения объекты: само приложение, его данные,
        папка-архив и сами отслеживаемые папки."""
        try:
            rp = path.resolve()
        except OSError:
            return True
        # папка приложения и всё внутри неё
        if rp == APP_ROOT or APP_ROOT in rp.parents:
            return True
        # служебные данные приложения
        try:
            app_data = APP_DIR.resolve()
            if rp == app_data or app_data in rp.parents:
                return True
        except OSError:
            pass
        # сами отслеживаемые папки (их содержимое сортируем, а их — нет)
        for folder in self.settings.watched_folders:
            try:
                if rp == Path(folder).resolve():
                    return True
            except OSError:
                continue
        return False

    @staticmethod
    def _unique_target(target: Path) -> Path:
        """Если объект с таким именем уже есть — добавить (1), (2)..."""
        if not target.exists():
            return target
        stem, suffix = target.stem, target.suffix
        if target.is_dir() or not suffix:
            stem, suffix = target.name, ""
        i = 1
        while True:
            candidate = target.with_name(f"{stem} ({i}){suffix}")
            if not candidate.exists():
                return candidate
            i += 1

    def _dest_dir(self, category: str, ts: float) -> tuple[Path, int, int]:
        dt = datetime.fromtimestamp(ts)
        dest_dir = (
            Path(self.settings.destination)
            / category
            / str(dt.year)
            / MONTHS_RU[dt.month]
        )
        dest_dir.mkdir(parents=True, exist_ok=True)
        return dest_dir, dt.year, dt.month

    # ---- сортировка отдельных объектов ----

    def sort_file(self, file_path: str | Path) -> Path | None:
        """Отсортировать один файл. Возвращает новый путь или None."""
        path = Path(file_path)
        if not path.is_file():
            return None
        if not self._is_ready(path):
            return None
        if self._is_inside_destination(path) or self._is_protected(path):
            return None

        ext = path.suffix.lower()
        category = self.settings.category_for_extension(ext)
        ts = self._download_time(path)
        dest_dir, year, month = self._dest_dir(category, ts)
        target = self._unique_target(dest_dir / path.name)

        try:
            shutil.move(str(path), str(target))
        except (OSError, shutil.Error):
            return None

        self.index.add_file(
            name=target.name, path=str(target), source_path=str(path),
            category=category, extension=ext, size=target.stat().st_size,
            added_ts=ts, year=year, month=month, kind="file",
        )
        self._record_move(str(path), str(target), "file", ts)
        return target

    def sort_directory(self, dir_path: str | Path) -> Path | None:
        """Отсортировать одну папку (перенести целиком в категорию 'Папки')."""
        path = Path(dir_path)
        if not path.is_dir():
            return None
        if not self.settings.sort_folders:
            return None
        if not self._is_ready(path):
            return None
        if self._is_inside_destination(path) or self._is_protected(path):
            return None

        ts = self._download_time(path)
        size = self._folder_size(path)
        dest_dir, year, month = self._dest_dir(FOLDER_CATEGORY, ts)
        target = self._unique_target(dest_dir / path.name)

        try:
            shutil.move(str(path), str(target))
        except (OSError, shutil.Error):
            return None

        self.index.add_file(
            name=target.name, path=str(target), source_path=str(path),
            category=FOLDER_CATEGORY, extension="", size=size,
            added_ts=ts, year=year, month=month, kind="dir",
        )
        self._record_move(str(path), str(target), "dir", ts)
        return target

    def sort_entry(self, entry_path: str | Path) -> Path | None:
        """Отсортировать файл или папку — автоматически определяет тип."""
        path = Path(entry_path)
        if path.is_dir():
            return self.sort_directory(path)
        return self.sort_file(path)

    # ---- пакетная сортировка ----

    def sort_folder(self, folder: str | Path) -> int:
        """Отсортировать все файлы и папки верхнего уровня внутри folder."""
        folder = Path(folder)
        if not folder.is_dir():
            return 0
        count = 0
        dest = Path(self.settings.destination).resolve()
        try:
            entries = list(folder.iterdir())
        except OSError:
            return 0
        for entry in entries:
            # никогда не трогаем сам архив
            try:
                if entry.resolve() == dest:
                    continue
            except OSError:
                continue
            if self.sort_entry(entry):
                count += 1
        return count

    def sort_all(self) -> int:
        """Отсортировать все отслеживаемые папки. Возвращает общее количество."""
        total = 0
        dest = Path(self.settings.destination).resolve()
        self.current_batch = f"sort-{datetime.now():%Y%m%d-%H%M%S}-{time.time():.0f}"
        try:
            for folder in self.settings.watched_folders:
                fpath = Path(folder).resolve()
                if fpath == dest or dest in fpath.parents:
                    continue
                total += self.sort_folder(fpath)
        finally:
            self.current_batch = None
        return total

    def undo_last(self) -> tuple[int, int]:
        """Отменить последнюю сортировку: вернуть файлы/папки на прежние места.

        Возвращает (успешно возвращено, не удалось).
        """
        batch = self.index.last_batch()
        if not batch:
            return (0, 0)
        ok = 0
        fail = 0
        for mv in self.index.moves_in_batch(batch):
            dst = Path(mv["dst"])
            src = Path(mv["src"])
            if not dst.exists():
                # уже нет на месте — просто чистим индекс
                self.index.remove_by_path(str(dst))
                continue
            try:
                src.parent.mkdir(parents=True, exist_ok=True)
                target = src
                if target.exists():
                    target = self._unique_target(src)
                shutil.move(str(dst), str(target))
                self.index.remove_by_path(str(dst))
                ok += 1
            except (OSError, shutil.Error):
                fail += 1
        self.index.delete_batch(batch)
        return (ok, fail)

    def reindex_destination(self) -> int:
        """Перестроить индекс по содержимому архива (файлы и папки верхнего
        уровня внутри Категория/Год/Месяц)."""
        dest = Path(self.settings.destination)
        if not dest.is_dir():
            return 0
        count = 0
        for category_dir in dest.iterdir():
            if not category_dir.is_dir():
                continue
            category = category_dir.name
            for year_dir in category_dir.iterdir():
                if not year_dir.is_dir():
                    continue
                for month_dir in year_dir.iterdir():
                    if not month_dir.is_dir():
                        continue
                    for entry in month_dir.iterdir():
                        ts = self._download_time(entry)
                        dt = datetime.fromtimestamp(ts)
                        is_dir = entry.is_dir()
                        self.index.add_file(
                            name=entry.name, path=str(entry), source_path="",
                            category=category,
                            extension="" if is_dir else entry.suffix.lower(),
                            size=self._folder_size(entry) if is_dir
                            else entry.stat().st_size,
                            added_ts=ts, year=dt.year, month=dt.month,
                            kind="dir" if is_dir else "file",
                        )
                        count += 1
        return count
