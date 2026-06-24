"""Индекс отсортированных файлов в SQLite — для быстрого поиска и фильтров."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from .config import DB_PATH


class FileIndex:
    """Простой потокобезопасный индекс перемещённых файлов."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self._lock = threading.Lock()
        # check_same_thread=False — обращаемся из GUI и из фонового потока
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    path TEXT NOT NULL UNIQUE,
                    source_path TEXT,
                    category TEXT NOT NULL,
                    extension TEXT,
                    size INTEGER,
                    added_ts REAL NOT NULL,
                    year INTEGER NOT NULL,
                    month INTEGER NOT NULL
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_category ON files(category)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_date ON files(year, month)"
            )
            # миграция: добавляем колонку kind ('file' | 'dir'), если её нет
            cols = {
                row["name"]
                for row in self._conn.execute("PRAGMA table_info(files)").fetchall()
            }
            if "kind" not in cols:
                self._conn.execute(
                    "ALTER TABLE files ADD COLUMN kind TEXT DEFAULT 'file'"
                )
            # журнал перемещений — нужен для отмены последней сортировки
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS moves (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    batch TEXT NOT NULL,
                    src TEXT NOT NULL,
                    dst TEXT NOT NULL,
                    kind TEXT DEFAULT 'file',
                    ts REAL NOT NULL
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_moves_batch ON moves(batch)"
            )
            self._conn.commit()

    def add_file(
        self,
        *,
        name: str,
        path: str,
        source_path: str,
        category: str,
        extension: str,
        size: int,
        added_ts: float,
        year: int,
        month: int,
        kind: str = "file",
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO files
                    (name, path, source_path, category, extension, size,
                     added_ts, year, month, kind)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    name=excluded.name,
                    source_path=excluded.source_path,
                    category=excluded.category,
                    extension=excluded.extension,
                    size=excluded.size,
                    added_ts=excluded.added_ts,
                    year=excluded.year,
                    month=excluded.month,
                    kind=excluded.kind
                """,
                (
                    name, path, source_path, category, extension, size,
                    added_ts, year, month, kind,
                ),
            )
            self._conn.commit()

    # ---- журнал перемещений (для отмены) ----

    def log_move(self, *, batch: str, src: str, dst: str, kind: str, ts: float) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO moves (batch, src, dst, kind, ts) VALUES (?, ?, ?, ?, ?)",
                (batch, src, dst, kind, ts),
            )
            self._conn.commit()

    def last_batch(self) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT batch FROM moves ORDER BY ts DESC, id DESC LIMIT 1"
            ).fetchone()
        return row["batch"] if row else None

    def moves_in_batch(self, batch: str) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(
                "SELECT * FROM moves WHERE batch = ? ORDER BY id DESC", (batch,)
            ).fetchall()

    def delete_batch(self, batch: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM moves WHERE batch = ?", (batch,))
            self._conn.commit()

    def remove_by_path(self, path: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM files WHERE path = ?", (path,))
            self._conn.commit()

    def remove_missing(self) -> int:
        """Удалить из индекса записи о файлах, которых уже нет на диске."""
        removed = 0
        with self._lock:
            rows = self._conn.execute("SELECT id, path FROM files").fetchall()
            for row in rows:
                if not Path(row["path"]).exists():
                    self._conn.execute("DELETE FROM files WHERE id=?", (row["id"],))
                    removed += 1
            self._conn.commit()
        return removed

    def query(
        self,
        *,
        category: str | None = None,
        year: int | None = None,
        month: int | None = None,
        search: str | None = None,
    ) -> list[sqlite3.Row]:
        sql = "SELECT * FROM files WHERE 1=1"
        params: list = []
        if category and category != "Все":
            sql += " AND category = ?"
            params.append(category)
        if year:
            sql += " AND year = ?"
            params.append(year)
        if month:
            sql += " AND month = ?"
            params.append(month)
        if search:
            sql += " AND name LIKE ?"
            params.append(f"%{search}%")
        sql += " ORDER BY added_ts DESC"
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def categories(self) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT DISTINCT category FROM files ORDER BY category"
            ).fetchall()
        return [r["category"] for r in rows]

    def years(self) -> list[int]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT DISTINCT year FROM files ORDER BY year DESC"
            ).fetchall()
        return [r["year"] for r in rows]

    def count(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) AS c FROM files").fetchone()["c"]

    def close(self) -> None:
        with self._lock:
            self._conn.close()
