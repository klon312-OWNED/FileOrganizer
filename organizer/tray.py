"""Значок в системном трее для фонового агента."""

from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

import pystray

from .config import Settings
from .database import FileIndex
from .icon import make_icon_image
from .notify import SortNotifyBatcher
from .sorter import Sorter
from .watcher import FolderWatcher


def _make_icon_image():
    return make_icon_image(64)


class TrayAgent:
    """Фоновый агент с иконкой в трее и меню управления."""

    def __init__(self) -> None:
        self.settings = Settings()
        self.index = FileIndex()
        self.sorter = Sorter(self.settings, self.index)
        self.watcher = FolderWatcher(self.sorter, on_sorted=self._on_sorted)
        self.icon: pystray.Icon | None = None
        self._sort_notifier = SortNotifyBatcher()

    def _on_sorted(self, new_path: str, src_name: str = "") -> None:
        if self.settings.notify_on_sort:
            self._sort_notifier.add(src_name or Path(new_path).name)

    # --- действия меню ---

    def _reload_settings(self) -> None:
        """Перечитать settings.json (GUI мог изменить настройки)."""
        was_watching = self.watcher.running
        self.watcher.stop()
        self.settings.load()
        self.sorter = Sorter(self.settings, self.index)
        self.watcher = FolderWatcher(self.sorter, on_sorted=self._on_sorted)
        if was_watching:
            self.watcher.start()

    def _open_manager(self, *_):
        if getattr(sys, "frozen", False):
            mgr = Path(sys.executable).with_name("FileOrganizer.exe")
            if mgr.exists():
                subprocess.Popen([str(mgr)])
                return
        run_py = Path(__file__).resolve().parent.parent / "run.py"
        pyw = Path(sys.executable).with_name("pythonw.exe")
        exe = str(pyw) if pyw.exists() else sys.executable
        try:
            subprocess.Popen([exe, str(run_py)])
        except OSError:
            subprocess.Popen([sys.executable, str(run_py)])

    def _sort_now(self, *_):
        self._reload_settings()
        threading.Thread(target=self.sorter.sort_all, daemon=True).start()

    def _reload_settings_menu(self, icon, *_):
        self._reload_settings()
        icon.update_menu()

    def _toggle_watch(self, icon, item):
        if self.watcher.running:
            self.watcher.stop()
        else:
            self.watcher.start()
        icon.update_menu()

    def _is_watching(self, item) -> bool:
        return self.watcher.running

    def _quit(self, icon, *_):
        self.watcher.stop()
        self.index.close()
        icon.stop()

    # --- запуск ---

    def run(self) -> None:
        # стартовая сортировка + включаем слежение
        self.sorter.sort_all()
        self.watcher.start()

        menu = pystray.Menu(
            pystray.MenuItem("Открыть менеджер", self._open_manager, default=True),
            pystray.MenuItem("Сортировать сейчас", self._sort_now),
            pystray.MenuItem(
                "Следить за папками", self._toggle_watch,
                checked=self._is_watching,
            ),
            pystray.MenuItem("Обновить настройки", self._reload_settings_menu),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Выход", self._quit),
        )
        self.icon = pystray.Icon(
            "FileOrganizer", _make_icon_image(),
            "Файловый агент (сортировка)", menu,
        )
        self.icon.run()


def main() -> None:
    TrayAgent().run()


if __name__ == "__main__":
    main()
