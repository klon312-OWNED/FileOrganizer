"""Эвристика: какие файлы скорее всего можно удалить.

Помечает «кандидатами на удаление» личные/мусорные файлы (установщики,
временные файлы, дубликаты, скриншоты, старые медиа в загрузках) и НЕ трогает
то, что похоже на учёбу/работу (документы в рабочих папках, по ключевым словам).

Это лишь подсказка — окончательное решение всегда за пользователем.
"""

from __future__ import annotations

import re
import time

# Ключевые слова «учёба/работа» — такие файлы считаем важными (не удалять)
WORK_STUDY_KEYWORDS = [
    "учеб", "лекц", "практик", "конспект", "реферат", "курсов", "курс",
    "диплом", "диссер", "семинар", "экзамен", "зачет", "зачёт", "лаб",
    "задани", "отчет", "отчёт", "доклад", "проект", "работа", "резюме",
    "договор", "счет", "счёт", "акт", "налог", "справк", "study", "course",
    "lecture", "report", "thesis", "homework", "assignment", "project",
    "work", "resume", "cv", "invoice", "contract",
    # частые написания латиницей
    "kursov", "kursach", "diplom", "referat", "lekci", "lekt", "praktik",
    "konspekt", "zadani", "otchet", "seminar", "ekzamen", "uchеb", "laborat",
]

# Офисные документы — защищаем сильнее (это часто учёба/работа)
OFFICE_EXTS = {".doc", ".docx", ".pdf", ".xls", ".xlsx", ".ppt", ".pptx",
               ".odt", ".ods", ".odp", ".rtf"}

WORK_STUDY_FOLDERS = [
    "документы", "documents", "onedrive", "учеб", "study", "work", "работа",
    "проект", "project", "универ", "институт", "школа", "diplom",
]

# Расширения «мусора»
TEMP_EXTS = {
    ".tmp", ".temp", ".log", ".bak", ".old", ".crdownload", ".part",
    ".partial", ".dmp", ".chk", ".gid",
}
INSTALLER_EXTS = {".exe", ".msi", ".apk", ".dmg", ".appx", ".msix"}
ARCHIVE_EXTS = {".zip", ".rar", ".7z", ".gz", ".tar", ".iso"}
PERSONAL_MEDIA_EXTS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".bmp",
    ".mp4", ".mov", ".avi", ".mkv", ".webm", ".3gp",
    ".mp3", ".wav", ".m4a", ".ogg",
}

# Папки, где обычно копится мусор
JUNK_FOLDERS = ["downloads", "загрузки", "temp", "tmp", "telegram desktop", "cache"]

# Признаки дубликата в имени
DUP_PATTERNS = [
    re.compile(r"\(\d+\)"),            # file (1), image (12)
    re.compile(r"-\s*копия"),          # - копия
    re.compile(r"\bкопия\b"),
    re.compile(r"\bcopy\b"),
    re.compile(r"_copy"),
]

# Имена-«мусор»: скриншоты, фото с телефона, случайные хеши
JUNK_NAME_PATTERNS = [
    re.compile(r"screenshot", re.I),
    re.compile(r"снимок экрана", re.I),
    re.compile(r"^img[_\-]?\d+", re.I),
    re.compile(r"^image[_ \-]?\(?\d", re.I),
    re.compile(r"^photo[_\-]?\d+", re.I),
    re.compile(r"^received_\d+", re.I),
    re.compile(r"^video_\d{4}", re.I),
    re.compile(r"^-?\d{6,}_-?\d{4,}"),   # -2147483648_-219114
    re.compile(r"^[0-9a-f]{16,}$", re.I),  # длинный хеш
]

OLD_DAYS = 365  # «старый» файл — не менялся больше года


def classify(item: dict) -> tuple[bool, str]:
    """Вернуть (кандидат_на_удаление, причина)."""
    name = item.get("name", "")
    folder = item.get("folder", "")
    ext = (item.get("ext", "") or "").lower()
    size = item.get("size", 0) or 0
    mtime = item.get("mtime", 0) or 0

    name_l = name.lower()
    folder_l = folder.lower()
    full_l = folder_l + "\\" + name_l

    # 1) Явная защита: учёба/работа по папке или ключевым словам в пути
    is_work_study = (
        any(k in full_l for k in WORK_STUDY_KEYWORDS)
        or any(f in folder_l for f in WORK_STUDY_FOLDERS)
    )

    # Временные файлы — мусор всегда, даже в рабочих папках
    if ext in TEMP_EXTS:
        return True, "Временный/служебный файл"

    if is_work_study:
        return False, ""

    score = 0
    reasons: list[str] = []

    in_junk_folder = any(f in folder_l for f in JUNK_FOLDERS)

    if ext in INSTALLER_EXTS:
        score += 3
        reasons.append("установщик программы")
    if any(p.search(name_l) for p in DUP_PATTERNS):
        score += 2
        reasons.append("похоже на дубликат")
    if any(p.search(name) for p in JUNK_NAME_PATTERNS):
        score += 2
        reasons.append("скриншот/фото/случайное имя")
    if ext in ARCHIVE_EXTS and in_junk_folder:
        score += 2
        reasons.append("архив в загрузках")
    if ext in PERSONAL_MEDIA_EXTS and in_junk_folder:
        score += 2
        reasons.append("личное медиа в загрузках")
    if in_junk_folder:
        score += 1

    # старый файл
    if mtime and (time.time() - mtime) > OLD_DAYS * 86400:
        score += 1
        reasons.append("старый файл")

    # большой личный медиафайл (>300 МБ)
    if ext in PERSONAL_MEDIA_EXTS and size > 300 * 1024 * 1024:
        score += 1
        reasons.append("большой медиафайл")

    # офисные документы защищаем: понижаем оценку, чтобы не зацепить учёбу/работу
    if ext in OFFICE_EXTS:
        score -= 2

    if score >= 3:
        return True, ", ".join(reasons) if reasons else "вероятно лишний файл"
    return False, ""
