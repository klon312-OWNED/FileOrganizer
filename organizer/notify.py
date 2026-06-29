"""Windows toast-уведомления (без дополнительных зависимостей)."""

from __future__ import annotations

import subprocess
import sys


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
