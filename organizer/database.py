"""Индекс отсортированных файлов в SQLite — для быстрого поиска и фильтров."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from .config import DB_PATH


class FileIndex:
    """Потокобезопасный индекс перемещённых файлов и журнал истории."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self._lock = threading.Lock()
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
            cols = {
                row["name"]
                for row in self._conn.execute("PRAGMA table_info(files)").fetchall()
            }
            if "kind" not in cols:
                self._conn.execute(
                    "ALTER TABLE files ADD COLUMN kind TEXT DEFAULT 'file'"
                )

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

            move_cols = {
                row["name"]
                for row in self._conn.execute("PRAGMA table_info(moves)").fetchall()
            }
            for col, default in (
                ("category", "''"),
                ("action", "'move'"),
                ("name", "''"),
            ):
                if col not in move_cols:
                    self._conn.execute(
                        f"ALTER TABLE moves ADD COLUMN {col} TEXT DEFAULT {default}"
                    )

            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS batches (
                    batch TEXT PRIMARY KEY,
                    ts REAL NOT NULL,
                    sort_mode TEXT,
                    storage_mode TEXT,
                    item_count INTEGER DEFAULT 0
                )
                """
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

    # ---- журнал перемещений ----

    def start_batch(
        self, *, batch: str, sort_mode: str, storage_mode: str, ts: float,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO batches (batch, ts, sort_mode, storage_mode, item_count)
                VALUES (?, ?, ?, ?, 0)
                ON CONFLICT(batch) DO UPDATE SET
                    ts=excluded.ts,
                    sort_mode=excluded.sort_mode,
                    storage_mode=excluded.storage_mode
                """,
                (batch, ts, sort_mode, storage_mode),
            )
            self._conn.commit()

    def finish_batch(self, batch: str, item_count: int) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE batches SET item_count = ? WHERE batch = ?",
                (item_count, batch),
            )
            self._conn.commit()

    def log_move(
        self,
        *,
        batch: str,
        src: str,
        dst: str,
        kind: str,
        ts: float,
        category: str = "",
        action: str = "move",
        name: str = "",
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO moves
                    (batch, src, dst, kind, ts, category, action, name)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (batch, src, dst, kind, ts, category, action, name or Path(dst).name),
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
            self._conn.execute("DELETE FROM batches WHERE batch = ?", (batch,))
            self._conn.commit()

    def delete_moves(self, move_ids: list[int]) -> None:
        if not move_ids:
            return
        with self._lock:
            self._conn.executemany("DELETE FROM moves WHERE id = ?", [(i,) for i in move_ids])
            self._conn.commit()

    def moves_count(self, batch: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS c FROM moves WHERE batch = ?", (batch,)
            ).fetchone()
        return row["c"] if row else 0

    def set_batch_item_count(self, batch: str, count: int) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE batches SET item_count = ? WHERE batch = ?",
                (count, batch),
            )
            self._conn.commit()

    def get_by_id(self, file_id: int) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(
                "SELECT * FROM files WHERE id = ?", (file_id,)
            ).fetchone()

    def query_history(
        self,
        *,
        batch: str | None = None,
        search: str | None = None,
        limit: int = 500,
    ) -> list[sqlite3.Row]:
        sql = """
            SELECT m.*, b.sort_mode, b.storage_mode
            FROM moves m
            LEFT JOIN batches b ON b.batch = m.batch
            WHERE 1=1
        """
        params: list = []
        if batch and batch != "Все операции":
            sql += " AND m.batch = ?"
            params.append(batch)
        if search:
            sql += " AND (m.name LIKE ? OR m.src LIKE ? OR m.dst LIKE ?)"
            like = f"%{search}%"
            params.extend([like, like, like])
        sql += " ORDER BY m.ts DESC, m.id DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def history_batches(self) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(
                """
                SELECT b.*, COUNT(m.id) AS moves_count
                FROM batches b
                LEFT JOIN moves m ON m.batch = b.batch
                GROUP BY b.batch
                ORDER BY b.ts DESC
                LIMIT 200
                """
            ).fetchall()

    def history_count(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) AS c FROM moves").fetchone()["c"]

    def remove_by_path(self, path: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM files WHERE path = ?", (path,))
            self._conn.commit()

    def remove_missing(self) -> int:
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
