"""Генерация миниатюр для фото (включая HEIC) и видео (кадр из ролика)."""

from __future__ import annotations

from pathlib import Path

try:
    from PIL import Image, ImageDraw
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False

# Поддержка HEIC/HEIF (фото с iPhone)
try:
    import pillow_heif
    pillow_heif.register_heif_opener()
    _HAS_HEIF = True
except Exception:
    _HAS_HEIF = False

# Кадры из видео
try:
    import cv2
    _HAS_CV2 = True
except Exception:
    _HAS_CV2 = False

IMAGE_EXTS = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif", ".ico",
    ".heic", ".heif",
}
VIDEO_EXTS = {
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v",
    ".mpg", ".mpeg", ".3gp",
}


def is_previewable_media(ext: str) -> bool:
    ext = ext.lower()
    return ext in IMAGE_EXTS or ext in VIDEO_EXTS


def _image_thumb(path: Path, max_size):
    img = Image.open(path)
    img = img.convert("RGB")
    img.thumbnail(max_size)
    return img


def _video_thumb(path: Path, max_size):
    if not _HAS_CV2:
        return None
    cap = cv2.VideoCapture(str(path))
    try:
        if not cap.isOpened():
            return None
        frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        # берём кадр примерно на 10% длительности (но не нулевой)
        target = int(frame_count * 0.1) if frame_count > 10 else 0
        if target:
            cap.set(cv2.CAP_PROP_POS_FRAMES, target)
        ok, frame = cap.read()
        if not ok or frame is None:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = cap.read()
        if not ok or frame is None:
            return None
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(frame)
        img.thumbnail(max_size)
        _draw_play_icon(img)
        return img
    finally:
        cap.release()


def _draw_play_icon(img) -> None:
    """Нарисовать значок ▶ поверх кадра, чтобы было видно, что это видео."""
    w, h = img.size
    d = ImageDraw.Draw(img, "RGBA")
    r = max(18, min(w, h) // 8)
    cx, cy = w // 2, h // 2
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(0, 0, 0, 130))
    s = r * 0.55
    d.polygon(
        [(cx - s * 0.5, cy - s), (cx - s * 0.5, cy + s), (cx + s, cy)],
        fill=(255, 255, 255, 230),
    )


def get_thumbnail(path: str | Path, max_size=(360, 300)):
    """Вернуть PIL.Image-миниатюру для фото/видео или None."""
    if not _HAS_PIL:
        return None
    p = Path(path)
    if not p.is_file():
        return None
    ext = p.suffix.lower()
    try:
        if ext in IMAGE_EXTS:
            return _image_thumb(p, max_size)
        if ext in VIDEO_EXTS:
            return _video_thumb(p, max_size)
    except Exception:
        return None
    return None
