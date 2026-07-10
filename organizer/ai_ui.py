"""Вкладка «ИИ-помощник» — чат-подобный интерфейс."""

from __future__ import annotations

import threading
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, X, Y, Frame, Label, StringVar, Text, messagebox
from tkinter import ttk
from typing import Callable

from . import theme
from .ai_assistant import (
    QUICK_QUERIES,
    SearchIntent,
    SearchResult,
    Suggestion,
    create_assistant,
    format_intent_summary,
    generate_suggestions,
    human_size,
    search_files,
)

_MAX_HISTORY = 12  # пар user/assistant в сессии


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
        self._history: list[dict[str, str]] = []
        self._last_results: list[SearchResult] = []
        self._active_wheel: str | None = None
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
        ttk.Button(top, text="Копировать чат", command=self._copy_chat).pack(side=RIGHT, padx=(0, 8))
        ttk.Button(top, text="Очистить чат", command=self._clear_chat).pack(side=RIGHT, padx=(0, 8))
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
        input_frame.pack(side="top", fill=X, pady=(0, 4))
        self._input = Text(input_frame, height=3, font=("Segoe UI", 10), wrap="word")
        self._input.pack(side=LEFT, fill=BOTH, expand=True, padx=6, pady=6)
        self._input.bind("<Control-Return>", lambda _e: self._on_send())
        btn_col = Frame(input_frame, bg=theme.CARD)
        btn_col.pack(side=RIGHT, padx=6, pady=6)
        self._send_btn = ttk.Button(btn_col, text="Отправить", style="Accent.TButton", command=self._on_send)
        self._send_btn.pack(fill=X)
        ttk.Button(btn_col, text="Примеры", command=self._show_examples).pack(fill=X, pady=(4, 0))

        chips = Frame(left, bg=theme.BG)
        chips.pack(side="top", fill=X, pady=(0, 6))
        Label(chips, text="Быстро:", bg=theme.BG, fg=theme.TEXT_MUTED, font=("Segoe UI", 8)).pack(
            side=LEFT, padx=(0, 4),
        )
        for q in QUICK_QUERIES[:7]:
            short = q if len(q) <= 22 else q[:20] + "…"
            ttk.Button(
                chips, text=short, width=max(10, len(short) + 1),
                command=lambda query=q: self._run_quick(query),
            ).pack(side=LEFT, padx=2, pady=2)

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
        sug_vsb = ttk.Scrollbar(sug_wrap)
        sug_vsb.pack(side=RIGHT, fill=Y)
        self._sug_canvas = ttk.Canvas(sug_wrap, highlightthickness=0, bg=theme.CARD)
        self._sug_canvas.pack(side=LEFT, fill=BOTH, expand=True)
        sug_vsb.configure(command=self._sug_canvas.yview)
        self._sug_canvas.configure(yscrollcommand=sug_vsb.set)
        self._sug_inner = Frame(self._sug_canvas, bg=theme.CARD)
        self._sug_window = self._sug_canvas.create_window((0, 0), window=self._sug_inner, anchor="nw")
        self._sug_inner.bind("<Configure>", self._on_sug_configure)
        self._sug_canvas.bind("<Configure>", self._on_sug_canvas_configure)
        self._sug_canvas.bind("<Enter>", lambda _e: self._bind_sug_wheel(True))
        self._sug_canvas.bind("<Leave>", lambda _e: self._bind_sug_wheel(False))

        res_head = Frame(right, bg=theme.BG)
        res_head.pack(side="top", fill=X)
        Label(res_head, text="Результаты поиска", font=("Segoe UI", 10, "bold"), bg=theme.BG).pack(
            side=LEFT, anchor="w",
        )
        self._batch_frame = Frame(res_head, bg=theme.BG)
        self._batch_frame.pack(side=RIGHT)
        ttk.Button(
            self._batch_frame, text="Сорт. все", width=9,
            command=self._sort_all_results,
        ).pack(side=LEFT, padx=2)
        ttk.Button(
            self._batch_frame, text="Искл. все", width=9,
            command=self._exclude_all_results,
        ).pack(side=LEFT, padx=2)
        ttk.Button(
            self._batch_frame, text="Копир.", width=7,
            command=self._copy_result_paths,
        ).pack(side=LEFT)

        res_wrap = Frame(right, bg=theme.CARD, highlightbackground=theme.BORDER, highlightthickness=1)
        res_wrap.pack(side="top", fill=BOTH, expand=True, pady=(4, 0))
        res_vsb = ttk.Scrollbar(res_wrap)
        res_vsb.pack(side=RIGHT, fill=Y)
        self._res_canvas = ttk.Canvas(res_wrap, highlightthickness=0, bg=theme.CARD)
        self._res_canvas.pack(side=LEFT, fill=BOTH, expand=True)
        res_vsb.configure(command=self._res_canvas.yview)
        self._res_canvas.configure(yscrollcommand=res_vsb.set)
        self._results_frame = Frame(self._res_canvas, bg=theme.CARD)
        self._res_window = self._res_canvas.create_window((0, 0), window=self._results_frame, anchor="nw")
        self._results_frame.bind("<Configure>", self._on_res_configure)
        self._res_canvas.bind("<Configure>", self._on_res_canvas_configure)
        self._res_canvas.bind("<Enter>", lambda _e: self._bind_res_wheel(True))
        self._res_canvas.bind("<Leave>", lambda _e: self._bind_res_wheel(False))

        self._status_var = StringVar(value="Готов")
        Label(self, textvariable=self._status_var, bg=theme.SIDEBAR, fg=theme.TEXT_MUTED, anchor="w", padx=8, pady=4).pack(
            side="bottom", fill=X,
        )

        self._update_provider_label()
        self._append_chat(
            "Система",
            "Привет! Спросите, например: «найди все pdf за май», «файлы за неделю» или «установщики». "
            "История диалога сохраняется до закрытия окна.",
            to_history=False,
        )
        self.after(200, self._load_suggestions)

    def _on_sug_configure(self, _event=None) -> None:
        self._sug_canvas.configure(scrollregion=self._sug_canvas.bbox("all"))

    def _on_sug_canvas_configure(self, event) -> None:
        self._sug_canvas.itemconfig(self._sug_window, width=event.width)

    def _on_res_configure(self, _event=None) -> None:
        self._res_canvas.configure(scrollregion=self._res_canvas.bbox("all"))

    def _on_res_canvas_configure(self, event) -> None:
        self._res_canvas.itemconfig(self._res_window, width=event.width)

    def _bind_sug_wheel(self, on: bool) -> None:
        if on:
            self._active_wheel = "sug"
            self.bind_all("<MouseWheel>", self._on_active_wheel)
        elif self._active_wheel == "sug":
            self.unbind_all("<MouseWheel>")
            self._active_wheel = None

    def _bind_res_wheel(self, on: bool) -> None:
        if on:
            self._active_wheel = "res"
            self.bind_all("<MouseWheel>", self._on_active_wheel)
        elif self._active_wheel == "res":
            self.unbind_all("<MouseWheel>")
            self._active_wheel = None

    def _on_active_wheel(self, event) -> None:
        delta = int(-1 * (event.delta / 120))
        if self._active_wheel == "sug":
            self._sug_canvas.yview_scroll(delta, "units")
        elif self._active_wheel == "res":
            self._res_canvas.yview_scroll(delta, "units")

    def _on_sug_wheel(self, event) -> None:
        self._sug_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _on_res_wheel(self, event) -> None:
        self._res_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def refresh(self) -> None:
        self._update_provider_label()

    def _update_provider_label(self) -> None:
        s = self._get_settings()
        hist = f" · история: {len(self._history) // 2}" if self._history else ""
        labels = {
            "rules": "режим: локальные правила (без сети)",
            "openai": f"режим: API ({s.ai_model})",
            "ollama": f"режим: Ollama ({s.ai_ollama_model})",
        }
        self._provider_var.set(labels.get(s.ai_provider, labels["rules"]) + hist)

    def _append_chat(self, who: str, text: str, *, to_history: bool = True) -> None:
        self._chat.configure(state="normal")
        self._chat.insert(END, f"\n{who}: {text}\n")
        self._chat.see(END)
        self._chat.configure(state="disabled")
        if to_history and who in ("Вы", "Помощник"):
            role = "user" if who == "Вы" else "assistant"
            self._history.append({"role": role, "content": text})
            if len(self._history) > _MAX_HISTORY * 2:
                self._history = self._history[-_MAX_HISTORY * 2 :]
            self._update_provider_label()

    def _clear_chat(self) -> None:
        self._history.clear()
        self._chat.configure(state="normal")
        self._chat.delete("1.0", END)
        self._chat.configure(state="disabled")
        self._append_chat(
            "Система",
            "История очищена. Задайте новый вопрос.",
            to_history=False,
        )
        self._update_provider_label()

    def _copy_chat(self) -> None:
        text = self._chat.get("1.0", END).strip()
        if not text:
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self._status_var.set("Чат скопирован в буфер")

    def _copy_result_paths(self) -> None:
        paths = [r.path for r in self._last_results if r.path]
        if not paths:
            messagebox.showinfo("ИИ-помощник", "Нет результатов для копирования.")
            return
        self.clipboard_clear()
        self.clipboard_append("\n".join(paths))
        self._status_var.set(f"Скопировано путей: {len(paths)}")

    def _set_busy(self, busy: bool, msg: str = "") -> None:
        self._busy = busy
        state = "disabled" if busy else "normal"
        self._send_btn.configure(state=state)
        if msg:
            self._status_var.set(msg)

    def _run_quick(self, query: str) -> None:
        if self._busy:
            return
        self._input.delete("1.0", END)
        self._input.insert("1.0", query)
        self._on_send()

    def _show_examples(self) -> None:
        self._input.delete("1.0", END)
        self._input.insert("1.0", "\n".join(QUICK_QUERIES))

    def _on_send(self) -> None:
        if self._busy:
            return
        text = self._input.get("1.0", END).strip()
        if not text:
            return
        # Если вставили несколько строк примеров — берём первую
        first_line = text.splitlines()[0].strip()
        self._input.delete("1.0", END)
        self._append_chat("Вы", first_line)
        self._set_busy(True, "Думаю…")
        history_snapshot = list(self._history[:-1])
        threading.Thread(
            target=self._process_query, args=(first_line, history_snapshot), daemon=True,
        ).start()

    def _process_query(self, text: str, history: list[dict[str, str]]) -> None:
        try:
            settings = self._get_settings()
            assistant = create_assistant(settings)
            intent = assistant.parse_user_query(text, history=history)
            if intent.action == "suggest":
                suggestions = assistant.generate_suggestions(
                    settings, self._get_index(), self._get_watched(),
                )
                msg = (
                    f"Фильтр: {format_intent_summary(intent)}. "
                    f"Нашёл {len(suggestions)} совет(ов). Смотрите панель справа."
                )
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
            self.after(0, lambda: self._append_chat("Ошибка", str(exc), to_history=False))
        finally:
            self.after(0, lambda: self._set_busy(False, "Готов"))

    def _format_search_reply(self, intent: SearchIntent, results: list[SearchResult]) -> str:
        total = sum(r.size for r in results)
        parts = [
            f"Найдено: {len(results)} ({human_size(total)})",
            f"фильтр: {format_intent_summary(intent)}",
        ]
        if results:
            top = ", ".join(r.name for r in results[:3])
            parts.append(f"например: {top}")
            desktop_n = sum(1 for r in results if r.source == "desktop")
            if desktop_n:
                parts.append(f"из отслеживаемых: {desktop_n} — можно «Сорт. все»")
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
        if not suggestions:
            Label(
                self._sug_inner, text="Нет советов", bg=theme.CARD, fg=theme.TEXT_MUTED,
            ).pack(pady=8)
            return
        for sug in suggestions:
            card = Frame(
                self._sug_inner, bg=theme.SIDEBAR, padx=8, pady=6,
                highlightbackground=theme.BORDER, highlightthickness=1,
            )
            card.pack(fill=X, pady=4, padx=4)
            Label(card, text=sug.title, font=("Segoe UI", 9, "bold"), bg=theme.SIDEBAR, anchor="w").pack(fill=X)
            Label(
                card, text=sug.description, font=("Segoe UI", 8),
                bg=theme.SIDEBAR, fg=theme.TEXT_MUTED, wraplength=280, justify="left",
            ).pack(fill=X, pady=(2, 4))
            btns = Frame(card, bg=theme.SIDEBAR)
            btns.pack(fill=X)
            paths = list((sug.payload or {}).get("paths") or [])
            if paths:
                ttk.Button(
                    btns, text="Сорт.", width=6,
                    command=lambda p=paths: self._confirm_sort(p),
                ).pack(side=LEFT, padx=(0, 2))
                ttk.Button(
                    btns, text="Откр.", width=6,
                    command=lambda p=paths[0]: self._on_open(p),
                ).pack(side=LEFT, padx=(0, 2))
                ttk.Button(
                    btns, text="Искл.", width=6,
                    command=lambda p=paths: self._confirm_exclude(p),
                ).pack(side=LEFT, padx=(0, 2))
            ttk.Button(
                btns, text="Применить",
                command=lambda s=sug: self._apply_suggestion(s),
            ).pack(side=LEFT)

    def _show_results(self, results: list[SearchResult]) -> None:
        self._last_results = list(results)
        self._clear_frame(self._results_frame)
        if not results:
            Label(
                self._results_frame, text="Ничего не найдено", bg=theme.CARD,
                fg=theme.TEXT_MUTED,
            ).pack(pady=8)
            return
        for res in results[:40]:
            row = Frame(self._results_frame, bg=theme.CARD)
            row.pack(fill=X, pady=2, padx=2)
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
            ttk.Button(row, text="Сорт.", width=5, command=lambda p=res.path: self._confirm_sort([p])).pack(side=RIGHT, padx=1)
            ttk.Button(row, text="Искл.", width=5, command=lambda p=res.path: self._confirm_exclude([p])).pack(side=RIGHT)

    def _desktop_result_paths(self) -> list[str]:
        return [r.path for r in self._last_results if r.source == "desktop" and r.path]

    def _sort_all_results(self) -> None:
        paths = self._desktop_result_paths()
        if not paths:
            messagebox.showinfo(
                "ИИ-помощник",
                "Нет файлов из отслеживаемых папок в результатах (архив сортировать отсюда нельзя).",
            )
            return
        self._confirm_sort(paths[:80])

    def _exclude_all_results(self) -> None:
        paths = self._desktop_result_paths()
        if not paths:
            messagebox.showinfo("ИИ-помощник", "Нет файлов из отслеживаемых папок для исключения.")
            return
        self._confirm_exclude(paths[:80])

    def _confirm_sort(self, paths: list[str]) -> None:
        if paths:
            self._on_sort(paths)

    def _confirm_exclude(self, paths: list[str]) -> None:
        if not messagebox.askyesno(
            "Исключить",
            f"Исключить из сортировки {len(paths)} элемент(ов)?",
        ):
            return
        self._on_exclude(paths)

    def _apply_suggestion(self, sug: Suggestion) -> None:
        action = sug.action
        payload = sug.payload or {}
        if action == "sort_paths":
            paths = payload.get("paths") or []
            if paths:
                self._confirm_sort(paths)
        elif action == "set_sort_mode":
            mode = payload.get("sort_mode")
            if mode and messagebox.askyesno(
                "Режим сортировки",
                f"Изменить режим сортировки?\n\n{sug.description}",
            ):
                self._on_sort_mode(mode)
        elif action == "enable_compression":
            if messagebox.askyesno(
                "Сжатие",
                f"Включить сжатие при сортировке?\n\n{sug.description}",
            ):
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
