"""Windows toast-уведомления (без дополнительных зависимостей)."""

from __future__ import annotations

import subprocess
import sys
import threading


def can_notify() -> bool:
    return sys.platform.startswith("win")


def show_toast(title: str, message: str, *, app_id: str = "FileOrganizer") -> None:
    """Показать короткое уведомление Windows 10/11. На других ОС — no-op."""
    if not can_notify():
        return
    safe_title = title.replace("'", "''").replace("`", "``")
    safe_msg = message.replace("'", "''").replace("`", "``")
    safe_id = app_id.replace("'", "''")
    ps = (
        "[Windows.UI.Notifications.ToastNotificationManager, "
        "Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null; "
        f"$id = '{safe_id}'; "
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($id) | Out-Null; "
        "$xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
        "[Windows.UI.Notifications.ToastTemplateType]::ToastText02); "
        "$text = $xml.GetElementsByTagName('text'); "
        f"$text.Item(0).AppendChild($xml.CreateTextNode('{safe_title}')) | Out-Null; "
        f"$text.Item(1).AppendChild($xml.CreateTextNode('{safe_msg}')) | Out-Null; "
        "$toast = [Windows.UI.Notifications.ToastNotification]::new($xml); "
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($id).Show($toast)"
    )
    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError:
        pass


class SortNotifyBatcher:
    """Группирует уведомления о фоновой сортировке в одно сводное toast."""

    def __init__(self, *, debounce_sec: float = 4.0) -> None:
        self._debounce_sec = debounce_sec
        self._lock = threading.Lock()
        self._count = 0
        self._timer: threading.Timer | None = None

    def add(self, _name: str = "") -> None:
        """Зарегистрировать отсортированный файл; toast уйдёт после паузы."""
        with self._lock:
            self._count += 1
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self._debounce_sec, self._flush)
            self._timer.daemon = True
            self._timer.start()

    def _flush(self) -> None:
        with self._lock:
            count = self._count
            self._count = 0
            self._timer = None
        if count <= 0:
            return
        if count == 1:
            show_toast("FileOrganizer", "Отсортирован 1 файл")
        else:
            show_toast("FileOrganizer", f"Отсортировано: {count} файлов")
