"""Современная тема оформления для Tkinter/ttk (светлая и тёмная)."""

from __future__ import annotations

from tkinter import ttk

_PALETTES = {
    "light": {
        "BG": "#f4f6f9",
        "CARD": "#ffffff",
        "HEADER": "#1a365d",
        "HEADER_FG": "#ffffff",
        "ACCENT": "#2563eb",
        "ACCENT_HOVER": "#1d4ed8",
        "SUCCESS": "#059669",
        "TEXT": "#1e293b",
        "TEXT_MUTED": "#64748b",
        "BORDER": "#e2e8f0",
        "SIDEBAR": "#eef2ff",
        "PREVIEW_BG": "#0f172a",
        "PREVIEW_FG": "#cbd5e1",
        "IMAGE_PREVIEW_BG": "#f5f5f5",
        "DOC_PAGE_BG": "#ffffff",
        "DOC_PAGE_FG": "#1a1a1a",
        "DOC_PAGE_BORDER": "#e2e8f0",
        "ROW_ALT": "#f8fafc",
        "HISTORY_MOVE": "#dbeafe",
        "HISTORY_COPY": "#d1fae5",
        "DESKTOP_TILE": "#ffffff",
        "DESKTOP_TILE_SEL": "#dbeafe",
        "DESKTOP_TILE_BORDER": "#e2e8f0",
        "DESKTOP_TILE_SEL_BORDER": "#2563eb",
        "DESKTOP_ICON_BG": "#f1f5f9",
        "DESKTOP_MUTED": "#94a3b8",
    },
    "dark": {
        "BG": "#0f172a",
        "CARD": "#1e293b",
        "HEADER": "#020617",
        "HEADER_FG": "#f1f5f9",
        "ACCENT": "#3b82f6",
        "ACCENT_HOVER": "#2563eb",
        "SUCCESS": "#10b981",
        "TEXT": "#e2e8f0",
        "TEXT_MUTED": "#94a3b8",
        "BORDER": "#334155",
        "SIDEBAR": "#1e293b",
        "PREVIEW_BG": "#020617",
        "PREVIEW_FG": "#cbd5e1",
        "IMAGE_PREVIEW_BG": "#f5f5f5",
        "DOC_PAGE_BG": "#ffffff",
        "DOC_PAGE_FG": "#1a1a1a",
        "DOC_PAGE_BORDER": "#cbd5e1",
        "ROW_ALT": "#1e293b",
        "HISTORY_MOVE": "#1e3a5f",
        "HISTORY_COPY": "#134e4a",
        "DESKTOP_TILE": "#1e293b",
        "DESKTOP_TILE_SEL": "#1e3a8a",
        "DESKTOP_TILE_BORDER": "#334155",
        "DESKTOP_TILE_SEL_BORDER": "#3b82f6",
        "DESKTOP_ICON_BG": "#0f172a",
        "DESKTOP_MUTED": "#64748b",
    },
}

_current = "light"

# Публичные константы (обновляются в apply)
BG = _PALETTES["light"]["BG"]
CARD = _PALETTES["light"]["CARD"]
HEADER = _PALETTES["light"]["HEADER"]
HEADER_FG = _PALETTES["light"]["HEADER_FG"]
ACCENT = _PALETTES["light"]["ACCENT"]
ACCENT_HOVER = _PALETTES["light"]["ACCENT_HOVER"]
SUCCESS = _PALETTES["light"]["SUCCESS"]
TEXT = _PALETTES["light"]["TEXT"]
TEXT_MUTED = _PALETTES["light"]["TEXT_MUTED"]
BORDER = _PALETTES["light"]["BORDER"]
SIDEBAR = _PALETTES["light"]["SIDEBAR"]
PREVIEW_BG = _PALETTES["light"]["PREVIEW_BG"]
PREVIEW_FG = _PALETTES["light"]["PREVIEW_FG"]
IMAGE_PREVIEW_BG = _PALETTES["light"]["IMAGE_PREVIEW_BG"]
DOC_PAGE_BG = _PALETTES["light"]["DOC_PAGE_BG"]
DOC_PAGE_FG = _PALETTES["light"]["DOC_PAGE_FG"]
DOC_PAGE_BORDER = _PALETTES["light"]["DOC_PAGE_BORDER"]
ROW_ALT = _PALETTES["light"]["ROW_ALT"]
HISTORY_MOVE = _PALETTES["light"]["HISTORY_MOVE"]
HISTORY_COPY = _PALETTES["light"]["HISTORY_COPY"]
DESKTOP_TILE = _PALETTES["light"]["DESKTOP_TILE"]
DESKTOP_TILE_SEL = _PALETTES["light"]["DESKTOP_TILE_SEL"]
DESKTOP_TILE_BORDER = _PALETTES["light"]["DESKTOP_TILE_BORDER"]
DESKTOP_TILE_SEL_BORDER = _PALETTES["light"]["DESKTOP_TILE_SEL_BORDER"]
DESKTOP_ICON_BG = _PALETTES["light"]["DESKTOP_ICON_BG"]
DESKTOP_MUTED = _PALETTES["light"]["DESKTOP_MUTED"]


