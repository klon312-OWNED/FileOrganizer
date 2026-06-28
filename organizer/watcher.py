"""Фоновый наблюдатель: следит за папками и сортирует новые файлы.

Работает на событиях файловой системы (watchdog), поэтому почти не нагружает
процессор. Новые/перемещённые файлы попадают в очередь и сортируются, как
только перестают изменяться (когда скачивание завершилось).
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .config import SKIP_EXTENSIONS
from .sorter import Sorter


class _Handler(FileSystemEventHandler):
    """Реагирует и на файлы, и на папки в отслеживаемой директории."""

    def __init__(self, on_change) -> None:
        self._on_change = on_change

    def on_created(self, event) -> None:
        self._on_change(event.src_path)

    def on_moved(self, event) -> None:
        self._on_change(event.dest_path)

    def on_modified(self, event) -> None:
        self._on_change(event.src_path)


class FolderWatcher:
    """Запускает наблюдение за отслеживаемыми папками в фоне."""

    def __init__(self, sorter: Sorter, on_sorted=None) -> None:
        self.sorter = sorter
        self.on_sorted = on_sorted  # callback(new_path) для обновления интерфейса
        self._observer: Observer | None = None
        self._pending: dict[str, float] = {}
        self._pending_lock = threading.Lock()
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self._protected: set[str] = set()

    def _build_protected(self) -> set[str]:
        """Пути, которые нельзя трогать: сами отслеживаемые папки и архив."""
        protected: set[str] = set()
        for folder in self.sorter.settings.watched_folders:
            try:
                protected.add(str(Path(folder).resolve()))
            except OSError:
                pass
        try:
            protected.add(str(Path(self.sorter.settings.destination).resolve()))
        except OSError:
            pass
        return protected

    def _queue(self, path: str) -> None:
        try:
            p = Path(path)
            rp = str(p.resolve())
        except OSError:
            return
        if rp in self._protected:
            return
        if p.is_file() and p.suffix.lower() in SKIP_EXTENSIONS:
            return
        with self._pending_lock:
            self._pending[path] = time.time()

    def _process_loop(self) -> None:
        """Периодически пытается отсортировать файлы из очереди."""
        while not self._stop.is_set():
            time.sleep(2)
            with self._pending_lock:
                items = list(self._pending.keys())

            to_sort: list[str] = []
            drop: list[str] = []
            for path in items:
                p = Path(path)
                if not p.exists():
                    drop.append(path)
                    continue
                if p.is_dir() and not self.sorter.settings.sort_folders:
                    drop.append(path)
                    continue
                if self.sorter._is_inside_destination(p) or self.sorter._is_protected(p):
                    drop.append(path)
                    continue
                if not self.sorter._is_ready(p):
                    continue
                to_sort.append(path)

            if drop:
                with self._pending_lock:
                    for path in drop:
                        self._pending.pop(path, None)

            if not to_sort:
                continue

            with self.sorter.batch_context("watch"):
                for path in to_sort:
                    result = self.sorter.sort_entry(path)
                    if result is not None:
                        with self._pending_lock:
                            self._pending.pop(path, None)
                        if self.on_sorted:
                            try:
                                self.on_sorted(str(result))
                            except Exception:
                                pass

    def start(self) -> None:
        if self._observer is not None:
            return
        self._stop.clear()
        self._protected = self._build_protected()
        self._observer = Observer()
        handler = _Handler(self._queue)
        for folder in self.sorter.settings.watched_folders:
            p = Path(folder)
            if p.is_dir():
                self._observer.schedule(handler, str(p), recursive=False)
        self._observer.start()
        self._worker = threading.Thread(target=self._process_loop, daemon=True)
        self._worker.start()

    def stop(self) -> None:
        self._stop.set()
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=3)
            self._observer = None

    @property
    def running(self) -> bool:
        return self._observer is not None
