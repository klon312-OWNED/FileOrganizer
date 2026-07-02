"""Общий виджет предпросмотра для вкладок «Архив» и «Поиск по ПК»."""

from __future__ import annotations

from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, X, Y, Frame, Label, Text, Toplevel, ttk

from . import theme
from .preview import RichPreview, code_highlight_spans, get_rich_preview
from .thumbs import IMAGE_EXTS, PDF_EXTS, VIDEO_EXTS, fit_preview_image, get_thumbnail

try:
    from PIL import ImageTk
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False

PREVIEW_EXTS = IMAGE_EXTS | VIDEO_EXTS | PDF_EXTS

_DOC_FONT = ("Segoe UI", 11)
_CODE_FONT = ("Consolas", 10)


class PreviewPanel:
    """Панель: изображение сверху, «страница» документа снизу, метаданные."""

    def __init__(self, parent, *, width: int = 380, show_meta: bool = True) -> None:
        self._photo = None
        self._full_photo = None
        self._current_path: Path | None = None
        self._zoom = 1.0

        root = Frame(
            parent, width=width, bg=theme.CARD, padx=10, pady=10,
            highlightbackground=theme.BORDER, highlightthickness=1,
        )
        root.pack(side=RIGHT, fill=Y, padx=(8, 0))
        root.pack_propagate(False)
        self.frame = root

        Label(root, text="Предпросмотр", font=("Segoe UI", 10, "bold"), bg=theme.CARD).pack(anchor="w")

        img_outer = Frame(root, bg=theme.CARD)
        img_outer.pack(fill=X, pady=(6, 4))

        self._img_box = Frame(img_outer, height=320, bg=theme.IMAGE_PREVIEW_BG,
                              highlightbackground=theme.BORDER, highlightthickness=1)
        self._img_box.pack(fill=X)
        self._img_box.pack_propagate(False)
        self._img_label = Label(
            self._img_box, text="(выберите файл)", anchor="center",
            bg=theme.IMAGE_PREVIEW_BG, fg=theme.TEXT_MUTED,
        )
        self._img_label.pack(fill=BOTH, expand=True)
        self._img_label.bind("<Double-1>", self._on_image_double_click)

        zoom_row = Frame(img_outer, bg=theme.CARD)
        zoom_row.pack(fill=X, pady=(2, 0))
        self._zoom_var = ttk.Scale(zoom_row, from_=0.5, to=2.0, orient="horizontal", command=self._on_zoom)
        self._zoom_var.set(1.0)
        self._zoom_var.pack(fill=X)

        doc_wrap = Frame(root, bg=theme.DOC_PAGE_BORDER, padx=1, pady=1)
        doc_wrap.pack(fill=BOTH, expand=True, pady=(4, 6))
        doc_inner = Frame(doc_wrap, bg=theme.DOC_PAGE_BG, padx=14, pady=12)
        doc_inner.pack(fill=BOTH, expand=True)
        text_frame = Frame(doc_inner, bg=theme.DOC_PAGE_BG)
        text_frame.pack(fill=BOTH, expand=True)
        self._doc_text = Text(
            text_frame, wrap="word", font=_DOC_FONT, height=10,
            bg=theme.DOC_PAGE_BG, fg=theme.DOC_PAGE_FG,
            relief="flat", borderwidth=0, padx=0, pady=0,
        )
        vsb = ttk.Scrollbar(text_frame, orient="vertical", command=self._doc_text.yview)
        self._doc_text.configure(yscrollcommand=vsb.set, state="disabled")
        vsb.pack(side=RIGHT, fill=Y)
        self._doc_text.pack(side=LEFT, fill=BOTH, expand=True)
        self._setup_text_tags()

        self.meta_var = None
        if show_meta:
            from tkinter import StringVar
            self.meta_var = StringVar(value="")
            Label(
                root, textvariable=self.meta_var, justify="left", anchor="nw",
                wraplength=width - 24, bg=theme.CARD, fg=theme.TEXT, font=("Segoe UI", 9),
            ).pack(fill=X, pady=(0, 4))

        self._btn_frame = Frame(root, bg=theme.CARD)
        self._btn_frame.pack(fill=X)

    def _setup_text_tags(self) -> None:
        t = self._doc_text
        t.tag_configure("bold", font=("Segoe UI", 11, "bold"))
        t.tag_configure("italic", font=("Segoe UI", 11, "italic"))
        t.tag_configure("bold_italic", font=("Segoe UI", 11, "bold", "italic"))
        t.tag_configure("kw", foreground="#0550ae")
        t.tag_configure("comment", foreground="#6a737d")
        t.tag_configure("string", foreground="#0a3069")
        t.tag_configure("muted", foreground=theme.TEXT_MUTED)

    def add_button(self, text: str, command) -> None:
        ttk.Button(self._btn_frame, text=text, command=command).pack(fill=X, pady=(2, 0))

    def clear(self) -> None:
        self._photo = None
        self._current_path = None
        self._img_label.configure(image="", text="(выберите файл)")
        self._fill_doc_text("")

    def set_metadata(self, text: str) -> None:
        if self.meta_var is not None:
            self.meta_var.set(text)

    def show(self, path: Path, *, kind: str = "file") -> None:
        self._current_path = path
        self._zoom_var.set(1.0)
        self._zoom = 1.0
        ext = path.suffix.lower()

        if kind == "dir":
            self._show_image_placeholder("Папка")
            self._fill_doc_text("Папка — содержимое не показывается.\nНажмите «Показать в папке».")
            return

        if not path.exists():
            self._show_image_placeholder("Файл не найден")
            self._fill_doc_text("Файл отсутствует на диске.")
            return

        showed_image = False
        if _HAS_PIL and ext in PREVIEW_EXTS:
            try:
                img = fit_preview_image(get_thumbnail(path, max_size=(900, 900)), (360, 320))
                if img is not None:
                    self._photo = ImageTk.PhotoImage(img)
                    self._img_label.configure(image=self._photo, text="")
                    showed_image = True
            except Exception:
                showed_image = False

        if not showed_image:
            if ext in IMAGE_EXTS:
                self._show_image_placeholder("Не удалось загрузить\nизображение")
            elif ext in VIDEO_EXTS:
                self._show_image_placeholder("Видео")
            elif ext in PDF_EXTS:
                self._show_image_placeholder("PDF")
            else:
                self._show_image_placeholder("")

        try:
            rich = get_rich_preview(path)
        except Exception:
            rich = RichPreview(kind="unavailable", note="Ошибка предпросмотра.")
        if rich is not None:
            try:
                self._render_rich(rich, ext)
            except Exception:
                self._fill_doc_text("Не удалось отобразить предпросмотр этого файла.")
        elif ext in PDF_EXTS:
            self._fill_doc_text("PDF — первая страница показана выше.\nНажмите «Открыть» для полного просмотра.")
        elif ext in VIDEO_EXTS:
            self._fill_doc_text("Видео — кадр показан выше.\nНажмите «Открыть», чтобы воспроизвести.")
        elif ext in IMAGE_EXTS and showed_image:
            self._fill_doc_text("Изображение — см. предпросмотр выше.\nДвойной щелчок по картинке — увеличение.")
        else:
            self._fill_doc_text(
                "Предпросмотр для этого типа недоступен.\nНажмите «Открыть», чтобы посмотреть файл.",
            )

    def _show_image_placeholder(self, text: str) -> None:
        self._photo = None
        self._img_label.configure(image="", text=text or "(нет изображения)")

    def _fill_doc_text(self, text: str) -> None:
        self._doc_text.configure(state="normal", font=_DOC_FONT)
        self._doc_text.delete("1.0", END)
        if text:
            self._doc_text.insert("1.0", text)
        self._doc_text.configure(state="disabled")

    def _render_rich(self, rich: RichPreview, ext: str) -> None:
        self._doc_text.configure(state="normal")
        self._doc_text.delete("1.0", END)

        if rich.kind == "unavailable":
            self._doc_text.insert("1.0", rich.note, "muted")
            self._doc_text.configure(state="disabled")
            return

        if rich.kind == "table" and rich.table:
            lines = []
            for row in rich.table:
                lines.append("  ".join(cell.ljust(14)[:14] for cell in row))
            self._doc_text.configure(font=("Consolas", 9))
            self._doc_text.insert("1.0", "\n".join(lines))
            if rich.note:
                self._doc_text.insert(END, "\n\n", ())
                self._doc_text.insert(END, rich.note, "muted")
            self._doc_text.configure(state="disabled")
            return

        if rich.kind == "rich" and rich.spans:
            for span in rich.spans:
                tags = []
                if span.bold and span.italic:
                    tags.append("bold_italic")
                elif span.bold:
                    tags.append("bold")
                elif span.italic:
                    tags.append("italic")
                self._doc_text.insert(END, span.text, tuple(tags) if tags else ())
            self._doc_text.configure(state="disabled")
            return

        text = rich.plain or rich.note
        if rich.kind == "code":
            self._doc_text.configure(font=_CODE_FONT)
            self._doc_text.insert("1.0", text)
            for start, end, tag in code_highlight_spans(ext, text):
                self._doc_text.tag_add(tag, f"1.0+{start}c", f"1.0+{end}c")
        else:
            self._doc_text.insert("1.0", text)
        self._doc_text.configure(state="disabled")

    def _on_zoom(self, value: str) -> None:
        if not self._current_path or not _HAS_PIL:
            return
        try:
            self._zoom = float(value)
        except ValueError:
            return
        ext = self._current_path.suffix.lower()
        if ext not in PREVIEW_EXTS:
            return
        base = (int(360 * self._zoom), int(320 * self._zoom))
        try:
            img = fit_preview_image(get_thumbnail(self._current_path, max_size=(1200, 1200)), base)
        except Exception:
            img = None
        if img is not None:
            self._photo = ImageTk.PhotoImage(img)
            self._img_label.configure(image=self._photo)

    def _on_image_double_click(self, _event=None) -> None:
        if not self._current_path or not _HAS_PIL:
            return
        ext = self._current_path.suffix.lower()
        if ext not in PREVIEW_EXTS:
            return
        img = fit_preview_image(get_thumbnail(self._current_path, max_size=(1600, 1200)), (800, 600))
        if img is None:
            return
        win = Toplevel(self.frame.winfo_toplevel())
        win.title(self._current_path.name)
        win.configure(bg=theme.IMAGE_PREVIEW_BG)
        photo = ImageTk.PhotoImage(img)
        lbl = Label(win, image=photo, bg=theme.IMAGE_PREVIEW_BG)
        lbl.image = photo  # noqa: SLF001 — удержать ссылку
        lbl.pack(padx=8, pady=8)
