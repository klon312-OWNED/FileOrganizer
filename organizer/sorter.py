"""Движок сортировки: перемещает или копирует файлы по выбранной схеме."""

from __future__ import annotations

import shutil
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .compression import remove_source, zip_group, zip_item
from .config import APP_DIR, FOLDER_CATEGORY, SKIP_EXTENSIONS, Settings, app_install_root
from .database import FileIndex
from .folder_profiles import MatchProposal, build_match_plan
from .layouts import dest_directory, infer_index_fields

APP_ROOT = app_install_root()
_SMART_INSTALLER_EXTS = {
    ".exe", ".msi", ".msix", ".appx", ".appxbundle", ".pkg", ".dmg", ".deb", ".rpm",
}
_SMART_TEMP_EXTS = {".tmp", ".temp", ".log", ".bak", ".old", ".cache", ".crdownload", ".part"}
_SMART_MEDIA_EXTS = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".tif", ".tiff",
    ".mp4", ".mov", ".mkv", ".avi", ".wmv", ".mp3", ".wav", ".flac", ".m4a",
}


@dataclass
class SortResult:
    """Итог сортировки: число обработанных файлов и список ошибок."""

    moved: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)

    def add_error(self, path: str, reason: str) -> None:
        self.errors.append((path, reason))


@dataclass
class UndoBatchReport:
    restored: int = 0
    missing: int = 0
    failed: int = 0
    details: list[tuple[str, str]] = field(default_factory=list)


