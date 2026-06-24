"""Значок в системном трее для фонового агента."""

from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

import pystray
from PIL import Image, ImageDraw

from .config import Settings
from .database import FileIndex
from .sorter import Sorter
from .watcher import FolderWatcher


def _make_icon_image() -> Image.Image:
    """Простая иконка-папка для трея."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([6, 18, 58, 54], radius=6, fill=(33, 150, 243, 255))
    d.rounded_rectangle([6, 12, 30, 24], radius=4, fill=(33, 150, 243, 255))
    d.rectangle([14, 30, 50, 34], fill=(255, 255, 255, 230))
    d.rectangle([14, 40, 42, 44], fill=(255, 255, 255, 230))
    return img


class TrayAgent:
    """Фоновый агент с иконкой в трее и меню управления."""

    def __init__(self) -> None:
        self.settings = Settings()
        self.index = FileIndex()
        self.sorter = Sorter(self.settings, self.index)
        self.watcher = FolderWatcher(self.sorter)
        self.icon: pystray.Icon | None = None

    # --- действия меню ---

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
        threading.Thread(target=self.sorter.sort_all, daemon=True).start()

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
