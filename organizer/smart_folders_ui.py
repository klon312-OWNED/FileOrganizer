"""Диалог подтверждения умной раскладки по пользовательским папкам."""

from __future__ import annotations

from pathlib import Path
from tkinter import END, BOTH, LEFT, RIGHT, X, Y, Frame, Label, StringVar, Toplevel, messagebox
from tkinter import ttk

from . import theme
from .folder_profiles import MatchProposal, apply_catchall, apply_create_folder


class SmartFolderMappingDialog(Toplevel):
    """Предпросмотр и правка сопоставления файл → папка перед перемещением."""

    def __init__(
        self,
        master,
        *,
        proposals: list[MatchProposal],
        library_root: Path,
        catchall_name: str,
        auto_create: bool,
        dry_run: bool,
    ) -> None:
        super().__init__(master)
        self.title("Умная раскладка по моим папкам")
        self.geometry("920x560")
        self.configure(bg=theme.BG)
        self.transient(master)
        self.grab_set()

        self._library_root = library_root
        self._catchall_name = catchall_name
        self._auto_create = auto_create
        self._dry_run = dry_run
        self._proposals = proposals
        self.confirmed = False
        self.result: list[MatchProposal] = []

        folder_names = sorted(
            {p.name for p in library_root.iterdir() if p.is_dir()}
            if library_root.is_dir() else set()
        )
        self._folder_choices = folder_names + [
            f"[Создать: {p.suggested_folder}]"
            for p in proposals
            if p.action == "create" and p.suggested_folder
            and p.suggested_folder not in folder_names
        ]
        self._folder_choices = sorted(set(self._folder_choices))
        extras = [catchall_name, "— Пропустить —"]
        for e in extras:
            if e not in self._folder_choices:
                self._folder_choices.append(e)

        header = Label(
            self,
            text=(
                f"Библиотека: {library_root}\n"
                f"Проверьте сопоставление и при необходимости измените папку назначения."
                + ("  [Тестовый режим — файлы не будут перемещены]" if dry_run else "")
            ),
            bg=theme.BG,
            fg=theme.TEXT_MUTED,
            justify="left",
            anchor="w",
            padx=12,
            pady=8,
        )
        header.pack(fill=X)

        if auto_create:
            self._apply_auto_create_defaults()

        tree_frame = Frame(self, bg=theme.BG)
        tree_frame.pack(fill=BOTH, expand=True, padx=12, pady=(0, 8))

        cols = ("file", "folder", "score", "action")
        self._tree = ttk.Treeview(tree_frame, columns=cols, show="headings", height=16)
        self._tree.heading("file", text="Файл")
        self._tree.heading("folder", text="Папка назначения")
        self._tree.heading("score", text="Оценка")
        self._tree.heading("action", text="Действие")
        self._tree.column("file", width=280, minwidth=120)
        self._tree.column("folder", width=220, minwidth=100)
        self._tree.column("score", width=70, anchor="center")
        self._tree.column("action", width=120, anchor="center")
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.pack(side=LEFT, fill=BOTH, expand=True)
        vsb.pack(side=RIGHT, fill=Y)

        self._row_map: dict[str, MatchProposal] = {}
        for i, prop in enumerate(proposals):
            iid = str(i)
            self._row_map[iid] = prop
            self._insert_row(iid, prop)

        self._tree.bind("<<TreeviewSelect>>", self._on_select)

        edit_frame = Frame(self, bg=theme.BG, padx=12, pady=4)
        edit_frame.pack(fill=X)
        Label(edit_frame, text="Папка для выбранного:", bg=theme.BG).pack(side=LEFT)
        self._folder_var = StringVar()
        self._folder_box = ttk.Combobox(
            edit_frame,
            textvariable=self._folder_var,
            values=self._folder_choices,
            width=36,
        )
        self._folder_box.pack(side=LEFT, padx=(8, 0))
        ttk.Button(edit_frame, text="Применить", command=self._apply_folder_choice).pack(
            side=LEFT, padx=(8, 0),
        )

        bulk = Frame(self, bg=theme.BG, padx=12, pady=4)
        bulk.pack(fill=X)
        ttk.Button(
            bulk, text="Все без совпадения → «Другое»",
            command=self._bulk_catchall,
        ).pack(side=LEFT)
        ttk.Button(
            bulk, text="Создать папки для «создать»",
            command=self._bulk_create,
        ).pack(side=LEFT, padx=(8, 0))
        ttk.Button(
            bulk, text="Пропустить все «создать»",
            command=self._bulk_skip_unmatched,
        ).pack(side=LEFT, padx=(8, 0))

        self._summary_var = StringVar()
        self._update_summary()
        Label(self, textvariable=self._summary_var, bg=theme.BG, fg=theme.ACCENT).pack(
            anchor="w", padx=12, pady=(4, 0),
        )

        btns = Frame(self, bg=theme.BG, padx=12, pady=12)
        btns.pack(fill=X)
        ttk.Button(btns, text="Отмена", command=self._cancel).pack(side=RIGHT, padx=(8, 0))
        ttk.Button(
            btns, text="Применить раскладку", style="Accent.TButton", command=self._confirm,
        ).pack(side=RIGHT)

        self.protocol("WM_DELETE_WINDOW", self._cancel)

    def _action_label(self, prop: MatchProposal) -> str:
        labels = {
            "move": "Переместить",
            "create": "Создать",
            "catchall": "В «Другое»",
            "skip": "Пропустить",
        }
        return labels.get(prop.action, prop.action)

    def _folder_display(self, prop: MatchProposal) -> str:
        if prop.action == "skip":
            return "—"
        if prop.dest_folder:
            return prop.dest_folder.name
        if prop.suggested_folder:
            return f"→ {prop.suggested_folder}"
        return "—"

    def _insert_row(self, iid: str, prop: MatchProposal) -> None:
        self._tree.insert(
            "",
            END,
            iid=iid,
            values=(
                prop.source.name,
                self._folder_display(prop),
                f"{prop.score:.0%}" if prop.score > 0 else "—",
                self._action_label(prop),
            ),
        )

    def _refresh_row(self, iid: str, prop: MatchProposal) -> None:
        self._tree.item(
            iid,
            values=(
                prop.source.name,
                self._folder_display(prop),
                f"{prop.score:.0%}" if prop.score > 0 else "—",
                self._action_label(prop),
            ),
        )

    def _apply_auto_create_defaults(self) -> None:
        for prop in self._proposals:
            if prop.action == "create" and prop.suggested_folder:
                apply_create_folder(
                    prop, self._library_root, prop.suggested_folder,
                )

    def _update_summary(self) -> None:
        move = sum(1 for p in self._proposals if p.action == "move")
        create = sum(1 for p in self._proposals if p.action == "create")
        catch = sum(1 for p in self._proposals if p.action == "catchall")
        skip = sum(1 for p in self._proposals if p.action == "skip")
        self._summary_var.set(
            f"Переместить: {move} · Создать папку: {create} · "
            f"В «{self._catchall_name}»: {catch} · Пропустить: {skip}",
        )

    def _on_select(self, _event=None) -> None:
        sel = self._tree.selection()
        if not sel:
            return
        prop = self._row_map.get(sel[0])
        if not prop:
            return
        if prop.dest_folder:
            self._folder_var.set(prop.dest_folder.name)
        elif prop.suggested_folder:
            self._folder_var.set(prop.suggested_folder)
        else:
            self._folder_var.set("— Пропустить —")

    def _apply_folder_choice(self) -> None:
        sel = self._tree.selection()
        if not sel:
            messagebox.showinfo("Выбор", "Выберите строку в таблице.", parent=self)
            return
        prop = self._row_map[sel[0]]
        choice = self._folder_var.get().strip()
        if not choice or choice == "— Пропустить —":
            prop.action = "skip"
            prop.dest_folder = None
            prop.reason = "Пропущено пользователем"
        elif choice.startswith("[Создать:"):
            name = choice.replace("[Создать:", "").replace("]", "").strip()
            apply_create_folder(prop, self._library_root, name or "Новая папка")
        elif choice == self._catchall_name:
            apply_catchall(prop, self._library_root, self._catchall_name)
        else:
            prop.action = "move"
            prop.dest_folder = self._library_root / choice
            prop.profile_name = choice
            prop.reason = "Выбрано вручную"
        self._refresh_row(sel[0], prop)
        self._update_summary()

    def _bulk_catchall(self) -> None:
        for iid, prop in self._row_map.items():
            if prop.action in ("create",) or (prop.action == "move" and prop.score < 0.01):
                apply_catchall(prop, self._library_root, self._catchall_name)
                self._refresh_row(iid, prop)
        self._update_summary()

    def _bulk_create(self) -> None:
        for iid, prop in self._row_map.items():
            if prop.action == "create" and prop.suggested_folder:
                apply_create_folder(prop, self._library_root, prop.suggested_folder)
                self._refresh_row(iid, prop)
        self._update_summary()

    def _bulk_skip_unmatched(self) -> None:
        for iid, prop in self._row_map.items():
            if prop.action == "create":
                prop.action = "skip"
                prop.dest_folder = None
                prop.reason = "Пропущено"
                self._refresh_row(iid, prop)
        self._update_summary()

    def _confirm(self) -> None:
        active = [p for p in self._proposals if p.action != "skip" and p.dest_folder]
        if not active:
            messagebox.showwarning(
                "Нечего применять",
                "Нет файлов для перемещения. Назначьте папки или отмените.",
                parent=self,
            )
            return
        self.confirmed = True
        self.result = list(self._proposals)
        self.destroy()

    def _cancel(self) -> None:
        self.confirmed = False
        self.result = []
        self.destroy()
