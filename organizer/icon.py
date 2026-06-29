"""Иконка приложения: генерация и путь к .ico для окна и сборки."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from .config import app_install_root

_ICON_CACHE: Path | None = None


def make_icon_image(size: int = 64) -> Image.Image:
    """Синяя папка с полосками — общий стиль для окна и трея."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = size / 64
    d.rounded_rectangle(
        [6 * m, 18 * m, 58 * m, 54 * m], radius=6 * m, fill=(37, 99, 235, 255),
    )
    d.rounded_rectangle(
        [6 * m, 12 * m, 30 * m, 24 * m], radius=4 * m, fill=(37, 99, 235, 255),
    )
    d.rectangle([14 * m, 30 * m, 50 * m, 34 * m], fill=(255, 255, 255, 230))
    d.rectangle([14 * m, 40 * m, 42 * m, 44 * m], fill=(255, 255, 255, 230))
    return img


def icon_path() -> Path:
    """Путь к .ico в assets/ (создаёт при первом обращении)."""
    global _ICON_CACHE
    if _ICON_CACHE is not None and _ICON_CACHE.exists():
        return _ICON_CACHE
    root = app_install_root()
    assets = root / "assets"
    assets.mkdir(exist_ok=True)
    ico = assets / "icon.ico"
    if not ico.exists():
        img = make_icon_image(256)
        img.save(ico, format="ICO", sizes=[(256, 256), (64, 64), (32, 32), (16, 16)])
    _ICON_CACHE = ico
    return ico