class Sorter:
    """Сортирует файлы и папки по настраиваемой схеме раскладки."""

    def __init__(self, settings: Settings, index: FileIndex) -> None:
        self.settings = settings
        self.index = index
        self.current_batch: str | None = None
        self._batch_count = 0
        self._batch_zip_queue: list[Path] = []
        self._operation_lock = threading.Lock()

    def _should_compress(self) -> bool:
        return (
            self.settings.compression_enabled
            and self.settings.compression_mode != "none"
        )

    def _compress_after_move(self, target: Path) -> Path:
        """Сжать перемещённый элемент, если включено в настройках."""
        if not self._should_compress():
            return target
        mode = self.settings.compression_mode
        level = self.settings.compression_level
        if mode == "zip_per_item":
            try:
                zip_path = zip_item(target, level=level)
                remove_source(target)
                self.index.remove_by_path(str(target))
                return zip_path
            except OSError:
                return target
        if mode == "zip":
            self._batch_zip_queue.append(target)
        return target

    def _finish_batch_zip(self) -> None:
        if not self._batch_zip_queue or self.settings.compression_mode != "zip":
            self._batch_zip_queue.clear()
            return
        level = self.settings.compression_level
        by_parent: dict[Path, list[Path]] = {}
        for target in self._batch_zip_queue:
            by_parent.setdefault(target.parent, []).append(target)
        self._batch_zip_queue.clear()
        batch = self.current_batch or "archive"
        for parent, items in by_parent.items():
            if not items:
                continue
            try:
                zip_name = parent / f"{batch}.zip"
                zip_path = zip_group(items, zip_name, level=level)
            except OSError:
                continue
            for item in items:
                try:
                    remove_source(item)
                    self.index.remove_by_path(str(item))
                except OSError:
                    pass
            try:
                size = zip_path.stat().st_size
            except OSError:
                size = 0
            ts = time.time()
            self.index.add_file(
                name=zip_path.name, path=str(zip_path), source_path="",
                category=self.settings.category_for_extension(".zip"),
                extension=".zip", size=size, added_ts=ts,
                year=datetime.fromtimestamp(ts).year,
                month=datetime.fromtimestamp(ts).month,
                kind="file",
            )

    def compression_summary(self, count: int) -> str:
        if not self._should_compress() or count <= 0:
            return ""
        mode = self.settings.compression_mode
        level = self.settings.compression_level
        from .compression import compression_level_label, compression_mode_label
        return (
            f"\n\nСжатие: {compression_mode_label(mode)}, "
            f"уровень — {compression_level_label(level)}."
        )

    def _record_move(
        self, src: str, dst: str, kind: str, ts: float,
        *, category: str, name: str,
    ) -> None:
        batch = self.current_batch or f"single-{time.time():.6f}"
        self.index.log_move(
            batch=batch, src=src, dst=dst, kind=kind, ts=time.time(),
            category=category,
            action=self.settings.storage_mode,
            name=name,
        )
        self._batch_count += 1

    def _file_time(self, path: Path) -> float:
        st = path.stat()
        src = self.settings.date_source
        if src == "modified":
            return st.st_mtime
        if src == "created":
            return st.st_ctime
        return min(st.st_ctime, st.st_mtime)

    @staticmethod
    def _folder_size(path: Path) -> int:
        total = 0
        try:
            for p in path.rglob("*"):
                if p.is_file():
                    try:
                        total += p.stat().st_size
                    except OSError:
                        pass
        except OSError:
            pass
        return total

    def _is_ready(self, path: Path) -> bool:
        if path.is_file():
            if path.suffix.lower() in SKIP_EXTENSIONS:
                return False
        try:
            age = time.time() - path.stat().st_mtime
        except OSError:
            return False
        return age >= self.settings.min_age_seconds

    def _is_inside_destination(self, path: Path) -> bool:
        try:
            dest = Path(self.settings.destination).resolve()
            rpath = path.resolve()
            return dest == rpath or dest in rpath.parents
        except OSError:
            return False

    def _is_inside_smart_library(self, path: Path) -> bool:
        root = self.settings.smart_folders_root.strip()
        if not root:
            return False
        try:
            lib = Path(root).resolve()
            rpath = path.resolve()
            return lib == rpath or lib in rpath.parents
        except OSError:
            return False

    def _is_protected(self, path: Path) -> bool:
        if self._is_excluded(path):
            return True
        try:
            rp = path.resolve()
        except OSError:
            return True
        if rp == APP_ROOT or APP_ROOT in rp.parents:
            return True
        try:
            app_data = APP_DIR.resolve()
            if rp == app_data or app_data in rp.parents:
                return True
        except OSError:
            pass
        for folder in self.settings.watched_folders:
            try:
                if rp == Path(folder).resolve():
                    return True
            except OSError:
                continue
        root = self.settings.smart_folders_root.strip()
        if root:
            try:
                if rp == Path(root).resolve():
                    return True
            except OSError:
                pass
        return False

    def _is_excluded(self, path: Path) -> bool:
        try:
            rp = str(path.resolve())
        except OSError:
            return False
        for raw in self.settings.excluded_paths:
            try:
                ex = str(Path(raw).resolve())
            except OSError:
                ex = raw
            if rp == ex:
                return True
        return False

    @staticmethod
    def _unique_target(target: Path) -> Path:
        if not target.exists():
            return target
        stem, suffix = target.stem, target.suffix
        if target.is_dir() or not suffix:
            stem, suffix = target.name, ""
        i = 1
        while True:
            candidate = target.with_name(f"{stem} ({i}){suffix}")
            if not candidate.exists():
                return candidate
            i += 1

    def _dest_dir(
        self, category: str, ts: float, extension: str = "", is_dir: bool = False,
    ) -> tuple[Path, int, int]:
        return dest_directory(
            archive_root=Path(self.settings.destination),
            sort_mode=self.settings.sort_mode,
            category=category,
            extension=extension,
            ts=ts,
            is_dir=is_dir,
        )

    def _transfer(self, src: Path, dst: Path) -> tuple[bool, str]:
        if self.settings.data.get("dry_run", False):
            return True, ""
        try:
            if self.settings.storage_mode == "copy":
                if src.is_dir():
                    shutil.copytree(str(src), str(dst))
                else:
                    shutil.copy2(str(src), str(dst))
            else:
                shutil.move(str(src), str(dst))
            return True, ""
        except OSError as e:
            return False, str(e)
        except shutil.Error as e:
            return False, str(e)

    def find_duplicates(self, paths: list[str | Path]) -> list[dict]:
        """Предупреждение: в архиве уже есть файл с таким именем в целевой папке."""
        conflicts: list[dict] = []
        seen_names: set[str] = set()
        for raw in paths:
            path = Path(raw)
            if not path.exists():
                continue
            if path.is_dir():
                if not self.settings.sort_folders:
                    continue
                category = FOLDER_CATEGORY
                ext = ""
                is_dir = True
            else:
                category = self.settings.category_for_extension(path.suffix.lower())
                ext = path.suffix.lower()
                is_dir = False
            ts = self._file_time(path)
            dest_dir, _, _ = self._dest_dir(category, ts, ext, is_dir=is_dir)
            target = dest_dir / path.name
            if target.exists() and path.name not in seen_names:
                seen_names.add(path.name)
                conflicts.append({
                    "path": str(path),
                    "name": path.name,
                    "existing": str(target),
                })
        return conflicts

    def sort_file(self, file_path: str | Path, result: SortResult | None = None) -> Path | None:
        path = Path(file_path)
        dry_run = bool(self.settings.data.get("dry_run", False))
        if not path.is_file():
            return None
        if not self._is_ready(path):
            return None
        if self._is_inside_destination(path) or self._is_protected(path):
            return None
        if self.settings.sort_mode == "smart_folders":
            return None

        ext = path.suffix.lower()
        category = self.settings.category_for_extension(ext)
        ts = self._file_time(path)
        dest_dir, year, month = self._dest_dir(category, ts, ext)
        target = self._unique_target(dest_dir / path.name)

        ok, err = self._transfer(path, target)
        if not ok:
            if result is not None:
                result.add_error(str(path), err or "не удалось переместить")
            return None

        if dry_run:
            return target

        final = self._compress_after_move(target)
        if final != target:
            target = final

        src_str = str(path)
        final_ext = target.suffix.lower()
        final_category = (
            self.settings.category_for_extension(final_ext)
            if final_ext else category
        )
        self.index.add_file(
            name=target.name, path=str(target), source_path=src_str,
            category=final_category, extension=final_ext or ext,
            size=target.stat().st_size,
            added_ts=ts, year=year, month=month, kind="file",
        )
        self._record_move(
            src_str, str(target), "file", ts,
            category=final_category, name=target.name,
        )
        return target

    def sort_directory(self, dir_path: str | Path, result: SortResult | None = None) -> Path | None:
        path = Path(dir_path)
        dry_run = bool(self.settings.data.get("dry_run", False))
        if not path.is_dir():
            return None
        if not self.settings.sort_folders:
            return None
        if not self._is_ready(path):
            return None
        if self._is_inside_destination(path) or self._is_protected(path):
            return None
        if self.settings.sort_mode == "smart_folders":
            return None

        ts = self._file_time(path)
        size = self._folder_size(path)
        dest_dir, year, month = self._dest_dir(FOLDER_CATEGORY, ts, is_dir=True)
        target = self._unique_target(dest_dir / path.name)

        ok, err = self._transfer(path, target)
        if not ok:
            if result is not None:
                result.add_error(str(path), err or "не удалось переместить")
            return None

        if dry_run:
            return target

        final = self._compress_after_move(target)
        if final != target:
            target = final
            size = target.stat().st_size if target.is_file() else self._folder_size(target)

        src_str = str(path)
        kind = "dir" if target.is_dir() else "file"
        ext = "" if target.is_dir() else target.suffix.lower()
        self.index.add_file(
            name=target.name, path=str(target), source_path=src_str,
            category=FOLDER_CATEGORY, extension=ext, size=size,
            added_ts=ts, year=year, month=month, kind=kind,
        )
        self._record_move(
            src_str, str(target), kind, ts,
            category=FOLDER_CATEGORY, name=target.name,
        )
        return target

    def sort_entry(self, entry_path: str | Path, result: SortResult | None = None) -> Path | None:
        path = Path(entry_path)
        if path.is_dir():
            return self.sort_directory(path, result)
        return self.sort_file(path, result)

    def sort_folder(self, folder: str | Path, result: SortResult | None = None) -> int:
        folder = Path(folder)
        if not folder.is_dir():
            return 0
        count = 0
        dest = Path(self.settings.destination).resolve()
        try:
            entries = list(folder.iterdir())
        except OSError:
            return 0
        for entry in entries:
            try:
                if entry.resolve() == dest:
                    continue
            except OSError:
                continue
            if self.sort_entry(entry, result):
                count += 1
        return count

    def build_smart_folder_plan(self, paths: list[str | Path]) -> tuple[list[MatchProposal], Path]:
        """Построить план умной раскладки по пользовательской библиотеке."""
        root = Path(self.settings.smart_folders_root.strip())
        if not root.is_dir():
            raise ValueError("Укажите существующую папку библиотеки в настройках «Мои папки».")
        file_paths = [
            p for p in paths
            if Path(p).is_file() and not self._is_protected(Path(p))
            and not self._is_inside_smart_library(Path(p))
        ]
        proposals, _profiles = build_match_plan(
            file_paths,
            root,
            threshold=self.settings.smart_folders_threshold,
            catchall_name=self.settings.smart_folders_catchall,
        )
        return proposals, root

    def apply_smart_folder_plan(
        self,
        proposals: list[MatchProposal],
        result: SortResult | None = None,
        *,
        on_progress=None,
        should_cancel=None,
    ) -> int:
        """Применить подтверждённый план умной раскладки."""
        moved = 0
        dry_run = bool(self.settings.data.get("dry_run", False))
        active = [
            p for p in proposals
            if p.action != "skip" and p.dest_folder is not None and p.source.is_file()
        ]
        total = len(active)
        for i, prop in enumerate(active, start=1):
            if should_cancel and should_cancel():
                break
            dest_dir = prop.dest_folder
            if dest_dir is None:
                continue
            if not dry_run:
                try:
                    dest_dir.mkdir(parents=True, exist_ok=True)
                except OSError as e:
                    if result is not None:
                        result.add_error(str(prop.source), str(e))
                    continue
            target = self._unique_target(dest_dir / prop.source.name)
            ok, err = self._transfer(prop.source, target)
            if not ok:
                if result is not None:
                    result.add_error(str(prop.source), err or "не удалось переместить")
                continue
            moved += 1
            if dry_run:
                if on_progress:
                    try:
                        on_progress(i, total, str(prop.source))
                    except Exception:
                        pass
                continue
            ts = self._file_time(target)
            ext = target.suffix.lower()
            category = prop.profile_name or self.settings.category_for_extension(ext)
            dt = datetime.fromtimestamp(ts)
            self.index.add_file(
                name=target.name,
                path=str(target),
                source_path=str(prop.source),
                category=category,
                extension=ext,
                size=target.stat().st_size,
                added_ts=ts,
                year=dt.year,
                month=dt.month,
                kind="file",
            )
            self._record_move(
                str(prop.source), str(target), "file", ts,
                category=category, name=target.name,
            )
            if on_progress:
                try:
                    on_progress(i, total, str(prop.source))
                except Exception:
                    pass
        return moved

    def apply_confirmed_smart_plan(
        self,
        proposals: list[MatchProposal],
        *,
        on_progress=None,
        should_cancel=None,
    ) -> SortResult:
        """Применить план после диалога подтверждения."""
        result = SortResult()
        prev_mode = self.settings.data.get("sort_mode")
        self.settings.data["sort_mode"] = "smart_folders"
        try:
            with self.batch_context("smart-folders"):
                result.moved = self.apply_smart_folder_plan(
                    proposals,
                    result,
                    on_progress=on_progress,
                    should_cancel=should_cancel,
                )
        finally:
            self.settings.data["sort_mode"] = prev_mode
        return result

    def list_watched_entries(self) -> list[dict]:
        """Верхнеуровневые элементы из отслеживаемых папок (для «Рабочего стола»)."""
        dest = Path(self.settings.destination).resolve()
        entries: list[dict] = []
        seen: set[str] = set()
        for folder in self.settings.watched_folders:
            try:
                fpath = Path(folder).resolve()
            except OSError:
                continue
            if fpath == dest or dest in fpath.parents:
                continue
            try:
                children = list(fpath.iterdir())
            except OSError:
                continue
            for entry in children:
                try:
                    if entry.resolve() == dest:
                        continue
                except OSError:
                    continue
                if self._is_protected(entry):
                    continue
                if self._is_inside_destination(entry):
                    continue
                try:
                    key = str(entry.resolve())
                except OSError:
                    continue
                if key in seen:
                    continue
                seen.add(key)
                is_dir = entry.is_dir()
                excluded = self._is_excluded(entry)
                if is_dir:
                    sortable = bool(
                        self.settings.sort_folders and self._is_ready(entry) and not excluded,
                    )
                else:
                    sortable = self._is_ready(entry) and not excluded
                try:
                    st = entry.stat()
                    mtime = st.st_mtime
                    size = self._folder_size(entry) if is_dir else st.st_size
                except OSError:
                    mtime = 0.0
                    size = 0
                category = (
                    FOLDER_CATEGORY if is_dir
                    else self.settings.category_for_extension(entry.suffix.lower())
                )
                entries.append({
                    "path": key,
                    "name": entry.name,
                    "is_dir": is_dir,
                    "sortable": sortable,
                    "excluded": excluded,
                    "folder": str(fpath),
                    "size": size,
                    "mtime": mtime,
                    "category": category,
                })
        entries.sort(key=lambda e: (e["folder"].lower(), e["name"].lower()))
        return entries

    @contextmanager
    def batch_context(self, prefix: str = "sort", *, blocking: bool = True):
        """Группировать несколько sort_entry в одну запись истории."""
        acquired = self._operation_lock.acquire(blocking=blocking)
        if not acquired:
            raise RuntimeError("Операция сортировки уже выполняется")
        batch = f"{prefix}-{datetime.now():%Y%m%d-%H%M%S}-{time.time():.0f}"
        self.current_batch = batch
        self._batch_count = 0
        self._batch_zip_queue = []
        dry_run = bool(self.settings.data.get("dry_run", False))
        if not dry_run:
            self.index.start_batch(
                batch=batch,
                sort_mode=self.settings.sort_mode,
                storage_mode=self.settings.storage_mode,
                ts=time.time(),
            )
        try:
            yield
        finally:
            try:
                self._finish_batch_zip()
                if dry_run:
                    self._batch_count = 0
                if not dry_run:
                    if self._batch_count > 0:
                        self.index.finish_batch(batch, self._batch_count)
                    else:
                        self.index.delete_batch(batch)
                self.current_batch = None
            finally:
                self._operation_lock.release()

    def sort_paths(
        self,
        paths: list[str | Path],
        *,
        on_progress=None,
        should_cancel=None,
    ) -> SortResult:
        """Сортировать только указанные пути (одна пакетная операция)."""
        result = SortResult()
        with self.batch_context("sort"):
            total = len(paths)
            for i, raw in enumerate(paths, start=1):
                if should_cancel and should_cancel():
                    break
                if self.sort_entry(raw, result):
                    result.moved += 1
                if on_progress:
                    try:
                        on_progress(i, total, str(raw))
                    except Exception:
                        pass
        return result

    def sort_all(self, *, on_progress=None, should_cancel=None, blocking: bool = True) -> SortResult:
        result = SortResult()
        entries: list[Path] = []
        dest = Path(self.settings.destination).resolve()
        for folder in self.settings.watched_folders:
            fpath = Path(folder).resolve()
            if fpath == dest or dest in fpath.parents:
                continue
            try:
                entries.extend([e for e in fpath.iterdir() if e.exists()])
            except OSError:
                continue
        with self.batch_context("sort", blocking=blocking):
            total = len(entries)
            done = 0
            for folder in self.settings.watched_folders:
                fpath = Path(folder).resolve()
                if fpath == dest or dest in fpath.parents:
                    continue
                try:
                    items = list(fpath.iterdir())
                except OSError:
                    continue
                for entry in items:
                    if should_cancel and should_cancel():
                        return result
                    try:
                        if entry.resolve() == dest:
                            done += 1
                            continue
                    except OSError:
                        done += 1
                        continue
                    if self.sort_entry(entry, result):
                        result.moved += 1
                    done += 1
                    if on_progress:
                        try:
                            on_progress(done, total, str(entry))
                        except Exception:
                            pass
        return result

    @staticmethod
    def _looks_temp_name(name: str) -> bool:
        low = name.lower()
        return (
            low.startswith("~$")
            or low.startswith("tmp")
            or low.endswith(".tmp")
            or low.endswith(".temp")
            or low.endswith(".log")
        )

    def build_smart_cleanup_plan(self, *, limit: int = 700) -> list[dict]:
        """Подобрать безопасные кандидаты для «Умной уборки»."""
        entries = self.list_watched_entries()
        duplicates: dict[tuple[str, int], list[dict]] = {}
        for e in entries:
            if e.get("is_dir"):
                continue
            if not e.get("sortable"):
                continue
            ext = Path(e["path"]).suffix.lower()
            if ext in _SMART_MEDIA_EXTS:
                key = (e.get("name", "").lower(), int(e.get("size") or 0))
                duplicates.setdefault(key, []).append(e)

        duplicate_paths: set[str] = set()
        for items in duplicates.values():
            if len(items) > 1:
                items = sorted(items, key=lambda x: x.get("mtime", 0), reverse=True)
                for dup in items[1:]:
                    duplicate_paths.add(dup["path"])

        out: list[dict] = []
        seen: set[str] = set()
        for e in entries:
            if len(out) >= limit:
                break
            path = e["path"]
            if path in seen:
                continue
            seen.add(path)
            if e.get("is_dir") or not e.get("sortable"):
                continue
            p = Path(path)
            ext = p.suffix.lower()
            reason = ""
            if ext in _SMART_INSTALLER_EXTS:
                reason = "Установщик/инсталлятор в загрузках"
            elif ext in _SMART_TEMP_EXTS or self._looks_temp_name(p.name):
                reason = "Временный или служебный файл"
            elif path in duplicate_paths:
                reason = "Похоже на дубликат медиа"
            if not reason:
                continue
            out.append({
                "path": path,
                "name": e.get("name", p.name),
                "reason": reason,
                "folder": e.get("folder", ""),
                "category": e.get("category", ""),
                "size": int(e.get("size") or 0),
            })
        return out

    def count_watched_protected(self) -> int:
        """Число элементов в отслеживаемых папках, недоступных для сортировки."""
        count = 0
        dest = Path(self.settings.destination).resolve()
        seen: set[str] = set()
        for folder in self.settings.watched_folders:
            try:
                fpath = Path(folder).resolve()
            except OSError:
                continue
            if fpath == dest or dest in fpath.parents:
                continue
            try:
                children = list(fpath.iterdir())
            except OSError:
                continue
            for entry in children:
                try:
                    key = str(entry.resolve())
                except OSError:
                    continue
                if key in seen:
                    continue
                seen.add(key)
                if self._is_protected(entry) or self._is_excluded(entry):
                    count += 1
        return count

    def undo_batch_detailed(self, batch: str) -> UndoBatchReport:
        report = UndoBatchReport()
        removed_ids: list[int] = []
        for mv in self.index.moves_in_batch(batch):
            dst = Path(mv["dst"])
            src = Path(mv["src"])
            action = mv["action"] if "action" in mv.keys() else "move"
            move_id = mv["id"]
            if not dst.exists():
                self.index.remove_by_path(str(dst))
                removed_ids.append(move_id)
                report.missing += 1
                report.details.append((str(dst), "Файл уже отсутствует в архиве"))
                continue
            try:
                if action == "copy":
                    if dst.is_dir():
                        shutil.rmtree(dst)
                    else:
                        dst.unlink()
                else:
                    src.parent.mkdir(parents=True, exist_ok=True)
                    target = src if not src.exists() else self._unique_target(src)
                    shutil.move(str(dst), str(target))
                self.index.remove_by_path(str(dst))
                removed_ids.append(move_id)
                report.restored += 1
                report.details.append((str(dst), "Восстановлено"))
            except (OSError, shutil.Error) as e:
                report.failed += 1
                report.details.append((str(dst), str(e)))
        if report.failed == 0:
            self.index.delete_batch(batch)
        else:
            self.index.delete_moves(removed_ids)
            self.index.set_batch_item_count(batch, self.index.moves_count(batch))
        return report

    def undo_batch(self, batch: str) -> tuple[int, int]:
        report = self.undo_batch_detailed(batch)
        return report.restored, report.failed

    def undo_last(self) -> tuple[int, int]:
        batch = self.index.last_batch()
        if not batch:
            return (0, 0)
        return self.undo_batch(batch)

    def undo_last_detailed(self) -> UndoBatchReport:
        batch = self.index.last_batch()
        if not batch:
            return UndoBatchReport()
        return self.undo_batch_detailed(batch)

    def undo_move(self, move_id: int) -> tuple[bool, str]:
        """Вернуть один файл из журнала на исходное место."""
        mv = self.index.get_move_by_id(move_id)
        if not mv:
            return False, "Запись не найдена"
        dst = Path(mv["dst"])
        src = Path(mv["src"])
        action = mv["action"] if "action" in mv.keys() else "move"
        if not dst.exists():
            self.index.remove_by_path(str(dst))
            self.index.delete_moves([move_id])
            return False, "Файл уже отсутствует в архиве"
        try:
            if action == "copy":
                if dst.is_dir():
                    shutil.rmtree(dst)
                else:
                    dst.unlink()
            else:
                src.parent.mkdir(parents=True, exist_ok=True)
                target = src if not src.exists() else self._unique_target(src)
                shutil.move(str(dst), str(target))
            self.index.remove_by_path(str(dst))
            self.index.delete_moves([move_id])
            batch = mv["batch"]
            remaining = self.index.moves_count(batch)
            if remaining == 0:
                self.index.delete_batch(batch)
            else:
                self.index.set_batch_item_count(batch, remaining)
            return True, ""
        except (OSError, shutil.Error) as e:
            return False, str(e)

    def reindex_destination(self) -> int:
        dest = Path(self.settings.destination)
        if not dest.is_dir():
            return 0
        count = 0
        file_paths: set[str] = set()
        sort_mode = self.settings.sort_mode
        cat_fn = self.settings.category_for_extension

        for entry in dest.rglob("*"):
            if not entry.is_file():
                continue
            rp = str(entry.resolve())
            file_paths.add(rp)
            ts = self._file_time(entry)
            category, year, month = infer_index_fields(
                dest, entry, sort_mode=sort_mode,
                category_for_extension=cat_fn, ts=ts,
            )
            self.index.add_file(
                name=entry.name, path=rp, source_path="",
                category=category, extension=entry.suffix.lower(),
                size=entry.stat().st_size, added_ts=ts,
                year=year, month=month, kind="file",
            )
            count += 1

        for entry in dest.rglob("*"):
            if not entry.is_dir() or entry == dest:
                continue
            try:
                kids = list(entry.iterdir())
            except OSError:
                continue
            if not kids or any(k.is_dir() for k in kids):
                continue
            if kids and all(k.is_file() and str(k.resolve()) in file_paths for k in kids):
                continue
            rp = str(entry.resolve())
            ts = self._file_time(entry)
            category, year, month = infer_index_fields(
                dest, entry, sort_mode=sort_mode,
                category_for_extension=cat_fn, ts=ts,
            )
            self.index.add_file(
                name=entry.name, path=rp, source_path="",
                category=category, extension="", size=self._folder_size(entry),
                added_ts=ts, year=year, month=month, kind="dir",
            )
            count += 1
        return count
