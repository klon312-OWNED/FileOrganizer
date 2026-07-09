"""ИИ-помощник: локальные эвристики и опциональный LLM для поиска и подсказок."""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from .classify import classify
from .config import OTHER_CATEGORY, Settings
from .database import FileIndex
from .layouts import MONTHS_RU

Provider = Literal["rules", "openai", "ollama"]

# Ключевые слова категорий (рус/англ)
_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "Картинки": ["картин", "фото", "изображен", "image", "photo", "jpg", "png", "jpeg"],
    "Видео": ["видео", "video", "movie", "фильм", "mp4", "mkv"],
    "Музыка": ["музык", "music", "audio", "песн", "mp3", "flac"],
    "Документы": ["документ", "document", "pdf", "word", "excel", "текст", "doc"],
    "Архивы": ["архив", "archive", "zip", "rar", "7z"],
    "Программы": ["программ", "установщик", "installer", "exe", "msi", "app"],
    "Код": ["код", "code", "script", "python", "js"],
    "Папки": ["папк", "folder", "директор"],
}

_MONTH_NAMES: dict[str, int] = {}
for num, label in MONTHS_RU.items():
    _MONTH_NAMES[label.split("-", 1)[1].lower()] = num
    _MONTH_NAMES[label.lower()] = num
for i, name in enumerate(
    ("январ", "феврал", "март", "апрел", "май", "мая", "июн", "июл",
     "август", "сентябр", "октябр", "ноябр", "декабр"),
    start=1,
):
    _MONTH_NAMES[name] = i

_SIZE_PATTERNS = [
    (re.compile(r"(\d+(?:[.,]\d+)?)\s*(гб|gb)", re.I), 1024 ** 3),
    (re.compile(r"(\d+(?:[.,]\d+)?)\s*(мб|mb)", re.I), 1024 ** 2),
    (re.compile(r"(\d+(?:[.,]\d+)?)\s*(кб|kb)", re.I), 1024),
]

_LARGE_WORDS = ("больш", "крупн", "тяжёл", "тяжел", "large", "big", "huge")
_SMALL_WORDS = ("маленьк", "мелк", "small", "tiny")


@dataclass
class SearchIntent:
    """Разобранный запрос пользователя."""

    action: str = "search"
    categories: list[str] = field(default_factory=list)
    extensions: list[str] = field(default_factory=list)
    month: int | None = None
    year: int | None = None
    min_size: int | None = None
    max_size: int | None = None
    name_contains: str = ""
    source: str = "all"
    raw_query: str = ""
    delete_candidates: bool = False


@dataclass
class SearchResult:
    path: str
    name: str
    category: str = ""
    size: int = 0
    source: str = ""
    reason: str = ""


@dataclass
class Suggestion:
    id: str
    title: str
    description: str
    action: str
    payload: dict[str, Any] = field(default_factory=dict)
    priority: int = 0


def human_size(num: int) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if num < 1024:
            return f"{num:.0f} {unit}" if unit == "Б" else f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} ПБ"