def _activate_palette(name: str) -> None:
    global _current, BG, CARD, HEADER, HEADER_FG, ACCENT, ACCENT_HOVER
    global SUCCESS, TEXT, TEXT_MUTED, BORDER, SIDEBAR, PREVIEW_BG, PREVIEW_FG
    global IMAGE_PREVIEW_BG, DOC_PAGE_BG, DOC_PAGE_FG, DOC_PAGE_BORDER
    global ROW_ALT, HISTORY_MOVE, HISTORY_COPY, DESKTOP_TILE, DESKTOP_TILE_SEL
    global DESKTOP_TILE_BORDER, DESKTOP_TILE_SEL_BORDER, DESKTOP_ICON_BG, DESKTOP_MUTED
    _current = name
    p = _PALETTES[name]
    BG = p["BG"]
    CARD = p["CARD"]
    HEADER = p["HEADER"]
    HEADER_FG = p["HEADER_FG"]
    ACCENT = p["ACCENT"]
    ACCENT_HOVER = p["ACCENT_HOVER"]
    SUCCESS = p["SUCCESS"]
    TEXT = p["TEXT"]
    TEXT_MUTED = p["TEXT_MUTED"]
    BORDER = p["BORDER"]
    SIDEBAR = p["SIDEBAR"]
    PREVIEW_BG = p["PREVIEW_BG"]
    PREVIEW_FG = p["PREVIEW_FG"]
    IMAGE_PREVIEW_BG = p["IMAGE_PREVIEW_BG"]
    DOC_PAGE_BG = p["DOC_PAGE_BG"]
    DOC_PAGE_FG = p["DOC_PAGE_FG"]
    DOC_PAGE_BORDER = p["DOC_PAGE_BORDER"]
    ROW_ALT = p["ROW_ALT"]
    HISTORY_MOVE = p["HISTORY_MOVE"]
    HISTORY_COPY = p["HISTORY_COPY"]
    DESKTOP_TILE = p["DESKTOP_TILE"]
    DESKTOP_TILE_SEL = p["DESKTOP_TILE_SEL"]
    DESKTOP_TILE_BORDER = p["DESKTOP_TILE_BORDER"]
    DESKTOP_TILE_SEL_BORDER = p["DESKTOP_TILE_SEL_BORDER"]
    DESKTOP_ICON_BG = p["DESKTOP_ICON_BG"]
    DESKTOP_MUTED = p["DESKTOP_MUTED"]


def current_palette() -> str:
    return _current


def recolor_widgets(root, from_palette: str, to_palette: str) -> None:
    """Обновить bg/fg у Tk-виджетов после смены палитры без перезапуска."""
    old = _PALETTES.get(from_palette, {})
    new = _PALETTES.get(to_palette, {})
    if not old or not new:
        return

    def visit(widget) -> None:
        for prop in ("bg", "fg", "highlightbackground", "activebackground"):
            try:
                val = widget.cget(prop)
            except Exception:
                continue
            for key, old_color in old.items():
                if val == old_color and key in new:
                    try:
                        widget.configure(**{prop: new[key]})
                    except Exception:
                        pass
                    break
        for child in widget.winfo_children():
            visit(child)

    visit(root)


def apply(root, *, dark: bool = False, large_text: bool = False) -> ttk.Style:
    _activate_palette("dark" if dark else "light")
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    root.configure(bg=BG)

    base = 11 if large_text else 10
    small = max(9, base - 1)
    head = base + 4
    style.configure(".", background=BG, foreground=TEXT, font=("Segoe UI", base))
    style.configure("TFrame", background=BG)
    style.configure("Card.TFrame", background=CARD)
    style.configure("Sidebar.TFrame", background=SIDEBAR)
    style.configure("Header.TFrame", background=HEADER)

    style.configure("TLabel", background=BG, foreground=TEXT)
    style.configure("Card.TLabel", background=CARD, foreground=TEXT)
    style.configure("Sidebar.TLabel", background=SIDEBAR, foreground=TEXT)
    style.configure("Muted.TLabel", background=BG, foreground=TEXT_MUTED, font=("Segoe UI", small))
    style.configure("Header.TLabel", background=HEADER, foreground=HEADER_FG, font=("Segoe UI", head, "bold"))
    style.configure("Subheader.TLabel", background=HEADER, foreground="#93c5fd", font=("Segoe UI", small))

    style.configure("TNotebook", background=BG, borderwidth=0)
    style.configure("TNotebook.Tab", padding=[14, 8], font=("Segoe UI", base))
    style.map("TNotebook.Tab", background=[("selected", CARD), ("!selected", BG)])

    style.configure(
        "Treeview",
        background=CARD,
        fieldbackground=CARD,
        foreground=TEXT,
        rowheight=34 if large_text else 30,
        font=("Segoe UI", base),
        borderwidth=0,
    )
    style.configure(
        "Treeview.Heading",
        background=SIDEBAR,
        foreground=TEXT,
        font=("Segoe UI", base, "bold"),
        relief="flat",
        padding=6,
    )
    style.map("Treeview", background=[("selected", ACCENT)], foreground=[("selected", "#ffffff")])

    style.configure("TButton", padding=[10, 6], font=("Segoe UI", base))
    style.configure("Accent.TButton", background=ACCENT, foreground="#ffffff", font=("Segoe UI", base, "bold"))
    style.map("Accent.TButton", background=[("active", ACCENT_HOVER), ("pressed", ACCENT_HOVER)])

    style.configure("Success.TButton", background=SUCCESS, foreground="#ffffff")
    style.map("Success.TButton", background=[("active", "#047857")])

    style.configure("TCombobox", padding=4)
    style.configure("TEntry", padding=4)
    style.configure("TCheckbutton", background=BG)
    style.configure("Sidebar.TCheckbutton", background=SIDEBAR)
    style.configure("TRadiobutton", background=BG)

    return style
