"""Перетаскивание файлов из Проводника на виджет Tk (только Windows)."""

from __future__ import annotations

import sys
from collections.abc import Callable


def bind_file_drop(widget, callback: Callable[[list[str]], None]) -> bool:
    """Подключить drop файлов. callback получает список абсолютных путей."""
    if not sys.platform.startswith("win"):
        return False
    try:
        import windnd  # type: ignore[import-untyped]
    except ImportError:
        return False

    def _on_drop(files) -> None:
        paths: list[str] = []
        for raw in files:
            text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
            text = text.strip().strip("{}")
            if text:
                paths.append(text)
        if paths:
            callback(paths)

    try:
        windnd.hook_dropfiles(widget, func=_on_drop, force_unicode=True)
    except Exception:
        return False
    return True