class RulesAssistant:
    """Локальный помощник без сети — ключевые слова и эвристики."""

    def parse_user_query(self, text: str) -> SearchIntent:
        q = text.strip()
        low = q.lower()
        intent = SearchIntent(raw_query=q)

        if any(w in low for w in ("подсказ", "совет", "рекоменд", "что сортир", "что удал")):
            intent.action = "suggest"

        if any(w in low for w in ("удал", "мусор", "лишн", "очист", "уборк")):
            intent.delete_candidates = True

        for cat, keys in _CATEGORY_KEYWORDS.items():
            if any(k in low for k in keys):
                if cat not in intent.categories:
                    intent.categories.append(cat)

        ext_match = re.findall(r"\.([a-z0-9]{1,8})\b", low)
        for ext in ext_match:
            e = f".{ext}"
            if e not in intent.extensions:
                intent.extensions.append(e)

        if "pdf" in low and ".pdf" not in intent.extensions:
            intent.extensions.append(".pdf")
            if "Документы" not in intent.categories:
                intent.categories.append("Документы")

        year_m = re.search(r"(20\d{2})", low)
        if year_m:
            intent.year = int(year_m.group(1))

        for key, num in _MONTH_NAMES.items():
            if key in low:
                intent.month = num
                break

        for pattern, mult in _SIZE_PATTERNS:
            m = pattern.search(low)
            if m:
                val = float(m.group(1).replace(",", "."))
                size = int(val * mult)
                if any(w in low for w in ("меньш", "до ", "макс", "не больш")):
                    intent.max_size = size
                else:
                    intent.min_size = size
                break

        if intent.min_size is None and any(w in low for w in _LARGE_WORDS):
            intent.min_size = 100 * 1024 * 1024
        if intent.max_size is None and any(w in low for w in _SMALL_WORDS):
            intent.max_size = 1024 * 1024

        if "архив" in low and "zip" not in low:
            intent.source = "archive"
        elif any(w in low for w in ("рабоч", "desktop", "загруз", "download", "отслеж")):
            intent.source = "desktop"

        if any(w in low for w in ("найд", "покаж", "ищ", "search", "find", "где ")):
            intent.action = "search"

        quoted = re.findall(r"[«\"']([^»\"']+)[»\"']", q)
        if quoted:
            intent.name_contains = quoted[0].lower()
        elif intent.action == "search":
            stop = {
                "найди", "найти", "покажи", "показать", "все", "всех", "за", "из",
                "большие", "большой", "маленькие", "файлы", "файл", "в", "на",
                "май", "июнь", "июль", "архиве", "рабочем", "столе",
            }
            tokens = [t for t in re.split(r"\s+", low) if t and t not in stop and len(t) > 2]
            if tokens and not intent.categories and not intent.extensions:
                intent.name_contains = " ".join(tokens[:4])

        return intent

    def search(
        self,
        intent: SearchIntent,
        *,
        index: FileIndex,
        watched_entries: list[dict],
    ) -> list[SearchResult]:
        results: list[SearchResult] = []

        if intent.source in ("all", "archive"):
            for row in index.query():
                if not self._matches_intent_row(intent, row):
                    continue
                results.append(SearchResult(
                    path=row["path"],
                    name=row["name"],
                    category=row["category"],
                    size=int(row["size"] or 0),
                    source="archive",
                ))

        if intent.source in ("all", "desktop"):
            for entry in watched_entries:
                if not self._matches_intent_entry(intent, entry):
                    continue
                item = {
                    "name": entry.get("name", ""),
                    "folder": entry.get("folder", ""),
                    "ext": Path(entry.get("name", "")).suffix.lower(),
                    "size": entry.get("size", 0),
                    "mtime": entry.get("mtime", 0),
                }
                reason = ""
                if intent.delete_candidates:
                    is_junk, why = classify(item)
                    if not is_junk:
                        continue
                    reason = why
                results.append(SearchResult(
                    path=entry["path"],
                    name=entry["name"],
                    category=entry.get("category", ""),
                    size=int(entry.get("size", 0)),
                    source="desktop",
                    reason=reason,
                ))

        if intent.delete_candidates and intent.source != "desktop":
            for entry in watched_entries:
                item = {
                    "name": entry.get("name", ""),
                    "folder": entry.get("folder", ""),
                    "ext": Path(entry.get("name", "")).suffix.lower(),
                    "size": entry.get("size", 0),
                    "mtime": entry.get("mtime", 0),
                }
                is_junk, why = classify(item)
                if not is_junk:
                    continue
                if entry["path"] in {r.path for r in results}:
                    continue
                results.append(SearchResult(
                    path=entry["path"],
                    name=entry["name"],
                    category=entry.get("category", ""),
                    size=int(entry.get("size", 0)),
                    source="desktop",
                    reason=why,
                ))

        results.sort(key=lambda r: r.size, reverse=True)
        return results[:200]

    def generate_suggestions(
        self,
        settings: Settings,
        index: FileIndex,
        watched_entries: list[dict],
    ) -> list[Suggestion]:
        suggestions: list[Suggestion] = []
        sortable = [e for e in watched_entries if e.get("sortable")]
        excluded = [e for e in watched_entries if e.get("excluded")]

        if sortable:
            total_size = sum(int(e.get("size", 0)) for e in sortable)
            by_cat: dict[str, list[dict]] = {}
            for e in sortable:
                by_cat.setdefault(e.get("category", OTHER_CATEGORY), []).append(e)
            top_cat = max(by_cat, key=lambda c: len(by_cat[c]))
            suggestions.append(Suggestion(
                id="sort_clutter",
                title=f"Сортировать {len(sortable)} элементов",
                description=(
                    f"В отслеживаемых папках {len(sortable)} файлов/папок "
                    f"({human_size(total_size)}). Больше всего: «{top_cat}» "
                    f"({len(by_cat[top_cat])} шт.)."
                ),
                action="sort_paths",
                payload={"paths": [e["path"] for e in sortable[:50]]},
                priority=90,
            ))

        archive_count = index.count()
        if archive_count > 0:
            stats = index.stats_by_category()
            if stats:
                dominant = stats[0]
                dom_cat = dominant["category"]
                dom_cnt = int(dominant["cnt"])
                if dom_cnt > archive_count * 0.6 and settings.sort_mode != "type_only":
                    suggestions.append(Suggestion(
                        id="sort_mode_type",
                        title="Режим «только по типу»",
                        description=(
                            f"В архиве {dom_cnt} из {archive_count} файлов — "
                            f"категория «{dom_cat}». Плоская раскладка по типу упростит навигацию."
                        ),
                        action="set_sort_mode",
                        payload={"sort_mode": "type_only"},
                        priority=50,
                    ))
                elif len(stats) >= 4 and settings.sort_mode == "flat":
                    suggestions.append(Suggestion(
                        id="sort_mode_type_date",
                        title="Режим «по типу и дате»",
                        description=(
                            f"В архиве {len(stats)} категорий. Режим type_date "
                            "разложит файлы по годам и месяцам."
                        ),
                        action="set_sort_mode",
                        payload={"sort_mode": "type_date"},
                        priority=45,
                    ))

        installers = [
            e for e in sortable
            if Path(e["name"]).suffix.lower() in {".exe", ".msi", ".msix", ".apk"}
            and int(e.get("size", 0)) > 50 * 1024 * 1024
        ]
        if installers and not settings.compression_enabled:
            sz = sum(int(e.get("size", 0)) for e in installers)
            suggestions.append(Suggestion(
                id="enable_compression",
                title="Включить сжатие при сортировке",
                description=(
                    f"Найдено {len(installers)} крупных установщиков "
                    f"({human_size(sz)}). ZIP сэкономит место в архиве."
                ),
                action="enable_compression",
                payload={},
                priority=70,
            ))

        junk: list[dict] = []
        for e in watched_entries:
            item = {
                "name": e.get("name", ""),
                "folder": e.get("folder", ""),
                "ext": Path(e.get("name", "")).suffix.lower(),
                "size": e.get("size", 0),
                "mtime": e.get("mtime", 0),
            }
            is_junk, why = classify(item)
            if is_junk:
                junk.append({**e, "reason": why})

        if junk:
            jsize = sum(int(e.get("size", 0)) for e in junk)
            suggestions.append(Suggestion(
                id="smart_cleanup",
                title=f"Умная уборка: {len(junk)} кандидатов",
                description=(
                    f"Эвристика нашла {len(junk)} вероятно лишних файлов "
                    f"({human_size(jsize)}). Проверьте перед удалением."
                ),
                action="smart_cleanup",
                payload={"paths": [e["path"] for e in junk[:30]]},
                priority=80,
            ))

        dup_names: dict[str, list[dict]] = {}
        for e in sortable:
            base = re.sub(r"\(\d+\)", "", e["name"].lower()).strip()
            dup_names.setdefault(base, []).append(e)
        dups = [g for g in dup_names.values() if len(g) > 1]
        if dups:
            suggestions.append(Suggestion(
                id="review_duplicates",
                title=f"Похожие дубликаты: {len(dups)} групп",
                description=(
                    "Есть файлы с похожими именами (копии). "
                    "Проверьте перед сортировкой или удалением."
                ),
                action="search",
                payload={"query": "похоже на дубликат"},
                priority=40,
            ))

        if excluded:
            suggestions.append(Suggestion(
                id="review_excluded",
                title=f"Исключено из сортировки: {len(excluded)}",
                description="Проверьте, нужны ли все исключения — возможно, часть уже неактуальна.",
                action="show_desktop",
                payload={},
                priority=20,
            ))

        if not suggestions:
            suggestions.append(Suggestion(
                id="all_good",
                title="Всё аккуратно",
                description="Отслеживаемые папки пусты или уже отсортированы. Добавьте файлы или папки для слежения.",
                action="none",
                payload={},
                priority=0,
            ))

        suggestions.sort(key=lambda s: s.priority, reverse=True)
        return suggestions

    def _matches_intent_row(self, intent: SearchIntent, row) -> bool:
        if intent.categories and row["category"] not in intent.categories:
            return False
        ext = (row["extension"] or "").lower()
        if intent.extensions and ext not in intent.extensions:
            return False
        if intent.year and int(row["year"]) != intent.year:
            return False
        if intent.month and int(row["month"]) != intent.month:
            return False
        size = int(row["size"] or 0)
        if intent.min_size is not None and size < intent.min_size:
            return False
        if intent.max_size is not None and size > intent.max_size:
            return False
        if intent.name_contains and intent.name_contains not in row["name"].lower():
            return False
        return True

    def _matches_intent_entry(self, intent: SearchIntent, entry: dict) -> bool:
        if intent.categories and entry.get("category") not in intent.categories:
            return False
        ext = Path(entry.get("name", "")).suffix.lower()
        if intent.extensions and ext not in intent.extensions:
            return False
        if intent.year or intent.month:
            mtime = entry.get("mtime", 0) or 0
            if mtime:
                dt = datetime.fromtimestamp(mtime)
                if intent.year and dt.year != intent.year:
                    return False
                if intent.month and dt.month != intent.month:
                    return False
        size = int(entry.get("size", 0))
        if intent.min_size is not None and size < intent.min_size:
            return False
        if intent.max_size is not None and size > intent.max_size:
            return False
        if intent.name_contains and intent.name_contains not in entry.get("name", "").lower():
            return False
        return True


