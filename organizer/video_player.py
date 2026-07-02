"""Встроенный видеоплеер для панели предпросмотра (OpenCV)."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import BOTH, LEFT, RIGHT, X, Frame, Label, ttk

from . import theme
from .thumbs import fit_preview_image

try:
    import cv2
    _HAS_CV2 = True
except Exception:
    _HAS_CV2 = False

try:
    from PIL import Image, ImageTk
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False


def _format_time(seconds: float) -> str:
    if seconds < 0:
        return "0:00"
    total = int(seconds)
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


class VideoPlayer(Frame):
    """Виджет воспроизведения видео: play/pause, перемотка, освобождение cap при смене файла."""

    def __init__(self, parent, *, max_size: tuple[int, int] = (360, 280)) -> None:
        super().__init__(parent, bg=theme.IMAGE_PREVIEW_BG)
        self._max_size = max_size
        self._path: Path | None = None
        self._cap = None
        self._photo = None
        self._playing = False
        self._seeking = False
        self._was_playing_before_seek = False
        self._after_id: str | None = None
        self._fps = 25.0
        self._frame_count = 0
        self._duration = 0.0

        self._display = Label(self, bg=theme.IMAGE_PREVIEW_BG, anchor="center")
        self._display.pack(fill=BOTH, expand=True)

        controls = Frame(self, bg=theme.IMAGE_PREVIEW_BG)
        controls.pack(fill=X, pady=(4, 0))

        self._play_btn = ttk.Button(controls, text="▶", width=3, command=self._toggle_play)
        self._play_btn.pack(side=LEFT)

        self._time_var = tk.StringVar(value="0:00 / 0:00")
        Label(
            controls, textvariable=self._time_var, bg=theme.IMAGE_PREVIEW_BG,
            fg=theme.TEXT_MUTED, font=("Segoe UI", 8),
        ).pack(side=RIGHT, padx=(4, 0))

        self._seek_var = tk.DoubleVar(value=0.0)
        self._seek_scale = ttk.Scale(
            controls, from_=0, to=1, orient="horizontal",
            variable=self._seek_var, command=self._on_seek_drag,
        )
        self._seek_scale.pack(side=LEFT, fill=X, expand=True, padx=4)
        self._seek_scale.bind("<ButtonPress-1>", self._on_seek_start)
        self._seek_scale.bind("<ButtonRelease-1>", self._on_seek_end)

    @staticmethod
    def is_available() -> bool:
        return _HAS_CV2 and _HAS_PIL

    def load(self, path: Path) -> bool:
        """Открыть видео. True — встроенное воспроизведение возможно."""
        self.stop()
        if not self.is_available():
            return False
        p = Path(path)
        if not p.is_file():
            return False

        cap = cv2.VideoCapture(str(p))
        if not cap.isOpened():
            cap.release()
            return False

        try:
            self._fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
            if self._fps <= 0:
                self._fps = 25.0
            self._frame_count = max(0, int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0))
            self._duration = self._frame_count / self._fps if self._frame_count > 0 else 0.0
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = cap.read()
            if not ok or frame is None:
                cap.release()
                return False
        except Exception:
            cap.release()
            return False

        self._path = p
        self._cap = cap
        self._seek_scale.configure(to=max(self._frame_count, 1))
        self._show_frame(frame)
        self._update_seek_ui(0)
        self._playing = False
        self._play_btn.configure(text="▶")
        return True

    def stop(self) -> None:
        """Остановить воспроизведение и освободить VideoCapture."""
        self._playing = False
        if self._after_id is not None:
            try:
                self.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None
        self._path = None
        self._photo = None
        self._display.configure(image="", text="")
        self._play_btn.configure(text="▶")
        self._seek_var.set(0.0)
        self._time_var.set("0:00 / 0:00")

    def play(self) -> None:
        if self._cap is None:
            return
        self._playing = True
        self._play_btn.configure(text="⏸")
        self._schedule_frame()

    def pause(self) -> None:
        self._playing = False
        self._play_btn.configure(text="▶")
        if self._after_id is not None:
            try:
                self.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _toggle_play(self) -> None:
        if self._playing:
            self.pause()
        else:
            self.play()

    def _schedule_frame(self) -> None:
        if not self._playing or self._cap is None:
            return
        delay = max(1, int(1000 / self._fps))
        self._after_id = self.after(delay, self._next_frame)

    def _next_frame(self) -> None:
        self._after_id = None
        if not self._playing or self._cap is None:
            return
        ok, frame = self._cap.read()
        if not ok or frame is None:
            self.pause()
            return
        self._show_frame(frame)
        pos = int(self._cap.get(cv2.CAP_PROP_POS_FRAMES) or 0)
        self._update_seek_ui(pos)
        self._schedule_frame()

    def _show_frame(self, frame_bgr) -> None:
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(rgb)
        fitted = fit_preview_image(img, self._max_size)
        if fitted is None:
            return
        self._photo = ImageTk.PhotoImage(fitted)
        self._display.configure(image=self._photo, text="")

    def _update_seek_ui(self, frame_pos: int) -> None:
        if self._seeking:
            return
        self._seek_var.set(float(frame_pos))
        cur = frame_pos / self._fps if self._fps else 0.0
        self._time_var.set(f"{_format_time(cur)} / {_format_time(self._duration)}")

    def _on_seek_start(self, _event=None) -> None:
        self._seeking = True
        was_playing = self._playing
        self._was_playing_before_seek = was_playing
        if was_playing:
            self.pause()

    def _on_seek_end(self, _event=None) -> None:
        self._seeking = False
        self._apply_seek()
        if getattr(self, "_was_playing_before_seek", False):
            self.play()

    def _on_seek_drag(self, value: str) -> None:
        if not self._seeking:
            return
        try:
            frame = int(float(value))
        except ValueError:
            return
        cur = frame / self._fps if self._fps else 0.0
        self._time_var.set(f"{_format_time(cur)} / {_format_time(self._duration)}")

    def _apply_seek(self) -> None:
        if self._cap is None:
            return
        try:
            frame = int(self._seek_var.get())
        except (ValueError, tk.TclError):
            return
        self._cap.set(cv2.CAP_PROP_POS_FRAMES, frame)
        ok, frame_img = self._cap.read()
        if ok and frame_img is not None:
            self._show_frame(frame_img)
            self._update_seek_ui(frame)
