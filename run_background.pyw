"""Фоновый агент со значком в трее.

Запускается через pythonw (без консольного окна). Показывает иконку в трее
с меню: открыть менеджер, сортировать сейчас, включить/выключить слежение,
выход. Если по какой-то причине нет pystray/Pillow — работает без иконки.
"""

import time


def main() -> None:
    try:
        from organizer.tray import TrayAgent
        TrayAgent().run()
        return
    except Exception:
        pass

    # Резервный режим без трея
    from organizer.config import Settings
    from organizer.database import FileIndex
    from organizer.sorter import Sorter
    from organizer.watcher import FolderWatcher

    settings = Settings()
    index = FileIndex()
    sorter = Sorter(settings, index)
    sorter.sort_all()
    watcher = FolderWatcher(sorter)
    watcher.start()
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        watcher.stop()
    finally:
        index.close()


if __name__ == "__main__":
    main()