class LLMAssistant:
    """Опциональный LLM-клиент (OpenAI-совместимый API или Ollama)."""

    def __init__(self, settings: Settings, rules: RulesAssistant | None = None) -> None:
        self.settings = settings
        self.rules = rules or RulesAssistant()

    @property
    def provider(self) -> Provider:
        p = self.settings.ai_provider
        return p if p in ("rules", "openai", "ollama") else "rules"

    def parse_user_query(self, text: str) -> SearchIntent:
        if self.provider == "rules":
            return self.rules.parse_user_query(text)
        try:
            parsed = self._llm_parse(text)
            if parsed:
                return parsed
        except Exception:
            pass
        return self.rules.parse_user_query(text)

    def generate_suggestions(
        self,
        settings: Settings,
        index: FileIndex,
        watched_entries: list[dict],
    ) -> list[Suggestion]:
        base = self.rules.generate_suggestions(settings, index, watched_entries)
        if self.provider == "rules":
            return base
        try:
            extra = self._llm_suggestions(settings, index, watched_entries)
            if extra:
                seen = {s.id for s in base}
                for s in extra:
                    if s.id not in seen:
                        base.append(s)
                base.sort(key=lambda s: s.priority, reverse=True)
        except Exception:
            pass
        return base

    def _metadata_summary(
        self,
        settings: Settings,
        index: FileIndex,
        watched_entries: list[dict],
    ) -> dict:
        sortable = [e for e in watched_entries if e.get("sortable")]
        stats = index.stats_by_category()
        return {
            "sort_mode": settings.sort_mode,
            "compression_enabled": settings.compression_enabled,
            "watched_folders": settings.watched_folders,
            "archive_files": index.count(),
            "archive_size": index.total_size(),
            "desktop_sortable": len(sortable),
            "desktop_size": sum(int(e.get("size", 0)) for e in sortable),
            "categories_in_archive": [
                {"name": r["category"], "count": int(r["cnt"]), "size": int(r["total_size"])}
                for r in stats[:12]
            ],
            "desktop_by_category": _count_by(watched_entries, "category"),
        }

    def _llm_parse(self, text: str) -> SearchIntent | None:
        system = (
            "Ты парсер запросов файлового менеджера. Верни ТОЛЬКО JSON без markdown: "
            '{"action":"search|suggest","categories":[],"extensions":[],"month":null,'
            '"year":null,"min_size":null,"max_size":null,"name_contains":"","source":"all|archive|desktop",'
            '"delete_candidates":false}. '
            "categories — из: Картинки, Видео, Музыка, Документы, Архивы, Программы, Код, Папки. "
            "sizes в байтах."
        )
        raw = self._chat(system, text)
        if not raw:
            return None
        data = _extract_json(raw)
        if not data:
            return None
        return SearchIntent(
            action=str(data.get("action") or "search"),
            categories=[str(c) for c in (data.get("categories") or [])],
            extensions=[str(e) if str(e).startswith(".") else f".{e}" for e in (data.get("extensions") or [])],
            month=data.get("month"),
            year=data.get("year"),
            min_size=data.get("min_size"),
            max_size=data.get("max_size"),
            name_contains=str(data.get("name_contains") or ""),
            source=str(data.get("source") or "all"),
            raw_query=text,
            delete_candidates=bool(data.get("delete_candidates")),
        )

    def _llm_suggestions(
        self,
        settings: Settings,
        index: FileIndex,
        watched_entries: list[dict],
    ) -> list[Suggestion]:
        meta = self._metadata_summary(settings, index, watched_entries)
        system = (
            "Ты помощник по организации файлов. По метаданным предложи 1-2 совета. "
            "Верни ТОЛЬКО JSON-массив: "
            '[{"id":"...","title":"...","description":"...","action":"sort_paths|set_sort_mode|'
            'enable_compression|smart_cleanup|search|none","payload":{},"priority":0-100}]. '
            "Не предлагай удалять без подтверждения. Только metadata, без содержимого файлов."
        )
        raw = self._chat(system, json.dumps(meta, ensure_ascii=False))
        if not raw:
            return []
        data = _extract_json(raw)
        if not isinstance(data, list):
            return []
        out: list[Suggestion] = []
        for item in data[:3]:
            if not isinstance(item, dict):
                continue
            out.append(Suggestion(
                id=str(item.get("id") or f"llm_{len(out)}"),
                title=str(item.get("title") or ""),
                description=str(item.get("description") or ""),
                action=str(item.get("action") or "none"),
                payload=dict(item.get("payload") or {}),
                priority=int(item.get("priority") or 30),
            ))
        return [s for s in out if s.title]

    def _chat(self, system: str, user: str) -> str | None:
        if self.provider == "ollama":
            return self._ollama_chat(system, user)
        return self._openai_chat(system, user)

    def _openai_chat(self, system: str, user: str) -> str | None:
        key = self.settings.ai_api_key.strip()
        if not key:
            return None
        url = self.settings.ai_base_url.rstrip("/") + "/chat/completions"
        body = json.dumps({
            "model": self.settings.ai_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
        }).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}",
            },
        )
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        choices = data.get("choices") or []
        if not choices:
            return None
        return choices[0].get("message", {}).get("content")

    def _ollama_chat(self, system: str, user: str) -> str | None:
        url = self.settings.ai_ollama_url.rstrip("/") + "/api/chat"
        body = json.dumps({
            "model": self.settings.ai_ollama_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
        }).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        msg = data.get("message") or {}
        return msg.get("content")


def _count_by(entries: list[dict], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for e in entries:
        k = str(e.get(key, ""))
        out[k] = out.get(k, 0) + 1
    return out


def _extract_json(text: str) -> Any:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"[\[{][\s\S]*[\]}]", text)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
    return None


def create_assistant(settings: Settings) -> RulesAssistant | LLMAssistant:
    """Фабрика: rules или LLM с fallback."""
    if settings.ai_provider in ("openai", "ollama"):
        return LLMAssistant(settings)
    return RulesAssistant()


def parse_user_query(text: str, settings: Settings) -> SearchIntent:
    return create_assistant(settings).parse_user_query(text)


def generate_suggestions(
    settings: Settings,
    index: FileIndex,
    watched_entries: list[dict],
) -> list[Suggestion]:
    return create_assistant(settings).generate_suggestions(settings, index, watched_entries)


def search_files(
    intent: SearchIntent,
    *,
    index: FileIndex,
    watched_entries: list[dict],
) -> list[SearchResult]:
    return RulesAssistant().search(intent, index=index, watched_entries=watched_entries)
