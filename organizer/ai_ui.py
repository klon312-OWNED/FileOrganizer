"""Вкладка «ИИ-помощник» — чат-подобный интерфейс."""

from __future__ import annotations

import threading
from tkinter import BOTH, END, LEFT, RIGHT, X, Y, Frame, Label, StringVar, Text, messagebox
from tkinter import ttk
from pathlib import Path
from typing import Callable

from . import theme
from .ai_assistant import (
    SearchIntent,
    SearchResult,
    Suggestion,
    create_assistant,
    generate_suggestions,
    human_size,
    parse_user_query,
    search_files,
)


class AIAssistantPanel(Frame):
    """Панель ИИ-помощника с вводом запроса, подсказками и результатами."""

    def __init__(
        self,
        master,
        *,
        get_settings,
        get_index,
        get_watched_entries,
        on_open_path: Callable[[str], None],
        on_sort_paths: Callable[[list[str]], None],
        on_exclude_paths: Callable[[list[str]], None],
        on_smart_cleanup: Callable[[], None],
        on_set_sort_mode: Callable[[str], None],
        on_enable_compression: Callable[[], None],
        on_show_desktop: Callable[[], None],
        on_open_settings: Callable[[], None],
    ) -> None:
        super().__init__(master, bg=theme.BG)
        self._get_settings = get_settings
        self._get_index = get_index
        self._get_watched = get_watched_entries
        self._on_open = on_open_path
        self._on_sort = on_sort_paths
        self._on_exclude = on_exclude_paths
        self._on_cleanup = on_smart_cleanup
        self._on_sort_mode = on_set_sort_mode
        self._on_compress = on_enable_compression
        self._on_desktop = on_show_desktop
        self._on_settings = on_open_settings
        self._busy = False
        self._build()

    def _build(self) -> None:
        top = Frame(self, bg=theme.BG, padx=8, pady=8)
        top.pack(side="top", fill=X)

        Label(
            top, text="ИИ-помощник", font=("Segoe UI", 13, "bold"), bg=theme.BG,
        ).pack(side=LEFT)
        self._provider_var = StringVar()
        Label(
            top, textvariable=self._provider_var, bg=theme.BG,
            fg=theme.TEXT_MUTED, font=("Segoe UI", 9),
        ).pack(side=LEFT, padx=(12, 0))
        ttk.Button(top, text="Обновить советы", command=self._load_suggestions).pack(side=RIGHT)
        ttk.Button(top, text="Настройки ИИ", command=self._on_settings).pack(side=RIGHT, padx=(0, 8))

        disclaimer = Label(
            self,
            text=(
                "⚠ Помощник только подсказывает — сортировка и удаление только по вашему подтверждению. "
                "На API отправляются только метаданные (имена, размеры, категории), не содержимое файлов."
            ),
            bg=theme.SIDEBAR, fg=theme.TEXT_MUTED, wraplength=900,
            justify="left", padx=10, pady=6,
        )
        disclaimer.pack(side="top", fill=X, padx=8, pady=(0, 4))

        body = Frame(self, bg=theme.BG)
        body.pack(side="top", fill=BOTH, expand=True, padx=8, pady=4)

        left = Frame(body, bg=theme.BG)
        left.pack(side=LEFT, fill=BOTH, expand=True)

        input_frame = Frame(left, bg=theme.CARD, highlightbackground=theme.BORDER, highlightthickness=1)
        input_frame.pack(side="top", fill=X, pady=(0, 6))
        self._input = Text(input_frame, height=3, font=("Segoe UI", 10), wrap="word")
        self._input.pack(side=LEFT, fill=BOTH, expand=True, padx=6, pady=6)
        self._input.bind("<Control-Return>", lambda _e: self._on_send())
        btn_col = Frame(input_frame, bg=theme.CARD)
        btn_col.pack(side=RIGHT, padx=6, pady=6)
        self._send_btn = ttk.Button(btn_col, text="Отправить", style="Accent.TButton", command=self._on_send)
        self._send_btn.pack(fill=X)
        ttk.Button(btn_col, text="Примеры", command=self._show_examples).pack(fill=X, pady=(4, 0))

        Label(left, text="Диалог", font=("Segoe UI", 10, "bold"), bg=theme.BG).pack(anchor="w")
        chat_wrap = Frame(left, bg=theme.CARD, highlightbackground=theme.BORDER, highlightthickness=1)
        chat_wrap.pack(side="top", fill=BOTH, expand=True, pady=(4, 0))
        self._chat = Text(
            chat_wrap, wrap="word", state="disabled",
            font=("Segoe UI", 10), bg=theme.CARD, fg=theme.TEXT,
        )
        chat_vsb = ttk.Scrollbar(chat_wrap, command=self._chat.yview)
        self._chat.configure(yscrollcommand=chat_vsb.set)
        chat_vsb.pack(side=RIGHT, fill=Y)
        self._chat.pack(side=LEFT, fill=BOTH, expand=True, padx=4, pady=4)

        right = Frame(body, width=340, bg=theme.BG)
        right.pack(side=RIGHT, fill=Y, padx=(8, 0))
        right.pack_propagate(False)

        Label(right, text="Советы", font=("Segoe UI", 10, "bold"), bg=theme.BG).pack(anchor="w")
        sug_wrap = Frame(
            right, bg=theme.CARD, highlightbackground=theme.BORDER, highlightthickness=1,
        )
        sug_wrap.pack(side="top", fill=BOTH, expand=True, pady=(4, 6))
        self._suggestions_frame = Frame(sug_wrap, bg=theme.CARD)
        self._suggestions_frame.pack(fill=BOTH, expand=True, padx=4, pady=4)
        sug_vsb = ttk.Scrollbar(sug_wrap, command=self._scroll_suggestions)
        sug_vsb.pack(side=RIGHT, fill=Y)
        self._sug_canvas = ttk.Canvas(sug_wrap, highlightthickness=0)
        self._sug_canvas.pack(side=LEFT, fill=BOTH, expand=True)
        self._sug_inner = Frame(self._sug_canvas)
        self._sug_window = self._sug_canvas.create_window((0, 0), window=self._sug_inner, anchor="nw")
        self._sug_inner.bind("<Configure>", self._on_sug_configure)
        self._sug_canvas.bind("<Configure>", self._on_sug_canvas_configure)

        Label(right, text="Результаты поиска", font=("Segoe UI", 10, "bold"), bg=theme.BG).pack(anchor="w")
        res_wrap = Frame(right, bg=theme.CARD, highlightbackground=theme.BORDER, highlightthickness=1)
        res_wrap.pack(side="top", fill=BOTH, expand=True, pady=(4, 0))
        self._results_frame = Frame(res_wrap, bg=theme.CARD)
        self._results_frame.pack(fill=BOTH, expand=True, padx=4, pady=4)
        res_vsb = ttk.Scrollbar(res_wrap)
        res_vsb.pack(side=RIGHT, fill=Y)

        self._status_var = StringVar(value="Готов")
        Label(self, textvariable=self._status_var, bg=theme.SIDEBAR, fg=theme.TEXT_MUTED, anchor="w", padx=8, pady=4).pack(
            side="bottom", fill=X,
        )

        self._update_provider_label()
        self._append_chat("Система", "Привет! Спросите, например: «найди все pdf за май» или «что сортировать сейчас?»")
        self.after(200, self._load_suggestions)

    def _on_sug_configure(self, _event=None) -> None:
        self._sug_canvas.configure(scrollregion=self._sug_canvas.bbox("all"))

    def _on_sug_canvas_configure(self, event) -> None:
        self._sug_canvas.itemconfig(self._sug_window, width=event.width)

    def _scroll_suggestions(self, *args) -> None:
        self._sug_canvas.yview(*args)

    def refresh(self) -> None:
        self._update_provider_label()

    def _update_provider_label(self) -> None:
        s = self._get_settings()
        labels = {
            "rules": "режим: локальные правила (без сети)",
            "openai": f"режим: API ({s.ai_model})",
            "ollama": f"режим: Ollama ({s.ai_ollama_model})",
        }
        self._provider_var.set(labels.get(s.ai_provider, labels["rules"]))

    def _append_chat(self, who: str, text: str) -> None:
        self._chat.configure(state="normal")
        self._chat.insert(END, f"\n{who}: {text}\n")
        self._chat.see(END)
        self._chat.configure(state="disabled")

    def _set_busy(self, busy: bool, msg: str = "") -> None:
        self._busy = busy
        state = "disabled" if busy else "normal"
        self._send_btn.configure(state=state)
        if msg:
            self._status_var.set(msg)

    def _show_examples(self) -> None:
        examples = (
            "найди все pdf за май\n"
            "покажи большие видео\n"
            "что сортировать сейчас?\n"
            "какие файлы можно удалить?"
        )
        self._input.delete("1.0", END)
        self._input.insert("1.0", examples.split("\n")[0])

    def _on_send(self) -> None:
        if self._busy:
            return
        text = self._input.get("1.0", END).strip()
        if not text:
            return
        self._input.delete("1.0", END)
        self._append_chat("Вы", text)
        self._set_busy(True, "Думаю…")
        threading.Thread(target=self._process_query, args=(text,), daemon=True).start()

    def _process_query(self, text: str) -> None:
        try:
            settings = self._get_settings()
            assistant = create_assistant(settings)
            intent = assistant.parse_user_query(text)
            if intent.action == "suggest":
                suggestions = assistant.generate_suggestions(
                    settings, self._get_index(), self._get_watched(),
                )
                msg = f"Нашёл {len(suggestions)} совет(ов). Смотрите панель справа."
                self.after(0, lambda: self._show_suggestions(suggestions))
            else:
                results = search_files(
                    intent,
                    index=self._get_index(),
                    watched_entries=self._get_watched(),
                )
                msg = self._format_search_reply(intent, results)
                self.after(0, lambda: self._show_results(results))
            self.after(0, lambda: self._append_chat("Помощник", msg))
        except Exception as exc:
            self.after(0, lambda: self._append_chat("Ошибка", str(exc)))
        finally:
            self.after(0, lambda: self._set_busy(False, "Готов"))

    def _format_search_reply(self, intent: SearchIntent, results: list[SearchResult]) -> str:
        parts = [f"Найдено: {len(results)}"]
        if intent.categories:
            parts.append(f"категории: {', '.join(intent.categories)}")
        if intent.month:
            parts.append(f"месяц: {intent.month}")
        if intent.min_size:
            parts.append(f"от {human_size(intent.min_size)}")
        return ". ".join(parts) + "."

    def _load_suggestions(self) -> None:
        if self._busy:
            return
        self._set_busy(True, "Анализирую папки…")

        def work():
            try:
                suggestions = generate_suggestions(
                    self._get_settings(),
                    self._get_index(),
                    self._get_watched(),
                )
                self.after(0, lambda: self._show_suggestions(suggestions))
            except Exception as exc:
                self.after(0, lambda: messagebox.showerror("ИИ-помощник", str(exc)))
            finally:
                self.after(0, lambda: self._set_busy(False, "Готов"))

        threading.Thread(target=work, daemon=True).start()

    def _clear_frame(self, frame: Frame) -> None:
        for w in frame.winfo_children():
            w.destroy()

    def _show_suggestions(self, suggestions: list[Suggestion]) -> None:
        self._clear_frame(self._sug_inner)
        for sug in suggestions:
            card = Frame(
                self._sug_inner, bg=theme.SIDEBAR, padx=8, pady=6,
                highlightbackground=theme.BORDER, highlightthickness=1,
            )
            card.pack(fill=X, pady=4)
            Label(card, text=sug.title, font=("Segoe UI", 9, "bold"), bg=theme.SIDEBAR, anchor="w").pack(fill=X)
            Label(
                card, text=sug.description, font=("Segoe UI", 8),
                bg=theme.SIDEBAR, fg=theme.TEXT_MUTED, wraplength=280, justify="left",
            ).pack(fill=X, pady=(2, 4))
            btns = Frame(card, bg=theme.SIDEBAR)
            btns.pack(fill=X)
            ttk.Button(
                btns, text="Применить",
                command=lambda s=sug: self._apply_suggestion(s),
            ).pack(side=LEFT)

    def _show_results(self, results: list[SearchResult]) -> None:
        self._clear_frame(self._results_frame)
        if not results:
            Label(
                self._results_frame, text="Ничего не найдено", bg=theme.CARD,
                fg=theme.TEXT_MUTED,
            ).pack(pady=8)
            return
        for res in results[:40]:
            row = Frame(self._results_frame, bg=theme.CARD)
            row.pack(fill=X, pady=2)
            meta = f"{res.name} · {human_size(res.size)}"
            if res.category:
                meta += f" · {res.category}"
            if res.reason:
                meta += f" · {res.reason}"
            Label(
                row, text=meta, font=("Segoe UI", 8), bg=theme.CARD,
                anchor="w", wraplength=300, justify="left",
            ).pack(side=LEFT, fill=X, expand=True)
            ttk.Button(row, text="Откр.", width=5, command=lambda p=res.path: self._on_open(p)).pack(side=RIGHT, padx=1)
            ttk.Button(row, text="Сорт.", width=5, command=lambda p=res.path: self._on_sort([p])).pack(side=RIGHT, padx=1)
            ttk.Button(row, text="⊘", width=3, command=lambda p=res.path: self._on_exclude([p])).pack(side=RIGHT)

    def _apply_suggestion(self, sug: Suggestion) -> None:
        action = sug.action
        payload = sug.payload or {}
        if action == "sort_paths":
            paths = payload.get("paths") or []
            if paths:
                self._on_sort(paths)
        elif action == "set_sort_mode":
            mode = payload.get("sort_mode")
            if mode:
                self._on_sort_mode(mode)
        elif action == "enable_compression":
            self._on_compress()
        elif action == "smart_cleanup":
            self._on_cleanup()
        elif action == "show_desktop":
            self._on_desktop()
        elif action == "search":
            q = payload.get("query", "")
            if q:
                self._input.delete("1.0", END)
                self._input.insert("1.0", q)
                self._on_send()
        elif action == "none":
            self._append_chat("Помощник", sug.description)
        else:
            messagebox.showinfo("ИИ-помощник", sug.description)
