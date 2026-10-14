"""Text of the newest weekly Reflex reports, through the guard. Memory only (DR-02)."""

import datetime as dt
import io

import docx

from .guard import ReflexGuard

SOURCES = [
    ("Weekly Priorities", "Notes", "*_Weekly_Priorities.docx"),
    ("Day Plan", "Notes", "*_Day_Plan.docx"),
    ("Action Items Report", "ToDo", "*_Action_Items_Report*.docx"),
    ("Monday Update", "ToDo", "*_Monday_Update.docx"),
    ("Marlow Monday Update Section", "ToDo", "*_Marlow_Monday_Update_Section*.md"),
]
MAX_CHARS = 12000


def _docx_text(raw: bytes) -> str:
    d = docx.Document(io.BytesIO(raw))
    parts = [p.text for p in d.paragraphs if p.text.strip()]
    for t in d.tables:
        for row in t.rows:
            cells = [c.text.strip().replace("\n", " ") for c in row.cells]
            parts.append(" | ".join(cells))
    return "\n".join(parts)


def newest_reports(guard: ReflexGuard) -> list[dict]:
    """[{kind, file, date, age_days, text}] for the newest file of each kind."""
    out = []
    today = dt.date.today()
    for kind, folder, pattern in SOURCES:
        hit = guard.newest(folder, pattern)
        if hit is None:
            continue
        name, st = hit
        with guard.open(folder, name, st) as f:
            raw = f.read()
        text = _docx_text(raw) if name.endswith(".docx") else raw.decode("utf-8", "replace")
        try:
            date = dt.date.fromisoformat(name[:10])
        except ValueError:
            date = dt.date.fromtimestamp(st.st_mtime)
        out.append({"kind": kind, "file": name, "date": date.isoformat(), "age_days": (today - date).days,
                    "text": text[:MAX_CHARS]})
    return out
