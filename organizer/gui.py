"""Менеджер файлов: фильтр по категории и дате, поиск, открытие файлов."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
import shutil
from tkinter import (
    BOTH, END, LEFT, RIGHT, X, Y, Frame, Label, StringVar, Tk, Toplevel,
    Text, filedialog, messagebox,
)
from tkinter import ttk

from .classify import classify
from .config import OTHER_CATEGORY, Settings
from .database import FileIndex
from .layouts import DATE_SOURCES, SORT_MODES, STORAGE_MODES, sort_mode_label, storage_mode_label
from .preview import get_text_preview
from .scanner import Scanner, fixed_drives
from .sorter import MONTHS_RU, Sorter
from . import theme
from .thumbs import IMAGE_EXTS, VIDEO_EXTS, get_thumbnail
from .watcher import FolderWatcher

try:
    from PIL import ImageTk  # вывод миниатюр в Tkinter
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False

try:
    from send2trash import send2trash  # удаление в корзину
    _HAS_TRASH = True
except ImportError:
    _HAS_TRASH = False

# что считаем медиа для предпросмотра (фото + видео)
PREVIEW_EXTS = IMAGE_EXTS | VIDEO_EXTS

MONTH_NAMES = {0: "Все месяцы", **{k: v.split("-")[1] for k, v in MONTHS_RU.items()}}


def human_size(num: int) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if num < 1024:
            return f"{num:.0f} {unit}" if unit == "Б" else f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} ПБ"


def open_path(path: str) -> None:
    """Открыть файл в стандартной программе (кроссплатформенно)."""
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except OSError as e:
        messagebox.showerror("Ошибка", f"Не удалось открыть файл:\n{e}")


def reveal_in_explorer(path: str) -> None:
    """Открыть папку с файлом и выделить его."""
    p = Path(path)
    try:
        if sys.platform.startswith("win"):
            subprocess.Popen(["explorer", "/select,", str(p)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p.parent)])
    except OSError as e:
        messagebox.showerror("Ошибка", f"Не удалось открыть папку:\n{e}")


class App(Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("FileOrganizer — умная сортировка файлов")
        self.geometry("1140x700")
        self.minsize(900, 520)

        theme.apply(self)

        self.settings = Settings()
        self.index = FileIndex()
        self.sorter = Sorter(self.settings, self.index)
        self.watcher = FolderWatcher(self.sorter, on_sorted=self._on_background_sorted)

        self._build_header()
        self._build_ui()
        self._refresh_filters()
        self._reload_table()
        self._reload_history()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_header(self) -> None:
        hdr = Frame(self, bg=theme.HEADER, height=56)
        hdr.pack(side="top", fill=X)
        hdr.pack_propagate(False)
        inner = Frame(hdr, bg=theme.HEADER)
        inner.pack(fill=BOTH, expand=True, padx=16, pady=8)
        Label(
            inner, text="FileOrganizer", bg=theme.HEADER, fg=theme.HEADER_FG,
            font=("Segoe UI", 16, "bold"),
        ).pack(side=LEFT)
        self.mode_info_var = StringVar()
        self._update_mode_banner()
        Label(
            inner, textvariable=self.mode_info_var, bg=theme.HEADER, fg="#93c5fd",
            font=("Segoe UI", 9),
        ).pack(side=LEFT, padx=(16, 0))

    def _update_mode_banner(self) -> None:
        sm = sort_mode_label(self.settings.sort_mode)
        st = storage_mode_label(self.settings.storage_mode)
        self.mode_info_var.set(f"  |  {sm}  |  {st}")

    # ---------- построение интерфейса ----------

    def _build_ui(self) -> None:
        style = ttk.Style(self)
        style.configure("Treeview", rowheight=30, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))

        self.status_var = StringVar(value="Готово")
        status = Label(
            self, textvariable=self.status_var, anchor="w", padx=12,
            pady=6, bg=theme.SIDEBAR, fg=theme.TEXT_MUTED,
        )
        status.pack(side="bottom", fill=X)

        nb = ttk.Notebook(self)
        nb.pack(side="top", fill=BOTH, expand=True, padx=10, pady=(6, 10))
        tab_archive = Frame(nb, bg=theme.BG)
        tab_history = Frame(nb, bg=theme.BG)
        tab_pc = Frame(nb, bg=theme.BG)
        nb.add(tab_archive, text="  Архив  ")
        nb.add(tab_history, text="  История  ")
        nb.add(tab_pc, text="  Поиск по ПК  ")

        self._build_archive_tab(tab_archive)
        self._build_history_tab(tab_history)
        self._build_pc_tab(tab_pc)

    def _build_archive_tab(self, root) -> None:
        toolbar = Frame(root, padx=4, pady=8, bg=theme.BG)
        toolbar.pack(side="top", fill=X)

        ttk.Button(toolbar, text="Сортировать сейчас", style="Accent.TButton",
                   command=self._sort_now).pack(side=LEFT)
        ttk.Button(toolbar, text="Отменить последнюю", command=self._undo_last).pack(side=LEFT, padx=(8, 0))
        ttk.Button(toolbar, text="Обновить индекс", command=self._reindex).pack(side=LEFT, padx=(8, 0))

        self.bg_var = StringVar(value="Фон: выкл")
        self.bg_btn = ttk.Button(toolbar, textvariable=self.bg_var, command=self._toggle_watcher)
        self.bg_btn.pack(side=LEFT, padx=(8, 0))

        ttk.Button(toolbar, text="Настройки сортировки", command=self._open_settings).pack(side=LEFT, padx=(8, 0))

        Label(toolbar, text="Поиск:", bg=theme.BG).pack(side=LEFT, padx=(20, 4))
        self.search_var = StringVar()
        self.search_var.trace_add("write", lambda *_: self._reload_table())
        ttk.Entry(toolbar, textvariable=self.search_var, width=28).pack(side=LEFT)

        body = Frame(root, bg=theme.BG)
        body.pack(side="top", fill=BOTH, expand=True, padx=4, pady=(0, 4))

        sidebar = Frame(body, width=220, bg=theme.SIDEBAR, padx=10, pady=10)
        sidebar.pack(side=LEFT, fill=Y, padx=(0, 8))
        sidebar.pack_propagate(False)

        Label(sidebar, text="Фильтры", font=("Segoe UI", 11, "bold"),
              bg=theme.SIDEBAR).pack(anchor="w", pady=(0, 8))
        Label(sidebar, text="Категория", font=("Segoe UI", 9, "bold"),
              bg=theme.SIDEBAR, fg=theme.TEXT_MUTED).pack(anchor="w")
        self.category_var = StringVar(value="Все")
        self.category_box = ttk.Combobox(sidebar, textvariable=self.category_var, state="readonly")
        self.category_box.pack(fill=X, pady=(2, 12))
        self.category_box.bind("<<ComboboxSelected>>", lambda *_: self._reload_table())

        Label(sidebar, text="Год", font=("Segoe UI", 9, "bold"),
              bg=theme.SIDEBAR, fg=theme.TEXT_MUTED).pack(anchor="w")
        self.year_var = StringVar(value="Все годы")
        self.year_box = ttk.Combobox(sidebar, textvariable=self.year_var, state="readonly")
        self.year_box.pack(fill=X, pady=(2, 12))
        self.year_box.bind("<<ComboboxSelected>>", lambda *_: self._reload_table())

        Label(sidebar, text="Месяц", font=("Segoe UI", 9, "bold"),
              bg=theme.SIDEBAR, fg=theme.TEXT_MUTED).pack(anchor="w")
        self.month_var = StringVar(value="Все месяцы")
        self.month_box = ttk.Combobox(
            sidebar, textvariable=self.month_var, state="readonly",
            values=list(MONTH_NAMES.values()),
        )
        self.month_box.current(0)
        self.month_box.pack(fill=X, pady=(2, 12))
        self.month_box.bind("<<ComboboxSelected>>", lambda *_: self._reload_table())

        ttk.Button(sidebar, text="Сбросить фильтры", command=self._reset_filters).pack(fill=X, pady=(4, 0))

        # Таблица файлов
        table_frame = Frame(body, bg=theme.CARD, highlightbackground=theme.BORDER, highlightthickness=1)
        table_frame.pack(side=LEFT, fill=BOTH, expand=True)

        columns = ("name", "category", "date", "size")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")
        self.tree.heading("name", text="Имя файла")
        self.tree.heading("category", text="Категория")
        self.tree.heading("date", text="Дата загрузки")
        self.tree.heading("size", text="Размер")
        self.tree.column("name", width=420, anchor="w")
        self.tree.column("category", width=130, anchor="w")
        self.tree.column("date", width=150, anchor="center")
        self.tree.column("size", width=90, anchor="e")

        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side=RIGHT, fill=Y)
        self.tree.pack(side=LEFT, fill=BOTH, expand=True)

        self.tree.bind("<Double-1>", self._open_selected)
        self.tree.bind("<Button-3>", self._show_context_menu)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        # Панель предпросмотра справа
        preview = Frame(body, width=300, bg=theme.CARD, padx=10, pady=10,
                        highlightbackground=theme.BORDER, highlightthickness=1)
        preview.pack(side=RIGHT, fill=Y, padx=(8, 0))
        preview.pack_propagate(False)
        Label(preview, text="Предпросмотр", font=("Segoe UI", 10, "bold"),
              bg=theme.CARD).pack(anchor="w")
        img_box = Frame(preview, height=280, bg=theme.PREVIEW_BG)
        img_box.pack(fill=X, pady=(6, 8))
        img_box.pack_propagate(False)
        self.preview_img_label = Label(img_box, text="(выберите файл)", anchor="center",
                                       bg=theme.PREVIEW_BG, fg=theme.PREVIEW_FG)
        self.preview_img_label.pack(fill=BOTH, expand=True)
        self.preview_info = StringVar(value="")
        Label(preview, textvariable=self.preview_info, justify="left", anchor="nw",
              wraplength=280, bg=theme.CARD, fg=theme.TEXT).pack(fill=BOTH, expand=True, anchor="nw")
        ttk.Button(preview, text="Открыть файл", command=self._open_selected).pack(fill=X, pady=(4, 2))
        ttk.Button(preview, text="Показать в папке", command=self._reveal_selected).pack(fill=X)
        self._preview_photo = None  # ссылка, чтобы картинку не съел сборщик мусора

        from tkinter import Menu
        self.ctx = Menu(self, tearoff=0)
        self.ctx.add_command(label="Открыть файл", command=self._open_selected)
        self.ctx.add_command(label="Показать в папке", command=self._reveal_selected)

    # ---------- вкладка «история» ----------

    def _build_history_tab(self, root) -> None:
        top = Frame(root, bg=theme.BG, padx=4, pady=8)
        top.pack(side="top", fill=X)

        Label(top, text="Операция:", bg=theme.BG).pack(side=LEFT)
        self.hist_batch_var = StringVar(value="Все операции")
        self.hist_batch_box = ttk.Combobox(
            top, textvariable=self.hist_batch_var, state="readonly", width=36,
        )
        self.hist_batch_box.pack(side=LEFT, padx=(6, 12))
        self.hist_batch_box.bind("<<ComboboxSelected>>", lambda *_: self._reload_history())

        Label(top, text="Поиск:", bg=theme.BG).pack(side=LEFT)
        self.hist_search_var = StringVar()
        self.hist_search_var.trace_add("write", lambda *_: self._reload_history())
        ttk.Entry(top, textvariable=self.hist_search_var, width=24).pack(side=LEFT, padx=(6, 12))

        ttk.Button(top, text="Обновить", command=self._reload_history).pack(side=LEFT)
        ttk.Button(top, text="Отменить выбранную операцию",
                   command=self._undo_selected_batch).pack(side=LEFT, padx=(8, 0))

        body = Frame(root, bg=theme.BG)
        body.pack(side="top", fill=BOTH, expand=True, padx=4, pady=(0, 4))

        table_frame = Frame(body, bg=theme.CARD, highlightbackground=theme.BORDER, highlightthickness=1)
        table_frame.pack(side=LEFT, fill=BOTH, expand=True)

        cols = ("when", "name", "action", "category", "from", "to")
        self.hist_tree = ttk.Treeview(table_frame, columns=cols, show="headings", selectmode="browse")
        self.hist_tree.heading("when", text="Когда")
        self.hist_tree.heading("name", text="Имя")
        self.hist_tree.heading("action", text="Действие")
        self.hist_tree.heading("category", text="Категория")
        self.hist_tree.heading("from", text="Откуда")
        self.hist_tree.heading("to", text="Куда")
        self.hist_tree.column("when", width=130, anchor="center")
        self.hist_tree.column("name", width=180, anchor="w")
        self.hist_tree.column("action", width=90, anchor="center")
        self.hist_tree.column("category", width=100, anchor="w")
        self.hist_tree.column("from", width=240, anchor="w")
        self.hist_tree.column("to", width=240, anchor="w")
        self.hist_tree.tag_configure("move", background=theme.HISTORY_MOVE)
        self.hist_tree.tag_configure("copy", background=theme.HISTORY_COPY)

        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.hist_tree.yview)
        self.hist_tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side=RIGHT, fill=Y)
        self.hist_tree.pack(side=LEFT, fill=BOTH, expand=True)
        self.hist_tree.bind("<Double-1>", self._hist_reveal_dst)
        self.hist_tree.bind("<<TreeviewSelect>>", self._hist_on_select)

        side = Frame(body, width=280, bg=theme.CARD, padx=12, pady=12,
                     highlightbackground=theme.BORDER, highlightthickness=1)
        side.pack(side=RIGHT, fill=Y, padx=(8, 0))
        side.pack_propagate(False)
        Label(side, text="Детали операции", font=("Segoe UI", 10, "bold"),
              bg=theme.CARD).pack(anchor="w")
        self.hist_detail = StringVar(value="Выберите запись в журнале")
        Label(side, textvariable=self.hist_detail, justify="left", anchor="nw",
              wraplength=250, bg=theme.CARD, fg=theme.TEXT).pack(fill=BOTH, expand=True, pady=8)
        ttk.Button(side, text="Показать в папке (куда)", command=self._hist_reveal_dst).pack(fill=X, pady=2)
        ttk.Button(side, text="Показать исходную папку", command=self._hist_reveal_src).pack(fill=X, pady=2)

        self._hist_rows: dict[str, dict] = {}

    def _refresh_history_batches(self) -> None:
        batches = self.index.history_batches()
        labels = ["Все операции"]
        self._batch_id_map: dict[str, str] = {}
        for b in batches:
            dt = datetime.fromtimestamp(b["ts"])
            sm = sort_mode_label(b["sort_mode"] or "")
            cnt = b["moves_count"] or b["item_count"] or 0
            label = f"{dt:%d.%m.%Y %H:%M} — {cnt} шт. ({sm})"
            labels.append(label)
            self._batch_id_map[label] = b["batch"]
        self.hist_batch_box["values"] = labels
        if self.hist_batch_var.get() not in labels:
            self.hist_batch_var.set("Все операции")

    def _reload_history(self) -> None:
        self._refresh_history_batches()
        batch_label = self.hist_batch_var.get()
        batch = None
        if batch_label in getattr(self, "_batch_id_map", {}):
            batch = self._batch_id_map[batch_label]
        search = self.hist_search_var.get().strip() or None
        rows = self.index.query_history(batch=batch, search=search, limit=1000)
        self.hist_tree.delete(*self.hist_tree.get_children())
        self._hist_rows.clear()
        for r in rows:
            dt = datetime.fromtimestamp(r["ts"])
            action = r["action"] if "action" in r.keys() else "move"
            action_txt = "Копия" if action == "copy" else "Перенос"
            iid = str(r["id"])
            self._hist_rows[iid] = {k: r[k] for k in r.keys()}
            tags = ("copy",) if action == "copy" else ("move",)
            name = r["name"] if "name" in r.keys() and r["name"] else Path(r["dst"]).name
            cat = r["category"] if "category" in r.keys() else ""
            self.hist_tree.insert(
                "", END, iid=iid, tags=tags,
                values=(
                    dt.strftime("%d.%m.%Y %H:%M"),
                    name, action_txt, cat, r["src"], r["dst"],
                ),
            )

    def _hist_selected(self) -> dict | None:
        sel = self.hist_tree.selection()
        if not sel:
            return None
        return self._hist_rows.get(sel[0])

    def _hist_on_select(self, *_):
        row = self._hist_selected()
        if not row:
            return
        dt = datetime.fromtimestamp(row["ts"])
        sm = sort_mode_label(row["sort_mode"]) if row.get("sort_mode") else "—"
        st = storage_mode_label(row["storage_mode"]) if row.get("storage_mode") else "—"
        action = "Копирование" if row.get("action") == "copy" else "Перенос"
        self.hist_detail.set(
            f"Когда: {dt:%d.%m.%Y %H:%M:%S}\n"
            f"Действие: {action}\n"
            f"Режим: {sm}\n"
            f"Хранение: {st}\n"
            f"Категория: {row.get('category', '')}\n"
            f"Пакет: {row['batch']}\n\n"
            f"Откуда:\n{row['src']}\n\n"
            f"Куда:\n{row['dst']}"
        )

    def _hist_reveal_dst(self, *_):
        row = self._hist_selected()
        if row and Path(row["dst"]).exists():
            reveal_in_explorer(row["dst"])
        elif row:
            messagebox.showinfo("Нет файла", "Файл уже отсутствует по этому пути.")

    def _hist_reveal_src(self, *_):
        row = self._hist_selected()
        if not row:
            return
        src = Path(row["src"])
        if src.exists():
            reveal_in_explorer(str(src))
        else:
            parent = src.parent
            if parent.exists():
                reveal_in_explorer(str(parent))
            else:
                messagebox.showinfo("Нет папки", "Исходная папка недоступна.")

    def _undo_selected_batch(self):
        batch_label = self.hist_batch_var.get()
        if batch_label == "Все операции" or batch_label not in getattr(self, "_batch_id_map", {}):
            messagebox.showinfo("Выберите операцию", "Выберите конкретную операцию в списке сверху.")
            return
        batch = self._batch_id_map[batch_label]
        if not messagebox.askyesno("Отмена", f"Отменить операцию?\n{batch_label}"):
            return
        self.status_var.set("Отменяю операцию...")

        def work():
            ok, fail = self.sorter.undo_batch(batch)
            self.after(0, lambda: self._after_undo(ok, fail))

        threading.Thread(target=work, daemon=True).start()

    # ---------- вкладка «весь компьютер» ----------

    def _build_pc_tab(self, root) -> None:
        bar = Frame(root, padx=8, pady=8)
        bar.pack(side="top", fill=X)

        Label(bar, text="Категория:").pack(side=LEFT)
        self.pc_category_var = StringVar(value="Документы")
        cats = list(self.settings.categories.keys()) + [OTHER_CATEGORY, "Все файлы"]
        self.pc_category_box = ttk.Combobox(
            bar, textvariable=self.pc_category_var, state="readonly",
            values=cats, width=16,
        )
        self.pc_category_box.pack(side=LEFT, padx=(4, 10))

        Label(bar, text="Только расширения (через запятую, напр. .docx,.doc):").pack(side=LEFT)
        self.pc_ext_var = StringVar()
        ttk.Entry(bar, textvariable=self.pc_ext_var, width=20).pack(side=LEFT, padx=(4, 10))

        self.pc_scan_btn = ttk.Button(bar, text="Искать по ПК", command=self._pc_start_scan)
        self.pc_scan_btn.pack(side=LEFT)
        self.pc_stop_btn = ttk.Button(bar, text="Стоп", command=self._pc_stop_scan, state="disabled")
        self.pc_stop_btn.pack(side=LEFT, padx=(6, 0))

        bar2 = Frame(root, padx=8)
        bar2.pack(side="top", fill=X)
        Label(bar2, text="Фильтр по имени:").pack(side=LEFT)
        self.pc_filter_var = StringVar()
        self.pc_filter_var.trace_add("write", lambda *_: self._pc_apply_filter())
        ttk.Entry(bar2, textvariable=self.pc_filter_var, width=24).pack(side=LEFT, padx=(4, 10))

        self.pc_only_cand_var = StringVar(value="off")
        ttk.Checkbutton(
            bar2, text="Только кандидаты на удаление", variable=self.pc_only_cand_var,
            onvalue="on", offvalue="off", command=self._pc_apply_filter,
        ).pack(side=LEFT)
        ttk.Button(bar2, text="Выделить кандидатов", command=self._pc_select_candidates).pack(side=LEFT, padx=(8, 0))

        self.pc_progress_var = StringVar(value="")
        Label(bar2, textvariable=self.pc_progress_var, fg="#1565c0").pack(side=LEFT, padx=(12, 0))

        body = Frame(root)
        body.pack(side="top", fill=BOTH, expand=True, padx=8, pady=8)

        table_frame = Frame(body)
        table_frame.pack(side=LEFT, fill=BOTH, expand=True)
        columns = ("name", "folder", "size", "date", "advice")
        self.pc_tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="extended")
        self.pc_tree.heading("name", text="Имя файла")
        self.pc_tree.heading("folder", text="Папка")
        self.pc_tree.heading("size", text="Размер")
        self.pc_tree.heading("date", text="Изменён")
        self.pc_tree.heading("advice", text="Рекомендация")
        self.pc_tree.column("name", width=240, anchor="w")
        self.pc_tree.column("folder", width=250, anchor="w")
        self.pc_tree.column("size", width=75, anchor="e")
        self.pc_tree.column("date", width=120, anchor="center")
        self.pc_tree.column("advice", width=180, anchor="w")
        self.pc_tree.tag_configure("candidate", background="#ffdede", foreground="#a30000")
        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.pc_tree.yview)
        self.pc_tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side=RIGHT, fill=Y)
        self.pc_tree.pack(side=LEFT, fill=BOTH, expand=True)
        self.pc_tree.bind("<Double-1>", self._pc_open)
        self.pc_tree.bind("<<TreeviewSelect>>", self._pc_on_select)

        # правая панель: предпросмотр + действия
        side = Frame(body, width=320)
        side.pack(side=RIGHT, fill=Y, padx=(8, 0))
        side.pack_propagate(False)
        Label(side, text="Предпросмотр", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        pc_img_box = Frame(side, height=300, bg="#2b2b2b", relief="groove", bd=1)
        pc_img_box.pack(fill=X, pady=(4, 6))
        pc_img_box.pack_propagate(False)
        self.pc_img_label = Label(pc_img_box, text="(выберите файл)", anchor="center",
                                  bg="#2b2b2b", fg="#dddddd")
        self.pc_img_label.pack(fill=BOTH, expand=True)
        text_frame = Frame(side)
        text_frame.pack(fill=BOTH, expand=True)
        self.pc_text = Text(text_frame, wrap="word", height=8, font=("Consolas", 9))
        tvsb = ttk.Scrollbar(text_frame, orient="vertical", command=self.pc_text.yview)
        self.pc_text.configure(yscrollcommand=tvsb.set, state="disabled")
        tvsb.pack(side=RIGHT, fill=Y)
        self.pc_text.pack(side=LEFT, fill=BOTH, expand=True)

        actions = Frame(side)
        actions.pack(fill=X, pady=(8, 0))
        ttk.Button(actions, text="Открыть", command=self._pc_open).pack(fill=X, pady=1)
        ttk.Button(actions, text="Открыть папку с файлом", command=self._pc_reveal).pack(fill=X, pady=1)
        ttk.Button(actions, text="Копировать в...", command=self._pc_copy).pack(fill=X, pady=1)
        ttk.Button(actions, text="Переместить в...", command=self._pc_move).pack(fill=X, pady=1)
        ttk.Button(actions, text="Удалить выбранные", command=self._pc_delete).pack(fill=X, pady=1)
        Label(
            side, justify="left", wraplength=300, fg="#555",
            text=("Подсказка: красным подсвечены файлы, которые, скорее всего, "
                  "можно удалить (личное/мусор, не учёба/работа).\n"
                  "Несколько файлов: Ctrl+клик или Shift+клик, либо кнопка "
                  "«Выделить кандидатов»."),
        ).pack(fill=X, pady=(8, 0))

        self._pc_photo = None
        self._pc_results: list[dict] = []
        self._pc_scanner = Scanner()
        self._pc_pending: list[dict] = []
        self._pc_scan_thread = None

    # ---------- данные / фильтры ----------

    def _refresh_filters(self) -> None:
        cats = ["Все"] + self.index.categories()
        self.category_box["values"] = cats
        if self.category_var.get() not in cats:
            self.category_var.set("Все")

        years = ["Все годы"] + [str(y) for y in self.index.years()]
        self.year_box["values"] = years
        if self.year_var.get() not in years:
            self.year_var.set("Все годы")

    def _reset_filters(self) -> None:
        self.category_var.set("Все")
        self.year_var.set("Все годы")
        self.month_var.set("Все месяцы")
        self.search_var.set("")
        self._reload_table()

    def _reload_table(self) -> None:
        category = self.category_var.get()
        year = None
        if self.year_var.get() not in ("Все годы", ""):
            year = int(self.year_var.get())
        month = None
        month_label = self.month_var.get()
        for num, name in MONTH_NAMES.items():
            if name == month_label and num != 0:
                month = num
                break
        search = self.search_var.get().strip() or None

        rows = self.index.query(category=category, year=year, month=month, search=search)

        self.tree.delete(*self.tree.get_children())
        total_size = 0
        for r in rows:
            dt = datetime.fromtimestamp(r["added_ts"])
            is_dir = (r["kind"] if "kind" in r.keys() else "file") == "dir"
            display_name = ("[Папка] " + r["name"]) if is_dir else r["name"]
            self.tree.insert(
                "", END, iid=str(r["id"]),
                values=(
                    display_name, r["category"], dt.strftime("%d.%m.%Y %H:%M"),
                    human_size(r["size"] or 0),
                ),
            )
            total_size += r["size"] or 0
        self.status_var.set(
            f"Показано: {len(rows)} файлов · {human_size(total_size)} · "
            f"всего в индексе: {self.index.count()}"
        )

    def _selected_path(self) -> str | None:
        sel = self.tree.selection()
        if not sel:
            return None
        rows = self.index.query()
        for r in rows:
            if str(r["id"]) == sel[0]:
                return r["path"]
        return None

    def _selected_row(self):
        sel = self.tree.selection()
        if not sel:
            return None
        for r in self.index.query():
            if str(r["id"]) == sel[0]:
                return r
        return None

    def _on_select(self, *_):
        row = self._selected_row()
        if row is None:
            return
        path = Path(row["path"])
        kind = row["kind"] if "kind" in row.keys() else "file"
        dt = datetime.fromtimestamp(row["added_ts"])
        info = (
            f"Имя: {row['name']}\n"
            f"Категория: {row['category']}\n"
            f"Тип: {'Папка' if kind == 'dir' else (row['extension'] or 'файл')}\n"
            f"Дата: {dt.strftime('%d.%m.%Y %H:%M')}\n"
            f"Размер: {human_size(row['size'] or 0)}\n\n"
            f"Путь:\n{row['path']}"
        )
        self.preview_info.set(info)
        self._show_preview(path, kind)

    def _show_preview(self, path: Path, kind: str):
        self._preview_photo = None
        ext = path.suffix.lower()
        if (_HAS_PIL and kind == "file" and ext in PREVIEW_EXTS and path.exists()):
            img = get_thumbnail(path, max_size=(300, 290))
            if img is not None:
                self._preview_photo = ImageTk.PhotoImage(img)
                self.preview_img_label.configure(image=self._preview_photo, text="")
                return
        label = "Папка" if kind == "dir" else "Нет предпросмотра"
        self.preview_img_label.configure(image="", text=label)

    # ---------- действия ----------

    def _open_selected(self, *_):
        path = self._selected_path()
        if not path:
            return
        if not Path(path).exists():
            messagebox.showwarning("Файл не найден", "Файл был перемещён или удалён.")
            self._reindex()
            return
        open_path(path)

    def _reveal_selected(self, *_):
        path = self._selected_path()
        if path:
            reveal_in_explorer(path)

    def _show_context_menu(self, event):
        row = self.tree.identify_row(event.y)
        if row:
            self.tree.selection_set(row)
            self.ctx.tk_popup(event.x_root, event.y_root)

    def _sort_now(self):
        self.status_var.set("Сортирую...")
        self.update_idletasks()

        def work():
            moved = self.sorter.sort_all()
            self.after(0, lambda: self._after_sort(moved))

        threading.Thread(target=work, daemon=True).start()

    def _after_sort(self, moved: int):
        self._update_mode_banner()
        self._refresh_filters()
        self._reload_table()
        self._reload_history()
        messagebox.showinfo("Готово", f"Обработано файлов: {moved}")

    def _undo_last(self):
        if not messagebox.askyesno(
            "Отменить последнюю сортировку",
            "Вернуть файлы из последней сортировки на прежние места?",
        ):
            return
        self.status_var.set("Отменяю...")
        self.update_idletasks()

        def work():
            ok, fail = self.sorter.undo_last()
            self.after(0, lambda: self._after_undo(ok, fail))

        threading.Thread(target=work, daemon=True).start()

    def _after_undo(self, ok: int, fail: int):
        self._refresh_filters()
        self._reload_table()
        self._reload_history()
        if ok == 0 and fail == 0:
            messagebox.showinfo("Отмена", "Нечего отменять.")
        else:
            msg = f"Возвращено: {ok}"
            if fail:
                msg += f"\nНе удалось вернуть: {fail}"
            messagebox.showinfo("Отмена выполнена", msg)

    def _reindex(self):
        self.status_var.set("Обновляю индекс...")
        self.update_idletasks()

        def work():
            self.index.remove_missing()
            added = self.sorter.reindex_destination()
            self.after(0, lambda: self._after_reindex(added))

        threading.Thread(target=work, daemon=True).start()

    def _after_reindex(self, added: int):
        self._refresh_filters()
        self._reload_table()
        self.status_var.set(f"Индекс обновлён. Записей: {self.index.count()}")

    def _toggle_watcher(self):
        if self.watcher.running:
            self.watcher.stop()
            self.bg_var.set("Фон: выкл")
        else:
            self.watcher.start()
            self.bg_var.set("Фон: ВКЛ")

    def _on_background_sorted(self, new_path: str):
        self.after(0, self._on_bg_update)

    def _on_bg_update(self):
        self._refresh_filters()
        self._reload_table()
        self._reload_history()

    # ---------- логика вкладки «весь компьютер» ----------

    def _pc_category_exts(self) -> set[str]:
        override = self.pc_ext_var.get().strip()
        if override:
            exts = set()
            for part in override.replace(";", ",").split(","):
                part = part.strip().lower()
                if part and not part.startswith("."):
                    part = "." + part
                if part:
                    exts.add(part)
            return exts
        cat = self.pc_category_var.get()
        if cat == "Все файлы":
            return set()
        if cat == OTHER_CATEGORY:
            return set()  # «Другое» трудно перечислить — лучше задать расширения
        return set(self.settings.categories.get(cat, []))

    def _pc_start_scan(self):
        if getattr(self, "_pc_scanning", False):
            return
        exts = self._pc_category_exts()
        if not exts and self.pc_category_var.get() not in ("Все файлы",):
            messagebox.showinfo(
                "Уточните поиск",
                "Для этой категории укажите расширения (например .docx,.doc) "
                "или выберите «Все файлы».",
            )
            return
        self.pc_tree.delete(*self.pc_tree.get_children())
        self._pc_results = []
        self._pc_stage = []
        self._pc_stage_lock = threading.Lock()
        self._pc_progress_text = "Сканирую..."
        self._pc_scanning = True
        self.pc_scan_btn.configure(state="disabled")
        self.pc_stop_btn.configure(state="normal")
        self._pc_scanner.reset()

        def on_result(item):
            with self._pc_stage_lock:
                self._pc_stage.append(item)

        def on_progress(folder, found):
            self._pc_progress_text = f"Найдено: {found} · {folder}"

        def work():
            try:
                self._pc_scanner.scan(exts, on_progress=on_progress, on_result=on_result)
            finally:
                self._pc_scanning = False

        self._pc_scan_thread = threading.Thread(target=work, daemon=True)
        self._pc_scan_thread.start()
        self._pc_poll()

    def _pc_poll(self):
        with self._pc_stage_lock:
            new_items = self._pc_stage
            self._pc_stage = []
        flt = self.pc_filter_var.get().strip().lower()
        only_cand = self.pc_only_cand_var.get() == "on"
        for item in new_items:
            cand, reason = classify(item)
            item["del"] = cand
            item["reason"] = reason
            idx = len(self._pc_results)
            self._pc_results.append(item)
            if flt and flt not in item["name"].lower():
                continue
            if only_cand and not cand:
                continue
            self._pc_insert_row(idx, item)
        cand_total = sum(1 for r in self._pc_results if r.get("del"))
        base = getattr(self, "_pc_progress_text", "")
        self.pc_progress_var.set(f"{base} · кандидатов: {cand_total}")
        if getattr(self, "_pc_scanning", False) or new_items:
            self.after(250, self._pc_poll)
        else:
            self.pc_scan_btn.configure(state="normal")
            self.pc_stop_btn.configure(state="disabled")
            self.pc_progress_var.set(f"Готово. Всего найдено: {len(self._pc_results)}")

    def _pc_insert_row(self, idx: int, item: dict):
        dt = datetime.fromtimestamp(item["mtime"])
        advice = ("УДАЛИТЬ? " + item["reason"]) if item.get("del") else ""
        tags = ("candidate",) if item.get("del") else ()
        self.pc_tree.insert(
            "", END, iid=str(idx), tags=tags,
            values=(item["name"], item["folder"], human_size(item["size"]),
                    dt.strftime("%d.%m.%Y %H:%M"), advice),
        )

    def _pc_stop_scan(self):
        self._pc_scanner.stop()

    def _pc_apply_filter(self):
        flt = self.pc_filter_var.get().strip().lower()
        only_cand = self.pc_only_cand_var.get() == "on"
        self.pc_tree.delete(*self.pc_tree.get_children())
        for idx, item in enumerate(self._pc_results):
            if flt and flt not in item["name"].lower():
                continue
            if only_cand and not item.get("del"):
                continue
            self._pc_insert_row(idx, item)

    def _pc_select_candidates(self):
        """Выделить в таблице все показанные файлы-кандидаты на удаление."""
        rows = [iid for iid in self.pc_tree.get_children()
                if "candidate" in self.pc_tree.item(iid, "tags")]
        self.pc_tree.selection_set(rows)
        if rows:
            self.pc_tree.see(rows[0])
        self.status_var.set(f"Выделено кандидатов: {len(rows)}")

    def _pc_selected(self) -> dict | None:
        """Один файл (для предпросмотра) — текущий в фокусе или первый выделенный."""
        focus = self.pc_tree.focus()
        sel = self.pc_tree.selection()
        iid = focus if focus in sel else (sel[0] if sel else None)
        if iid is None:
            return None
        try:
            return self._pc_results[int(iid)]
        except (ValueError, IndexError):
            return None

    def _pc_selected_items(self) -> list[dict]:
        items = []
        for iid in self.pc_tree.selection():
            try:
                items.append(self._pc_results[int(iid)])
            except (ValueError, IndexError):
                continue
        return items

    def _pc_on_select(self, *_):
        item = self._pc_selected()
        if not item:
            return
        path = Path(item["path"])
        ext = path.suffix.lower()
        # фото / видео-кадр
        self._pc_photo = None
        is_media = ext in PREVIEW_EXTS
        if _HAS_PIL and is_media and path.exists():
            img = get_thumbnail(path, max_size=(300, 290))
            if img is not None:
                self._pc_photo = ImageTk.PhotoImage(img)
                self.pc_img_label.configure(image=self._pc_photo, text="")
            else:
                self.pc_img_label.configure(
                    image="", text="Не удалось показать\n(откройте файл)")
        else:
            self.pc_img_label.configure(image="", text="(нет изображения)")
        # текст / Word / Excel
        text = get_text_preview(path)
        self.pc_text.configure(state="normal")
        self.pc_text.delete("1.0", END)
        if text:
            self.pc_text.insert("1.0", text)
        elif ext in VIDEO_EXTS:
            self.pc_text.insert("1.0", "Видео — кадр показан выше. "
                                       "Нажмите «Открыть», чтобы воспроизвести.")
        elif ext in IMAGE_EXTS:
            self.pc_text.insert("1.0", "Изображение — см. предпросмотр выше.")
        else:
            self.pc_text.insert("1.0", "Предпросмотр для этого типа недоступен.\n"
                                       "Нажмите «Открыть», чтобы посмотреть файл.")
        self.pc_text.configure(state="disabled")

    def _pc_open(self, *_):
        item = self._pc_selected()
        if not item:
            return
        if not Path(item["path"]).exists():
            messagebox.showwarning("Нет файла", "Файл был перемещён или удалён.")
            return
        open_path(item["path"])

    def _pc_reveal(self, *_):
        item = self._pc_selected()
        if item:
            reveal_in_explorer(item["path"])

    def _pc_copy(self):
        items = self._pc_selected_items()
        if not items:
            return
        dest = filedialog.askdirectory(title="Куда скопировать файлы?")
        if not dest:
            return
        ok = fail = 0
        for item in items:
            try:
                shutil.copy2(item["path"], dest)
                ok += 1
            except (OSError, shutil.Error):
                fail += 1
        self.status_var.set(f"Скопировано: {ok}" + (f", ошибок: {fail}" if fail else ""))

    def _pc_move(self):
        items = self._pc_selected_items()
        if not items:
            return
        dest = filedialog.askdirectory(title="Куда переместить файлы?")
        if not dest:
            return
        ok = fail = 0
        for item in items:
            try:
                new_path = shutil.move(item["path"], dest)
                item["path"] = str(new_path)
                item["folder"] = dest
                ok += 1
            except (OSError, shutil.Error):
                fail += 1
        self._pc_apply_filter()
        self.status_var.set(f"Перемещено: {ok}" + (f", ошибок: {fail}" if fail else ""))

    def _pc_delete(self):
        items = self._pc_selected_items()
        if not items:
            return
        where = "в корзину" if _HAS_TRASH else "БЕЗВОЗВРАТНО"
        if len(items) == 1:
            msg = f"Удалить {where}?\n\n{items[0]['name']}\n{items[0]['folder']}"
        else:
            preview = "\n".join(f"• {i['name']}" for i in items[:12])
            more = f"\n…и ещё {len(items) - 12}" if len(items) > 12 else ""
            msg = f"Удалить {where} {len(items)} файлов?\n\n{preview}{more}"
        if not messagebox.askyesno("Удаление файлов", msg):
            return
        ok = fail = 0
        deleted = set()
        for item in items:
            try:
                if _HAS_TRASH:
                    send2trash(item["path"])
                else:
                    os.remove(item["path"])
                deleted.add(id(item))
                ok += 1
            except OSError:
                fail += 1
        self._pc_results = [r for r in self._pc_results if id(r) not in deleted]
        self._pc_apply_filter()
        self.status_var.set(f"Удалено: {ok}" + (f", ошибок: {fail}" if fail else ""))

    # ---------- настройки ----------

    def _open_settings(self):
        win = Toplevel(self)
        win.title("Настройки сортировки")
        win.geometry("720x620")
        win.configure(bg=theme.BG)
        win.transient(self)
        win.grab_set()

        from tkinter import Radiobutton, Text

        canvas_frame = Frame(win, bg=theme.BG)
        canvas_frame.pack(fill=BOTH, expand=True)

        Label(canvas_frame, text="Схема раскладки файлов",
              font=("Segoe UI", 11, "bold"), bg=theme.BG).pack(anchor="w", padx=16, pady=(14, 4))
        sort_var = StringVar(value=self.settings.sort_mode)
        for key, label in SORT_MODES.items():
            Radiobutton(
                canvas_frame, text=label, variable=sort_var, value=key,
                bg=theme.BG, anchor="w", padx=20,
            ).pack(fill=X)

        Label(canvas_frame, text="Что делать с файлами",
              font=("Segoe UI", 11, "bold"), bg=theme.BG).pack(anchor="w", padx=16, pady=(14, 4))
        storage_var = StringVar(value=self.settings.storage_mode)
        for key, label in STORAGE_MODES.items():
            Radiobutton(
                canvas_frame, text=label, variable=storage_var, value=key,
                bg=theme.BG, anchor="w", padx=20,
            ).pack(fill=X)

        Label(canvas_frame, text="Дата для папок",
              font=("Segoe UI", 11, "bold"), bg=theme.BG).pack(anchor="w", padx=16, pady=(14, 4))
        date_var = StringVar(value=self.settings.date_source)
        for key, label in DATE_SOURCES.items():
            Radiobutton(
                canvas_frame, text=label, variable=date_var, value=key,
                bg=theme.BG, anchor="w", padx=20,
            ).pack(fill=X)

        Label(canvas_frame, text="Папка архива",
              font=("Segoe UI", 11, "bold"), bg=theme.BG).pack(anchor="w", padx=16, pady=(14, 4))
        dest_frame = Frame(canvas_frame, bg=theme.BG)
        dest_frame.pack(fill=X, padx=16)
        loc_var = StringVar(value=self.settings.archive_location)
        name_var = StringVar(value=self.settings.archive_name)
        ttk.Entry(dest_frame, textvariable=loc_var).pack(side=LEFT, fill=X, expand=True)

        def choose_dest():
            d = filedialog.askdirectory(initialdir=loc_var.get() or str(Path.home()))
            if d:
                loc_var.set(d)

        ttk.Button(dest_frame, text="Обзор...", command=choose_dest).pack(side=LEFT, padx=(6, 0))

        name_frame = Frame(canvas_frame, bg=theme.BG)
        name_frame.pack(fill=X, padx=16, pady=(6, 0))
        Label(name_frame, text="Имя папки-архива:", bg=theme.BG).pack(side=LEFT)
        ttk.Entry(name_frame, textvariable=name_var, width=24).pack(side=LEFT, padx=(6, 0))

        result_var = StringVar()
        Label(canvas_frame, textvariable=result_var, fg=theme.ACCENT, bg=theme.BG).pack(
            anchor="w", padx=16, pady=(6, 0))

        def update_result(*_):
            result_var.set(
                "Итог: " + str(Path(loc_var.get().strip() or str(Path.home()))
                               / (name_var.get().strip() or "Архив"))
            )

        loc_var.trace_add("write", update_result)
        name_var.trace_add("write", update_result)
        update_result()

        sort_folders_var = StringVar(value="on" if self.settings.sort_folders else "off")
        ttk.Checkbutton(
            canvas_frame, text="Сортировать папки целиком (категория «Папки»)",
            variable=sort_folders_var, onvalue="on", offvalue="off",
        ).pack(anchor="w", padx=16, pady=(8, 0))

        Label(canvas_frame, text="Отслеживаемые папки (по одной в строке):",
              font=("Segoe UI", 10, "bold"), bg=theme.BG).pack(anchor="w", padx=16, pady=(12, 2))
        folders_text = Text(canvas_frame, height=5, font=("Consolas", 9))
        folders_text.pack(fill=X, padx=16)
        folders_text.insert("1.0", "\n".join(self.settings.watched_folders))

        def add_folder():
            d = filedialog.askdirectory(initialdir=str(Path.home()))
            if d:
                folders_text.insert(END, ("\n" if folders_text.get("1.0", END).strip() else "") + d)

        btns = Frame(win, bg=theme.BG)
        btns.pack(fill=X, padx=16, pady=12)
        ttk.Button(btns, text="Добавить папку...", command=add_folder).pack(side=LEFT)

        def save():
            folders = [
                line.strip()
                for line in folders_text.get("1.0", END).splitlines()
                if line.strip()
            ]
            self.settings.data["sort_mode"] = sort_var.get()
            self.settings.data["storage_mode"] = storage_var.get()
            self.settings.data["date_source"] = date_var.get()
            self.settings.data["archive_location"] = loc_var.get().strip()
            self.settings.data["archive_name"] = name_var.get().strip() or "Архив"
            self.settings.data["sort_folders"] = sort_folders_var.get() == "on"
            self.settings.data.pop("destination", None)
            self.settings.data["watched_folders"] = folders
            self.settings.save()
            self._update_mode_banner()
            if self.watcher.running:
                self.watcher.stop()
                self.watcher.start()
            messagebox.showinfo("Сохранено", "Настройки сортировки сохранены.")
            win.destroy()

        ttk.Button(btns, text="Сохранить", style="Accent.TButton", command=save).pack(side=RIGHT)
        ttk.Button(btns, text="Отмена", command=win.destroy).pack(side=RIGHT, padx=(0, 8))

    # ---------- закрытие ----------

    def _on_close(self):
        try:
            self.watcher.stop()
            self.index.close()
        finally:
            self.destroy()


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
