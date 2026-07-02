"""Сводка для диалога «Умная уборка»."""

from __future__ import annotations


def summarize_cleanup_plan(plan: list[dict]) -> dict:
    """Сгруппировать кандидатов по причине с подсчётом размера."""
    by_reason: dict[str, dict[str, int]] = {}
    total_size = 0
    for item in plan:
        reason = item.get("reason") or "Другое"
        size = int(item.get("size") or 0)
        total_size += size
        bucket = by_reason.setdefault(reason, {"count": 0, "size": 0})
        bucket["count"] += 1
        bucket["size"] += size
    return {
        "total": len(plan),
        "total_size": total_size,
        "by_reason": by_reason,
    }


def format_cleanup_dialog(
    summary: dict,
    *,
    protected_count: int,
    excluded_paths: list[str],
    sample: list[dict],
    sample_limit: int = 12,
) -> str:
    """Текст подтверждения умной уборки."""
    lines = [
        f"Найдено кандидатов: {summary['total']}",
        f"Общий размер: {_human_size(summary['total_size'])}",
        "",
        "Категории:",
    ]
    for reason, info in sorted(summary["by_reason"].items(), key=lambda x: x[0]):
        lines.append(
            f"• {reason}: {info['count']} шт. ({_human_size(info['size'])})",
        )
    lines.append("")
    if protected_count:
        lines.append(
            f"Защищено от уборки: {protected_count} элемент(ов) "
            "(исключённые пути, служебные папки).",
        )
    if excluded_paths:
        preview = excluded_paths[:4]
        more = f" …и ещё {len(excluded_paths) - 4}" if len(excluded_paths) > 4 else ""
        lines.append("Исключённые пути:")
        lines.append("  " + "\n  ".join(preview) + more)
    lines.append("")
    lines.append("Превью:")
    for item in sample[:sample_limit]:
        lines.append(f"• {item.get('name', '?')} — {item.get('reason', '')}")
    extra = summary["total"] - min(sample_limit, len(sample))
    if extra > 0:
        lines.append(f"…и ещё {extra}")
    lines.append("")
    lines.append("Переместить в архив как обычную сортировку?")
    return "\n".join(lines)


def _human_size(num: int) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if num < 1024:
            return f"{num:.0f} {unit}" if unit == "Б" else f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} ПБ"
