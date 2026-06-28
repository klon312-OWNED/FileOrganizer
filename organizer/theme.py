"""Современная тема оформления для Tkinter/ttk."""

from __future__ import annotations

from tkinter import ttk

# Палитра
BG = "#f4f6f9"
CARD = "#ffffff"
HEADER = "#1a365d"
HEADER_FG = "#ffffff"
ACCENT = "#2563eb"
ACCENT_HOVER = "#1d4ed8"
SUCCESS = "#059669"
TEXT = "#1e293b"
TEXT_MUTED = "#64748b"
BORDER = "#e2e8f0"
SIDEBAR = "#eef2ff"
PREVIEW_BG = "#0f172a"
PREVIEW_FG = "#cbd5e1"
ROW_ALT = "#f8fafc"
HISTORY_MOVE = "#dbeafe"
HISTORY_COPY = "#d1fae5"
DESKTOP_TILE = "#ffffff"
DESKTOP_TILE_SEL = "#dbeafe"
DESKTOP_TILE_BORDER = "#e2e8f0"
DESKTOP_TILE_SEL_BORDER = "#2563eb"
DESKTOP_ICON_BG = "#f1f5f9"
DESKTOP_MUTED = "#94a3b8"


def apply(root) -> ttk.Style:
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    root.configure(bg=BG)

    style.configure(".", background=BG, foreground=TEXT, font=("Segoe UI", 10))
    style.configure("TFrame", background=BG)
    style.configure("Card.TFrame", background=CARD)
    style.configure("Sidebar.TFrame", background=SIDEBAR)
    style.configure("Header.TFrame", background=HEADER)

    style.configure("TLabel", background=BG, foreground=TEXT)
    style.configure("Card.TLabel", background=CARD, foreground=TEXT)
    style.configure("Sidebar.TLabel", background=SIDEBAR, foreground=TEXT)
    style.configure("Muted.TLabel", background=BG, foreground=TEXT_MUTED, font=("Segoe UI", 9))
    style.configure("Header.TLabel", background=HEADER, foreground=HEADER_FG, font=("Segoe UI", 14, "bold"))
    style.configure("Subheader.TLabel", background=HEADER, foreground="#93c5fd", font=("Segoe UI", 9))

    style.configure("TNotebook", background=BG, borderwidth=0)
    style.configure("TNotebook.Tab", padding=[14, 8], font=("Segoe UI", 10))
    style.map("TNotebook.Tab", background=[("selected", CARD), ("!selected", BG)])

    style.configure(
        "Treeview",
        background=CARD,
        fieldbackground=CARD,
        foreground=TEXT,
        rowheight=30,
        font=("Segoe UI", 10),
        borderwidth=0,
    )
    style.configure(
        "Treeview.Heading",
        background=SIDEBAR,
        foreground=TEXT,
        font=("Segoe UI", 10, "bold"),
        relief="flat",
        padding=6,
    )
    style.map("Treeview", background=[("selected", ACCENT)], foreground=[("selected", "#ffffff")])

    style.configure("TButton", padding=[10, 6], font=("Segoe UI", 10))
    style.configure("Accent.TButton", background=ACCENT, foreground="#ffffff", font=("Segoe UI", 10, "bold"))
    style.map("Accent.TButton", background=[("active", ACCENT_HOVER), ("pressed", ACCENT_HOVER)])

    style.configure("Success.TButton", background=SUCCESS, foreground="#ffffff")
    style.map("Success.TButton", background=[("active", "#047857")])

    style.configure("TCombobox", padding=4)
    style.configure("TEntry", padding=4)
    style.configure("TCheckbutton", background=BG)
    style.configure("Sidebar.TCheckbutton", background=SIDEBAR)
    style.configure("TRadiobutton", background=BG)

    return style
