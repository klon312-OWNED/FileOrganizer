"""Сжатие файлов и папок в ZIP (только стандартная библиотека)."""

from __future__ import annotations

import zipfile
from pathlib import Path

COMPRESSION_MODES = ("none", "zip", "zip_per_item")
COMPRESSION_LEVELS = ("store", "fast", "best")

_MODE_LABELS = {
    "none": "Без сжатия",
    "zip": "Один ZIP на группу",
    "zip_per_item": "ZIP для каждого элемента",
}

_LEVEL_LABELS = {
    "store": "Без сжатия (store)",
    "fast": "Быстрое",
    "best": "Максимальное",
}


def compression_mode_label(mode: str) -> str:
    return _MODE_LABELS.get(mode, mode)


def compression_level_label(level: str) -> str:
    return _LEVEL_LABELS.get(level, level)


def _zip_params(level: str) -> tuple[int, int | None]:
    if level == "store":
        return zipfile.ZIP_STORED, None
    if level == "best":
        return zipfile.ZIP_DEFLATED, 9
    return zipfile.ZIP_DEFLATED, 1


def _unique_zip_path(base: Path) -> Path:
    if not base.exists():
        return base
    stem = base.stem
    parent = base.parent
    i = 1
    while True:
        candidate = parent / f"{stem} ({i}).zip"
        if not candidate.exists():
            return candidate
        i += 1


def _add_to_zip(zf: zipfile.ZipFile, source: Path, arc_prefix: str = "") -> None:
    if source.is_file():
        arcname = f"{arc_prefix}{source.name}" if arc_prefix else source.name
        zf.write(source, arcname)
        return
    if not source.is_dir():
        return
    for child in sorted(source.rglob("*")):
        if child.is_file():
            rel = child.relative_to(source)
            arcname = f"{arc_prefix}{source.name}/{rel.as_posix()}"
            zf.write(child, arcname)


def zip_item(source: Path, dest_zip: Path | None = None, *, level: str = "fast") -> Path:
    """Упаковать один файл или папку в .zip рядом с источником (или в dest_zip)."""
    source = Path(source)
    if not source.exists():
        raise FileNotFoundError(source)
    if dest_zip is None:
        dest_zip = source.with_suffix(".zip") if source.is_file() else source.parent / f"{source.name}.zip"
    dest_zip = _unique_zip_path(Path(dest_zip))
    compression, compresslevel = _zip_params(level)
    kwargs: dict = {"compression": compression}
    if compresslevel is not None:
        kwargs["compresslevel"] = compresslevel
    dest_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest_zip, "w", **kwargs) as zf:
        _add_to_zip(zf, source)
    return dest_zip


def zip_group(sources: list[Path], dest_zip: Path, *, level: str = "fast") -> Path:
    """Упаковать несколько элементов в один архив."""
    dest_zip = _unique_zip_path(Path(dest_zip))
    compression, compresslevel = _zip_params(level)
    kwargs: dict = {"compression": compression}
    if compresslevel is not None:
        kwargs["compresslevel"] = compresslevel
    dest_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest_zip, "w", **kwargs) as zf:
        for source in sources:
            source = Path(source)
            if source.exists():
                _add_to_zip(zf, source)
    return dest_zip


def remove_source(path: Path) -> None:
    import shutil

    path = Path(path)
    if path.is_dir():
        shutil.rmtree(path)
    elif path.is_file():
        path.unlink()
