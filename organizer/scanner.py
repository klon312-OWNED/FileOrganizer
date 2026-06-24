"""Поиск файлов по всему компьютеру по категории/расширениям.

Обходит выбранные корни (по умолчанию — все локальные диски), пропуская
системные и «шумные» папки, и возвращает найденные файлы. Работает в фоновом
потоке с возможностью остановки и обратным вызовом прогресса.
"""

from __future__ import annotations

import os
import string
import threading
from pathlib import Path

# Папки, которые пропускаем (системные/служебные/мусорные)
SKIP_DIR_NAMES = {
    "windows", "$recycle.bin", "system volume information", "program files",
    "program files (x86)", "programdata", "appdata", "node_modules",
    ".git", "__pycache__", "site-packages", ".cache", "perflogs",
    "intel", "amd", "nvidia", "msocache", "recovery", "boot", ".venv",
    "venv", "env", "dist-packages", "windows.old",
}


def fixed_drives() -> list[str]:
    """Список доступных локальных дисков на Windows (C:\\, D:\\, ...)."""
    drives = []
    if os.name == "nt":
        for letter in string.ascii_uppercase:
            root = f"{letter}:\\"
            if os.path.exists(root):
                drives.append(root)
    else:
        drives.append("/")
    return drives


class Scanner:
    """Сканер файлов по расширениям с поддержкой остановки и прогресса."""

    def __init__(self) -> None:
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def reset(self) -> None:
        self._stop.clear()

    def scan(
        self,
        extensions: set[str],
        roots: list[str] | None = None,
        on_progress=None,
        on_result=None,
        max_results: int = 100000,
    ) -> list[dict]:
        """Найти файлы с указанными расширениями.

        extensions — множество расширений в нижнем регистре с точкой; пустое
        множество означает «все файлы».
        on_progress(folder, found) — вызывается периодически.
        on_result(item) — вызывается на каждый найденный файл (для стрима в UI).
        """
        self.reset()
        roots = roots or fixed_drives()
        exts = {e.lower() for e in extensions}
        results: list[dict] = []
        scanned_dirs = 0

        for root in roots:
            for dirpath, dirnames, filenames in os.walk(root, topdown=True):
                if self._stop.is_set():
                    return results
                # отфильтровать системные/шумные подпапки на месте
                dirnames[:] = [
                    d for d in dirnames
                    if d.lower() not in SKIP_DIR_NAMES and not d.startswith("$")
                ]
                scanned_dirs += 1
                if on_progress and scanned_dirs % 40 == 0:
                    on_progress(dirpath, len(results))

                for fname in filenames:
                    if self._stop.is_set():
                        return results
                    ext = os.path.splitext(fname)[1].lower()
                    if exts and ext not in exts:
                        continue
                    full = os.path.join(dirpath, fname)
                    try:
                        st = os.stat(full)
                    except OSError:
                        continue
                    item = {
                        "name": fname,
                        "path": full,
                        "folder": dirpath,
                        "ext": ext,
                        "size": st.st_size,
                        "mtime": st.st_mtime,
                    }
                    results.append(item)
                    if on_result:
                        on_result(item)
                    if len(results) >= max_results:
                        return results
        if on_progress:
            on_progress("Готово", len(results))
        return results
