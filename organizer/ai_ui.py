"""Вкладка «ИИ-помощник» — чат-подобный интерфейс."""

from __future__ import annotations

import csv
import io
import threading
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, X, Y, Canvas, Frame, Label, StringVar, Text, filedialog, messagebox
from tkinter import ttk
from typing import Callable

from . import theme
from .ai_assistant import (
    QUICK_QUERIES,
    SUGGESTED_PROMPTS,
    SearchIntent,
    SearchResult,
    SortPlan,
    Suggestion,
    build_sort_preview,
    collect_sort_paths,
    create_assistant,
    create_conversational_agent,
    format_assistant_message,
    format_intent_summary,
    format_sort_plan_summary,
    format_storage_stats,
    compute_storage_stats,
    generate_suggestions,
    human_size,
    load_persisted_chat,
    save_persisted_chat,
    search_files,
)

_MAX_HISTORY = 20  # пар user/assistant в сессии (контекст агента — 10)


class AIAssistantPanel(Frame):
    """Панель ИИ-помощника с вводом запроса, подсказками и результатами."""

    def __init__(
        self,
        master,
        *,
        get_settings,
        get_index,
        get_watched_entries,
        get_sorter,
        on_open_path: Callable[[str], None],
        on_reveal_path: Callable[[str], None],
        on_sort_paths: Callable[[list[str]], None],
        on_exclude_paths: Callable[[list[str]], None],
        on_smart_cleanup: Callable[[], None],
        on_set_sort_mode: Callable[[str], None],
        on_enable_compression: Callable[[], None],
        on_show_desktop: Callable[[], None],
        on_open_settings: Callable[[], None],
        on_smart_folders: Callable[[list[str]], None] | None = None,
        on_apply_sort_plan: Callable[[SortPlan], None] | None = None,
        on_undo_last: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(master, bg=theme.BG)
        self._get_settings = get_settings
        self._get_index = get_index
        self._get_watched = get_watched_entries
        self._get_sorter = get_sorter
        self._on_open = on_open_path
        self._on_reveal = on_reveal_path
        self._on_sort = on_sort_paths
        self._on_exclude = on_exclude_paths
        self._on_cleanup = on_smart_cleanup
        self._on_sort_mode = on_set_sort_mode
        self._on_compress = on_enable_compression
        self._on_desktop = on_show_desktop
        self._on_settings = on_open_settings
        self._on_smart_folders = on_smart_folders
        self._on_apply_sort_plan = on_apply_sort_plan
        self._on_undo_last = on_undo_last
        self._busy = False
        self._typing_after: str | None = None
        self._history: list[dict[str, str]] = []
        self._last_results: list[SearchResult] = []
        self._pending_plan: SortPlan | None = None
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
        for q in SUGGESTED_PROMPTS:
            short = q if len(q) <= 28 else q[:26] + "…"
            ttk.Button(
                chips, text=short, width=max(10, len(short) + 1),
                command=lambda query=q: self._run_quick(query),
            ).pack(side=LEFT, padx=2, pady=2)

        plan_card = Frame(left, bg=theme.SIDEBAR, highlightbackground=theme.BORDER, highlightthickness=1)
        plan_card.pack(side="top", fill=X, pady=(0, 4), padx=0)
        plan_inner = Frame(plan_card, bg=theme.SIDEBAR, padx=8, pady=6)
        plan_inner.pack(fill=X)
        Label(plan_inner, text="План действий", font=("Segoe UI", 9, "bold"), bg=theme.SIDEBAR).pack(anchor="w")
        self._plan_var = StringVar(value="Нет активного плана")
        Label(
            plan_inner, textvariable=self._plan_var, bg=theme.SIDEBAR,
            fg=theme.TEXT_MUTED, font=("Segoe UI", 8), wraplength=520, justify="left",
        ).pack(anchor="w", pady=(2, 6))
        plan_btns = Frame(plan_inner, bg=theme.SIDEBAR)
        plan_btns.pack(fill=X)
        self._apply_plan_btn = ttk.Button(
            plan_btns, text="Применить", style="Accent.TButton",
            command=self._apply_pending_plan, state="disabled",
        )
        self._apply_plan_btn.pack(side=LEFT, padx=(0, 4))
        ttk.Button(plan_btns, text="Отмена", command=self._clear_pending_plan).pack(side=LEFT, padx=(0, 4))
        ttk.Button(plan_btns, text="Изменить", command=self._edit_pending_plan).pack(side=LEFT)

        clarify_frame = Frame(left, bg=theme.BG)
        clarify_frame.pack(side="top", fill=X, pady=(0, 4))
        self._clarify_frame = clarify_frame

        Label(left, text="Диалог", font=("Segoe UI", 10, "bold"), bg=theme.BG).pack(anchor="w")
        chat_wrap = Frame(left, bg=theme.CARD, highlightbackground=theme.BORDER, highlightthickness=1)
        chat_wrap.pack(side="top", fill=BOTH, expand=True, pady=(4, 0))
        self._chat = Text(
            chat_wrap, wrap="word", state="disabled",
            font=("Segoe UI", 10), bg=theme.CARD, fg=theme.TEXT,
            padx=4, pady=4,
        )
        self._chat.tag_configure("user_bubble", background="#dbeafe", lmargin1=40, lmargin2=40, rmargin=8, spacing3=6)
        self._chat.tag_configure("assistant_bubble", background="#f1f5f9", lmargin1=8, lmargin2=8, rmargin=40, spacing3=6)
        self._chat.tag_configure("system_bubble", foreground=theme.TEXT_MUTED, spacing3=4)
        self._chat.tag_configure("typing", foreground=theme.TEXT_MUTED, font=("Segoe UI", 9, "italic"))
        self._chat.tag_configure("user_label", foreground="#1d4ed8", font=("Segoe UI", 9, "bold"))
        self._chat.tag_configure("assistant_label", foreground="#475569", font=("Segoe UI", 9, "bold"))
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
        self._sug_canvas = Canvas(sug_wrap, highlightthickness=0, bg=theme.CARD)
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
        ttk.Button(
            self._batch_frame, text="CSV", width=5,
            command=self._export_results_csv,
        ).pack(side=LEFT, padx=(2, 0))

        res_wrap = Frame(right, bg=theme.CARD, highlightbackground=theme.BORDER, highlightthickness=1)
        res_wrap.pack(side="top", fill=BOTH, expand=True, pady=(4, 0))
        res_vsb = ttk.Scrollbar(res_wrap)
        res_vsb.pack(side=RIGHT, fill=Y)
        self._res_canvas = Canvas(res_wrap, highlightthickness=0, bg=theme.CARD)
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
        persisted = load_persisted_chat()
        settings = self._get_settings()
        if persisted and settings.ai_persist_chat:
            for msg in persisted[-_MAX_HISTORY * 2 :]:
                role = msg.get("role", "")
                who = "Вы" if role == "user" else "Помощник"
                if role in ("user", "assistant"):
                    self._append_chat(who, msg.get("content", ""), to_history=True, bubble=(role == "user"))
        self._append_chat(
            "Система",
            "Привет! Пишите как в чате: «разбери загрузки», «найди курсовые», «сожми установщики», "
            "«покажи что можно удалить». Сначала покажу план — потом «Применить».",
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

    def _append_chat(
        self,
        who: str,
        text: str,
        *,
        to_history: bool = True,
        bubble: bool | None = None,
    ) -> None:
        self._hide_typing()
        self._chat.configure(state="normal")
        if who == "Вы":
            self._chat.insert(END, "\n", "user_bubble")
            self._chat.insert(END, "Вы\n", "user_label")
            self._chat.insert(END, f"{text}\n", "user_bubble")
        elif who == "Помощник":
            self._chat.insert(END, "\n", "assistant_bubble")
            self._chat.insert(END, "Помощник\n", "assistant_label")
            self._chat.insert(END, f"{text}\n", "assistant_bubble")
        else:
            self._chat.insert(END, f"\n{who}: {text}\n", "system_bubble")
        self._chat.see(END)
        self._chat.configure(state="disabled")
        if to_history and who in ("Вы", "Помощник"):
            role = "user" if who == "Вы" else "assistant"
            self._history.append({"role": role, "content": text})
            if len(self._history) > _MAX_HISTORY * 2:
                self._history = self._history[-_MAX_HISTORY * 2 :]
            save_persisted_chat(
                self._history,
                enabled=self._get_settings().ai_persist_chat,
            )
            self._update_provider_label()

    def _show_typing(self) -> None:
        self._hide_typing()
        self._chat.configure(state="normal")
        self._chat.insert(END, "\n", "typing")
        self._chat.insert(END, "Помощник печатает…\n", "typing")
        self._chat.see(END)
        self._chat.configure(state="disabled")
        dots = ["", ".", "..", "..."]
        idx = [0]

        def tick():
            if not self._busy:
                return
            self._chat.configure(state="normal")
            self._chat.delete("typing_line.first", "typing_line.last")
            self._chat.insert("typing_line", f"Помощник печатает{dots[idx[0] % len(dots)]}", "typing")
            self._chat.configure(state="disabled")
            idx[0] += 1
            self._typing_after = self.after(400, tick)

        self._chat.mark_set("typing_line", "end-2l linestart")
        self._chat.mark_gravity("typing_line", "left")
        tick()

    def _hide_typing(self) -> None:
        if self._typing_after:
            try:
                self.after_cancel(self._typing_after)
            except Exception:
                pass
            self._typing_after = None
        content = self._chat.get("1.0", END)
        if "Помощник печатает" in content:
            self._chat.configure(state="normal")
            lines = content.splitlines()
            filtered = [ln for ln in lines if not ln.startswith("Помощник печатает")]
            self._chat.delete("1.0", END)
            if filtered:
                self._chat.insert("1.0", "\n".join(filtered) + "\n")
            self._chat.configure(state="disabled")

    def _clear_chat(self) -> None:
        self._history.clear()
        save_persisted_chat([], enabled=self._get_settings().ai_persist_chat)
        self._chat.configure(state="normal")
        self._chat.delete("1.0", END)
        self._chat.configure(state="disabled")
        self._clear_clarify_chips()
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

    def _export_results_csv(self) -> None:
        if not self._last_results:
            messagebox.showinfo("ИИ-помощник", "Нет результатов для экспорта.")
            return
        path = filedialog.asksaveasfilename(
            title="Экспорт результатов",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("Все файлы", "*.*")],
            initialfile="ai_search_results.csv",
        )
        if not path:
            return
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["path", "name", "category", "size", "source", "reason"])
        for r in self._last_results:
            writer.writerow([r.path, r.name, r.category, r.size, r.source, r.reason])
        Path(path).write_text(buf.getvalue(), encoding="utf-8-sig")
        self._status_var.set(f"Экспортировано: {len(self._last_results)} строк")

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
        self.after(0, self._show_typing)
        history_snapshot = list(self._history[:-1])[-20:]
        threading.Thread(
            target=self._process_query, args=(first_line, history_snapshot), daemon=True,
        ).start()

    def _process_query(self, text: str, history: list[dict[str, str]]) -> None:
        try:
            settings = self._get_settings()
            agent = create_conversational_agent(
                settings,
                self._get_index(),
                self._get_watched(),
                sorter=self._get_sorter(),
            )
            turn = agent.chat(text, history=history[-20:])

            if turn.action == "clarify":
                msg = turn.message
                if turn.next_steps:
                    msg += " Дальше: " + "; ".join(turn.next_steps[:2]) + "."
                self.after(0, lambda: self._clear_pending_plan())
                self.after(0, lambda: self._show_results([]))
                if turn.clarify_options:
                    self.after(0, lambda opts=list(turn.clarify_options): self._show_clarify_chips(opts))
            elif turn.action == "undo":
                msg = turn.message
                self.after(0, lambda m=turn.message: self._confirm_undo(m))
            elif turn.action == "exclude" and turn.pending_path:
                msg = turn.message
                self.after(0, lambda p=turn.pending_path: self._confirm_exclude([p]))
            elif turn.action == "open" and turn.pending_path:
                self._on_open(turn.pending_path)
                msg = turn.message
            elif turn.action == "reveal" and turn.pending_path:
                self._on_reveal(turn.pending_path)
                msg = turn.message
            elif turn.action == "stats":
                msg = turn.message
                if turn.next_steps:
                    msg += " Дальше: " + "; ".join(turn.next_steps[:2]) + "."
                self.after(0, lambda: self._show_results([]))
            elif turn.action == "suggest":
                msg = turn.message
                if turn.suggestions:
                    self.after(0, lambda s=list(turn.suggestions): self._show_suggestions(s))
                if turn.search_results:
                    self.after(0, lambda r=list(turn.search_results): self._show_results(r))
            elif turn.action == "sort" and turn.sort_plan is not None:
                plan = turn.sort_plan
                if not plan.items and plan.paths:
                    plan = self._prepare_sort_plan(plan, turn.search)
                summary = format_sort_plan_summary(plan)
                msg = turn.message if turn.message else summary
                if summary not in msg:
                    msg = f"{msg}\n\n{summary}"
                self.after(0, lambda p=plan: self._set_pending_plan(p))
                self.after(0, lambda p=plan: self._show_plan_items(p))
            else:
                msg = turn.message
                if turn.next_steps:
                    msg += " Дальше: " + "; ".join(turn.next_steps[:2]) + "."
                results = turn.search_results
                if not results and turn.search:
                    results = search_files(
                        turn.search,
                        index=self._get_index(),
                        watched_entries=self._get_watched(),
                    )
                self.after(0, lambda: self._clear_pending_plan())
                self.after(0, lambda r=list(results): self._show_results(r))
            self.after(0, lambda m=msg: self._append_chat("Помощник", m))
        except Exception as exc:
            self.after(0, lambda: self._append_chat("Ошибка", str(exc), to_history=False))
        finally:
            self.after(0, lambda: self._set_busy(False, "Готов"))
            self.after(0, self._hide_typing)

    def _prepare_sort_plan(
        self,
        plan: SortPlan,
        filter_intent: SearchIntent | None,
    ) -> SortPlan:
        settings = self._get_settings()
        watched = self._get_watched()
        paths = collect_sort_paths(
            plan,
            watched,
            filter_intent=filter_intent,
            index=self._get_index(),
        )
        plan.paths = paths[:120]
        return build_sort_preview(
            plan,
            settings=settings,
            sorter=self._get_sorter(),
            watched_entries=watched,
        )

    def _set_pending_plan(self, plan: SortPlan) -> None:
        self._pending_plan = plan
        ok = sum(1 for i in plan.items if i.dest_hint and not i.skip_reason)
        self._plan_var.set(
            f"{ok} из {len(plan.paths)} к раскладке · {plan.plan_type}"
            + (" · ZIP" if plan.enable_compression else "")
            + (f" · {plan.filter_summary}" if plan.filter_summary else "")
        )
        state = "normal" if plan.paths and ok > 0 else "disabled"
        self._apply_plan_btn.configure(state=state)

    def _edit_pending_plan(self) -> None:
        plan = self._pending_plan
        hint = plan.raw_query if plan and plan.raw_query else "сортируй по типу"
        self._input.delete("1.0", END)
        self._input.insert("1.0", hint)
        self._input.focus_set()
        self._status_var.set("Измените запрос и отправьте снова")

    def _confirm_undo(self, message: str) -> None:
        if not self._on_undo_last:
            self._append_chat("Система", "Отмена недоступна.", to_history=False)
            return
        if messagebox.askyesno("Отменить последнюю операцию", message):
            self._on_undo_last()
            self._append_chat("Помощник", "Запросил отмену последней сортировки.")

    def _clear_clarify_chips(self) -> None:
        for w in self._clarify_frame.winfo_children():
            w.destroy()

    def _clear_pending_plan(self) -> None:
        self._pending_plan = None
        self._plan_var.set("Нет активного плана")
        self._apply_plan_btn.configure(state="disabled")

    def _apply_pending_plan(self) -> None:
        plan = self._pending_plan
        if not plan or not plan.paths:
            messagebox.showinfo("ИИ-помощник", "Нет активного плана сортировки.")
            return
        ok = [i for i in plan.items if i.dest_hint and not i.skip_reason]
        preview = "\n".join(f"• {i.name} → {i.dest_hint}" for i in ok[:8])
        more = f"\n… и ещё {len(ok) - 8}" if len(ok) > 8 else ""
        if not messagebox.askyesno(
            "Применить план",
            f"Переместить {len(ok)} файл(ов)?\n\n{preview}{more}\n\n"
            "Это изменит расположение файлов на диске.",
        ):
            return
        if self._on_apply_sort_plan:
            self._on_apply_sort_plan(plan)
        elif plan.plan_type == "smart_folders" and self._on_smart_folders:
            self._on_smart_folders(plan.paths)
        else:
            self._on_sort(plan.paths)
        self._append_chat(
            "Помощник",
            f"Запустил раскладку ({len(plan.paths)} файл(ов)). Смотрите статус внизу окна.",
        )
        self._clear_pending_plan()

    def _show_plan_items(self, plan: SortPlan) -> None:
        """Показать элементы плана в панели результатов."""
        fake: list[SearchResult] = []
        for item in plan.items[:40]:
            fake.append(SearchResult(
                path=item.path,
                name=f"{item.name} → {item.dest_hint or item.skip_reason or '—'}",
                category=item.category,
                size=item.size,
                source="desktop",
                reason="ZIP" if item.will_compress else (item.skip_reason or "план"),
            ))
        self._show_results(fake)
        # Сохраняем реальные пути для «Сорт. все»
        self._last_results = [
            SearchResult(path=p, name=Path(p).name, source="desktop")
            for p in plan.paths
        ]

    def _show_clarify_chips(self, options: list[str]) -> None:
        self._clear_clarify_chips()
        Label(
            self._clarify_frame, text="Уточните:", bg=theme.BG, fg=theme.TEXT_MUTED,
            font=("Segoe UI", 8),
        ).pack(side=LEFT, padx=(0, 4))
        mapping = {
            "Сортировать по типу": "сортируй по типу",
            "Сортировать по дате": "сортируй по дате",
            "Разложить по моим папкам": "разложи по моим папкам",
            "Разбери загрузки": "разбери загрузки",
            "Найди PDF за этот год": "найди pdf за этот год",
        }
        for opt in options[:4]:
            q = mapping.get(opt, opt)
            if opt.startswith("Открыть настройки"):
                ttk.Button(
                    self._clarify_frame, text=opt[:20],
                    command=self._on_settings,
                ).pack(side=LEFT, padx=2)
                continue
            if q:
                ttk.Button(
                    self._clarify_frame, text=opt[:24],
                    command=lambda query=q: self._run_quick(query),
                ).pack(side=LEFT, padx=2)

    def _format_search_reply(
        self,
        intent: SearchIntent,
        results: list[SearchResult],
        next_steps: list[str] | None = None,
    ) -> str:
        total = sum(r.size for r in results)
        parts = [
            f"Найдено: {len(results)} ({human_size(total)})",
            f"фильтр: {format_intent_summary(intent)}",
        ]
        if results:
            by_cat: dict[str, int] = {}
            for r in results:
                cat = r.category or "—"
                by_cat[cat] = by_cat.get(cat, 0) + 1
            top_cats = sorted(by_cat.items(), key=lambda x: x[1], reverse=True)[:3]
            if top_cats:
                parts.append(
                    "категории: " + ", ".join(f"{c}×{n}" for c, n in top_cats)
                )
            top = ", ".join(r.name for r in results[:3])
            parts.append(f"например: {top}")
            desktop_n = sum(1 for r in results if r.source == "desktop")
            if desktop_n:
                parts.append(f"из отслеживаемых: {desktop_n} — «Сорт. все» или «отсортируй найденное»")
        msg = ". ".join(parts) + "."
        steps = next_steps or [
            "Уточните: «только pdf» / «за май»",
            "Или: «отсортируй найденное»",
        ]
        if not results:
            steps = ["Попробуйте «файлы за неделю» или «большие видео»"]
        return msg + " Дальше: " + "; ".join(steps[:2]) + "."

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
                    btns, text="Папк.", width=6,
                    command=lambda p=paths[0]: self._on_reveal(p),
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
            ttk.Button(row, text="Папк.", width=5, command=lambda p=res.path: self._on_reveal(p)).pack(side=RIGHT, padx=1)
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
        elif action == "smart_folders":
            paths = payload.get("paths") or []
            if paths and self._on_smart_folders:
                self._on_smart_folders(paths)
            elif not self._on_smart_folders:
                messagebox.showinfo("ИИ-помощник", sug.description)
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
